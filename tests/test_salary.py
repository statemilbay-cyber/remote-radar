import pytest

from remote_radar.salary import HOURS_PER_YEAR, Salary, parse_salary


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("$170k - $200k", 170_000, 200_000),
        ("Salary: $120,000 – $150,000 per year", 120_000, 150_000),
        ("$80-100k", 80_000, 100_000),
        ("USD 4,000–6,000 per month", 48_000, 72_000),
        ("$60/hr", 60 * HOURS_PER_YEAR, 60 * HOURS_PER_YEAR),
        ("120,000 - 150,000 USD", 120_000, 150_000),
        ("$95k annually", 95_000, 95_000),
    ],
)
def test_parses_usd_ranges(text: str, low: int, high: int) -> None:
    salary = parse_salary(text, require_context=False)
    assert salary is not None
    assert (salary.min_usd, salary.max_usd) == (low, high)


def test_converts_other_currencies_and_marks_them_approximate() -> None:
    salary = parse_salary("€5,000/month (full-time)", require_context=False)
    assert salary is not None
    assert salary.approximate
    assert salary.period == "month"
    assert salary.min_usd == round(5000 * 12 * 1.08)


@pytest.mark.parametrize(
    "text",
    [
        "5+ years of experience",
        "Founded in 2019, 40 people",
        "We raised $20M in our Series A",
        "Compensation: competitive",
    ],
)
def test_ignores_numbers_that_are_not_pay(text: str) -> None:
    assert parse_salary(text) is None


def test_description_mode_reads_only_pay_lines() -> None:
    text = "We offer a $1,500 learning budget.\nSalary range: $90k-$120k plus equity"
    salary = parse_salary(text)
    assert salary is not None
    assert (salary.min_usd, salary.max_usd) == (90_000, 120_000)


def test_structured_amounts() -> None:
    assert Salary.from_amounts(0, 0) is None
    assert Salary.from_amounts(None, None) is None
    salary = Salary.from_amounts(60_000, 90_000)
    assert salary is not None
    assert salary.monthly_floor == 5_000
    assert salary.monthly_ceiling == 7_500


def test_rejects_unknown_currency_and_absurd_values() -> None:
    assert Salary.from_amounts(5000, None, "XYZ", "month") is None
    assert Salary.from_amounts(1, None, "USD", "year") is None
