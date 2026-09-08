import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.core.rate_limiter import RedisGeminiRateLimiter
from app.services.ai.ai_service import AIService
from app.services.ai.prompts.rag_prompt import RAG_SYSTEM_INSTRUCTION, RAG_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


def _extract_retry_delay(err_msg: str, default_delay: float = 25.0) -> float:
    """
    Extract retry delay (in seconds) from Gemini 429 quota/resource exhausted error messages.
    E.g. 'Please retry in 23.056241508s.' or 'retryDelay: 24s'
    """
    m = re.search(r"retry(?:\s+in|\s+after)?\s+([0-9]+(?:\.[0-9]+)?)\s*s", err_msg, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) + 1.0  # +1s buffer
        except (ValueError, TypeError):
            pass
    m = re.search(r"retryDelay['\":\s]+([0-9]+(?:\.[0-9]+)?)s?", err_msg, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) + 1.0
        except (ValueError, TypeError):
            pass
    return default_delay


# Shared distributed rate limiter enforcing 15 RPM / 240,000 TPM across generation & recovery calls
_generation_rate_limiter = RedisGeminiRateLimiter(
    max_rpm=getattr(settings, "GEMINI_GENERATION_MAX_RPM", 15),
    max_tpm=getattr(settings, "GEMINI_GENERATION_MAX_TPM", 240000),
    window_seconds=60.0,
    key_prefix="gemini:generation",
)


class GeminiServiceError(RuntimeError):
    """Base exception for Gemini service provider issues."""
    pass


class GeminiOutputTruncatedError(GeminiServiceError):
    """Raised when Gemini output generation reaches MAX_TOKENS limit and is truncated."""
    pass


class GeminiRateLimitError(GeminiServiceError):
    """Raised when Gemini returns HTTP 429, RESOURCE_EXHAUSTED, or quota exceeded."""
    pass


class GeminiProviderError(GeminiServiceError):
    """Raised when Gemini provider returns HTTP 500, 502, 503, UNAVAILABLE, or network failure."""
    pass


class GeminiInvalidResponseError(GeminiServiceError):
    """Raised when Gemini completes normally but returns malformed or unparseable JSON/text."""
    pass


