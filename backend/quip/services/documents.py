"""Document processing — text extraction, chunking, embedding orchestration."""
import logging
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.file import File, DocumentChunk
from quip.services.config import get_setting

logger = logging.getLogger(__name__)


def extract_text(file_path: str, content_type: str) -> str:
    """Extract plain text from a file based on its content type."""
    path = Path(file_path)

    if content_type in ("text/plain", "text/markdown", "text/csv"):
        return path.read_text(encoding="utf-8", errors="replace")

    if content_type == "application/pdf":
        return _extract_pdf(path)

    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx(path)

    # Fallback: try reading as text
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using pymupdf."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except ImportError:
        logger.warning("pymupdf not installed, cannot extract PDF text")
        return ""
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def _extract_docx(path: Path) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        logger.warning("python-docx not installed, cannot extract DOCX text")
        return ""
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def chunk_text(text: str, max_tokens: int = 512, overlap_tokens: int = 64) -> list[str]:
    """Split text into chunks with overlap, sentence-aware."""
    if not text.strip():
        return []

    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        count_tokens = lambda t: len(enc.encode(t))
    except ImportError:
        # Fallback: approximate 1 token ≈ 4 chars
        count_tokens = lambda t: len(t) // 4

    # Split on sentence boundaries, keeping delimiters with preceding text
    parts = re.split(r'(\.\s|\n|!\s|\?\s|;\s|:\s)', text)
    segments = []
    for i in range(0, len(parts), 2):
        seg = parts[i]
        if i + 1 < len(parts):
            seg += parts[i + 1]
        if seg.strip():
            segments.append(seg)

    if not segments:
        return [text[:max_tokens * 4]] if text.strip() else []

    chunks = []
    current_segments: list[str] = []
    current_tokens = 0

    for segment in segments:
        seg_tokens = count_tokens(segment)

        if current_tokens + seg_tokens > max_tokens and current_segments:
            # Save current chunk
            chunks.append("".join(current_segments).strip())

            # Calculate overlap: keep trailing segments that fit in overlap_tokens
            overlap_segments: list[str] = []
            overlap_count = 0
            for s in reversed(current_segments):
                s_tokens = count_tokens(s)
                if overlap_count + s_tokens > overlap_tokens:
                    break
                overlap_segments.insert(0, s)
                overlap_count += s_tokens

            current_segments = overlap_segments
            current_tokens = overlap_count

        current_segments.append(segment)
        current_tokens += seg_tokens

    # Don't forget the last chunk
    if current_segments:
        final = "".join(current_segments).strip()
        if final:
            chunks.append(final)

    return chunks


async def process_file(file_id: UUID, db: AsyncSession) -> None:
    """Process a document: extract text, chunk, embed, save to DB."""
    from quip.routers.files import UPLOAD_DIR

    result = await db.execute(select(File).where(File.id == file_id))
    file_record = result.scalar_one_or_none()
    if not file_record:
        return

    file_record.embedding_status = "processing"
    await db.commit()

    try:
        # Extract text
        file_path = UPLOAD_DIR / file_record.storage_path
        text = extract_text(str(file_path), file_record.content_type or "")

        if not text.strip():
            file_record.embedding_status = "failed"
            await db.commit()
            return

        # Chunk
        max_tokens = int(get_setting("rag_chunk_size", "512"))
        overlap = int(get_setting("rag_chunk_overlap", "64"))
        chunks = chunk_text(text, max_tokens=max_tokens, overlap_tokens=overlap)

        if not chunks:
            file_record.embedding_status = "failed"
            await db.commit()
            return

        # Embed
        from quip.services.embeddings import get_embeddings
        embeddings = await get_embeddings(chunks)

        if not embeddings or len(embeddings) != len(chunks):
            file_record.embedding_status = "failed"
            await db.commit()
            return

        # Save chunks
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            count_tokens = lambda t: len(enc.encode(t))
        except ImportError:
            count_tokens = lambda t: len(t) // 4

        for i, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = DocumentChunk(
                file_id=file_id,
                chat_id=file_record.chat_id,
                chunk_index=i,
                content=chunk_text_content,
                embedding=embedding,
                token_count=count_tokens(chunk_text_content),
            )
            db.add(chunk)

        file_record.embedding_status = "completed"
        await db.commit()
        logger.info(f"Processed file {file_id}: {len(chunks)} chunks embedded")

    except Exception as e:
        logger.error(f"File processing failed for {file_id}: {e}")
        file_record.embedding_status = "failed"
        try:
            await db.commit()
        except Exception:
            pass
