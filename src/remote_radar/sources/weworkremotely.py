"""We Work Remotely category RSS feeds: https://weworkremotely.com

Each item carries a region ("Anywhere in the World", "USA Only"), an optional list of
countries applicants may live in, the engagement type and a full HTML description.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from xml.etree.ElementTree import Element, ParseError

from defusedxml.ElementTree import fromstring

from ..http import FetchError, HttpClient
from ..models import Job, normalize_employment, parse_datetime
from ..salary import parse_salary
from ..text import html_to_text

_FLAG_RE = re.compile("[\U0001f1e6-\U0001f1ff]")


class WeWorkRemotely:
    name = "weworkremotely"
    label = "We Work Remotely"
    homepage = "https://weworkremotely.com"
    feeds = (
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    )

    def fetch(self, http: HttpClient) -> Iterator[Job]:
        for feed in self.feeds:
            yield from parse_feed(http.get_text(feed), feed)


def parse_feed(xml_text: str, origin: str = "feed") -> Iterator[Job]:
    try:
        root = fromstring(xml_text)
    except ParseError as exc:
        raise FetchError(f"{origin}: invalid RSS ({exc})") from exc
    for item in root.iter("item"):
        job = parse_item(item)
        if job is not None:
            yield job


def parse_item(item: Element) -> Job | None:
    raw_title = (item.findtext("title") or "").strip()
    link = (item.findtext("link") or item.findtext("guid") or "").strip()
    if not raw_title or not link:
        return None
    company, sep, title = raw_title.partition(": ")
    if not sep:
        company, title = "", raw_title
    countries = split_countries(item.findtext("country") or "")
    region = (item.findtext("region") or "").strip()
    description = html_to_text(item.findtext("description"))
    skills = [
        s.strip().lower()
        for s in re.split(r",\s*|\s+and\s+", item.findtext("skills") or "")
        if s.strip()
    ]
    return Job(
        source=WeWorkRemotely.name,
        source_id=link.rstrip("/").rsplit("/", 1)[-1],
        url=link,
        apply_url=link,
        title=title.strip(),
        company=company.strip(),
        description=description,
        location=region or ("Worldwide" if not countries else ", ".join(countries)),
        tags=skills,
        employment_type=normalize_employment(item.findtext("type")),
        posted_at=parse_datetime(item.findtext("pubDate")),
        salary=parse_salary(description),
        countries=countries,
        attribution=WeWorkRemotely.label,
    )


def split_countries(raw: str) -> list[str]:
    """'🇩🇪 Germany, 🇪🇸 Spain, and 🇺🇸 United States of America' -> ['Germany', ...]."""
    names = []
    for part in _FLAG_RE.sub("", raw).split(","):
        name = re.sub(r"^\s*and\s+", "", part).strip()
        if name:
            names.append(name)
    return names
