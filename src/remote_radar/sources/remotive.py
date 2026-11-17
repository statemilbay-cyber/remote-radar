"""Remotive public API: https://remotive.com/api/remote-jobs

Terms: link back to the listing on Remotive, name Remotive as the source, do not
re-submit its jobs to other job boards, and keep the request rate low (listings are
delayed by 24 hours anyway, so the HTTP cache is safe to rely on).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..http import HttpClient
from ..models import Job, normalize_employment, parse_datetime
from ..salary import parse_salary
from ..text import html_to_text
from .base import as_str_list


class Remotive:
    name = "remotive"
    label = "Remotive"
    homepage = "https://remotive.com"
    endpoint = "https://remotive.com/api/remote-jobs"

    def fetch(self, http: HttpClient) -> Iterator[Job]:
        # The public feed is a small, 24h-delayed sample and ignores the category filter,
        # so a single request returns everything it exposes.
        payload = http.get_json(self.endpoint)
        for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
            job = parse_item(item)
            if job is not None:
                yield job


def parse_item(item: Any) -> Job | None:
    if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
        return None
    url = str(item.get("url") or "")
    salary_text = str(item.get("salary") or "").strip()
    return Job(
        source=Remotive.name,
        source_id=str(item["id"]),
        url=url,
        apply_url=url,
        title=str(item["title"]).strip(),
        company=str(item.get("company_name") or "").strip(),
        description=html_to_text(item.get("description")),
        location=str(item.get("candidate_required_location") or "").strip(),
        tags=[t.lower() for t in as_str_list(item.get("tags"))],
        employment_type=normalize_employment(item.get("job_type")),
        posted_at=parse_datetime(item.get("publication_date")),
        salary=parse_salary(salary_text, require_context=False) if salary_text else None,
        attribution=Remotive.label,
    )
