"""Candidate profile: what to look for and which roles you can legally accept."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

_ENGAGEMENTS = frozenset({"contract", "part_time", "full_time"})
_CANDIDATE_KEYS = frozenset(
    {
        "utc_offset", "max_timezone_gap", "country", "regions", "min_monthly_usd",
        "max_required_years", "engagement_preference", "prefer_web3", "large_country_list",
    }
)  # fmt: skip


class ProfileError(ValueError):
    """The profile file is missing, malformed or contains unknown keys."""


@dataclass(frozen=True, slots=True)
class Track:
    key: str
    label: str
    short: str
    title_terms: tuple[str, ...]
    keywords: dict[str, int]


@dataclass(frozen=True, slots=True)
class Profile:
    utc_offset: float = 0.0
    max_timezone_gap: float = 6.0
    country: str = ""
    regions: frozenset[str] = frozenset({"worldwide"})
    min_monthly_usd: float = 1500.0
    max_required_years: int = 5
    engagement_preference: tuple[str, ...] = ("contract", "part_time", "full_time")
    prefer_web3: bool = False
    exclude_titles: tuple[str, ...] = ()
    off_track_titles: tuple[str, ...] = ()
    talent_networks: tuple[str, ...] = ()
    tracks: tuple[Track, ...] = ()
    large_country_list: int = 10


_DEFAULTS = Profile()


def load_profile(path: str | Path | None = None) -> Profile:
    """Load a profile TOML; without a path the built-in default profile is used."""
    if path is None:
        origin = "built-in profile"
        text = resources.files("remote_radar").joinpath("profiles/default.toml").read_text("utf-8")
    else:
        origin = str(path)
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ProfileError(f"cannot read profile {origin}: {exc.strerror}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{origin}: {exc}") from exc
    return parse_profile(data, origin=origin)


def parse_profile(data: dict[str, Any], *, origin: str = "profile") -> Profile:
    _reject_unknown(data, {"candidate", "filters", "tracks"}, origin)
    candidate = data.get("candidate", {})
    filters = data.get("filters", {})
    _reject_unknown(candidate, _CANDIDATE_KEYS, f"{origin} [candidate]")
    _reject_unknown(
        filters, {"exclude_titles", "off_track_titles", "talent_networks"}, f"{origin} [filters]"
    )

    tracks: list[Track] = []
    for key, raw in (data.get("tracks") or {}).items():
        where = f"{origin} [tracks.{key}]"
        _reject_unknown(raw, {"label", "short", "title_terms", "keywords"}, where)
        keywords = {str(k).lower(): int(v) for k, v in (raw.get("keywords") or {}).items()}
        if not keywords:
            raise ProfileError(f"{where}: needs at least one keyword")
        tracks.append(
            Track(
                key=key,
                label=str(raw.get("label", key)),
                short=str(raw.get("short", key)),
                title_terms=tuple(str(t).lower() for t in raw.get("title_terms", [])),
                keywords=keywords,
            )
        )
    if not tracks:
        raise ProfileError(f"{origin}: define at least one [tracks.<name>] table")

    preference = tuple(
        str(p) for p in candidate.get("engagement_preference", _DEFAULTS.engagement_preference)
    )
    unknown = set(preference) - _ENGAGEMENTS
    if unknown:
        raise ProfileError(
            f"{origin}: unknown engagement type(s) {sorted(unknown)}; use {sorted(_ENGAGEMENTS)}"
        )

    return Profile(
        utc_offset=float(candidate.get("utc_offset", _DEFAULTS.utc_offset)),
        max_timezone_gap=float(candidate.get("max_timezone_gap", _DEFAULTS.max_timezone_gap)),
        country=str(candidate.get("country", "")).strip(),
        regions=frozenset(str(r).lower() for r in candidate.get("regions", ["worldwide"])),
        min_monthly_usd=float(candidate.get("min_monthly_usd", _DEFAULTS.min_monthly_usd)),
        max_required_years=int(candidate.get("max_required_years", _DEFAULTS.max_required_years)),
        engagement_preference=preference,
        prefer_web3=bool(candidate.get("prefer_web3", False)),
        exclude_titles=tuple(str(t).lower() for t in filters.get("exclude_titles", [])),
        off_track_titles=tuple(str(t).lower() for t in filters.get("off_track_titles", [])),
        talent_networks=tuple(str(t).lower() for t in filters.get("talent_networks", [])),
        tracks=tuple(tracks),
        large_country_list=int(candidate.get("large_country_list", _DEFAULTS.large_country_list)),
    )


def _reject_unknown(table: Any, allowed: set[str] | frozenset[str], where: str) -> None:
    if not isinstance(table, dict):
        raise ProfileError(f"{where}: expected a table")
    unknown = set(table) - set(allowed)
    if unknown:
        raise ProfileError(f"{where}: unknown key(s) {sorted(unknown)}")
