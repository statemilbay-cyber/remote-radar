from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from remote_radar.http import FetchError, HttpClient
from remote_radar.models import Job
from remote_radar.profile import load_profile
from remote_radar.report import SourceInfo, write_reports
from remote_radar.salary import Salary
from remote_radar.scoring import rank
from remote_radar.store import Store

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


def sample_job(source_id: str = "1", **kwargs: object) -> Job:
    base: dict[str, object] = {
        "source": "test",
        "source_id": source_id,
        "url": f"https://example.com/{source_id}",
        "title": "Python Developer",
        "company": "Acme <script>",
        "description": "Python, FastAPI, PostgreSQL. Async team.",
        "location": "Worldwide",
        "tags": ["python"],
        "posted_at": NOW - timedelta(days=2),
        "salary": Salary.from_amounts(5000, None, "USD", "month"),
        "countries": ["Spain"],
        "timezones": [1.0],
        "attribution": "Test Board",
    }
    base.update(kwargs)
    return Job(**base)  # type: ignore[arg-type]


def test_store_round_trip_and_window(tmp_path: Path) -> None:
    with Store(tmp_path / "radar.db") as store:
        assert store.upsert([sample_job("1"), sample_job("1"), sample_job("2")], seen_at=NOW) == 2
        store.upsert([sample_job("3")], seen_at=NOW - timedelta(days=5))
        active = store.active_jobs(since=NOW - timedelta(hours=36))
        assert sorted(j.source_id for j in active) == ["1", "2"]
        job = store.get("test:1")
        assert job is not None
        assert job.salary is not None and job.salary.period == "month"
        assert job.countries == ["Spain"] and job.timezones == [1.0]
        assert job.posted_at == NOW - timedelta(days=2)


def test_reports_are_written_and_escaped(tmp_path: Path) -> None:
    ranked = rank([sample_job("1", countries=[], timezones=[])], load_profile(), now=NOW)
    assert ranked[0].eligible
    paths = write_reports(
        ranked,
        tmp_path / "site",
        generated_at=NOW,
        sources=[SourceInfo("test", "Test Board", "https://example.com", 1)],
    )
    html = paths["html"].read_text()
    assert "Remote Radar" in html
    assert '<script>"' not in html and "Acme \\u003cscript\\u003e" in html
    assert "Python Developer" in paths["markdown"].read_text()
    assert paths["csv"].read_text().startswith("score,eligible,title")


def test_http_client_retries_then_raises(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    client = HttpClient(
        cache_dir=tmp_path, transport=httpx.MockTransport(handler), backoff=0, min_interval=0
    )
    with client, pytest.raises(FetchError, match="HTTP 503"):
        client.get_json("https://api.example.com/jobs")
    assert calls["n"] == 3


def test_http_client_caches_successful_responses(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"jobs": [1, 2]})

    client = HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler), min_interval=0)
    with client:
        assert client.get_json("https://api.example.com/jobs", {"q": "x"}) == {"jobs": [1, 2]}
        assert client.get_json("https://api.example.com/jobs", {"q": "x"}) == {"jobs": [1, 2]}
    assert calls["n"] == 1


def test_demo_dataset_exercises_every_rule(tmp_path: Path) -> None:
    from remote_radar.demo import DEMO_NOW, build_demo, sample_jobs

    ranked = rank(sample_jobs(), load_profile(), now=DEMO_NOW)
    flags = {flag for a in ranked for flag in a.flags}
    assert sum(a.eligible for a in ranked) == 4
    assert {"location_restricted", "below_target", "non_engineering"} <= flags
    assert build_demo(tmp_path)["html"].exists()
