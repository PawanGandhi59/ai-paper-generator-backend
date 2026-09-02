import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.ai.ai_service import AIService
from app.services.ai.prompts.rag_prompt import RAG_SYSTEM_INSTRUCTION, RAG_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


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
    Official Google GenAI SDK Service wrapper for gemini-3.5-flash-lite.
    Enforces strict API key validation and structured response generation.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_GENERATION_MODEL
        self.client = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not configured.")
            raise ValueError("GEMINI_API_KEY is not configured. Cannot initialize GeminiService.")

        try:
            self.client = genai.Client(api_key=self.api_key)
            logger.info(f"GeminiService initialized with model: {self.model_name}")
        except Exception as exc:
            logger.error(f"Failed to initialize Google GenAI SDK client: {exc}")
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        response_schema: Optional[Any] = None,
    ) -> str:
        if not self.client:
            raise RuntimeError("GeminiService client is not initialized.")

        sys_instruct = system_instruction or RAG_SYSTEM_INSTRUCTION
        token_limit = max_output_tokens or settings.GEMINI_PAPER_MAX_OUTPUT_TOKENS
        config = types.GenerateContentConfig(
            system_instruction=sys_instruct,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.2,
            max_output_tokens=token_limit,
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                if not response:
                    raise GeminiProviderError("Gemini API returned an empty response object.")

                # Inspect candidates finish_reason for MAX_TOKENS truncation
                if hasattr(response, "candidates") and response.candidates:
                    first_cand = response.candidates[0]
                    finish_reason_str = str(getattr(first_cand, "finish_reason", "")).upper()
                    if "MAX_TOKENS" in finish_reason_str:
                        logger.warning(
                            f"Gemini output token limit reached (finish_reason={finish_reason_str}, "
                            f"max_output_tokens={token_limit}). Raising GeminiOutputTruncatedError."
                        )
                        raise GeminiOutputTruncatedError(
                            f"Gemini output token limit reached ({token_limit} tokens). Response truncated."
                        )

                if not response.text:
                    raise GeminiInvalidResponseError("Gemini API returned an empty text response.")

                return response.text

            except GeminiOutputTruncatedError:
                # Do NOT retry wasteful MAX_TOKENS truncations repeatedly with identical prompt
                raise

            except Exception as exc:
                err_msg = str(exc)
                is_rate_limit = any(k in err_msg.upper() for k in ["429", "RESOURCE_EXHAUSTED", "QUOTA"])
                is_transient = is_rate_limit or any(k in err_msg.upper() for k in ["503", "UNAVAILABLE", "500", "502", "504", "TIMEOUT"])

                if is_transient and attempt < max_retries - 1:
                    import time
                    logger.warning(f"Gemini API transient error hit ({err_msg[:60]}), backing off 3s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(3)
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

        if not self.client:
            raise RuntimeError("GeminiService client is not initialized.")

        try:
            sys_instruct = system_instruction or RAG_SYSTEM_INSTRUCTION
            config = types.GenerateContentConfig(
                system_instruction=sys_instruct,
                response_mime_type="application/json",
                temperature=0.2,
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            if not response or not response.text:
                raise RuntimeError("Gemini API returned an empty text response.")

            return {
                "answer": response.text,
                "model_used": self.model_name,
                "usage": None,
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
        if not self.client:
            raise RuntimeError("GeminiService client is not initialized.")

        try:
            contents = [prompt]
            if context:
                contents.append(f"\n[Context]: {context}")

            if image_bytes:
                part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/png")
                contents.append(part)

            config = types.GenerateContentConfig(system_instruction=RAG_SYSTEM_INSTRUCTION, temperature=0.2)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            if not response or not response.text:
                raise RuntimeError("Gemini API returned an empty text response.")

            return {
                "answer": response.text,
                "model_used": self.model_name,
            }
        except Exception as exc:
            logger.error(f"Gemini API error during multimodal generation: {str(exc)}")
            raise RuntimeError(f"AI service provider error: {str(exc)}")

    def count_tokens(self, prompt: str, system_instruction: Optional[str] = None) -> int:
        """
        Calculates the exact input token count for prompt + system instruction using official Google GenAI SDK.
        """
        if not self.client:
            raise RuntimeError("GeminiService client is not initialized.")

        sys_instruct = system_instruction or RAG_SYSTEM_INSTRUCTION
        combined_contents = f"{sys_instruct}\n\n{prompt}"

        try:
            res = self.client.models.count_tokens(
                model=self.model_name,
                contents=combined_contents,
            )
            if res and hasattr(res, "total_tokens") and res.total_tokens is not None:
                return res.total_tokens
        except Exception as exc:
            logger.warning(f"Gemini SDK count_tokens API call failed ({exc}); using fallback token estimation.")

        return len(combined_contents) // 4


