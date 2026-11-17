"""The contract every source implements, plus small parsing helpers they share."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from ..http import HttpClient
from ..models import Job


class Source(Protocol):
    #: Stable machine name, used in job ids and on the command line.
    name: str
    #: Name shown next to every listing; most board APIs require this attribution.
    label: str
    homepage: str

    def fetch(self, http: HttpClient) -> Iterator[Job]: ...


def as_number(value: Any) -> float | None:
    """'120000', 120000, '0', None, 'None' -> float or None (zero means 'not published')."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return number or None


def as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]
