"""Scoring: how well a role fits the profile, with reasons a human can audit.

Score (0-100) = track fit (40) + pay (20) + location (20) + engagement (10) + async (10)
                + adjustments (experience demands, seniority, freshness).

A role is *eligible* only if it is an engineering role inside one of your tracks, pays at
least your floor (or does not say), and is open to where you live and your timezone.
Ineligible roles are kept with the reason, so filters can be audited instead of trusted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

from .geo import assess_location
from .models import Job
from .profile import Profile, Track
from .text import find_terms

MIN_TRACK_POINTS = 8
TRACK_SATURATION = 24  # raw keyword points that already count as a perfect fit

ENGAGEMENT_LABELS = {
    "contract": "Contract / B2B",
    "part_time": "Part-time",
    "full_time": "Full-time",
    "internship": "Internship",
}
ASYNC_TERMS = (
    "async", "asynchronous", "async-first", "written communication", "documentation-first",
    "remote-first", "flexible hours", "flexible schedule", "no meetings", "few meetings",
    "minimal meetings", "own your schedule", "work your own hours",
)  # fmt: skip
SYNC_TERMS = (
    "on-call", "on call rotation", "daily standup", "daily stand-up", "pair programming",
    "core hours", "in-office", "hybrid", "relocation",
)  # fmt: skip
WEB3_TERMS = (
    "web3", "blockchain", "crypto", "cryptocurrency", "defi", "solidity", "ethereum", "solana",
    "onchain", "on-chain", "smart contract", "smart contracts", "nft", "evm", "stablecoin",
)  # fmt: skip

_ENGINEERING_TITLE_RE = re.compile(
    r"\b(engineer(ing)?|developer|dev|sdet|qa|tester|test|testing|programmer|architect|"
    r"automation|scrap(er|ing)|data|back[- ]?end|front[- ]?end|full[- ]?stack|python|typescript|"
    r"javascript|node(\.js)?|react|integrations?|devops|sre|software|coder|bot)\b",
    re.I,
)
_LEADERSHIP_RE = re.compile(
    r"\b(staff|principal|director|head\s+of|vp|vice\s+president|chief|cto|manager|lead)\b", re.I
)
_JUNIOR_RE = re.compile(
    r"\b(junior|jr\.?|intern(ship)?|graduate|trainee|entry[- ]level|apprentice)\b", re.I
)
_YEARS_RE = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b"
    r"[^.\n\d]{0,40}?\b(?:experience|exp\b)",
    re.I,
)
_CONTRACT_RE = re.compile(
    r"\b(contract(or)?|freelance(r)?|b2b|fixed[- ]term|consulting\s+engagement|1099)\b", re.I
)
_PART_TIME_RE = re.compile(r"\bpart[- ]time\b", re.I)
_FULL_TIME_RE = re.compile(r"\bfull[- ]time\b", re.I)


@dataclass(slots=True)
class Assessment:
    job: Job
    score: int
    eligible: bool
    track: Track | None
    terms: list[str]
    reasons: list[str]
    flags: list[str]
    monthly_usd: float | None
    engagement: str | None
    required_years: int | None
    also_on: list[str] = field(default_factory=list)


@lru_cache(maxsize=32)
def _title_exclusion(terms: tuple[str, ...]) -> re.Pattern[str] | None:
    if not terms:
        return None
    alternation = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alternation})(?![a-z0-9])", re.I)


def track_fit(job: Job, track: Track) -> tuple[int, list[str]]:
    """Raw fit points for one track and the terms that produced them."""
    title_hits = find_terms(job.title, track.title_terms)
    in_title = find_terms(job.title, track.keywords)
    in_body = find_terms(f"{' '.join(job.tags)}\n{job.description}", track.keywords)
    points = (8 if title_hits else 0) + sum(2 * track.keywords[t] for t in in_title)
    points += sum(track.keywords[t] for t in in_body if t not in in_title)
    return points, list(dict.fromkeys([*title_hits, *in_title, *in_body]))


def detect_engagement(job: Job) -> str | None:
    if job.employment_type:
        return job.employment_type
    for scope in (f"{job.title} {' '.join(job.tags)}", job.description[:2000]):
        if _CONTRACT_RE.search(scope):
            return "contract"
        if _PART_TIME_RE.search(scope):
            return "part_time"
        if _FULL_TIME_RE.search(scope):
            return "full_time"
    return None


def required_years(text: str) -> int | None:
    years = [int(m.group(1)) for m in _YEARS_RE.finditer(text or "")]
    years = [y for y in years if 0 < y <= 20]
    return max(years) if years else None


def assess(job: Job, profile: Profile, *, now: datetime | None = None) -> Assessment:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    flags: list[str] = []
    eligible = True

    # 1. Is this an engineering role in one of the tracks?
    best: Track | None = None
    best_points, best_terms = 0, []
    for track in profile.tracks:
        points, terms = track_fit(job, track)
        if points > best_points:
            best, best_points, best_terms = track, points, terms

    exclusion = _title_exclusion(profile.exclude_titles)
    in_title = bool(best and find_terms(job.title, best.title_terms))
    if (exclusion and exclusion.search(job.title)) or not (
        _ENGINEERING_TITLE_RE.search(job.title) or in_title
    ):
        eligible = False
        flags.append("non_engineering")
        reasons.append("Not an engineering role")

    # "Senior DevOps Engineer" whose description happens to mention Python is not a Python role.
    off_track_title = _title_exclusion(profile.off_track_titles)
    names_a_track = any(find_terms(job.title, t.title_terms) for t in profile.tracks)
    specialist_title = bool(off_track_title and off_track_title.search(job.title))
    if best is None or best_points < MIN_TRACK_POINTS or (specialist_title and not names_a_track):
        eligible = False
        flags.append("off_track")
        reasons.append("Outside your tracks")
        best, fit = None, 0
    else:
        fit = min(40, round(best_points * 40 / TRACK_SATURATION))
        reasons.append(f"{best.label}: {', '.join(best_terms[:6])}")

    # 2. Pay.
    monthly = job.salary.monthly_floor if job.salary else None
    if job.salary is None or monthly is None:
        pay = 7
        reasons.append("Pay not stated")
    elif monthly < profile.min_monthly_usd:
        pay = 0
        eligible = False
        flags.append("below_target")
        reasons.append(
            f"Pay from ~${monthly:,.0f}/mo, below your ${profile.min_monthly_usd:,.0f} floor"
        )
    else:
        stretch = (monthly - profile.min_monthly_usd) / (2 * profile.min_monthly_usd)
        pay = 10 + round(10 * min(1.0, stretch))
        basis = " full-time equivalent" if job.salary.period in {"hour", "day", "week"} else ""
        approx = " (approx.)" if job.salary.approximate else ""
        reasons.append(f"Pay from ~${monthly:,.0f}/mo{basis}{approx}: {job.salary.text}")

    # 3. Location and timezone.
    location = assess_location(job, profile)
    reasons.append(location.reason)
    if location.flag:
        flags.append(location.flag)
    if not location.eligible:
        eligible = False

    # 4. Engagement type.
    engagement = detect_engagement(job)
    ranking = (10, 8, 6)
    engagement_points = {
        kind: ranking[i] for i, kind in enumerate(profile.engagement_preference[:3])
    }.get(engagement or "", 0 if engagement == "internship" else 5)
    if engagement:
        reasons.append(ENGAGEMENT_LABELS[engagement])

    # 5. How async the team is.
    blob = f"{job.title}\n{job.location}\n{job.description}"
    async_hits = find_terms(blob, ASYNC_TERMS)
    sync_hits = find_terms(blob, SYNC_TERMS)
    async_points = max(0, min(10, 5 + 2 * len(async_hits) - 3 * len(sync_hits)))
    if async_hits:
        reasons.append("Async signals: " + ", ".join(async_hits[:3]))
    if sync_hits:
        reasons.append("Sync signals: " + ", ".join(sync_hits[:3]))

    # 6. Adjustments.
    adjust = 0
    years = required_years(job.description)
    if years and years > profile.max_required_years:
        adjust -= 15
        flags.append("experience_heavy")
        reasons.append(f"Asks for {years}+ years of experience")
    if _LEADERSHIP_RE.search(job.title):
        adjust -= 10
        flags.append("leadership")
        reasons.append("Leadership-level title")
    if _JUNIOR_RE.search(job.title):
        adjust -= 6
        flags.append("junior")
        reasons.append("Junior-level title")
    if job.posted_at:
        age = (now - job.posted_at).days
        if age > 30:
            adjust -= 10
            flags.append("stale")
            reasons.append(f"Posted {age} days ago")
        elif age <= 3:
            adjust += 3
    if profile.talent_networks and find_terms(job.company, profile.talent_networks):
        adjust -= 8
        flags.append("talent_network")
        reasons.append("Talent network / marketplace: multi-stage vetting with live interviews")
    if find_terms(blob, WEB3_TERMS):
        flags.append("web3")
        reasons.append("Web3 / crypto company")
        if profile.prefer_web3:
            adjust += 3

    total = fit + pay + location.points + engagement_points + async_points + adjust
    return Assessment(
        job=job,
        score=max(0, min(100, total)),
        eligible=eligible,
        track=best,
        terms=best_terms if best else [],
        reasons=reasons,
        flags=flags,
        monthly_usd=monthly,
        engagement=engagement,
        required_years=years,
    )


def rank(jobs: Iterable[Job], profile: Profile, *, now: datetime | None = None) -> list[Assessment]:
    """De-duplicate cross-posted roles, assess each one and sort best-first."""
    now = now or datetime.now(UTC)
    groups: dict[str, list[Job]] = {}
    for job in jobs:
        groups.setdefault(job.dedupe_key, []).append(job)

    results: list[Assessment] = []
    for group in groups.values():
        primary = max(group, key=_richness)
        assessment = assess(primary, profile, now=now)
        assessment.also_on = sorted(
            {j.attribution for j in group if j is not primary and j.attribution}
            - {primary.attribution}
        )
        results.append(assessment)

    oldest = datetime.min.replace(tzinfo=UTC)
    results.sort(key=lambda a: (a.eligible, a.score, a.job.posted_at or oldest), reverse=True)
    return results


def _richness(job: Job) -> tuple[bool, int, datetime]:
    return (
        job.salary is not None,
        len(job.description),
        job.posted_at or datetime.min.replace(tzinfo=UTC),
    )
