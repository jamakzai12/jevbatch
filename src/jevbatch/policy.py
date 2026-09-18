from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from typesafe_sdk import Choice, Noul, Score


def load_policy(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError(f"Invalid policy: {path}")
    return data


def build_questions(policy: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, q in policy["questions"].items():
        t = q["type"]
        if t == "choice":
            out[name] = Choice(instructions=q["instructions"], criteria=q["criteria"])
        elif t == "score":
            out[name] = Score(instructions=q["instructions"], criteria=q["criteria"])
        elif t == "noul":
            out[name] = Noul(instructions=q["instructions"])
        else:
            raise ValueError(f"Unknown question type: {t}")
    return out


def extract_metrics(answers: dict[str, Any], policy_name: str) -> dict[str, float]:
    """Normalize answers into floats used by route expressions."""
    m: dict[str, float] = {}
    for name, ans in answers.items():
        t = getattr(ans, "type", None) or ans.__class__.__name__.lower()
        if hasattr(ans, "noul"):
            m[name] = float(ans.noul)
            if name == "is_urgent":
                m["urgency"] = float(ans.noul)
            if name == "is_spammy":
                m["spam"] = float(ans.noul)
            if name == "is_useful":
                m["useful"] = float(ans.noul)
        elif hasattr(ans, "score"):
            m[name] = float(ans.score)
            if name == "frustration":
                m["frustration"] = float(ans.score)
            if name == "on_brand":
                # 0..2 scale → rough 0..1 for thresholds written that way
                m["on_brand"] = float(ans.score) / 2.0
        if hasattr(ans, "confidence") and ans.confidence is not None:
            m["confidence"] = float(ans.confidence)
            m[f"{name}_confidence"] = float(ans.confidence)
    if "confidence" not in m:
        m["confidence"] = 1.0
    return m


def apply_routes(metrics: dict[str, float], routes: list[dict[str, str]]) -> str:
    env = dict(metrics)
    for rule in routes:
        expr = rule["when"]
        try:
            if expr == "true" or eval(expr, {"__builtins__": {}}, env):  # noqa: S307 — trusted policy file
                return rule["route"]
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Bad route expression {expr!r}: {e}") from e
    return "review"
