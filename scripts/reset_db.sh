#!/usr/bin/env sh
# Full local rebuild: migrations down -> up, then reseed the catalog.
# Run from deploy/:  sh ../scripts/reset_db.sh
set -e
sh "$(dirname "$0")/roundtrip.sh"
(cd .. && .venv/Scripts/python.exe -m scripts.seed_catalog)
