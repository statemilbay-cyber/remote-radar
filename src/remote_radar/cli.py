"""Command line interface: ``radar run | top | show | sources``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import __version__
from .http import HttpClient
from .profile import ProfileError, load_profile
from .report import SourceInfo, to_row, write_reports
from .scoring import ENGAGEMENT_LABELS, Assessment, assess, rank
from .sources import ALL_SOURCES
from .store import Store

log = logging.getLogger("remote_radar")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar", description="Find remote engineering roles that fit your profile."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", type=Path, help="profile TOML (default: built-in profile)")
    common.add_argument("--db", type=Path, default=Path("data/radar.db"), help="SQLite database")
    common.add_argument(
        "--window-hours", type=int, default=36, help="only rank jobs seen in the last N hours"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", parents=[common], help="fetch sources, rank, write reports")
    run.add_argument("--sources", help=f"comma-separated subset of: {', '.join(ALL_SOURCES)}")
    run.add_argument("--out", type=Path, default=Path("site"), help="report directory")
    run.add_argument("--cache", type=Path, default=Path(".cache/http"), help="HTTP cache dir")
    run.add_argument("--cache-ttl", type=int, default=6 * 3600, help="cache TTL in seconds")
    run.add_argument("--no-cache", action="store_true", help="always hit the network")
    run.add_argument("--top", type=int, default=10, help="rows to print and put in top.md")
    run.set_defaults(func=cmd_run)

    top = sub.add_parser("top", parents=[common], help="print the best matches from the database")
    top.add_argument("-n", type=int, default=10, help="number of rows")
    top.add_argument("--track", help="only this track key")
    top.add_argument("--json", action="store_true", help="machine-readable output")
    top.set_defaults(func=cmd_top)

    show = sub.add_parser("show", parents=[common], help="print one job with its assessment")
    show.add_argument("uid", help="job id as printed by `radar top` (source:id)")
    show.set_defaults(func=cmd_show)

    sources = sub.add_parser("sources", help="list supported sources")
    sources.set_defaults(func=cmd_sources)

    demo = sub.add_parser("demo", help="write a dashboard from built-in sample data (no network)")
    demo.add_argument("--out", type=Path, default=Path("site-demo"), help="report directory")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        return int(args.func(args))
    except ProfileError as exc:
        print(f"radar: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def cmd_run(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    selected = _select_sources(args.sources)
    now = datetime.now(UTC)
    infos: list[SourceInfo] = []

    with Store(args.db) as store:
        cache = None if args.no_cache else args.cache
        with HttpClient(cache_dir=cache, ttl_seconds=args.cache_ttl) as http:
            for source in selected:
                started = datetime.now(UTC)
                try:
                    jobs = list(source.fetch(http))
                except Exception as exc:  # one broken board must not take the run down
                    log.warning("%s failed: %s", source.label, exc)
                    store.log_fetch(source.name, started, datetime.now(UTC), 0, str(exc))
                    infos.append(
                        SourceInfo(source.name, source.label, source.homepage, 0, str(exc))
                    )
                    continue
                count = store.upsert(jobs, seen_at=now)
                store.log_fetch(source.name, started, datetime.now(UTC), count, None)
                infos.append(SourceInfo(source.name, source.label, source.homepage, count))
                print(f"  {source.label:<30} {count:>5} jobs")

        if all(info.error for info in infos):
            print("radar: every source failed; nothing to rank", file=sys.stderr)
            return 1
        ranked = rank(
            store.active_jobs(since=now - timedelta(hours=args.window_hours)), profile, now=now
        )

    paths = write_reports(ranked, args.out, generated_at=now, sources=infos, top_n=args.top)
    eligible = sum(1 for a in ranked if a.eligible)
    print(f"\n{len(ranked)} unique roles, {eligible} match the profile.\n")
    print_table([a for a in ranked if a.eligible][: args.top])
    print(f"\nDashboard: {paths['html']}\nDigest:    {paths['markdown']}")
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    now = datetime.now(UTC)
    with Store(args.db) as store:
        ranked = rank(
            store.active_jobs(since=now - timedelta(hours=args.window_hours)), profile, now=now
        )
    best = [
        a
        for a in ranked
        if a.eligible and (not args.track or (a.track and a.track.key == args.track))
    ]
    best = best[: args.n]
    if args.json:
        print(json.dumps([to_row(a, now) for a in best], indent=2, ensure_ascii=False))
    else:
        print_table(best)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    with Store(args.db) as store:
        job = store.get(args.uid)
    if job is None:
        print(f"radar: no job with id {args.uid!r}", file=sys.stderr)
        return 1
    a = assess(job, profile)
    print(f"{job.title}\n{job.company} · via {job.attribution}\n")
    print(f"Score     {a.score}/100 ({'eligible' if a.eligible else 'excluded'})")
    print(f"Track     {a.track.label if a.track else 'n/a'}")
    print(f"Pay       {job.salary.text if job.salary else 'not stated'}")
    print(f"Location  {job.location or 'not stated'}")
    print(f"Type      {ENGAGEMENT_LABELS.get(a.engagement or '', 'not stated')}")
    print(f"Posted    {job.posted_at:%Y-%m-%d}" if job.posted_at else "Posted    n/a")
    print(f"Listing   {job.url}")
    if job.apply_url and job.apply_url != job.url:
        print(f"Apply     {job.apply_url}")
    print("\nWhy:")
    for reason in a.reasons:
        print(f"  - {reason}")
    if a.flags:
        print(f"Flags: {', '.join(a.flags)}")
    print("\n" + job.description)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo import build_demo  # local import keeps `radar run` startup lean

    paths = build_demo(args.out)
    print(f"Demo dashboard: {paths['html']}")
    return 0


def cmd_sources(_args: argparse.Namespace) -> int:
    for source in ALL_SOURCES.values():
        print(f"{source.name:<16} {source.label:<30} {source.homepage}")
    return 0


def print_table(assessments: Sequence[Assessment]) -> None:
    if not assessments:
        print("No matching roles.")
        return
    print(f"{'#':>2}  {'SCORE':>5}  {'TRACK':<12} {'PAY/MO':>9}  {'TYPE':<10} {'ROLE'}")
    for i, a in enumerate(assessments, 1):
        pay = f"${a.monthly_usd:,.0f}" if a.monthly_usd else "n/a"
        kind = {"contract": "Contract", "part_time": "Part-time", "full_time": "Full-time"}.get(
            a.engagement or "", "n/a"
        )
        role = textwrap.shorten(f"{a.job.title} · {a.job.company}", width=70, placeholder="…")
        track = a.track.short if a.track else "n/a"
        print(f"{i:>2}  {a.score:>5}  {track:<12} {pay:>9}  {kind:<10} {role}")
        print(f"{'':>22}{a.job.uid}")


def _select_sources(spec: str | None) -> list:
    if not spec:
        return list(ALL_SOURCES.values())
    names = [n.strip() for n in spec.split(",") if n.strip()]
    unknown = [n for n in names if n not in ALL_SOURCES]
    if unknown:
        raise SystemExit(f"radar: unknown source(s) {', '.join(unknown)}; see `radar sources`")
    return [ALL_SOURCES[n] for n in names]