class GeminiService(AIService):
    """
    LangChain Google Generative AI Service wrapper for gemini models.
    Enforces strict API key validation, token-safety, distributed sliding-window rate limiting,
    and structured response generation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        rate_limiter: Optional[RedisGeminiRateLimiter] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_GENERATION_MODEL
        self.rate_limiter = rate_limiter or _generation_rate_limiter
        self.llm: Optional[ChatGoogleGenerativeAI] = None
        self.client = None
        self.session_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "call_count": 0,
        }
        self._init_client()

    def reset_session_usage(self):
        """Reset accumulated token metrics for a new paper generation run."""
        self.session_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "call_count": 0,
        }

    def get_session_usage(self) -> Dict[str, int]:
        """Return a copy of accumulated token metrics."""
        return dict(self.session_usage)

    def _init_client(self):
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not configured.")
            raise ValueError("GEMINI_API_KEY is not configured. Cannot initialize GeminiService.")

        try:
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self.api_key,
                temperature=0.2,
                max_retries=2,
                request_timeout=getattr(settings, "GEMINI_REQUEST_TIMEOUT", 300),
            )
            logger.info(f"GeminiService (LangChain) initialized with model: {self.model_name}")
        except Exception as exc:
            logger.error(f"Failed to initialize LangChain ChatGoogleGenerativeAI: {exc}")
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def _legacy_client_generate(
        self,
        prompt: str,
        system_instruction: str,
        max_output_tokens: int,
        response_schema: Optional[Any],
    ) -> str:
        """Handles mock client compatibility for legacy tests."""
        class _LegacyConfig:
            def __init__(self, sys_inst, mime, schema, temp, max_tokens):
                self.system_instruction = sys_inst
                self.response_mime_type = mime
                self.response_schema = schema
                self.temperature = temp
                self.max_output_tokens = max_tokens

        config = _LegacyConfig(
            sys_inst=system_instruction,
            mime="application/json",
            schema=response_schema,
            temp=0.2,
            max_tokens=max_output_tokens,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )
        if not response:
            raise GeminiProviderError("Gemini API returned an empty response object.")

        if hasattr(response, "candidates") and response.candidates:
            first_cand = response.candidates[0]
            finish_reason_str = str(getattr(first_cand, "finish_reason", "")).upper()
            if "MAX_TOKENS" in finish_reason_str:
                logger.warning(
                    f"Gemini output token limit reached (finish_reason={finish_reason_str}, "
                    f"max_output_tokens={max_output_tokens}). Raising GeminiOutputTruncatedError."
                )
                raise GeminiOutputTruncatedError(
                    f"Gemini output token limit reached ({max_output_tokens} tokens). Response truncated."
                )

        if not getattr(response, "text", None):
            raise GeminiInvalidResponseError("Gemini API returned an empty text response.")

        return response.text

    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        response_schema: Optional[Any] = None,
    ) -> str:
        if not self.llm and not (hasattr(self, "client") and self.client):
            raise RuntimeError("GeminiService client is not initialized.")

        sys_instruct = system_instruction
        token_limit = max_output_tokens or settings.GEMINI_PAPER_MAX_OUTPUT_TOKENS

        if hasattr(self, "client") and self.client is not None and hasattr(self.client, "models"):
            return self._legacy_client_generate(prompt, sys_instruct, token_limit, response_schema)

        messages: List[BaseMessage] = []
        if sys_instruct:
            messages.append(SystemMessage(content=sys_instruct))
        messages.append(HumanMessage(content=prompt))

        schema_dict = None
        if response_schema is not None:
            if hasattr(response_schema, "model_json_schema"):
                schema_dict = response_schema.model_json_schema()
            elif isinstance(response_schema, dict):
                schema_dict = response_schema

        invocation_kwargs: Dict[str, Any] = {
            "max_output_tokens": token_limit,
            "response_mime_type": "application/json",
        }
        if schema_dict:
            invocation_kwargs["response_schema"] = schema_dict

        configured_llm = self.llm.bind(**invocation_kwargs)

        # Proactively check token count and acquire capacity from Redis sliding window
        limiter = getattr(self, "rate_limiter", None)
        prompt_tokens = 0
        if limiter is not None:
            try:
                prompt_tokens = self.count_tokens(prompt, system_instruction=sys_instruct)
                limiter.acquire(token_count=prompt_tokens)
            except Exception as acq_err:
                logger.warning(f"Rate limiter acquire encountered an issue ({acq_err}), continuing...")

        max_retries = 4
        for attempt in range(max_retries):
            try:
                response = configured_llm.invoke(messages)
                if not response:
                    raise GeminiProviderError("Gemini API returned an empty response object.")

                finish_reason = ""
                if hasattr(response, "response_metadata") and isinstance(response.response_metadata, dict):
                    finish_reason = str(response.response_metadata.get("finish_reason", "")).upper()
                elif hasattr(response, "generation_info") and isinstance(response.generation_info, dict):
                    finish_reason = str(response.generation_info.get("finish_reason", "")).upper()

                if "MAX_TOKENS" in finish_reason:
                    logger.warning(
                        f"Gemini output token limit reached (finish_reason={finish_reason}, "
                        f"max_output_tokens={token_limit}). Raising GeminiOutputTruncatedError."
                    )
                    raise GeminiOutputTruncatedError(
                        f"Gemini output token limit reached ({token_limit} tokens). Response truncated."
                    )

                res_text = response.content
                if isinstance(res_text, list):
                    res_text = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in res_text])

                if not res_text or not str(res_text).strip():
                    raise GeminiInvalidResponseError("Gemini API returned an empty text response.")

                # Extract and record token usage
                p_tokens = 0
                c_tokens = 0
                t_tokens = 0
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    if isinstance(usage, dict):
                        p_tokens = usage.get("input_tokens", 0)
                        c_tokens = usage.get("output_tokens", 0)
                        t_tokens = usage.get("total_tokens", p_tokens + c_tokens)
                    else:
                        p_tokens = getattr(usage, "input_tokens", 0)
                        c_tokens = getattr(usage, "output_tokens", 0)
                        t_tokens = getattr(usage, "total_tokens", p_tokens + c_tokens)
                elif hasattr(response, "response_metadata") and isinstance(response.response_metadata, dict):
                    meta_usage = response.response_metadata.get("usage_metadata") or response.response_metadata.get("token_usage") or {}
                    if isinstance(meta_usage, dict):
                        p_tokens = meta_usage.get("prompt_token_count", meta_usage.get("prompt_tokens", 0))
                        c_tokens = meta_usage.get("candidates_token_count", meta_usage.get("completion_tokens", 0))
                        t_tokens = meta_usage.get("total_token_count", meta_usage.get("total_tokens", p_tokens + c_tokens))

                self.session_usage["prompt_tokens"] += p_tokens
                self.session_usage["completion_tokens"] += c_tokens
                self.session_usage["total_tokens"] += t_tokens
                self.session_usage["call_count"] += 1

                log_call_msg = (
                    f"[LLM_TOKEN_USAGE] Call #{self.session_usage['call_count']} | "
                    f"Prompt Tokens: {p_tokens} | "
                    f"Completion Tokens: {c_tokens} | "
                    f"Total Tokens: {t_tokens}"
                )
                logger.info(log_call_msg)
                print(log_call_msg, flush=True)

                return str(res_text)

            except GeminiOutputTruncatedError:
                raise

            except Exception as exc:
                err_msg = str(exc)
                is_rate_limit = any(k in err_msg.upper() for k in ["429", "RESOURCE_EXHAUSTED", "QUOTA"])
                is_transient = is_rate_limit or any(k in err_msg.upper() for k in ["503", "UNAVAILABLE", "500", "502", "504", "TIMEOUT", "DEADLINE_EXCEEDED"])

                if is_transient and attempt < max_retries - 1:
                    if is_rate_limit:
                        backoff_sec = _extract_retry_delay(err_msg, default_delay=25.0)
                        logger.warning(
                            f"Gemini API rate limit/quota hit ({err_msg[:80]}). "
                            f"Backing off {backoff_sec:.2f}s (attempt {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(backoff_sec)
                        if limiter is not None and prompt_tokens > 0:
                            try:
                                limiter.acquire(token_count=prompt_tokens)
                            except Exception:
                                pass
                    else:
                        logger.warning(
                            f"Gemini API transient error hit ({err_msg[:80]}), "
                            f"backing off 4s (attempt {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(4)
                    continue

                logger.error(f"Gemini API error during generate_response: {str(exc)}")
                if is_rate_limit:
                    raise GeminiRateLimitError(f"Gemini API rate limit exceeded: {str(exc)}")
                raise GeminiProviderError(f"AI service provider error: {str(exc)}")

    def generate_with_context(
        self,
        query: str,
        context: str,
        system_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = RAG_USER_PROMPT_TEMPLATE.format(query=query, context=context)
        sys_instruct = system_instruction or RAG_SYSTEM_INSTRUCTION

        if not self.llm and not (hasattr(self, "client") and self.client):
            raise RuntimeError("GeminiService client is not initialized.")

        limiter = getattr(self, "rate_limiter", None)
        if limiter is not None:
            try:
                prompt_tokens = self.count_tokens(prompt, system_instruction=sys_instruct)
                limiter.acquire(token_count=prompt_tokens)
            except Exception as acq_err:
                logger.warning(f"Rate limiter acquire encountered an issue ({acq_err}), continuing...")

        try:
            messages: List[BaseMessage] = [
                SystemMessage(content=sys_instruct),
                HumanMessage(content=prompt),
            ]
            configured_llm = self.llm.bind(response_mime_type="application/json")
            response = configured_llm.invoke(messages)

            res_text = response.content
            if isinstance(res_text, list):
                res_text = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in res_text])

            if not res_text or not str(res_text).strip():
                raise RuntimeError("Gemini API returned an empty text response.")

            return {
                "answer": str(res_text),
                "model_used": self.model_name,
                "usage": getattr(response, "usage_metadata", None),
            }
        except Exception as exc:
            logger.error(f"Gemini API error during RAG generation: {str(exc)}")
            raise RuntimeError(f"AI service provider error: {str(exc)}")

    def generate_multimodal_response(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        mime_type: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.llm and not (hasattr(self, "client") and self.client):
            raise RuntimeError("GeminiService client is not initialized.")

        limiter = getattr(self, "rate_limiter", None)
        if limiter is not None:
            try:
                limiter.acquire(token_count=self.count_tokens(prompt))
            except Exception as acq_err:
                logger.warning(f"Rate limiter acquire encountered an issue ({acq_err}), continuing...")

        try:
            content: List[Union[str, Dict[str, Any]]] = [{"type": "text", "text": prompt}]
            if context:
                content.append({"type": "text", "text": f"\n[Context]: {context}"})

            if image_bytes:
                b64_str = base64.b64encode(image_bytes).decode("utf-8")
                media_mime = mime_type or "image/png"
                content.append({
                    "type": "image_url",
                    "image_url": f"data:{media_mime};base64,{b64_str}",
                })

            messages: List[BaseMessage] = [
                SystemMessage(content=RAG_SYSTEM_INSTRUCTION),
                HumanMessage(content=content),
            ]
            response = self.llm.invoke(messages)

            res_text = response.content
            if isinstance(res_text, list):
                res_text = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in res_text])

            if not res_text or not str(res_text).strip():
                raise RuntimeError("Gemini API returned an empty text response.")

            return {
                "answer": str(res_text),
                "model_used": self.model_name,
            }
        except Exception as exc:
            logger.error(f"Gemini API error during multimodal generation: {str(exc)}")
            raise RuntimeError(f"AI service provider error: {str(exc)}")

    def count_tokens(self, prompt: str, system_instruction: Optional[str] = None) -> int:
        """
        Calculates input token count using LangChain get_num_tokens.
        Does not inject RAG_SYSTEM_INSTRUCTION; counts system_instruction only if explicitly provided.
        """
        if system_instruction:
            combined_contents = f"{system_instruction}\n\n{prompt}"
        else:
            combined_contents = prompt

        if self.llm:
            try:
                return self.llm.get_num_tokens(combined_contents)
            except Exception as exc:
                logger.warning(f"LangChain get_num_tokens failed ({exc}); using fallback token estimation.")

        return len(combined_contents) // 4



