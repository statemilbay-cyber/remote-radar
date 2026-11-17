from dataclasses import replace

import pytest

from remote_radar.geo import assess_location, parse_offsets, tz_gap
from remote_radar.models import Job
from remote_radar.profile import load_profile

PROFILE = replace(load_profile(), utc_offset=6.0, max_timezone_gap=5.0)


def job(**kwargs: object) -> Job:
    base: dict[str, object] = {
        "source": "t",
        "source_id": "1",
        "url": "https://x",
        "title": "Engineer",
        "company": "Acme",
    }
    base.update(kwargs)
    return Job(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("location", ["Worldwide", "Anywhere in the World", "REMOTE (global)"])
def test_worldwide_roles_are_open(location: str) -> None:
    verdict = assess_location(job(location=location), PROFILE)
    assert verdict.eligible
    assert verdict.points == 20


@pytest.mark.parametrize("location", ["USA only", "Europe", "UK", "LATAM", "Germany", "US-based"])
def test_regional_roles_are_closed_without_matching_region(location: str) -> None:
    verdict = assess_location(job(location=location), PROFILE)
    assert not verdict.eligible
    assert verdict.flag == "location_restricted"


def test_region_in_profile_opens_the_role() -> None:
    profile = replace(PROFILE, regions=frozenset({"worldwide", "apac"}))
    assert assess_location(job(location="APAC"), profile).eligible


def test_long_country_list_needs_verification_when_country_unknown() -> None:
    countries = [f"Country {i}" for i in range(30)]
    verdict = assess_location(job(location="Anywhere in the World", countries=countries), PROFILE)
    assert verdict.eligible
    assert verdict.flag == "country_list"


def test_country_list_is_checked_when_country_is_known() -> None:
    profile = replace(PROFILE, country="Kyrgyzstan")
    assert assess_location(job(countries=["Kyrgyzstan", "Georgia"]), profile).eligible
    assert not assess_location(job(countries=["Poland"]), profile).eligible


def test_timezone_mismatch_closes_the_role() -> None:
    verdict = assess_location(job(location="Remote", timezones=[-8.0, -5.0]), PROFILE)
    assert not verdict.eligible
    assert verdict.flag == "timezone"


def test_timezone_from_description_line() -> None:
    description = "About us\nYou need 4 hours of overlap with EST every day."
    verdict = assess_location(job(location="Remote", description=description), PROFILE)
    assert not verdict.eligible


def test_parse_offsets() -> None:
    assert parse_offsets("UTC-3 to UTC+3") == [-3.0, 3.0]
    assert parse_offsets("CET") == [1.0]
    assert parse_offsets("US time zones") == [-8.0, -7.0, -6.0, -5.0]
    assert parse_offsets("GMT+5:30") == [5.5]
    assert parse_offsets("we test our code") == []


def test_tz_gap_is_circular() -> None:
    assert tz_gap(6, -5) == 11
    assert tz_gap(6, 14) == 8
    assert tz_gap(-10, 12) == 2


def test_title_restriction_overrides_worldwide_board_label() -> None:
    title = "Web Developer: WordPress & HubSpot (U.S. Based, Remote Contractor)"
    verdict = assess_location(job(title=title, location="Worldwide"), PROFILE)
    assert not verdict.eligible
    assert verdict.flag == "location_restricted"


@pytest.mark.parametrize(
    "description",
    [
        "Headquarters: Remote - United States\n\nWe build things.",
        "Job Title: Front-End Developer\nLocation: Fully Remote (US)\n",
        "This role is remote in the United States, Canada, or some countries in South America.",
        "Applicants must be based in the EU and hold a work permit.",
        "Headquarters: Remote Poland",
    ],
)
def test_posting_text_overrides_worldwide_board_label(description: str) -> None:
    verdict = assess_location(
        job(location="Anywhere in the World", description=description), PROFILE
    )
    assert not verdict.eligible
    assert verdict.flag == "location_restricted"


@pytest.mark.parametrize(
    "description",
    [
        "Headquarters: New York, NY\nWe hire anywhere.",
        "Location: Remote (open to candidates in India and worldwide).",
        "Headquarters: Remote\n\nAbout us",
    ],
)
def test_posting_text_that_does_not_restrict(description: str) -> None:
    verdict = assess_location(job(location="Worldwide", description=description), PROFILE)
    assert verdict.eligible


def test_two_letter_country_codes_in_remote_headquarters() -> None:
    description = "Headquarters: Remote - MX\nWe build lending products."
    assert not assess_location(
        job(location="Anywhere in the World", description=description), PROFILE
    ).eligible
