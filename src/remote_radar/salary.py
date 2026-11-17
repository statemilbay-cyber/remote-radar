"""Salary extraction and normalisation to annual USD.

Job boards publish pay in every shape imaginable: "$170k - $200k", "€5,000/month",
"USD 60-80 per hour", or structured min/max fields with a period. Everything is
normalised to an annual USD range so roles can be compared and filtered.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

HOURS_PER_YEAR = 1920  # 160 billable hours a month
DAYS_PER_YEAR = 220
WEEKS_PER_YEAR = 48
MIN_PLAUSIBLE_USD = 4_000
MAX_PLAUSIBLE_USD = 1_500_000

#: Approximate USD value of one unit of each currency. Good enough for ranking roles;
#: never use these numbers for invoicing.
DEFAULT_FX: Mapping[str, float] = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.13, "CAD": 0.73, "AUD": 0.66,
    "NZD": 0.60, "SGD": 0.75, "PLN": 0.25, "CZK": 0.043, "SEK": 0.095, "NOK": 0.093,
    "DKK": 0.145, "INR": 0.012, "BRL": 0.18, "MXN": 0.055, "AED": 0.27, "ILS": 0.27,
    "JPY": 0.0067, "ZAR": 0.055, "RON": 0.22, "HUF": 0.0028,
}  # fmt: skip

_MULTIPLIER = {"hour": HOURS_PER_YEAR, "day": DAYS_PER_YEAR, "week": WEEKS_PER_YEAR,
               "month": 12, "year": 1}  # fmt: skip
_PERIODS = {
    "hour": "hour", "hr": "hour", "h": "hour", "hourly": "hour",
    "day": "day", "daily": "day",
    "week": "week", "wk": "week", "weekly": "week",
    "month": "month", "mo": "month", "monthly": "month",
    "year": "year", "yr": "year", "annum": "year", "per annum": "year",
    "annual": "year", "annually": "year", "yearly": "year",
}  # fmt: skip
_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

_CODES = "|".join(sorted(DEFAULT_FX, key=len, reverse=True))
_CUR = rf"(?:[$€£]|\b(?:{_CODES})\b)"
_NUM = r"\d{1,3}(?:[,.\u202f\u00a0 ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_END = r"(?!\d|[,.]\d)"  # never stop in the middle of a number
_K = r"(?:[kK](?![a-zA-Z]))"
_NOT_BIG = r"(?!\s*(?:[mM](?:illion|n)?|[bB](?:illion|n)?)\b)"  # "$20M raised" is not pay
_PERIOD_SEP = r"(?i:/|\bper\b|\ban?\b)"
_PERIOD_WORD = r"(?i:hour|hr|h|day|week|wk|month|mo|year|yr|annum)"
_PERIOD_ADVERB = r"(?i:hourly|daily|weekly|monthly|yearly|annually|annual|per\s+annum)"

_MONEY_RE = re.compile(
    rf"""
    (?P<cur_a>{_CUR})?\s*
    (?P<a>{_NUM}){_END}(?P<ka>{_K})?{_NOT_BIG}
    (?:\s*(?P<cur_b>\b(?:{_CODES})\b))?
    (?:
        \s*(?:-|–|—|\bto\b)\s*
        (?P<cur_c>{_CUR})?\s*
        (?P<b>{_NUM}){_END}(?P<kb>{_K})?{_NOT_BIG}
        (?:\s*(?P<cur_d>\b(?:{_CODES})\b))?
    )?
    (?:
        \s*{_PERIOD_SEP}\s*(?P<period>{_PERIOD_WORD})\b
      | \s*(?P<period_adv>{_PERIOD_ADVERB})\b
    )?
    """,
    re.VERBOSE,
)

# A line must look like it talks about pay before we read numbers from it...
_CONTEXT_RE = re.compile(
    r"(?i)\b(salary|salaries|compensation|pay|paid|rate|rates|base|ote|range|"
    r"per\s+(hour|day|month|year|annum)|hourly|monthly|annual(ly)?)\b"
    r"|/\s*(hr|hour|h|mo|month|yr|year)\b|[$€£]\s?\d{2,3}\s?[kK]\b"
)
# ...and must not be about something else that happens to cost money.
_NOISE_RE = re.compile(
    r"(?i)\b(stipend|allowance|budget|bonus|equipment|reimburse\w*|learning|education|"
    r"funding|raised|series\s+[a-e]|revenue|arr|valuation|investors?|grants?|prize|"
    r"insurance|401\s?\(k\))"
)
_STRONG_CONTEXT_RE = re.compile(
    r"(?i)\b(salary|compensation|base\s+pay|pay\s+range|hourly\s+rate)\b"
)


@dataclass(frozen=True, slots=True)
class Salary:
    """A pay range normalised to annual USD."""

    min_usd: float | None
    max_usd: float | None
    text: str = ""
    approximate: bool = False
    period: str = "year"

    @property
    def monthly_floor(self) -> float | None:
        base = self.min_usd if self.min_usd is not None else self.max_usd
        return None if base is None else base / 12

    @property
    def monthly_ceiling(self) -> float | None:
        top = self.max_usd if self.max_usd is not None else self.min_usd
        return None if top is None else top / 12

    @classmethod
    def from_amounts(
        cls,
        low: float | None,
        high: float | None = None,
        currency: str | None = "USD",
        period: str | None = "year",
        *,
        text: str = "",
        approximate: bool = False,
        fx: Mapping[str, float] = DEFAULT_FX,
    ) -> Salary | None:
        """Build a salary from structured amounts; ``None`` when the data is missing or absurd."""
        code = (currency or "USD").strip().upper()
        rate = fx.get(code)
        unit = normalize_period(period) or "year"
        values = [float(v) for v in (low, high) if v]
        if rate is None or not values:
            return None
        lo, hi = min(values), max(values)
        factor = _MULTIPLIER[unit] * rate
        lo_usd, hi_usd = lo * factor, min(hi * factor, MAX_PLAUSIBLE_USD)
        if not MIN_PLAUSIBLE_USD <= lo_usd <= MAX_PLAUSIBLE_USD:
            return None
        return cls(
            min_usd=round(lo_usd),
            max_usd=round(max(lo_usd, hi_usd)),
            text=text or _describe(lo, hi, code, unit),
            approximate=approximate or code != "USD",
            period=unit,
        )


def normalize_period(value: str | None) -> str | None:
    if not value:
        return None
    return _PERIODS.get(" ".join(value.lower().split()))


def parse_salary(text: str | None, *, require_context: bool = True) -> Salary | None:
    """Find the first plausible pay range in free text.

    With ``require_context`` (the default for long job descriptions) only lines that talk
    about pay are considered, which keeps "$1,000 learning budget" out of the results.
    Short, dedicated fields such as a board's ``salary`` value should pass ``False``.
    """
    if not text:
        return None
    lines = text.splitlines() if require_context else [" ".join(text.split())]
    for line in lines:
        if require_context:
            if not _CONTEXT_RE.search(line):
                continue
            if _NOISE_RE.search(line) and not _STRONG_CONTEXT_RE.search(line):
                continue
        for match in _MONEY_RE.finditer(line):
            salary = _from_match(match)
            if salary is not None:
                return salary
    return None


def _number(raw: str) -> float:
    cleaned = raw.replace("\u202f", "").replace("\u00a0", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", cleaned):
        return float(re.sub(r"[,.]", "", cleaned))
    return float(cleaned.replace(",", ""))


def _from_match(m: re.Match[str]) -> Salary | None:
    marker = m.group("cur_a") or m.group("cur_b") or m.group("cur_c") or m.group("cur_d")
    if not marker:
        return None
    currency = _SYMBOLS.get(marker, marker.upper())
    a = _number(m.group("a"))
    b = _number(m.group("b")) if m.group("b") else None
    if m.group("ka"):
        a *= 1000
    if b is not None and m.group("kb"):
        b *= 1000
        if not m.group("ka") and a < 1000:  # "$80-100k"
            a *= 1000
    if b is not None and b < a:
        b = None
    period = normalize_period(m.group("period") or m.group("period_adv"))
    inferred = period is None
    if inferred:
        reference = max(a, b or 0)
        period = "hour" if reference < 300 else "month" if reference < 25_000 else "year"
    return Salary.from_amounts(
        a, b, currency, period, text=m.group(0).strip(), approximate=inferred
    )


def _describe(lo: float, hi: float, currency: str, unit: str) -> str:
    def fmt(v: float) -> str:
        return f"{v / 1000:g}k" if v >= 10_000 else f"{v:,.0f}"

    amount = fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"
    return f"{currency} {amount}/{unit}"
