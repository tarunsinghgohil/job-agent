"""Resume text extraction, section detection, and skill extraction.

Deterministic on purpose. AI is not required to read a resume, so uploads keep
working (and stay free) when no provider key is configured.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.normalize import norm_text

logger = logging.getLogger(__name__)

# Canonical skill vocabulary used for deterministic extraction. Matching is
# alias-aware so "ReactJS", "React.js" and "React" all resolve to one skill.
SKILL_VOCABULARY: dict[str, tuple[str, ...]] = {
    "React": ("react", "react.js", "reactjs", "react js"),
    "React Native": ("react native",),
    "Next.js": ("next.js", "nextjs", "next js"),
    "JavaScript": ("javascript", "es6", "ecmascript"),
    "TypeScript": ("typescript", "ts"),
    "HTML": ("html", "html5"),
    "CSS": ("css", "css3"),
    "Sass": ("sass", "scss"),
    "Tailwind CSS": ("tailwind", "tailwind css"),
    "Material UI": ("material ui", "mui", "material-ui"),
    "Bootstrap": ("bootstrap",),
    "Redux": ("redux",),
    "Redux Toolkit": ("redux toolkit", "rtk"),
    "Zustand": ("zustand",),
    "React Query": ("react query", "tanstack query"),
    "React Router": ("react router",),
    "GraphQL": ("graphql", "apollo"),
    "REST APIs": ("rest api", "rest apis", "restful"),
    "Node.js": ("node.js", "nodejs", "node js"),
    "Express.js": ("express.js", "express", "expressjs"),
    "Python": ("python",),
    "Django": ("django",),
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "Java": ("java",),
    "Go": ("golang", "go lang"),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "MongoDB": ("mongodb", "mongo"),
    "Redis": ("redis",),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "CI/CD": ("ci/cd", "continuous integration", "continuous delivery"),
    "Git": ("git", "github", "gitlab", "bitbucket"),
    "Jest": ("jest",),
    "Vitest": ("vitest",),
    "React Testing Library": ("react testing library", "testing library"),
    "Cypress": ("cypress",),
    "Playwright": ("playwright",),
    "Webpack": ("webpack",),
    "Vite": ("vite",),
    "Babel": ("babel",),
    "Figma": ("figma",),
    "Accessibility": ("accessibility", "a11y", "wcag"),
    "Performance Optimization": ("performance optimization", "web vitals", "lighthouse"),
    "Agile": ("agile", "scrum", "kanban"),
    "Microservices": ("microservices",),
    "WebSockets": ("websocket", "websockets", "socket.io"),
    "Jenkins": ("jenkins",),
    "Terraform": ("terraform",),
    "OpenAI": ("openai", "gpt", "llm"),
}

# Headings that mark a section. Order does not matter; position in the text does.
SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "profile", "objective", "about me", "professional summary"),
    "experience": (
        "experience", "work experience", "employment", "professional experience",
        "work history", "career history",
    ),
    "education": ("education", "academic", "qualifications", "academics"),
    "skills": ("skills", "technical skills", "core competencies", "technologies", "tech stack"),
    "projects": ("projects", "personal projects", "key projects", "selected projects"),
    "certifications": ("certifications", "certificates", "licenses", "courses"),
    "achievements": ("achievements", "awards", "honors", "accomplishments"),
    "contact": ("contact", "contact information", "personal details"),
}

_MAX_HEADING_WORDS = 6


@dataclass(slots=True)
class ParsedResume:
    text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text.strip()) and not self.error


def extract_text(path: str | Path, extension: str = "") -> str:
    """Extract plain text from a PDF or DOCX file."""
    path = Path(path)
    ext = (extension or path.suffix).lower()

    if ext == ".pdf":
        import fitz  # PyMuPDF

        parts: list[str] = []
        with fitz.open(path) as doc:
            for page in doc:
                parts.append(page.get_text("text"))
        return "\n".join(parts)

    if ext == ".docx":
        import docx

        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs]
        # Table cells often hold skills grids, which would otherwise be lost.
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)

    raise ValueError(f"Unsupported resume format: {ext!r}")


def _looks_like_heading(line: str) -> str | None:
    """Return the canonical section name when a line reads as its heading."""
    stripped = line.strip().strip(":").strip()
    if not stripped or len(stripped.split()) > _MAX_HEADING_WORDS:
        return None
    normalized = norm_text(stripped)
    if not normalized:
        return None
    for section, aliases in SECTION_PATTERNS.items():
        if normalized in aliases:
            return section
    return None


def detect_sections(text: str) -> dict[str, str]:
    """Split resume text into named sections by heading lines."""
    lines = text.splitlines()
    sections: dict[str, list[str]] = {}
    current = "header"

    for line in lines:
        heading = _looks_like_heading(line)
        if heading:
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return {
        name: "\n".join(body).strip()
        for name, body in sections.items()
        if "\n".join(body).strip()
    }


def extract_skills(text: str) -> list[str]:
    """Find canonical skills present in the text, preserving vocabulary order."""
    haystack = norm_text(text)
    found: list[str] = []
    for canonical, aliases in SKILL_VOCABULARY.items():
        for alias in aliases:
            needle = norm_text(alias)
            if needle and needle in haystack:
                found.append(canonical)
                break
    return found


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,13}\d")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s,;)\]]+", re.I)


def parse(path: str | Path, extension: str = "") -> ParsedResume:
    """Full parse. Never raises: failures come back on ``error``."""
    try:
        text = extract_text(path, extension)
    except Exception as exc:
        logger.warning("Resume text extraction failed for %s: %s", path, exc)
        return ParsedResume(error=f"Could not read the document: {exc}")

    if not text.strip():
        return ParsedResume(
            text="",
            error=(
                "No text could be extracted. The file is most likely a scanned "
                "image; a text-based PDF or DOCX is required."
            ),
        )

    return ParsedResume(
        text=text,
        sections=detect_sections(text),
        skills=extract_skills(text),
        emails=sorted(set(_EMAIL_RE.findall(text)))[:5],
        phones=sorted({re.sub(r"[\s-]", "", p) for p in _PHONE_RE.findall(text) if len(re.sub(r"[^0-9]", "", p)) >= 10})[:3],
        links=sorted(set(_URL_RE.findall(text)))[:10],
    )
