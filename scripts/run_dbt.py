"""Run dbt and record the result in meta.dbt_runs.

Cron calls this rather than dbt directly, so model duration, failures and
freshness become queryable -- and so fo_mart_last_build_timestamp has something
to report. Airflow to schedule six SQL models would be four containers of
ceremony and a second Postgres to page yourself about.

Crontab (on the worker host):

    * * * * *   cd /srv && python -m scripts.run_dbt --select tag:realtime
    0 * * * *   cd /srv && python -m scripts.run_dbt --select tag:hourly
    30 3 * * *  cd /srv && python -m scripts.run_dbt --full
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.conn import Role, tx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = ROOT / "dbt"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select", default="")
    parser.add_argument("--full", action="store_true", help="full refresh plus every test")
    args = parser.parse_args()

    command = ["dbt", "build"]
    if args.full:
        command.append("--full-refresh")
    elif args.select:
        command += ["--select", args.select]

    env = {**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)}
    completed = subprocess.run(command, cwd=DBT_DIR, env=env, capture_output=True, text=True)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)

    passed, failed = record(DBT_DIR / "target" / "run_results.json")
    print(f"dbt: {passed} passed, {failed} failed (exit {completed.returncode})")
    # A non-zero exit is what makes the nightly alert fire before the owner sees
    # a wrong number.
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
