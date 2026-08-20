import logging
import time
from typing import List, Optional

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.embeddings.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:
    GoogleGenerativeAIEmbeddings = None


class GeminiEmbeddingService(EmbeddingService):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.client = None
        self.lc_embeddings = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not configured.")
            raise ValueError("GEMINI_API_KEY is missing. Gemini embedding service requires a valid API key.")

        try:
            if GoogleGenerativeAIEmbeddings:
                self.lc_embeddings = GoogleGenerativeAIEmbeddings(
                    model=self.model_name,
                    google_api_key=self.api_key,
                    output_dimensionality=self.dimension,
                )
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            logger.error(f"Failed to initialize Gemini SDK/LangChain client: {exc}")
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def generate_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            text = "empty text"

        res = self.generate_embeddings_batch([text])
        return res[0]

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if not self.api_key or (not self.client and not self.lc_embeddings):
            raise ValueError("GEMINI_API_KEY is missing. Gemini embedding service requires a valid API key.")

        try:
            clean_texts = [t if t and t.strip() else "empty text" for t in texts]
            batch_size = 100
            all_embeddings = []

            for i in range(0, len(clean_texts), batch_size):
                sub_batch = clean_texts[i : i + batch_size]
                max_retries = 5
                backoff = 2.0
                sub_embeddings = None

                for attempt in range(max_retries):
                    try:
                        if self.lc_embeddings:
                            sub_embeddings = self.lc_embeddings.embed_documents(sub_batch)
                        else:
                            contents = [{"parts": [{"text": t}]} for t in sub_batch]
                            res = self.client.models.embed_content(
                                model=self.model_name,
                                contents=contents,
                                config=types.EmbedContentConfig(output_dimensionality=self.dimension),
                            )
                            if not res or not hasattr(res, "embeddings") or not res.embeddings:
                                raise RuntimeError("Gemini embedding API returned empty response.")
                            sub_embeddings = [emb.values for emb in res.embeddings]
                        break
                    except Exception as exc:
                        exc_str = str(exc)
                        if ("429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower()) and attempt < max_retries - 1:
                            logger.warning(
                                f"Gemini embedding API rate limit/quota reached on batch index {i} (attempt {attempt + 1}/{max_retries}): {exc_str}. "
                                f"Retrying in {backoff} seconds..."
                            )
                            time.sleep(backoff)
                            backoff *= 2.0
                        else:
                            logger.error(f"Gemini embedding error on batch starting index {i}: {exc_str}")
                            raise RuntimeError(f"Gemini embedding API failure: {exc_str}")

                if not sub_embeddings:
                    raise RuntimeError(f"Failed to generate embeddings for batch starting index {i}")

                all_embeddings.extend(sub_embeddings)
                if i + batch_size < len(clean_texts):
                    time.sleep(0.3)

            # Validate batch count and dimensions
            if len(all_embeddings) != len(texts):
                raise RuntimeError(
                    f"Gemini embedding batch count mismatch: expected {len(texts)}, got {len(all_embeddings)}"
                )

            for idx, vec in enumerate(all_embeddings):
                if len(vec) != self.dimension:
                    raise RuntimeError(
                        f"Gemini embedding dimension mismatch at index {idx}: expected {self.dimension}, got {len(vec)}"
                    )

            return all_embeddings

        except Exception as exc:
            logger.error(f"Gemini embedding API error: {str(exc)}")
            raise RuntimeError(f"Gemini embedding API failure: {str(exc)}")
