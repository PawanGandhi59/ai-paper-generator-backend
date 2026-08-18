import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.generated_visual import GeneratedVisual
from app.services.ai.gemini_service import GeminiService
from app.services.ai.prompts.rag_prompt import RAG_SYSTEM_INSTRUCTION, RAG_USER_PROMPT_TEMPLATE
from app.services.retrieval.context_builder import ContextBuilder

try:
    from langchain_core.documents import Document as LCDocument
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    LCDocument = None
    StrOutputParser = None
    ChatPromptTemplate = None
    ChatGoogleGenerativeAI = None

logger = logging.getLogger(__name__)


def _parse_llm_json(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()
    if "```json" in text:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "answer" in data:
            return data
    except Exception:
        pass

    return {"answer": raw_text, "visuals": []}


class RAGOrchestrator:
    """
    Dedicated LangChain RAG Orchestration Layer.
    Executes LCEL pipeline: Query + Retrieved Documents -> ChatPromptTemplate -> ChatGoogleGenerativeAI -> Structured Output Parser.
    Handles diagram/chart visuals and actual Gemini image byte generation.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_GENERATION_MODEL
        self.llm = None
        self.chain = None
        self._init_chain()

    def _init_chain(self):
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set. RAGOrchestrator running in mock/fallback mode.")
            return

        try:
            if ChatGoogleGenerativeAI and ChatPromptTemplate and StrOutputParser:
                self.llm = ChatGoogleGenerativeAI(
                    model=self.model_name,
                    google_api_key=self.api_key,
                    temperature=0.2,
                    max_retries=2,
                    request_timeout=60,
                )
                prompt = ChatPromptTemplate.from_messages([
                    SystemMessagePromptTemplate.from_template(RAG_SYSTEM_INSTRUCTION.strip()),
                    HumanMessagePromptTemplate.from_template(RAG_USER_PROMPT_TEMPLATE.strip()),
                ])
                self.chain = prompt | self.llm | StrOutputParser()
        except Exception as exc:
            logger.error(f"Failed to initialize LangChain RAG chain: {exc}")
            raise RuntimeError(f"RAGOrchestrator initialization error: {exc}")

    def execute_rag(
        self,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Convert retrieved chunks into LangChain Document instances, format context,
        execute LCEL RAG chain, process structured visual artifacts (diagrams, charts, images),
        and return answer with provenance sources.
        """
        lc_docs = []
        for chunk in retrieved_chunks:
            meta = {
                "chunk_id": chunk.get("chunk_id"),
                "document_id": chunk.get("document_id"),
                "page_number": chunk.get("page_number", 1),
                "chapter_id": chunk.get("chapter_id"),
                "book_id": chunk.get("book_id"),
                "subject_id": chunk.get("subject_id"),
                "workspace_id": chunk.get("workspace_id"),
                "distance": chunk.get("distance", 0.0),
            }
            if LCDocument:
                doc_obj = LCDocument(page_content=chunk.get("content", ""), metadata=meta)
            else:
                doc_obj = meta
            lc_docs.append(doc_obj)

        context_text, source_citations = ContextBuilder.build_context(retrieved_chunks)

        if not self.api_key or not self.chain:
            mock_answer = (
                f"Based on the provided context regarding '{query}', here is the explanation:\n\n"
                f"{context_text[:300]}...\n\n(This is a verified test response generated from course context.)"
            )
            return {
                "answer": mock_answer,
                "visuals": [],
                "model_used": self.model_name,
                "sources": source_citations,
                "lc_documents": lc_docs,
            }

        try:
            raw_response = self.chain.invoke({"query": query, "context": context_text})
            parsed = _parse_llm_json(str(raw_response))
            answer_content = parsed.get("answer", str(raw_response))
            raw_visuals = parsed.get("visuals", [])
            valid_visuals = []

            gemini_service = GeminiService(api_key=self.api_key, model_name=self.model_name)

            for vis in raw_visuals:
                if not isinstance(vis, dict):
                    continue
                v_type = vis.get("type")
                v_format = vis.get("format")
                v_title = vis.get("title", "Visual Explanation")
                v_content = vis.get("content", "")
                v_caption = vis.get("caption")

                if v_type not in ["diagram", "chart", "image"]:
                    continue

                if v_type == "image":
                    try:
                        img_bytes = gemini_service.generate_image_bytes(v_content)
                        if img_bytes and workspace_id and user_id and db:
                            visual_id = uuid4()
                            storage_dir = os.path.join("/app/storage/generated_visuals", str(workspace_id))
                            os.makedirs(storage_dir, exist_ok=True)
                            file_path = os.path.join(storage_dir, f"{visual_id}.png")

                            with open(file_path, "wb") as f:
                                f.write(img_bytes)

                            db_visual = GeneratedVisual(
                                id=visual_id,
                                workspace_id=workspace_id,
                                user_id=user_id,
                                file_path=file_path,
                                mime_type="image/png",
                                title=v_title,
                            )
                            db.add(db_visual)
                            db.commit()

                            valid_visuals.append({
                                "id": str(visual_id),
                                "type": "image",
                                "format": "url",
                                "title": v_title,
                                "content": f"/api/v1/ai/visuals/{visual_id}",
                                "caption": v_caption,
                            })
                    except Exception as exc:
                        logger.error(f"Failed to generate or store image visual: {exc}")
                        continue
                else:
                    vis_id = vis.get("id") or f"visual_{len(valid_visuals) + 1}"
                    v_fmt = "mermaid" if v_type == "diagram" else ("json" if v_type == "chart" else v_format)
                    valid_visuals.append({
                        "id": str(vis_id),
                        "type": v_type,
                        "format": v_fmt,
                        "title": v_title,
                        "content": v_content,
                        "caption": v_caption,
                    })

            return {
                "answer": answer_content,
                "visuals": valid_visuals,
                "model_used": self.model_name,
                "sources": source_citations,
                "lc_documents": lc_docs,
            }
        except Exception as exc:
            logger.error(f"LangChain RAG chain execution error: {str(exc)}")
            return {
                "answer": f"Based on the retrieved context regarding '{query}':\n\n{context_text[:300]}...",
                "visuals": [],
                "model_used": self.model_name,
                "sources": source_citations,
                "lc_documents": lc_docs,
            }

