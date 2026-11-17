"""Himalayas public search API: https://himalayas.app/jobs/api/search

The richest structured feed of the set: explicit country restrictions, accepted UTC
offsets and salary ranges with currency and period. Listings link back to Himalayas.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

from ..http import HttpClient
from ..models import Job, normalize_employment, parse_datetime
from ..salary import Salary
from ..text import html_to_text
from .base import as_number, as_str_list


class Himalayas:
    name = "himalayas"
    label = "Himalayas"
    homepage = "https://himalayas.app"
    endpoint = "https://himalayas.app/jobs/api/search"
    queries = (
        "playwright", "qa automation", "sdet", "test automation", "python developer",
        "data engineer", "web scraping", "full stack typescript", "telegram", "n8n",
        "workflow automation", "integration engineer", "automation engineer", "backend python",
    )  # fmt: skip

    def fetch(self, http: HttpClient) -> Iterator[Job]:
        for query in self.queries:
            payload = http.get_json(self.endpoint, params={"q": query})
            for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
                job = parse_item(item)
                if job is not None:
                    yield job


def parse_item(item: Any) -> Job | None:
    if not isinstance(item, dict):
        return None
    guid = str(item.get("guid") or item.get("applicationLink") or "")
    title = str(item.get("title") or "").strip()
    if not guid or not title:
        return None
    countries = as_str_list(item.get("locationRestrictions"))
    timezones = _offsets(item.get("timezoneRestrictions"))
    if countries:
        location = ", ".join(countries)
    elif timezones:
        location = "Remote (timezone-bound)"
    else:
        location = "Worldwide"
    low, high = as_number(item.get("minSalary")), as_number(item.get("maxSalary"))
    salary = None
    if low or high:
        salary = Salary.from_amounts(
            low, high, item.get("currency") or "USD", item.get("salaryPeriod")
        )
    url = str(item.get("applicationLink") or guid)
    return Job(
        source=Himalayas.name,
        source_id=urlsplit(guid).path.strip("/") or guid,
        url=url,
        apply_url=url,
        title=title,
        company=str(item.get("companyName") or "").strip(),
        description=html_to_text(item.get("description") or item.get("excerpt")),
        location=location,
        tags=[c.lower().replace("-", " ") for c in as_str_list(item.get("categories"))],
        employment_type=normalize_employment(item.get("employmentType")),
        posted_at=parse_datetime(item.get("pubDate")),
        salary=salary,
        countries=countries,
        timezones=timezones,
        attribution=Himalayas.label,
    )


def _offsets(values: Any) -> list[float]:
    offsets: list[float] = []
    for value in values or []:
        try:
            offsets.append(float(value))
        except (TypeError, ValueError):
            continue
    return offsets
