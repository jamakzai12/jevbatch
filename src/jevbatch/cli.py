from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import polars as pl
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from typesafe_sdk import TypeSafeClient

from jevbatch.policy import apply_routes, build_questions, extract_metrics, load_policy

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()
ROOT = Path(__file__).resolve().parents[2]


def _client() -> TypeSafeClient:
    load_dotenv(ROOT / ".env")
    if not os.getenv("TYPESAFE_API_KEY"):
        console.print("[red]TYPESAFE_API_KEY missing[/red]")
        raise typer.Exit(1)
    return TypeSafeClient()


def _row_state(row: dict, policy: dict) -> object:
    if "brand" in policy:
        state = {"brand": policy["brand"]}
        for f in policy.get("state_fields", ["draft"]):
            state[f] = row.get(f)
        return state
    field = policy.get("state_field", "text")
    return row[field]


@app.command()
def run(
    data: Path = typer.Argument(..., help="CSV/JSONL input"),
    policy: Path = typer.Option(..., "--policy", "-p", help="YAML policy"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="JSON output path"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
) -> None:
    """Score each row with Jev and apply policy routes."""
    if not data.exists():
        console.print(f"[red]Input not found: {data}[/red]")
        raise typer.Exit(1)
    if not policy.exists():
        console.print(f"[red]Policy not found: {policy}[/red]")
        raise typer.Exit(1)
    pol = load_policy(policy)
    questions = build_questions(pol)
    routes = pol.get("routes", [{"when": "true", "route": "auto"}])
    model = pol.get("model", "jev-latest")

    if data.suffix.lower() == ".csv":
        df = pl.read_csv(data)
    else:
        df = pl.read_ndjson(data)
    if limit:
        df = df.head(limit)

    client = _client()
    rows_out: list[dict] = []
    for row in df.iter_rows(named=True):
        resp = client.system_one(state=_row_state(row, pol), model=model, questions=questions)
        metrics = extract_metrics(resp.answers, pol.get("name", ""))
        route = apply_routes(metrics, routes)
        choices = {
            k: getattr(v, "choice", None)
            for k, v in resp.answers.items()
            if getattr(v, "choice", None) is not None
        }
        rec = {
            **{k: row[k] for k in row if k in ("id", "platform", "draft", "text", "name")},
            "route": route,
            "metrics": {k: round(v, 4) for k, v in metrics.items()},
            "choices": choices,
            "model": resp.model,
        }
        rows_out.append(rec)

    out_path = output or (ROOT / "data" / f"scored_{pol.get('name', 'out')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows_out, indent=2))

    table = Table(title=f"{pol.get('name')} → {out_path.name}")
    table.add_column("id")
    table.add_column("route")
    table.add_column("metrics")
    for r in rows_out:
        table.add_row(str(r.get("id", "")), r["route"], json.dumps(r["metrics"]))
    console.print(table)
    console.print(f"[green]Wrote {out_path}[/green]")


@app.command("policies")
def list_policies() -> None:
    """List bundled policy files."""
    for p in sorted((ROOT / "examples" / "policies").glob("*.yaml")):
        console.print(f"• {p.name}")


if __name__ == "__main__":
    app()
