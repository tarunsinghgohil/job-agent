"""Type-ahead suggestions for form fields (locations, roles, skills, ...)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from app.core.deps import Context, DbSession
from app.core.errors import ValidationError
from app.services.suggest import KINDS, suggest

router = APIRouter(tags=["suggest"])


class SuggestionOut(BaseModel):
    value: str
    label: str
    hint: str = ""
    source: str = "catalog"
    # True when the query equals this entry or one of its aliases, so the UI
    # can resolve "reactjs" + Enter to the canonical "React".
    exact: bool = False


class SuggestionsOut(BaseModel):
    kind: str
    q: str
    items: list[SuggestionOut] = Field(default_factory=list)


@router.get("/suggest", response_model=SuggestionsOut)
def get_suggestions(
    response: Response,
    db: DbSession,
    ctx: Context,
    kind: str = Query(..., description=", ".join(KINDS)),
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=8, ge=1, le=25),
    exclude: list[str] = Query(default_factory=list),
) -> SuggestionsOut:
    if kind not in KINDS:
        raise ValidationError(f"Unknown suggestion kind {kind!r}. Use one of: {', '.join(KINDS)}.")
    # Private because results include the user's own data; short because
    # that data changes when they edit their profile or preferences.
    response.headers["Cache-Control"] = "private, max-age=60"
    return SuggestionsOut(**suggest(db, ctx.user_id, kind, q, limit=limit, exclude=exclude))
