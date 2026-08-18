import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from sqlalchemy.orm import Session

from langchain_core.documents import Document as LCDocument
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.services.ai.prompts.rag_prompt import RAG_SYSTEM_INSTRUCTION, RAG_USER_PROMPT_TEMPLATE
from app.services.retrieval.context_builder import ContextBuilder
from app.services.visuals.svg_renderer import SVGRenderer

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
    Converts structured diagram/chart specifications into SVG using backend SVGRenderer.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_GENERATION_MODEL
        self.llm = None
        self.chain = None

        logger.info(f"RAGOrchestrator initializing with model: {self.model_name}")
        logger.info(f"Gemini API key present: {bool(self.api_key)}")

        self._init_chain()

    def _init_chain(self):
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not configured.")
            raise ValueError("GEMINI_API_KEY is not configured. Cannot initialize RAGOrchestrator.")

        try:
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self.api_key,
                temperature=0.2,
                max_retries=2,
                request_timeout=60,
            )
            logger.info(f"ChatGoogleGenerativeAI initialized successfully for model: {self.model_name}")

            prompt = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(RAG_SYSTEM_INSTRUCTION.strip()),
                HumanMessagePromptTemplate.from_template(RAG_USER_PROMPT_TEMPLATE.strip()),
            ])
            self.chain = prompt | self.llm | StrOutputParser()
            logger.info("RAG chain initialized successfully")
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
        execute LCEL RAG chain, process structured visual artifacts (diagrams, charts) into SVG,
        and return answer with provenance sources.
        """
        # Relevance Gating Audit & Evaluation
        threshold = settings.RAG_RELEVANCE_THRESHOLD
        chunk_distances = [float(c.get("distance", 1.0)) for c in retrieved_chunks]
        min_distance = min(chunk_distances) if chunk_distances else 1.0

        relevant_chunks = [c for c in retrieved_chunks if float(c.get("distance", 1.0)) <= threshold]
        is_relevant = len(relevant_chunks) > 0

        chunk_summary = [
            {
                "chunk_id": c.get("chunk_id"),
                "document_id": c.get("document_id"),
                "chapter_id": c.get("chapter_id"),
                "distance": c.get("distance"),
            }
            for c in retrieved_chunks
        ]

        logger.info(
            f"RAG Relevance Gate Evaluation | Query: '{query[:60]}...' | "
            f"Total Retrived Chunks: {len(retrieved_chunks)} | Relevant Chunks (<= {threshold}): {len(relevant_chunks)} | "
            f"Min Distance: {min_distance:.4f} | Gate Status: {'PASSED' if is_relevant else 'FAILED'} | "
            f"Chunks Summary: {chunk_summary}"
        )

        if not is_relevant:
            logger.info(f"Relevance gate FAILED (min_distance {min_distance:.4f} > threshold {threshold}). Returning controlled fallback without LLM invocation.")
            return {
                "answer": "I couldn't find this information in the provided course materials.",
                "visuals": [],
                "model_used": self.model_name,
                "sources": [],
                "lc_documents": [],
            }

        lc_docs = []
        for chunk in relevant_chunks:
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
            doc_obj = LCDocument(page_content=chunk.get("content", ""), metadata=meta)
            lc_docs.append(doc_obj)

        context_text, source_citations = ContextBuilder.build_context(relevant_chunks)

        if not self.chain:
            logger.error("RAGOrchestrator execute_rag failed: chain is not initialized.")
            raise RuntimeError("RAGOrchestrator chain is not initialized.")

        try:
            logger.info(f"Invoking Gemini model: {self.model_name} for query: '{query[:60]}...'")
            raw_response = self.chain.invoke({"query": query, "context": context_text})
            logger.info("Gemini response received")

            parsed = _parse_llm_json(str(raw_response))
            answer_content = parsed.get("answer", str(raw_response))
            raw_visuals = parsed.get("visuals", [])
            logger.info(f"Structured response parsed successfully. Raw visual count: {len(raw_visuals)}")

            valid_visuals = []

            for vis in raw_visuals:
                if not isinstance(vis, dict):
                    continue
                v_type = vis.get("type")
                if v_type not in ["diagram", "chart"]:
                    continue

                vis_id = vis.get("id") or f"visual_{len(valid_visuals) + 1}"
                vis["id"] = str(vis_id)
                v_title = vis.get("title", "Visual Explanation")
                v_caption = vis.get("caption")

                try:
                    svg_content = SVGRenderer.render(vis)
                    valid_visuals.append({
                        "id": str(vis_id),
                        "type": v_type,
                        "format": "svg",
                        "title": v_title,
                        "content": svg_content,
                        "caption": v_caption,
                    })
                    logger.info(f"Visual renderer generated SVG for {vis_id} (type: {v_type})")
                except Exception as rendering_exc:
                    logger.error(f"Failed to render SVG for visual spec {vis_id}: {rendering_exc}")
                    continue

            logger.info(f"Final SVG Visual count: {len(valid_visuals)}")

            return {
                "answer": answer_content,
                "visuals": valid_visuals,
                "model_used": self.model_name,
                "sources": source_citations,
                "lc_documents": lc_docs,
            }
        except Exception as exc:
            logger.error(f"LangChain RAG chain execution error: {str(exc)}")
            raise RuntimeError(f"AI Service provider execution error: {str(exc)}")



