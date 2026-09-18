from pathlib import Path
from types import SimpleNamespace

import pytest

from jevbatch.policy import apply_routes, build_questions, extract_metrics, load_policy


ROOT = Path(__file__).resolve().parents[1]


def test_apply_routes_escalate():
    routes = [
        {"when": "confidence < 0.45", "route": "review"},
        {"when": "urgency >= 0.85 or frustration >= 1.6", "route": "escalate"},
        {"when": "true", "route": "auto"},
    ]
    assert apply_routes({"confidence": 0.9, "urgency": 0.99, "frustration": 1.0}, routes) == "escalate"
    assert apply_routes({"confidence": 0.2, "urgency": 0.1, "frustration": 0.0}, routes) == "review"
    assert apply_routes({"confidence": 0.9, "urgency": 0.1, "frustration": 0.0}, routes) == "auto"


def test_apply_routes_reply_gate():
    routes = [
        {"when": "spam >= 0.65", "route": "block"},
        {"when": "useful < 0.4 or on_brand < 0.35", "route": "rewrite"},
        {"when": "true", "route": "post"},
    ]
    assert apply_routes({"spam": 0.9, "useful": 0.8, "on_brand": 0.9}, routes) == "block"
    assert apply_routes({"spam": 0.1, "useful": 0.2, "on_brand": 0.9}, routes) == "rewrite"
    assert apply_routes({"spam": 0.1, "useful": 0.8, "on_brand": 0.9}, routes) == "post"


def test_apply_routes_bad_expression():
    with pytest.raises(ValueError, match="Bad route expression"):
        apply_routes({"confidence": 1.0}, [{"when": "nope(", "route": "x"}])


def test_load_example_policies():
    for name in ("tickets.yaml", "replies.yaml"):
        pol = load_policy(ROOT / "examples" / "policies" / name)
        assert "questions" in pol
        assert pol["routes"]


def test_load_policy_rejects_invalid(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: nope\n")
    with pytest.raises(ValueError, match="Invalid policy"):
        load_policy(bad)


def test_build_questions_types():
    pol = load_policy(ROOT / "examples" / "policies" / "tickets.yaml")
    qs = build_questions(pol)
    assert set(qs) == {"department", "frustration", "is_urgent"}


def test_build_questions_unknown_type():
    with pytest.raises(ValueError, match="Unknown question type"):
        build_questions({"questions": {"x": {"type": "essay", "instructions": "nope"}}})


def test_extract_metrics_aliases():
    answers = {
        "is_urgent": SimpleNamespace(noul=0.91, confidence=0.8, type="noul"),
        "is_spammy": SimpleNamespace(noul=0.12, confidence=0.7, type="noul"),
        "is_useful": SimpleNamespace(noul=0.6, confidence=0.75, type="noul"),
        "frustration": SimpleNamespace(score=1.7, confidence=0.85, type="score"),
        "on_brand": SimpleNamespace(score=1.5, confidence=0.9, type="score"),
        "department": SimpleNamespace(choice="billing", confidence=0.95, type="choice"),
    }
    m = extract_metrics(answers, "support-tickets")
    assert m["urgency"] == pytest.approx(0.91)
    assert m["spam"] == pytest.approx(0.12)
    assert m["useful"] == pytest.approx(0.6)
    assert m["frustration"] == pytest.approx(1.7)
    assert m["on_brand"] == pytest.approx(0.75)
    assert m["confidence"] == pytest.approx(0.95)
    assert m["department_confidence"] == pytest.approx(0.95)


def test_extract_metrics_default_confidence():
    answers = {"is_urgent": SimpleNamespace(noul=0.4, type="noul")}
    m = extract_metrics(answers, "x")
    assert m["confidence"] == 1.0
    assert m["urgency"] == pytest.approx(0.4)
