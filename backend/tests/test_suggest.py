"""Type-ahead suggestions: ranking, aliases, typos, personal data, API."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.db.models.identity import User
from app.services.suggest import invalidate_user, suggest

USER_ID = "s" * 32


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, future=True)()
    session.add(User(id=USER_ID, email="s@example.test", password_hash="x"))
    session.flush()
    invalidate_user(USER_ID)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def labels(db, kind, q, **kw):
    return [i["label"] for i in suggest(db, USER_ID, kind, q, **kw)["items"]]


@pytest.mark.parametrize(
    ("kind", "q", "first"),
    [
        ("location", "jai", "Jaipur"),
        ("location", "bang", "Bengaluru"),       # via the "Bangalore" alias
        ("location", "banglore", "Bengaluru"),   # typo
        ("location", "gurgaon", "Gurugram"),     # old name
        ("role", "front eng", "Frontend Engineer"),
        ("role", "sr react", "Senior React Developer"),  # abbreviation
        ("skill", "reac", "React"),
        ("skill", "typscript", "TypeScript"),    # typo
        ("skill", "mern", "MERN"),
        ("company", "raz", "Razorpay"),
        ("industry", "health", "Healthcare"),
        ("employment_type", "full", "Full-time"),
    ],
)
def test_first_suggestion(db, kind, q, first):
    assert labels(db, kind, q)[0] == first


def test_alias_is_resolved_to_the_canonical_value(db):
    item = suggest(db, USER_ID, "skill", "reactjs")["items"][0]
    assert item["value"] == "React"
    assert item["exact"] is True
    assert "reactjs" in item["hint"]


def test_employment_type_values_match_what_the_matcher_stores(db):
    items = suggest(db, USER_ID, "employment_type", "")["items"]
    assert {i["value"] for i in items} >= {"full_time", "contract", "part_time"}
    assert suggest(db, USER_ID, "employment_type", "full time")["items"][0]["value"] == "full_time"


def test_short_unrelated_queries_do_not_return_noise(db):
    assert "Senior Laravel Developer" not in labels(db, "role", "senior rea")
    assert labels(db, "skill", "zzqx") == []


def test_exclude_hides_already_chosen_values(db):
    assert "Jaipur" not in labels(db, "location", "jai", exclude=["Jaipur"])


def test_limit_is_respected(db):
    assert len(labels(db, "role", "developer", limit=3)) == 3


def test_personal_data_ranks_first_and_is_canonicalized(db):
    from app.db.models.hunt import HuntConfig

    db.add(HuntConfig(user_id=USER_ID, target_roles=["Design Systems Engineer"], skills=["React.js", "Recoil"],
                      location_tiers=[{"name": "Pune", "work_modes": ["onsite"], "places": ["Kharadi, Pune"]}]))
    db.flush()
    invalidate_user(USER_ID)
    roles = suggest(db, USER_ID, "role", "design")["items"]
    assert roles[0]["label"] == "Design Systems Engineer"
    assert roles[0]["source"] == "yours"
    skills = labels(db, "skill", "re")
    assert "React.js" not in skills          # folded into the canonical "React"
    assert "Recoil" in skills
    assert labels(db, "location", "khar")[0] == "Kharadi, Pune"
    # Custom-query suggestions combine hunt roles with hunt locations.
    assert "Design Systems Engineer Kharadi, Pune" in labels(db, "query", "design sys", limit=10)


def test_unknown_kind_is_rejected(db):
    with pytest.raises(ValueError):
        suggest(db, USER_ID, "nope", "x")


def test_api_endpoint(auth_client):
    response = auth_client.get("/api/v1/suggest", params={"kind": "location", "q": "jai"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"][0]["label"] == "Jaipur"
    assert "private" in response.headers["cache-control"]
    assert auth_client.get("/api/v1/suggest", params={"kind": "bad", "q": "x"}).status_code in (400, 422)


def test_api_requires_auth(client):
    assert client.get("/api/v1/suggest", params={"kind": "skill", "q": "re"}).status_code == 401
