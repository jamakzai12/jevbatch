from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from jevbatch.cli import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _ticket_response() -> SimpleNamespace:
    return SimpleNamespace(
        model="jev-latest",
        answers={
            "department": SimpleNamespace(choice="billing", confidence=0.92, type="choice"),
            "frustration": SimpleNamespace(score=1.8, confidence=0.88, type="score"),
            "is_urgent": SimpleNamespace(noul=0.97, confidence=0.9, type="noul"),
        },
    )


def _reply_response(*, spam: float, useful: float, on_brand: float) -> SimpleNamespace:
    return SimpleNamespace(
        model="jev-latest",
        answers={
            "is_spammy": SimpleNamespace(noul=spam, confidence=0.9, type="noul"),
            "is_useful": SimpleNamespace(noul=useful, confidence=0.9, type="noul"),
            "on_brand": SimpleNamespace(score=on_brand, confidence=0.9, type="score"),
        },
    )


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
    assert "run" in result.stdout
    assert "policies" in result.stdout


def test_missing_api_key(tmp_path):
    data = ROOT / "examples" / "data" / "sample_tickets.csv"
    policy = ROOT / "examples" / "policies" / "tickets.yaml"
    out = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
    with patch.dict(os.environ, env, clear=True), patch("jevbatch.cli.load_dotenv"):
        result = runner.invoke(
            app,
            ["run", str(data), "-p", str(policy), "-o", str(out)],
        )
    assert result.exit_code == 1
    assert "TYPESAFE_API_KEY missing" in result.stdout


def test_run_tickets_csv_mocked(tmp_path):
    data = ROOT / "examples" / "data" / "sample_tickets.csv"
    policy = ROOT / "examples" / "policies" / "tickets.yaml"
    out = tmp_path / "tickets.json"
    client = MagicMock()
    client.system_one.return_value = _ticket_response()

    with (
        patch.dict(os.environ, {"TYPESAFE_API_KEY": "test"}, clear=False),
        patch("jevbatch.cli.load_dotenv"),
        patch("jevbatch.cli.TypeSafeClient", return_value=client),
    ):
        result = runner.invoke(
            app,
            ["run", str(data), "-p", str(policy), "-o", str(out), "-n", "2"],
        )

    assert result.exit_code == 0, result.stdout
    assert client.system_one.call_count == 2
    payload = json.loads(out.read_text())
    assert len(payload) == 2
    assert payload[0]["route"] == "escalate"
    assert payload[0]["choices"]["department"] == "billing"
    assert "metrics" in payload[0]


def test_run_jsonl_mocked(tmp_path):
    data = tmp_path / "rows.jsonl"
    data.write_text(
        json.dumps({"id": "a", "text": "Need a refund ASAP"}) + "\n"
        + json.dumps({"id": "b", "text": "Where are the docs?"})
        + "\n"
    )
    policy = ROOT / "examples" / "policies" / "tickets.yaml"
    out = tmp_path / "jsonl.json"
    client = MagicMock()
    client.system_one.return_value = _ticket_response()

    with (
        patch.dict(os.environ, {"TYPESAFE_API_KEY": "test"}, clear=False),
        patch("jevbatch.cli.load_dotenv"),
        patch("jevbatch.cli.TypeSafeClient", return_value=client),
    ):
        result = runner.invoke(
            app,
            ["run", str(data), "-p", str(policy), "-o", str(out)],
        )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(out.read_text())
    assert [row["id"] for row in payload] == ["a", "b"]
    assert all(row["route"] == "escalate" for row in payload)


def test_run_replies_mocked(tmp_path):
    data = ROOT / "examples" / "data" / "sample_replies.csv"
    policy = ROOT / "examples" / "policies" / "replies.yaml"
    out = tmp_path / "replies.json"
    client = MagicMock()
    client.system_one.side_effect = [
        _reply_response(spam=0.1, useful=0.8, on_brand=1.8),
        _reply_response(spam=0.9, useful=0.1, on_brand=0.2),
        _reply_response(spam=0.1, useful=0.8, on_brand=1.8),
        _reply_response(spam=0.1, useful=0.1, on_brand=0.2),
        _reply_response(spam=0.1, useful=0.8, on_brand=1.8),
        _reply_response(spam=0.95, useful=0.05, on_brand=0.1),
    ]

    with (
        patch.dict(os.environ, {"TYPESAFE_API_KEY": "test"}, clear=False),
        patch("jevbatch.cli.load_dotenv"),
        patch("jevbatch.cli.TypeSafeClient", return_value=client),
    ):
        result = runner.invoke(
            app,
            ["run", str(data), "-p", str(policy), "-o", str(out)],
        )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(out.read_text())
    assert [row["route"] for row in payload] == [
        "post",
        "block",
        "post",
        "rewrite",
        "post",
        "block",
    ]
    # state dict includes brand + platform/draft
    first_state = client.system_one.call_args_list[0].kwargs["state"]
    assert "brand" in first_state
    assert "draft" in first_state


def test_policies_lists_bundled_yaml():
    result = runner.invoke(app, ["policies"])
    assert result.exit_code == 0
    assert "tickets.yaml" in result.stdout
    assert "replies.yaml" in result.stdout
