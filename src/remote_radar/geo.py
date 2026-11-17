"""Location and timezone eligibility.

Job boards express "who can apply" in three ways: free text ("Remote, US only", "EMEA",
"Anywhere"), explicit country lists, and lists of accepted UTC offsets. This module turns
all three into one verdict for a candidate profile, with a reason a human can check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Job
    from .profile import Profile

_REGION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "anywhere" counts only on its own or as "anywhere in the world": "anywhere in the US" is
    # a regional restriction, not a worldwide role.
    ("worldwide", re.compile(
        r"\b(world\s*-?\s*wide|anywhere(?!\s+(?:in|within)\s+(?!the\s+world))|global(ly)?|"
        r"any\s+(time\s*zone|location|country)|all\s+countries|international)\b", re.I)),
    ("us", re.compile(r"\b(united\s+states|usa|us[- ](only|based))\b|\bu\.s\.(a\.)?", re.I)),
    ("us", re.compile(r"\bUS\b")),
    ("canada", re.compile(r"\bcanada\b", re.I)),
    ("americas", re.compile(
        r"\b(americas|north\s+america|latam|latin\s+america|south\s+america|central\s+america)\b",
        re.I)),
    ("uk", re.compile(r"\b(united\s+kingdom|great\s+britain|england|scotland|wales)\b", re.I)),
    ("uk", re.compile(r"\bUK\b")),
    ("europe", re.compile(r"\b(europe|european|eea|schengen)\b", re.I)),
    ("europe", re.compile(r"\bEU\b")),
    ("emea", re.compile(r"\bemea\b", re.I)),
    ("apac", re.compile(r"\b(apac|asia|asia\s*-?\s*pacific|asean|oceania)\b", re.I)),
    ("middle_east", re.compile(r"\b(middle\s+east|mena|gcc)\b", re.I)),
    ("africa", re.compile(r"\bafrica\b", re.I)),
)  # fmt: skip

# Country names we recognise in free text. US/UK/Canada are handled as regions above;
# "Georgia" and "Jordan" are skipped in free text because they are also US state / person names.
_FREE_TEXT_COUNTRIES = (
    "argentina", "armenia", "australia", "austria", "azerbaijan", "bangladesh", "belarus",
    "belgium", "bolivia", "brazil", "bulgaria", "chile", "china", "colombia", "costa rica",
    "croatia", "cyprus", "czech republic", "czechia", "denmark", "ecuador", "egypt", "estonia",
    "finland", "france", "germany", "greece", "hong kong", "hungary", "iceland", "india",
    "indonesia", "ireland", "israel", "italy", "japan", "kazakhstan", "kenya", "kyrgyzstan",
    "latvia", "lithuania", "luxembourg", "malaysia", "malta", "mexico", "moldova", "montenegro",
    "morocco", "netherlands", "new zealand", "nigeria", "north macedonia", "norway", "pakistan",
    "panama", "paraguay", "peru", "philippines", "poland", "portugal", "romania", "russia",
    "saudi arabia", "serbia", "singapore", "slovakia", "slovenia", "south africa", "south korea",
    "spain", "sri lanka", "sweden", "switzerland", "taiwan", "thailand", "tunisia", "turkey",
    "ukraine", "united arab emirates", "uae", "uruguay", "uzbekistan", "vietnam",
)  # fmt: skip
_COUNTRY_ALIASES = {
    "usa": "united states", "us": "united states", "u.s.": "united states",
    "united states of america": "united states", "uk": "united kingdom",
    "great britain": "united kingdom", "england": "united kingdom",
    "united kingdom of great britain and northern ireland": "united kingdom",
    "korea": "south korea", "republic of korea": "south korea", "viet nam": "vietnam",
    "czechia": "czech republic", "türkiye": "turkey", "turkiye": "turkey",
    "uae": "united arab emirates", "russian federation": "russia",
}  # fmt: skip
_COUNTRY_RE = re.compile(
    r"\b("
    + "|".join(re.escape(c) for c in sorted(_FREE_TEXT_COUNTRIES, key=len, reverse=True))
    + r")\b",
    re.I,
)

_UTC_OFFSET_RE = re.compile(r"\b(?:utc|gmt)\s*([+\-−–])\s*(\d{1,2})(?:[:.]?(\d{2}))?", re.I)
_NAMED_ZONES = {
    "PST": (-8.0,), "PDT": (-7.0,), "MST": (-7.0,), "MDT": (-6.0,), "EST": (-5.0,),
    "EDT": (-4.0,), "CET": (1.0,), "CEST": (2.0,), "EET": (2.0,), "EEST": (3.0,),
    "WET": (0.0,), "BST": (1.0,), "GMT": (0.0,), "UTC": (0.0,), "AEST": (10.0,),
    "SGT": (8.0,), "JST": (9.0,), "MSK": (3.0,),
}  # fmt: skip
_NAMED_ZONE_RE = re.compile(r"\b(" + "|".join(_NAMED_ZONES) + r")\b")  # upper-case only on purpose
_ZONE_PHRASES: tuple[tuple[re.Pattern[str], tuple[float, ...]], ...] = (
    (re.compile(r"(?i)\b(us|usa|u\.s\.|american|north\s+american?|americas?)\s+"
                r"(time\s*zones?|hours|business\s+hours)\b"), (-8.0, -7.0, -6.0, -5.0)),
    (re.compile(r"(?i)\b(european|europe|central\s+european|cet)\s+"
                r"(time\s*zones?|hours|business\s+hours)\b"), (0.0, 1.0, 2.0)),
    (re.compile(r"(?i)\b(asian|asia|apac)\s+(time\s*zones?|hours)\b"), (5.0, 6.0, 7.0, 8.0, 9.0)),
    (re.compile(r"(?i)\b(east\s+coast|eastern\s+time)\b"), (-5.0,)),
    (re.compile(r"(?i)\b(west\s+coast|pacific\s+time)\b"), (-8.0,)),
)  # fmt: skip
_TZ_LINE_RE = re.compile(
    r"(?i)time\s*zones?|timezone|overlap|working\s+hours|business\s+hours|core\s+hours"
)


@dataclass(frozen=True, slots=True)
class LocationVerdict:
    points: int
    eligible: bool
    reason: str
    flag: str | None = None


def normalize_country(name: str) -> str:
    """'Korea (Republic of)' -> 'south korea', 'USA' -> 'united states'."""
    cleaned = re.sub(r"\(.*?\)", " ", name.lower())
    cleaned = re.sub(r"[^\w\s.'-]", " ", cleaned)  # flags, bullets
    cleaned = " ".join(cleaned.split())
    return _COUNTRY_ALIASES.get(cleaned, cleaned)


def detect_regions(text: str) -> set[str]:
    return {region for region, pattern in _REGION_PATTERNS if pattern.search(text or "")}


def detect_countries(text: str) -> set[str]:
    return {normalize_country(m.group(1)) for m in _COUNTRY_RE.finditer(text or "")}


def parse_offsets(text: str) -> list[float]:
    """Extract UTC offsets mentioned in text: 'UTC+3', 'GMT-5', 'CET', 'US time zones'."""
    if not text:
        return []
    found: set[float] = set()
    for m in _UTC_OFFSET_RE.finditer(text):
        sign = -1.0 if m.group(1) in "-−–" else 1.0
        hours, minutes = int(m.group(2)), int(m.group(3) or 0)
        if hours <= 14:
            found.add(sign * (hours + minutes / 60))
    remaining = _UTC_OFFSET_RE.sub(" ", text)
    for pattern, offsets in _ZONE_PHRASES:
        if pattern.search(remaining):
            found.update(offsets)
    for m in _NAMED_ZONE_RE.finditer(remaining):
        found.update(_NAMED_ZONES[m.group(1)])
    return sorted(found)


def tz_gap(a: float, b: float) -> float:
    """Circular distance between two UTC offsets, in hours."""
    d = abs(a - b) % 24
    return min(d, 24 - d)


def format_offset(offset: float) -> str:
    sign = "+" if offset >= 0 else "−"
    hours = int(abs(offset))
    minutes = round((abs(offset) - hours) * 60)
    return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")


def assess_location(job: Job, profile: Profile) -> LocationVerdict:
    text = job.location or ""
    # A title such as "Web Developer (U.S. Based)" or "Python Engineer, LATAM" overrides a
    # board that files the role under "Worldwide".
    title_regions = detect_regions(job.title) - {"worldwide"}
    if title_regions and not title_regions & profile.regions:
        label = ", ".join(sorted(r.upper() for r in title_regions))
        return LocationVerdict(0, False, f"Title restricts to {label}", "location_restricted")

    candidate_country = normalize_country(profile.country) if profile.country else ""

    # Boards often file a role under "Anywhere" while the posting itself says
    # "Location: Fully Remote (US)" or "must be based in the EU". The posting wins.
    stated = residency_text(job.description)
    if stated:
        stated_regions = detect_regions(stated)
        stated_countries = detect_countries(stated)
        limited = (stated_regions - {"worldwide"}) or stated_countries
        if (
            limited
            and "worldwide" not in stated_regions
            and not (stated_regions & profile.regions)
            and candidate_country not in stated_countries
        ):
            names = sorted(
                {r.upper() for r in stated_regions} | {c.title() for c in stated_countries}
            )
            listed = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
            return LocationVerdict(
                0, False, f"Posting restricts to {listed}", "location_restricted"
            )

    regions = detect_regions(text)
    explicit = {normalize_country(c) for c in job.countries if c.strip()}
    countries = explicit | detect_countries(text)
    restricted_regions = regions - {"worldwide"}
    worldwide = "worldwide" in regions

    if countries:
        if candidate_country and candidate_country in countries:
            verdict = LocationVerdict(18, True, f"Open to {profile.country}")
        elif restricted_regions & profile.regions:
            verdict = LocationVerdict(16, True, "Open to your region")
        elif explicit and len(explicit) > profile.large_country_list and not candidate_country:
            verdict = LocationVerdict(
                10,
                True,
                f"Limited to {len(explicit)} listed countries: check yours",
                "country_list",
            )
        elif worldwide and not explicit:
            verdict = LocationVerdict(18, True, "Open worldwide")
        else:
            listed = ", ".join(sorted(c.title() for c in countries)[:3])
            more = "…" if len(countries) > 3 else ""
            return LocationVerdict(0, False, f"Restricted to {listed}{more}", "location_restricted")
    elif restricted_regions:
        if restricted_regions & profile.regions:
            verdict = LocationVerdict(16, True, "Open to your region")
        elif worldwide:
            verdict = LocationVerdict(16, True, "Open worldwide (regional preference)")
        else:
            label = ", ".join(sorted(r.upper() for r in restricted_regions))
            return LocationVerdict(0, False, f"Restricted to {label}", "location_restricted")
    elif worldwide:
        verdict = LocationVerdict(20, True, "Open worldwide")
    else:
        verdict = LocationVerdict(10, True, "Location not stated: verify", "location_unclear")

    offsets = (
        list(job.timezones) or parse_offsets(text) or parse_offsets(_tz_lines(job.description))
    )
    if not offsets:
        return verdict
    best = min(tz_gap(o, profile.utc_offset) for o in offsets)
    zones = ", ".join(format_offset(o) for o in sorted(set(offsets))[:4])
    if best > profile.max_timezone_gap:
        return LocationVerdict(2, False, f"Works in {zones}: {best:g}h from you", "timezone")
    if verdict.flag == "location_unclear":
        return LocationVerdict(14, True, f"Timezone fits ({zones})")
    return verdict


_LOCATION_LINE_RE = re.compile(
    r"(?im)^\s*(?:job\s+|work\s+)?locations?\s*[:–-]\s*(.+)$"
    r"|^\s*headquarters\s*:\s*(.*\bremote\b.*)$"  # "Headquarters: Remote - United States"
)
_RESIDENCY_RE = re.compile(
    r"(?i)\b(?:(?:must|can|should)\s+(?:be\s+)?(?:based|located|resid\w*|living)\s+"
    r"(?:anywhere\s+)?in"
    r"|required\s+to\s+be\s+based\s+in"
    r"|(?:this\s+(?:role|position)\s+is\s+)?remote\s+(?:in|within)\s+the"
    r"|(?:legally\s+)?(?:eligible|authori[sz]ed)\s+to\s+work\s+in)\b[^.\n]{0,120}"
)
# "Engineer - Remote (United States)", "Remote, EU", "Remote – Canada". The place must start
# with a capital letter, so "remote-first" or "remote, flexible hours" never match.
_REMOTE_PLACE_RE = re.compile(r"\b(?i:remote)\s*(?:\(\s*|,\s*|\s+[-–]\s+)[A-Z][\w .'-]{1,40}")


# "Headquarters: Remote - MX" style two-letter codes seen on job boards.
_ISO2 = {
    "MX": "Mexico", "BR": "Brazil", "AR": "Argentina", "CO": "Colombia", "CL": "Chile",
    "PE": "Peru", "PL": "Poland", "DE": "Germany", "ES": "Spain", "PT": "Portugal",
    "FR": "France", "NL": "Netherlands", "IN": "India", "PH": "Philippines", "CA": "Canada",
}  # fmt: skip
_REMOTE_CODE_RE = re.compile(r"\bremote\s*[-–:(]\s*([A-Z]{2})\b", re.I)


@lru_cache(maxsize=2048)
def residency_text(description: str) -> str:
    """Lines and phrases in a posting that state where the hire must live."""
    if not description:
        return ""
    parts = [m.group(1) or m.group(2) for m in _LOCATION_LINE_RE.finditer(description)]
    parts += [m.group(0) for m in _RESIDENCY_RE.finditer(description)]
    parts += [m.group(0) for m in _REMOTE_PLACE_RE.finditer(description)]
    text = "\n".join(p for p in parts if p)
    return _REMOTE_CODE_RE.sub(
        lambda m: f"Remote - {_ISO2.get(m.group(1).upper(), m.group(1))}", text
    )


@lru_cache(maxsize=2048)
def _tz_lines(description: str) -> str:
    return "\n".join(line for line in description.splitlines() if _TZ_LINE_RE.search(line))
