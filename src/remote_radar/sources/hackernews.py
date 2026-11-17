"""Hacker News "Ask HN: Who is hiring?" monthly thread, via the Algolia HN API.

Each top-level comment is one company. By convention the first line is a pipe-separated
header ("Company | Role | REMOTE (worldwide) | $120k-$150k | https://..."), followed by
free-form details. Only remote postings are kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from ..http import HttpClient
from ..models import Job, parse_datetime
from ..salary import parse_salary
from ..text import extract_links, html_to_text

_ROLE_RE = re.compile(
    r"\b(engineers?|engineering|developers?|sdet|qa|tester|programmer|architect|devops|sre|"
    r"scientist|analyst|designer|manager|founding|full[- ]?stack|front[- ]?end|back[- ]?end|"
    r"intern|lead)\b",
    re.I,
)
_LOCATION_RE = re.compile(
    r"\b(remote|onsite|on-site|in[- ]office|hybrid|worldwide|anywhere|time\s*zones?|utc|gmt|"
    r"usa?|u\.s\.|eu|europe|uk|canada|emea|apac|latam|americas)\b",
    re.I,
)
_REMOTE_RE = re.compile(r"\bremote\b", re.I)
_NOT_REMOTE_RE = re.compile(r"\b(no\s+remote|not\s+remote|onsite\s+only|on-site\s+only)\b", re.I)
_CONTRACT_RE = re.compile(r"\b(contract(or)?|freelance|b2b|part[- ]time)\b", re.I)
_FULL_TIME_RE = re.compile(r"\bfull[- ]time\b", re.I)


class HackerNews:
    name = "hackernews"
    label = "Hacker News · Who is hiring?"
    homepage = "https://news.ycombinator.com"
    search_endpoint = "https://hn.algolia.com/api/v1/search_by_date"
    item_endpoint = "https://hn.algolia.com/api/v1/items/{id}"

    def fetch(self, http: HttpClient) -> Iterator[Job]:
        stories = http.get_json(
            self.search_endpoint, params={"tags": "story,author_whoishiring", "hitsPerPage": 10}
        )
        story = next(
            (
                hit
                for hit in stories.get("hits", [])
                if "who is hiring" in str(hit.get("title", "")).lower()
            ),
            None,
        )
        if story is None:
            return
        thread = http.get_json(self.item_endpoint.format(id=story["objectID"]))
        for comment in thread.get("children", []):
            job = parse_comment(comment)
            if job is not None:
                yield job


def parse_comment(comment: Any) -> Job | None:
    if not isinstance(comment, dict) or not comment.get("id"):
        return None
    markup = comment.get("text") or ""
    if not markup:
        return None  # deleted or flagged
    head = re.split(r"(?i)<p>", markup, maxsplit=1)[0]
    header = " ".join(html_to_text(head).split())
    parts = [p.strip() for p in header.split("|") if p.strip()]
    if len(parts) < 2 or len(parts[0]) > 80:
        return None
    if not _REMOTE_RE.search(header) or _NOT_REMOTE_RE.search(header):
        return None

    role = next((p for p in parts[1:] if _ROLE_RE.search(p) and not _REMOTE_RE.search(p)), parts[1])
    location = " · ".join(p for p in parts[1:] if p is not role and _LOCATION_RE.search(p))
    if _CONTRACT_RE.search(header):
        engagement = "part_time" if re.search(r"part[- ]time", header, re.I) else "contract"
    elif _FULL_TIME_RE.search(header):
        engagement = "full_time"
    else:
        engagement = None
    description = html_to_text(markup)
    return Job(
        source=HackerNews.name,
        source_id=str(comment["id"]),
        url=f"https://news.ycombinator.com/item?id={comment['id']}",
        apply_url=_apply_link(description, extract_links(markup)),
        title=role[:140],
        company=parts[0],
        description=description,
        location=location or "Remote",
        employment_type=engagement,
        posted_at=parse_datetime(comment.get("created_at") or comment.get("created_at_i")),
        salary=parse_salary(header, require_context=False),
        attribution=HackerNews.label,
    )


_APPLY_RE = re.compile(r"(?i)\b(?:apply|application|send|email)\b[^\n]{0,60}?(https?://\S+)")


def _apply_link(text: str, links: list[str]) -> str | None:
    """Prefer the URL that follows 'apply' / 'application'; fall back to the first link."""
    match = _APPLY_RE.search(text)
    if match:
        return match.group(1).rstrip(").,;")
    return next((link for link in links if "news.ycombinator.com" not in link), None)
