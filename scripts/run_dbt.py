"""Run dbt and record the result in meta.dbt_runs.

This is the entrypoint rather than dbt itself, so model duration, failures and
freshness become queryable -- and so fo_mart_last_build_timestamp has something
to report. Airflow to schedule six SQL models would be four containers of
ceremony and a second Postgres to page yourself about.

One-shot, for a shell or CI:

    python -m scripts.run_dbt --select tag:realtime
    python -m scripts.run_dbt --full

Long-running, which is how it runs in production -- the ``dbt`` service in
deploy/docker-compose.yml:

    python -m scripts.run_dbt --schedule

The schedule lives here, in the process that does the work, rather than in a
crontab on the host. A crontab is a deployment step nobody can see from the
repository, and the failure mode is silent: the marts simply stop moving while
every dashboard keeps rendering yesterday's numbers as though they were today's.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.conn import Role, tx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = ROOT / "dbt"

log = logging.getLogger("dbt")

# (every N seconds, dbt build arguments). Matches the model tags: the session
# and funnel marts the owner watches rebuild every minute, the heavier
# aggregates hourly, and a full refresh nightly to heal anything incremental
# logic drifted on.
SCHEDULE = (
    (60, ["--select", "tag:realtime"]),
    (3600, ["--select", "tag:hourly"]),
    (86400, ["--full-refresh"]),
)


def record(results_path: Path) -> tuple[int, int]:
    """Fold run_results.json into meta.dbt_runs. Failures are the point."""
    if not results_path.exists():
        return 0, 0
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    invocation = payload.get("metadata", {}).get("invocation_id")
    passed = failed = 0
    with tx(Role.ETL) as cur:
        for result in payload.get("results", []):
            status = result.get("status", "unknown")
            if status in {"success", "pass"}:
                passed += 1
            else:
                failed += 1
            cur.execute(
                """insert into meta.dbt_runs (invocation_id, model, status, rows_affected, duration_ms)
                   values (%s, %s, %s, %s, %s)""",
                (
                    invocation,
                    result.get("unique_id", "?"),
                    status,
                    (result.get("adapter_response") or {}).get("rows_affected"),
                    int(result.get("execution_time", 0) * 1000),
                ),
            )
            if result.get("unique_id", "").startswith("test."):
                cur.execute(
                    """insert into meta.dq_results (test_name, status, failures, message)
                       values (%s, %s, %s, %s)""",
                    (
                        result["unique_id"].split(".")[-2],
                        "pass" if status == "pass" else "fail",
                        result.get("failures") or 0,
                        (result.get("message") or "")[:500],
                    ),
                )
    return passed, failed


def run_once(extra: list[str]) -> int:
    env = {**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)}
    completed = subprocess.run(["dbt", "build", *extra], cwd=DBT_DIR, env=env,
                               capture_output=True, text=True)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)

    passed, failed = record(DBT_DIR / "target" / "run_results.json")
    label = " ".join(extra) or "build"
    print(f"dbt {label}: {passed} passed, {failed} failed (exit {completed.returncode})",
          flush=True)
    # A non-zero exit is what makes the nightly alert fire before the owner sees
    # a wrong number.
    return completed.returncode


def schedule() -> int:
    """Run forever. Never returns; the container restart policy is the retry."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("dbt scheduler up: %s", [f"{every}s {' '.join(extra)}" for every, extra in SCHEDULE])

    # Build everything once at boot, so a fresh install has marts before the
    # first minute elapses rather than an admin panel full of empty panels.
    _guarded(["--full-refresh"])
    last = [time.monotonic()] * len(SCHEDULE)

    while True:
        time.sleep(5)
        now = time.monotonic()
        for i, (every, extra) in enumerate(SCHEDULE):
            if now - last[i] >= every:
                _guarded(extra)
                # Stamped after the run, not before: a build that overruns its
                # interval delays the next one instead of stacking up behind it.
                last[i] = time.monotonic()


def _guarded(extra: list[str]) -> None:
    """A failed build must not take the scheduler down with it.

    Postgres restarting mid-run raises out of record(); without this the
    scheduler would exit and the marts would quietly stop moving.
    """
    try:
        run_once(extra)
    except Exception:                                    # noqa: BLE001
        log.exception("dbt run failed: %s", " ".join(extra) or "build")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select", default="")
    parser.add_argument("--full", action="store_true", help="full refresh plus every test")
    parser.add_argument("--schedule", action="store_true",
                        help="run on the built-in schedule until killed")
    args = parser.parse_args()

    if args.schedule:
        return schedule()
    if args.full:
        return run_once(["--full-refresh"])
    return run_once(["--select", args.select] if args.select else [])


if __name__ == "__main__":
    raise SystemExit(main())
