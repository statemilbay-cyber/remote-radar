"""Deterministic sample data: used by the end-to-end tests, screenshots and docs.

The companies are fictional. Every rule the dashboard shows (eligible, excluded by
location, below the pay floor, non-engineering title) is represented at least once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Job
from .profile import load_profile
from .report import SourceInfo, write_reports
from .salary import Salary
from .scoring import rank

DEMO_NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)


def _job(
    n: int,
    title: str,
    company: str,
    description: str,
    location: str,
    engagement: str | None,
    salary: Salary | None,
    days_ago: int,
) -> Job:
    return Job(
        source="demo",
        source_id=str(n),
        url=f"https://example.com/jobs/{n}",
        apply_url=f"https://example.com/apply/{n}",
        title=title,
        company=company,
        description=description,
        location=location,
        employment_type=engagement,
        salary=salary,
        posted_at=DEMO_NOW - timedelta(days=days_ago),
        attribution="Demo board",
    )


def sample_jobs() -> list[Job]:
    return [
        _job(
            1,
            "Senior QA Automation Engineer (Playwright)",
            "Northwind Labs",
            "Playwright and TypeScript end-to-end suites, API testing, GitHub Actions.\n"
            "Async-first team, written communication.",
            "Worldwide",
            "contract",
            Salary.from_amounts(6000, 8000, "USD", "month"),
            1,
        ),
        _job(
            2,
            "Python Data Engineer",
            "Globex Analytics",
            "Python, Airflow, dbt and PostgreSQL data pipelines. ETL from 40 sources.",
            "Anywhere in the World",
            "full_time",
            Salary.from_amounts(90_000, 120_000, "USD", "year"),
            2,
        ),
        _job(
            3,
            "Workflow Automation Engineer (n8n)",
            "Initech",
            "Build n8n workflows, webhooks and API integrations with LLM steps (Claude, OpenAI).",
            "Remote (worldwide)",
            "contract",
            Salary.from_amounts(45, 60, "USD", "hour"),
            4,
        ),
        _job(
            4,
            "Full-Stack Developer (Next.js, Telegram Mini Apps)",
            "Umbrella Apps",
            "TypeScript, React, Next.js, Telegram mini app, Supabase.",
            "Worldwide",
            "part_time",
            None,
            6,
        ),
        _job(
            5,
            "Backend Engineer (Python)",
            "Hooli",
            "Python, FastAPI, PostgreSQL.",
            "USA only",
            "full_time",
            Salary.from_amounts(150_000, 180_000),
            3,
        ),
        _job(
            6,
            "Scraping Engineer",
            "Vandelay Data",
            "Web scraping with Scrapy and Playwright, data pipelines.",
            "Europe",
            "contract",
            Salary.from_amounts(5000, None, "EUR", "month"),
            5,
        ),
        _job(
            7,
            "Junior QA Tester",
            "Stark Retail",
            "Manual testing and some Selenium and Playwright test automation.",
            "Worldwide",
            "full_time",
            Salary.from_amounts(600, 800, "USD", "month"),
            2,
        ),
        _job(
            8,
            "Account Executive",
            "Wayne Software",
            "Sell our Playwright-based QA automation platform.",
            "Worldwide",
            "full_time",
            None,
            1,
        ),
    ]


def build_demo(out_dir: str | Path) -> dict[str, Path]:
    ranked = rank(sample_jobs(), load_profile(), now=DEMO_NOW)
    sources = [SourceInfo("demo", "Demo board", "https://example.com", len(ranked))]
    return write_reports(ranked, out_dir, generated_at=DEMO_NOW, sources=sources, top_n=5)
