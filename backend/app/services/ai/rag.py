"""Evidence retrieval (spec section 6).

Every generative call must retrieve grounding evidence first. What comes back
carries an evidence id, and those ids are recorded on the generated asset so
the audit trail can show what a claim was based on.

Similarity uses pgvector on PostgreSQL and a pure-Python cosine on SQLite, so
a development database still behaves correctly, just more slowly.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.identity import CareerFact, CareerProfile
from app.db.models.resumes import Resume, ResumeChunk, ResumeVersion
from app.services.normalize import jaccard, tokens

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150


@dataclass(slots=True)
class Evidence:
    evidence_id: str
    kind: str
    content: str
    score: float
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "content": self.content,
            "score": round(self.score, 4),
            "source": self.source,
        }


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def chunk_text(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries, keeping chunks under ``max_chars``.

    Overlap preserves context for bullets that straddle a boundary.
    """
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > max_chars:
            # A single oversized block: break it on sentence boundaries.
            for sentence in re.split(r"(?<=[.!?])\s+", para):
                if len(current) + len(sentence) + 1 > max_chars and current:
                    chunks.append(current.strip())
                    current = current[-CHUNK_OVERLAP_CHARS:] if len(current) > CHUNK_OVERLAP_CHARS else ""
                current = f"{current} {sentence}".strip()
            continue
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = ""
        current = f"{current}\n\n{para}".strip()

    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c.strip()]


def _keyword_rank(query: str, content: str) -> float:
    return jaccard(tokens(query), tokens(content))


def retrieve_evidence(
    db: Session,
    user_id: str,
    query: str,
    *,
    limit: int = 8,
    query_embedding: list[float] | None = None,
    resume_id: str | None = None,
) -> list[Evidence]:
    """Return the most relevant resume chunks and career facts for ``query``.

    Falls back to keyword overlap when embeddings are absent, so evidence
    grounding still works before anything has been embedded.
    """
    results: list[Evidence] = []

    chunk_stmt = (
        select(ResumeChunk, ResumeVersion, Resume)
        .join(ResumeVersion, ResumeChunk.resume_version_id == ResumeVersion.id)
        .join(Resume, ResumeVersion.resume_id == Resume.id)
        .where(Resume.user_id == user_id, Resume.deleted_at.is_(None))
    )
    if resume_id:
        chunk_stmt = chunk_stmt.where(Resume.id == resume_id)

    for chunk, version, resume in db.execute(chunk_stmt).all():
        if query_embedding and chunk.embedding:
            score = cosine_similarity(query_embedding, chunk.embedding)
        else:
            score = _keyword_rank(query, chunk.content)
        if score > 0:
            results.append(
                Evidence(
                    evidence_id=f"chunk:{chunk.id}",
                    kind="resume_chunk",
                    content=chunk.content,
                    score=score,
                    source=f"{resume.name} v{version.version_number}"
                    + (f" / {chunk.section}" if chunk.section else ""),
                )
            )

    fact_stmt = (
        select(CareerFact)
        .join(CareerProfile, CareerFact.profile_id == CareerProfile.id)
        .where(CareerProfile.user_id == user_id)
    )
    for fact in db.execute(fact_stmt).scalars().all():
        blob = f"{fact.statement} {fact.detail}".strip()
        score = _keyword_rank(query, blob)
        # Verified facts outrank equally-relevant unverified text.
        if fact.is_verified:
            score += 0.05
        if score > 0:
            results.append(
                Evidence(
                    evidence_id=f"fact:{fact.id}",
                    kind=f"career_fact:{fact.kind}",
                    content=blob,
                    score=score,
                    source=fact.source_ref or "career profile",
                )
            )

    results.sort(key=lambda e: e.score, reverse=True)
    return results[:limit]


def render_evidence_block(evidence: list[Evidence]) -> str:
    """Format evidence for a prompt, with ids the model is told to cite."""
    if not evidence:
        return "(no stored evidence found)"
    lines = []
    for item in evidence:
        source = f" [{item.source}]" if item.source else ""
        lines.append(f"- ({item.evidence_id}){source} {item.content}")
    return "\n".join(lines)


def embed_resume_version(db: Session, ai: Any, version: ResumeVersion) -> int:
    """Chunk and embed one resume version. Returns the number of chunks stored.

    Safe to call when AI is disabled: chunks are still stored (so keyword
    retrieval works), just without vectors.
    """
    for existing in list(version.chunks):
        db.delete(existing)
    version.chunks.clear()

    pieces = chunk_text(version.extracted_text or "")
    if not pieces:
        return 0

    vectors: list[list[float]] = []
    if ai is not None and getattr(ai, "enabled", False):
        try:
            vectors = ai.embed(pieces, function="embed_resume")
        except Exception as exc:  # embedding is an optimisation, never fatal
            logger.warning("Resume embedding failed for version %s: %s", version.id, exc)
            vectors = []

    for index, piece in enumerate(pieces):
        db.add(
            ResumeChunk(
                resume_version_id=version.id,
                chunk_index=index,
                section="",
                content=piece,
                token_estimate=max(1, len(piece) // 4),
                embedding=vectors[index] if index < len(vectors) else None,
                embedding_model=settings.openai_embedding_model if vectors else "",
            )
        )
    return len(pieces)
