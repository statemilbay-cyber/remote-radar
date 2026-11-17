"""SQLite persistence: every job ever seen, with first/last-seen timestamps and a fetch log."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from .models import Job, parse_datetime
from .salary import Salary

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid             TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    dedupe_key      TEXT NOT NULL,
    url             TEXT NOT NULL,
    apply_url       TEXT,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    description     TEXT,
    tags            TEXT NOT NULL DEFAULT '[]',
    employment_type TEXT,
    posted_at       TEXT,
    salary_min_usd  REAL,
    salary_max_usd  REAL,
    salary_text     TEXT,
    salary_period   TEXT,
    salary_approx   INTEGER NOT NULL DEFAULT 0,
    countries       TEXT NOT NULL DEFAULT '[]',
    timezones       TEXT NOT NULL DEFAULT '[]',
    attribution     TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_last_seen ON jobs (last_seen);
CREATE INDEX IF NOT EXISTS jobs_dedupe_key ON jobs (dedupe_key);

CREATE TABLE IF NOT EXISTS fetch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    jobs        INTEGER NOT NULL,
    error       TEXT
);
"""

_COLUMNS = (
    "uid", "source", "source_id", "dedupe_key", "url", "apply_url", "title", "company",
    "location", "description", "tags", "employment_type", "posted_at", "salary_min_usd",
    "salary_max_usd", "salary_text", "salary_period", "salary_approx", "countries", "timezones",
    "attribution",
)  # fmt: skip


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def upsert(self, jobs: Iterable[Job], *, seen_at: datetime) -> int:
        """Insert or refresh jobs; returns the number of distinct jobs written."""
        stamp = _iso(seen_at)
        rows = {job.uid: {**_to_row(job), "first_seen": stamp, "last_seen": stamp} for job in jobs}
        if not rows:
            return 0
        columns = (*_COLUMNS, "first_seen", "last_seen")
        updates = ", ".join(
            f"{c} = excluded.{c}" for c in columns if c not in {"uid", "first_seen"}
        )
        sql = (
            f"INSERT INTO jobs ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)}) "
            f"ON CONFLICT(uid) DO UPDATE SET {updates}"
        )
        with self._db:
            self._db.executemany(sql, rows.values())
        return len(rows)

    def active_jobs(self, *, since: datetime) -> list[Job]:
        cursor = self._db.execute(
            "SELECT * FROM jobs WHERE last_seen >= ? ORDER BY last_seen DESC", (_iso(since),)
        )
        return [_from_row(row) for row in cursor]

    def get(self, uid: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE uid = ?", (uid,)).fetchone()
        return _from_row(row) if row else None

    def log_fetch(
        self, source: str, started: datetime, finished: datetime, jobs: int, error: str | None
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO fetch_log (source, started_at, finished_at, jobs, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (source, _iso(started), _iso(finished), jobs, error),
            )


def _to_row(job: Job) -> dict[str, Any]:
    salary = job.salary
    return {
        "uid": job.uid,
        "source": job.source,
        "source_id": job.source_id,
        "dedupe_key": job.dedupe_key,
        "url": job.url,
        "apply_url": job.apply_url,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description,
        "tags": json.dumps(job.tags, ensure_ascii=False),
        "employment_type": job.employment_type,
        "posted_at": _iso(job.posted_at) if job.posted_at else None,
        "salary_min_usd": salary.min_usd if salary else None,
        "salary_max_usd": salary.max_usd if salary else None,
        "salary_text": salary.text if salary else None,
        "salary_period": salary.period if salary else None,
        "salary_approx": int(bool(salary and salary.approximate)),
        "countries": json.dumps(job.countries, ensure_ascii=False),
        "timezones": json.dumps(job.timezones),
        "attribution": job.attribution,
    }


def _from_row(row: sqlite3.Row) -> Job:
    salary = None
    if row["salary_min_usd"] is not None or row["salary_max_usd"] is not None:
        salary = Salary(
            min_usd=row["salary_min_usd"],
            max_usd=row["salary_max_usd"],
            text=row["salary_text"] or "",
            approximate=bool(row["salary_approx"]),
            period=row["salary_period"] or "year",
        )
    return Job(
        source=row["source"],
        source_id=row["source_id"],
        url=row["url"],
        apply_url=row["apply_url"],
        title=row["title"],
        company=row["company"],
        location=row["location"] or "",
        description=row["description"] or "",
        tags=json.loads(row["tags"] or "[]"),
        employment_type=row["employment_type"],
        posted_at=parse_datetime(row["posted_at"]),
        salary=salary,
        countries=json.loads(row["countries"] or "[]"),
        timezones=json.loads(row["timezones"] or "[]"),
        attribution=row["attribution"] or "",
    )
