"""Semantic similarity between the candidate profile and a job description.

Two interchangeable backends:

* ``local`` -- TF-IDF cosine over the user's own job corpus, with skill
  aliases folded into canonical tokens so "ReactJS" and "React.js" count as
  the same concept. Free, offline, deterministic.
* ``embeddings`` -- cosine over OpenAI embeddings (the provider already used
  for resume chunks). Opt-in because it costs money per job; falls back to
  ``local`` whenever the AI provider is unavailable.

Both return a 0..1 value calibrated so that a clearly related job lands near
the top of the range. Scores are a ranking signal, not a probability.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from app.services.ai.rag import cosine_similarity
from app.services.normalize import norm_text
from app.services.resume.parser import extract_skills

logger = logging.getLogger(__name__)

MAX_DOC_CHARS = 6000
# TF-IDF cosine between a resume and a related posting rarely exceeds ~0.35.
LOCAL_FULL_SCALE = 0.3
# text-embedding-3-small puts unrelated text near 0.1-0.2, related near 0.5+.
EMBED_FLOOR = 0.15
EMBED_FULL_SCALE = 0.45

_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.]{1,30}")
_STOPWORDS = frozenset(
    """
    a about above across after again against all also am an and any are as at be
    because been before being below between both but by can could did do does
    doing down during each etc few for from further had has have having he her
    here hers him his how i if in into is it its itself just me more most my no
    nor not now of off on once only or other our ours out over own same she
    should so some such than that the their them then there these they this
    those through to too under until up very was we were what when where which
    while who whom why will with would you your yours
    work working job role team teams company candidate candidates experience
    years year looking join ability strong good excellent skills skill required
    requirements responsibilities preferred plus using use including within
    etc new help build building across well able must include includes
    """.split()
)


def _tokens(text: str) -> list[str]:
    normalized = norm_text(text[:MAX_DOC_CHARS])
    words = [w.strip(".") for w in _TOKEN_RE.findall(normalized)]
    out = [w for w in words if len(w) > 1 and w not in _STOPWORDS]
    # Canonical skill tokens bridge alias spellings across documents.
    out.extend(f"skill:{s.lower()}" for s in extract_skills(text[:MAX_DOC_CHARS]))
    return out


class LocalSemanticModel:
    """A tiny TF-IDF model fitted on one hunt's corpus."""

    def __init__(self, documents: list[str]):
        self._df: Counter[str] = Counter()
        self._n = 0
        for doc in documents:
            self._df.update(set(_tokens(doc)))
            self._n += 1

    def _idf(self, term: str) -> float:
        return math.log((1 + self._n) / (1 + self._df.get(term, 0))) + 1.0

    def vector(self, text: str) -> dict[str, float]:
        counts = Counter(_tokens(text))
        if not counts:
            return {}
        vec = {term: (1 + math.log(tf)) * self._idf(term) for term, tf in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return {t: v / norm for t, v in vec.items()} if norm else {}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())


def local_scores(profile_text: str, job_texts: dict[str, str]) -> dict[str, float]:
    """0..1 similarity for every job id against the profile."""
    if not profile_text.strip() or not job_texts:
        return {}
    model = LocalSemanticModel([profile_text, *job_texts.values()])
    profile_vec = model.vector(profile_text)
    return {
        job_id: round(min(1.0, model.cosine(profile_vec, model.vector(text)) / LOCAL_FULL_SCALE), 4)
        for job_id, text in job_texts.items()
    }


def _embedding_ratio(value: float) -> float:
    return round(max(0.0, min(1.0, (value - EMBED_FLOOR) / (EMBED_FULL_SCALE - EMBED_FLOOR))), 4)


def embedding_scores(
    ai: Any,
    profile_text: str,
    jobs: list[Any],
    *,
    batch_size: int = 50,
) -> dict[str, float]:
    """Embedding similarity; stores each new job vector on ``job.embedding``.

    Raises whatever the AI client raises, so the caller can fall back.
    """
    profile_vec = ai.embed([profile_text[:8000]], function="hunt_profile_embedding")[0]
    pending = [j for j in jobs if not getattr(j, "embedding", None)]
    for start in range(0, len(pending), batch_size):
        chunk = pending[start:start + batch_size]
        texts = [f"{j.title}\n{(j.description or '')[:MAX_DOC_CHARS]}" for j in chunk]
        vectors = ai.embed(texts, function="hunt_job_embedding")
        for job, vector in zip(chunk, vectors):
            if vector:
                job.embedding = vector
    return {
        j.id: _embedding_ratio(cosine_similarity(profile_vec, j.embedding))
        for j in jobs
        if getattr(j, "embedding", None)
    }


def compute_semantic_scores(
    mode: str,
    profile_text: str,
    jobs: list[Any],
    *,
    ai: Any = None,
) -> tuple[dict[str, float], str, str]:
    """Return ``(scores, mode_used, warning)``."""
    if mode == "off" or not jobs:
        return ({}, "off", "")
    texts = {j.id: f"{j.title}\n{j.description or ''}" for j in jobs}
    if mode == "embeddings":
        if ai is None or not getattr(ai, "enabled", False):
            return (
                local_scores(profile_text, texts),
                "local",
                "Embeddings need an OpenAI key; used local similarity instead.",
            )
        try:
            return (embedding_scores(ai, profile_text, jobs), "embeddings", "")
        except Exception as exc:  # noqa: BLE001 - semantic is advisory; never fail the hunt
            logger.warning("Hunt embeddings failed, falling back to local: %s", exc)
            return (
                local_scores(profile_text, texts),
                "local",
                f"Embeddings failed ({type(exc).__name__}); used local similarity instead.",
            )
    return (local_scores(profile_text, texts), "local", "")


__all__ = [
    "LocalSemanticModel",
    "compute_semantic_scores",
    "embedding_scores",
    "local_scores",
]
