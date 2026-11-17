"""Remote OK public API: https://remoteok.com/api

Terms: link back to the listing on Remote OK and name Remote OK as the source.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..http import HttpClient
from ..models import Job, parse_datetime
from ..salary import Salary
from ..text import html_to_text
from .base import as_number, as_str_list


class RemoteOK:
    name = "remoteok"
    label = "Remote OK"
    homepage = "https://remoteok.com"
    endpoint = "https://remoteok.com/api"

    def fetch(self, http: HttpClient) -> Iterator[Job]:
        payload = http.get_json(self.endpoint)
        for item in payload if isinstance(payload, list) else []:
            job = parse_item(item)
            if job is not None:
                yield job


def parse_item(item: Any) -> Job | None:
    # The first element of the feed is the API's legal notice, not a job.
    if not isinstance(item, dict) or not item.get("id") or not item.get("position"):
        return None
    low, high = as_number(item.get("salary_min")), as_number(item.get("salary_max"))
    url = str(item.get("url") or f"https://remoteok.com/remote-jobs/{item['id']}")
    return Job(
        source=RemoteOK.name,
        source_id=str(item["id"]),
        url=url,
        apply_url=url,  # Remote OK asks that every link points back to its listing
        title=str(item["position"]).strip(),
        company=str(item.get("company") or "").strip(),
        description=html_to_text(item.get("description")),
        location=str(item.get("location") or "").strip(),
        tags=[t.lower() for t in as_str_list(item.get("tags"))],
        posted_at=parse_datetime(item.get("date") or item.get("epoch")),
        salary=Salary.from_amounts(low, high, "USD", "year") if (low or high) else None,
        attribution=RemoteOK.label,
    )
