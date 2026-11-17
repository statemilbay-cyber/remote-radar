"""Jobicy public API: https://jobicy.com/api/v2/remote-jobs

Terms: credit Jobicy with a direct link and send applicants to the original job URL
from the feed (never a copy of it).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..http import HttpClient
from ..models import Job, normalize_employment, parse_datetime
from ..salary import Salary
from ..text import html_to_text
from .base import as_number, as_str_list


class Jobicy:
    name = "jobicy"
    label = "Jobicy"
    homepage = "https://jobicy.com"
    endpoint = "https://jobicy.com/api/v2/remote-jobs"
    requests: tuple[dict[str, str | int], ...] = (
        {"count": 100, "industry": "dev"},
        {"count": 50, "tag": "python"},
        {"count": 50, "tag": "playwright"},
        {"count": 50, "tag": "qa"},
        {"count": 50, "tag": "automation"},
        {"count": 50, "tag": "typescript"},
        # Roles open worldwide are rare; ask for them explicitly so none are crowded out.
        {"count": 50, "geo": "anywhere", "industry": "dev"},
        {"count": 50, "geo": "anywhere", "tag": "python"},
        {"count": 50, "geo": "anywhere", "tag": "automation"},
    )

    def fetch(self, http: HttpClient) -> Iterator[Job]:
        for params in self.requests:
            payload = http.get_json(self.endpoint, params=dict(params))
            for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
                job = parse_item(item)
                if job is not None:
                    yield job


def parse_item(item: Any) -> Job | None:
    if not isinstance(item, dict) or not item.get("id") or not item.get("jobTitle"):
        return None
    low, high = as_number(item.get("salaryMin")), as_number(item.get("salaryMax"))
    salary = None
    if low or high:
        salary = Salary.from_amounts(
            low, high, item.get("salaryCurrency") or "USD", item.get("salaryPeriod") or "year"
        )
    url = str(item.get("url") or "")
    return Job(
        source=Jobicy.name,
        source_id=str(item["id"]),
        url=url,
        apply_url=url,
        title=str(item["jobTitle"]).strip(),
        company=str(item.get("companyName") or "").strip(),
        description=html_to_text(item.get("jobDescription") or item.get("jobExcerpt")),
        location=" ".join(str(item.get("jobGeo") or "").split()),
        tags=[t.lower() for t in as_str_list(item.get("jobIndustry"))],
        employment_type=normalize_employment(", ".join(as_str_list(item.get("jobType")))),
        posted_at=parse_datetime(item.get("pubDate")),
        salary=salary,
        attribution=Jobicy.label,
    )
