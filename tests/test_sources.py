from remote_radar.salary import HOURS_PER_YEAR
from remote_radar.sources import hackernews, himalayas, jobicy, remoteok, remotive, weworkremotely

HN_COMMENT = {
    "id": 123,
    "created_at": "2026-11-02T16:01:43.000Z",
    "text": (
        "Acme Robotics | Senior QA Automation Engineer (Playwright) | REMOTE (worldwide) | "
        'Contract | $70-90/hr | <a href="https:&#x2F;&#x2F;acme.example&#x2F;jobs">'
        "https://acme.example/jobs</a><p>We build test tooling.<p>Stack: TypeScript, Playwright."
    ),
}


def test_hackernews_header_is_parsed() -> None:
    job = hackernews.parse_comment(HN_COMMENT)
    assert job is not None
    assert job.company == "Acme Robotics"
    assert job.title == "Senior QA Automation Engineer (Playwright)"
    assert "worldwide" in job.location.lower()
    assert job.employment_type == "contract"
    assert job.salary is not None and job.salary.min_usd == 70 * HOURS_PER_YEAR
    assert job.apply_url == "https://acme.example/jobs"
    assert job.url == "https://news.ycombinator.com/item?id=123"
    assert "Stack: TypeScript, Playwright." in job.description


def test_hackernews_skips_onsite_and_deleted_comments() -> None:
    onsite = dict(
        HN_COMMENT, text="Acme | Backend Engineer | Onsite, Berlin | Full-time<p>No remote."
    )
    assert hackernews.parse_comment(onsite) is None
    assert hackernews.parse_comment({"id": 1, "text": None}) is None


def test_remoteok_skips_legal_notice_and_parses_job() -> None:
    assert remoteok.parse_item({"legal": "API terms"}) is None
    job = remoteok.parse_item(
        {
            "id": "42",
            "position": "Python Developer",
            "company": "Acme",
            "tags": ["python", "Django"],
            "description": "<p>Build <b>APIs</b></p>",
            "location": "Worldwide",
            "salary_min": "90000",
            "salary_max": "0",
            "date": "2026-11-13T08:00:21+00:00",
            "url": "https://remoteOK.com/remote-jobs/42",
        }
    )
    assert job is not None
    assert job.uid == "remoteok:42"
    assert job.tags == ["python", "django"]
    assert job.salary is not None and job.salary.min_usd == 90_000
    assert job.description == "Build APIs"


def test_remotive_parses_free_text_salary_and_job_type() -> None:
    job = remotive.parse_item(
        {
            "id": 7,
            "url": "https://remotive.com/remote-jobs/x-7",
            "title": "Data Engineer",
            "company_name": "Acme",
            "tags": ["python", "airflow"],
            "job_type": "contract",
            "publication_date": "2026-11-14T20:33:53",
            "candidate_required_location": "Worldwide",
            "salary": "$100k - $120k",
            "description": "<p>Pipelines</p>",
        }
    )
    assert job is not None
    assert job.employment_type == "contract"
    assert job.salary is not None and job.salary.max_usd == 120_000
    assert job.posted_at is not None and job.posted_at.tzinfo is not None


def test_himalayas_empty_restrictions_mean_worldwide() -> None:
    item = {
        "guid": "https://himalayas.app/companies/acme/jobs/sdet",
        "title": "SDET",
        "companyName": "Acme",
        "employmentType": "Contractor",
        "minSalary": 5000,
        "maxSalary": 7000,
        "currency": "EUR",
        "salaryPeriod": "monthly",
        "locationRestrictions": [],
        "timezoneRestrictions": [],
        "pubDate": 1794936884,
        "description": "<p>Playwright</p>",
    }
    job = himalayas.parse_item(item)
    assert job is not None
    assert job.location == "Worldwide"
    assert job.employment_type == "contract"
    assert job.salary is not None and job.salary.min_usd == round(5000 * 12 * 1.08)
    restricted = himalayas.parse_item(
        dict(item, locationRestrictions=["United States"], timezoneRestrictions=[-5, "-8"])
    )
    assert restricted is not None
    assert restricted.countries == ["United States"]
    assert restricted.timezones == [-5.0, -8.0]


def test_jobicy_structured_salary() -> None:
    job = jobicy.parse_item(
        {
            "id": 1,
            "url": "https://jobicy.com/jobs/1-x",
            "jobTitle": "Product Engineer",
            "companyName": "Acme",
            "jobIndustry": ["Software Engineering"],
            "jobType": ["Full-Time"],
            "jobGeo": "France",
            "pubDate": "2026-11-17T13:46:01+00:00",
            "salaryMin": 45000,
            "salaryMax": 65000,
            "salaryCurrency": "EUR",
            "salaryPeriod": "yearly",
        }
    )
    assert job is not None
    assert job.employment_type == "full_time"
    assert job.salary is not None and job.salary.approximate


WWR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item>
  <title>Acme: Senior Python Engineer</title>
  <region>Anywhere in the World</region>
  <country>🇩🇪 Germany, 🇪🇸 Spain, and 🇺🇸 United States of America</country>
  <skills>Python, Back-End Dev, and Contract</skills>
  <type>Contract</type>
  <pubDate>Wed, 11 Nov 2026 16:41:48 +0000</pubDate>
  <link>https://weworkremotely.com/remote-jobs/acme-senior-python-engineer</link>
  <description>&lt;p&gt;Salary: $6,000 - $8,000 per month&lt;/p&gt;</description>
</item>
</channel></rss>"""


def test_weworkremotely_feed() -> None:
    jobs = list(weworkremotely.parse_feed(WWR_FEED))
    assert len(jobs) == 1
    job = jobs[0]
    assert (job.company, job.title) == ("Acme", "Senior Python Engineer")
    assert job.countries == ["Germany", "Spain", "United States of America"]
    assert job.employment_type == "contract"
    assert job.salary is not None and job.salary.min_usd == 72_000
    assert job.source_id == "acme-senior-python-engineer"


def test_hackernews_prefers_the_apply_link_over_demo_links() -> None:
    comment = {
        "id": 9,
        "text": (
            "Acme | Python Engineer | REMOTE worldwide | Full-time"
            '<p>Demo: <a href="https://www.youtube.com/watch?v=x">video</a>'
            '<p>Apply here: <a href="https://www.ycombinator.com/companies/acme/jobs/1">'
            "https://www.ycombinator.com/companies/acme/jobs/1</a>"
        ),
    }
    job = hackernews.parse_comment(comment)
    assert job is not None
    assert job.apply_url == "https://www.ycombinator.com/companies/acme/jobs/1"
