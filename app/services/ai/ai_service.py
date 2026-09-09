from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AIService(ABC):
    @abstractmethod
    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        response_schema: Optional[Any] = None,
        response_mime_type: Optional[str] = None,
    ) -> str:
        """Generate a response for a prompt."""
        pass

    @abstractmethod
    def generate_with_context(
        self,
        query: str,
        context: str,
        system_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a RAG response given a user query and retrieved context."""
        pass

    @abstractmethod
    def generate_multimodal_response(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        mime_type: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a response for text + optional image input + optional context."""
        pass

    @abstractmethod
    def count_tokens(self, prompt: str, system_instruction: Optional[str] = None) -> int:
        """Calculate input token count for prompt."""
        pass
