"""Source registry. Adding a board = one module with a class implementing ``Source``."""

from __future__ import annotations

from .base import Source
from .hackernews import HackerNews
from .himalayas import Himalayas
from .jobicy import Jobicy
from .remoteok import RemoteOK
from .remotive import Remotive
from .weworkremotely import WeWorkRemotely

ALL_SOURCES: dict[str, Source] = {
    source.name: source
    for source in (RemoteOK(), Remotive(), Himalayas(), Jobicy(), WeWorkRemotely(), HackerNews())
}

__all__ = ["ALL_SOURCES", "Source"]
