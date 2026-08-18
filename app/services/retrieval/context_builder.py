from typing import Any, Dict, List, Tuple


class ContextBuilder:
    @staticmethod
    def build_context(retrieved_chunks: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Organize retrieved chunks, eliminate duplicate texts, retain source citations,
        and construct formatted RAG prompt context string.
        """
        if not retrieved_chunks:
            return "No relevant context found in workspace course materials.", []

        context_blocks = []
        sources = []
        seen_contents = set()

        for idx, chunk in enumerate(retrieved_chunks):
            content = chunk["content"].strip()
            if content in seen_contents:
                continue
            seen_contents.add(content)

            page_num = chunk.get("page_number", 1)
            doc_id = chunk.get("document_id", "Unknown")
            chapter_id = chunk.get("chapter_id")
            chunk_id = chunk.get("chunk_id", str(idx))

            source_info = {
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "page_number": page_num,
                "chapter_id": chapter_id,
                "distance": chunk.get("distance", 0.0),
            }
            sources.append(source_info)

            header = f"[Source {len(sources)}: DocumentID={doc_id}, Page={page_num}"
            if chapter_id:
                header += f", ChapterID={chapter_id}"
            header += "]"

            context_blocks.append(f"{header}\n{content}")

        formatted_context = "\n\n".join(context_blocks)
        return formatted_context, sources
