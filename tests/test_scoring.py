from dataclasses import replace
from datetime import UTC, datetime, timedelta

from remote_radar.models import Job
from remote_radar.profile import load_profile
from remote_radar.salary import Salary
from remote_radar.scoring import assess, rank, required_years

NOW = datetime(2026, 11, 18, tzinfo=UTC)
PROFILE = replace(load_profile(), utc_offset=6.0, max_timezone_gap=5.0)


def make_job(**kwargs: object) -> Job:
    base: dict[str, object] = {
        "source": "test",
        "source_id": "1",
        "url": "https://example.com/1",
        "title": "QA Automation Engineer",
        "company": "Acme",
        "description": "We use Playwright and TypeScript. Async-first team, written communication.",
        "location": "Worldwide",
        "employment_type": "contract",
        "posted_at": NOW - timedelta(days=1),
        "salary": Salary.from_amounts(4000, 6000, "USD", "month"),
        "attribution": "Board A",
    }
    base.update(kwargs)
    return Job(**base)  # type: ignore[arg-type]


def test_strong_match_is_eligible_and_scores_high() -> None:
    a = assess(make_job(), PROFILE, now=NOW)
    assert a.eligible
    assert a.track is not None and a.track.key == "qa_automation"
    assert a.score >= 75
    assert any("Playwright" in r or "playwright" in r for r in a.reasons)


def test_us_only_role_is_excluded_with_reason() -> None:
    a = assess(make_job(location="USA only"), PROFILE, now=NOW)
    assert not a.eligible
    assert "location_restricted" in a.flags


def test_pay_below_floor_is_excluded() -> None:
    a = assess(make_job(salary=Salary.from_amounts(800, 1000, "USD", "month")), PROFILE, now=NOW)
    assert not a.eligible
    assert "below_target" in a.flags


def test_unstated_pay_is_neutral() -> None:
    a = assess(make_job(salary=None), PROFILE, now=NOW)
    assert a.eligible
    assert "Pay not stated" in a.reasons


def test_non_engineering_title_is_excluded() -> None:
    job = make_job(title="Account Executive", description="Sell our Playwright-based QA platform.")
    a = assess(job, PROFILE, now=NOW)
    assert not a.eligible
    assert "non_engineering" in a.flags


def test_off_track_engineering_role_is_excluded() -> None:
    job = make_job(title="Senior iOS Engineer", description="Swift, SwiftUI, UIKit.")
    a = assess(job, PROFILE, now=NOW)
    assert not a.eligible
    assert "off_track" in a.flags


def test_heavy_experience_requirement_is_penalised() -> None:
    base = assess(make_job(), PROFILE, now=NOW).score
    heavy = assess(
        make_job(description="Playwright, TypeScript. 8+ years of professional experience."),
        PROFILE,
        now=NOW,
    )
    assert heavy.score < base
    assert "experience_heavy" in heavy.flags


def test_required_years() -> None:
    assert required_years("3-5 years of experience with Python") == 3
    assert required_years("2+ years with Playwright and 6+ years experience overall") == 6
    assert required_years("We were founded 10 years ago") is None


def test_rank_dedupes_cross_posts_and_sorts() -> None:
    a = make_job(source="a", source_id="1", attribution="Board A")
    b = make_job(source="b", source_id="2", attribution="Board B", description="short")
    weak = make_job(source="c", source_id="3", title="Data Entry Clerk", attribution="Board C")
    ranked = rank([weak, a, b], PROFILE, now=NOW)
    assert len(ranked) == 2
    assert ranked[0].job.source == "a"
    assert ranked[0].also_on == ["Board B"]
    assert not ranked[1].eligible


def test_specialist_title_outside_tracks_is_excluded() -> None:
    job = make_job(
        title="Senior DevOps Engineer",
        description="Terraform, Kubernetes, some Python and TypeScript, Playwright smoke tests.",
    )
    a = assess(job, PROFILE, now=NOW)
    assert not a.eligible
    assert "off_track" in a.flags


def test_specialist_title_that_names_a_track_passes() -> None:
    job = make_job(title="DevOps / Python Engineer", description="Python, FastAPI, Airflow ETL.")
    assert assess(job, PROFILE, now=NOW).eligible


def test_talent_networks_are_flagged_and_pushed_down() -> None:
    direct = assess(make_job(), PROFILE, now=NOW)
    network = assess(make_job(company="Lemon.io"), PROFILE, now=NOW)
    assert "talent_network" in network.flags
    assert network.score < direct.score


def test_non_engineering_manager_with_tech_words_is_excluded() -> None:
    job = make_job(
        title="Lending Manager (Front End) - Remote", description="Lead loan assistants."
    )
    assert "non_engineering" in assess(job, PROFILE, now=NOW).flags
