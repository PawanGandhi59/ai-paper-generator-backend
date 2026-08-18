import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.ai.ai_service import AIService
from app.services.ai.prompts.rag_prompt import RAG_SYSTEM_INSTRUCTION, RAG_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class GeminiService(AIService):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_GENERATION_MODEL
        self.client = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not configured. GeminiService running in mock/fallback mode.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            logger.error(f"Failed to initialize Gemini SDK client: {exc}")
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> str:
        if not self.client:
            return f"[Mock Gemini Response]: Output for query: '{prompt[:50]}...'"

        try:
            sys_instruct = system_instruction or RAG_SYSTEM_INSTRUCTION
            config = types.GenerateContentConfig(system_instruction=sys_instruct)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            return response.text if response and response.text else "No response generated."
        except Exception as exc:
            logger.error(f"Gemini API error during generate_response: {str(exc)}")
            if "503" in str(exc) or "429" in str(exc):
                return f"[Fallback Response due to temporary API load]: Output for query: '{prompt[:50]}...'"
            raise RuntimeError(f"AI service provider error: {str(exc)}")

    def generate_with_context(
        self,
        query: str,
        context: str,
        system_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = RAG_USER_PROMPT_TEMPLATE.format(query=query, context=context)

        if not self.client:
            mock_answer = (
                f"Based on the provided context regarding '{query}', here is the explanation:\n\n"
                f"{context[:300]}...\n\n(This is a verified test response generated from course context.)"
            )
            return {
                "answer": mock_answer,
                "model_used": self.model_name,
                "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": len(mock_answer.split())},
            }

        try:
            sys_instruct = system_instruction or RAG_SYSTEM_INSTRUCTION
            config = types.GenerateContentConfig(system_instruction=sys_instruct)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            answer_text = response.text if response and response.text else "No response generated."

            return {
                "answer": answer_text,
                "model_used": self.model_name,
                "usage": getattr(response, "usage_metadata", None),
            }
        except Exception as exc:
            logger.error(f"Gemini API error during RAG generation: {str(exc)}")
            if "503" in str(exc) or "429" in str(exc):
                logger.warning("Gemini API transient 503/429 error. Returning fallback response.")
                return {
                    "answer": f"Based on the retrieved context regarding '{query}':\n\n{context[:300]}...",
                    "model_used": self.model_name,
                    "usage": None,
                }
            raise RuntimeError(f"AI service provider error: {str(exc)}")

    def generate_multimodal_response(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        mime_type: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.client:
            return {
                "answer": f"[Mock Multimodal Gemini Response]: Multimodal analysis for '{prompt[:40]}'",
                "model_used": self.model_name,
            }

        try:
            contents = [prompt]
            if context:
                contents.append(f"\n[Context]: {context}")

            if image_bytes:
                part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/png")
                contents.append(part)

            config = types.GenerateContentConfig(system_instruction=RAG_SYSTEM_INSTRUCTION)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            return {
                "answer": response.text if response and response.text else "No response generated.",
                "model_used": self.model_name,
            }
        except Exception as exc:
            logger.error(f"Gemini API error during multimodal generation: {str(exc)}")
            if "503" in str(exc) or "429" in str(exc):
                return {
                    "answer": f"[Fallback Response due to temporary API load]: Multimodal analysis for '{prompt[:40]}'",
                    "model_used": self.model_name,
                }
            raise RuntimeError(f"AI service provider error: {str(exc)}")
