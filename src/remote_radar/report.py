"""Report writers: static HTML dashboard, Markdown digest, CSV and JSON exports."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__
from .scoring import ENGAGEMENT_LABELS, Assessment


@dataclass(frozen=True, slots=True)
class SourceInfo:
    name: str
    label: str
    homepage: str
    jobs: int
    error: str | None = None


def to_row(a: Assessment, now: datetime) -> dict[str, Any]:
    job, salary = a.job, a.job.salary
    return {
        "uid": job.uid,
        "score": a.score,
        "eligible": a.eligible,
        "title": job.title,
        "company": job.company or "Unknown company",
        "track": a.track.key if a.track else None,
        "track_label": a.track.label if a.track else None,
        "track_short": a.track.short if a.track else None,
        "monthly_usd": round(a.monthly_usd) if a.monthly_usd else None,
        "salary_text": salary.text if salary else None,
        "salary_approx": bool(salary and salary.approximate),
        "location": job.location or "Not stated",
        "engagement": a.engagement,
        "engagement_label": ENGAGEMENT_LABELS.get(a.engagement or "", "Not stated"),
        "posted_at": job.posted_at.date().isoformat() if job.posted_at else None,
        "age_days": (now - job.posted_at).days if job.posted_at else None,
        "source": job.attribution or job.source,
        "url": job.url,
        "apply_url": job.apply_url,
        "required_years": a.required_years,
        "reasons": a.reasons,
        "flags": a.flags,
        "terms": a.terms,
        "also_on": a.also_on,
    }


def write_reports(
    assessments: Sequence[Assessment],
    out_dir: str | Path,
    *,
    generated_at: datetime,
    sources: Sequence[SourceInfo],
    top_n: int = 10,
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [to_row(a, generated_at) for a in assessments]
    paths = {
        "html": out / "index.html",
        "markdown": out / "top.md",
        "csv": out / "jobs.csv",
        "json": out / "jobs.json",
    }
    paths["json"].write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(timespec="seconds"),
                "version": __version__,
                "sources": [asdict(s) for s in sources],
                "jobs": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_csv(rows, paths["csv"])
    paths["markdown"].write_text(render_markdown(rows, generated_at, top_n), encoding="utf-8")
    paths["html"].write_text(render_html(rows, generated_at, sources), encoding="utf-8")
    return paths


def render_markdown(rows: Sequence[dict[str, Any]], generated_at: datetime, top_n: int) -> str:
    best = [r for r in rows if r["eligible"]][:top_n]
    lines = [
        f"# Remote Radar: top {len(best)} matches",
        "",
        f"Generated {generated_at:%Y-%m-%d %H:%M} UTC from {len(rows)} unique roles.",
        "",
        "| # | Score | Role | Company | Track | Pay (USD/mo) | Location | Type | Source |",
        "|---|------:|------|---------|-------|-------------:|----------|------|--------|",
    ]
    for i, r in enumerate(best, 1):
        pay = f"{r['monthly_usd']:,}" if r["monthly_usd"] else "n/a"
        lines.append(
            f"| {i} | {r['score']} | [{_md(r['title'])}]({r['url']}) | {_md(r['company'])} | "
            f"{r['track_short']} | {pay} | {_md(r['location'])[:40]} | {r['engagement_label']} | "
            f"{r['source']} |"
        )
    lines.append("")
    for i, r in enumerate(best, 1):
        lines += [f"## {i}. {r['title']} at {r['company']} ({r['score']}/100)", ""]
        lines += [f"- {reason}" for reason in r["reasons"]]
        if r["apply_url"] and r["apply_url"] != r["url"]:
            lines.append(f"- Apply: {r['apply_url']}")
        lines += [f"- Listing: {r['url']} (via {r['source']})", ""]
    return "\n".join(lines)


def render_html(
    rows: Sequence[dict[str, Any]], generated_at: datetime, sources: Sequence[SourceInfo]
) -> str:
    env = Environment(
        loader=PackageLoader("remote_radar", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    eligible = [r for r in rows if r["eligible"]]
    paid = [r["monthly_usd"] for r in eligible if r["monthly_usd"]]
    stats = {
        "scanned": len(rows),
        "eligible": len(eligible),
        "contract": sum(1 for r in eligible if r["engagement"] in {"contract", "part_time"}),
        "median_pay": sorted(paid)[len(paid) // 2] if paid else None,
    }
    tracks = sorted({(r["track"], r["track_short"]) for r in rows if r["track"]})
    return env.get_template("dashboard.html.j2").render(
        rows=list(rows),
        stats=stats,
        tracks=tracks,
        sources=sources,
        generated_at=generated_at,
        version=__version__,
    )


def _write_csv(rows: Sequence[dict[str, Any]], path: Path) -> None:
    fields = [
        "score", "eligible", "title", "company", "track", "monthly_usd", "salary_text",
        "location", "engagement", "posted_at", "source", "url", "apply_url", "flags", "reasons",
    ]  # fmt: skip
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {**r, "flags": "; ".join(r["flags"]), "reasons": " | ".join(r["reasons"])}
            )


def _md(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")
