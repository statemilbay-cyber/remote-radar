"""Core data model shared by every source, the store and the scorer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from .salary import Salary
from .text import normalize_key

ENGAGEMENTS = ("contract", "part_time", "full_time", "internship")


@dataclass(slots=True)
class Job:
    """One job posting, normalised. Everything a source knows goes here; nothing else does."""

    source: str
    source_id: str
    url: str
    title: str
    company: str
    description: str = ""
    location: str = ""
    apply_url: str | None = None
    tags: list[str] = field(default_factory=list)
    employment_type: str | None = None
    posted_at: datetime | None = None
    salary: Salary | None = None
    #: Explicit country list published by the source (who may apply), if any.
    countries: list[str] = field(default_factory=list)
    #: Explicit UTC offsets the employer works in, if the source publishes them.
    timezones: list[float] = field(default_factory=list)
    #: Human-readable source name, shown next to every link (required by most board APIs).
    attribution: str = ""

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def dedupe_key(self) -> str:
        return f"{normalize_key(self.company)}|{normalize_key(self.title)}"


def normalize_employment(value: str | None) -> str | None:
    """Map a board's employment label ("Full-Time", "contractor", "B2B") to our vocabulary."""
    if not value:
        return None
    v = value.lower().replace("-", " ").replace("_", " ")
    if any(w in v for w in ("contract", "freelance", "b2b", "temporary", "fixed term")):
        return "contract"
    if "part" in v:
        return "part_time"
    if "intern" in v or "werkstudent" in v:
        return "internship"
    if "full" in v or "permanent" in v:
        return "full_time"
    return None


def parse_datetime(value: object) -> datetime | None:
    """Parse ISO 8601, RFC 2822 (RSS) or Unix timestamps into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float) or (isinstance(value, str) and value.strip().isdigit()):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
