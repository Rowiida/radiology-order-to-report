#!/usr/bin/env bash
# Runs the whole pipeline. Set PGDATABASE (and PGHOST, PGPORT, PGUSER if needed) first.
set -euo pipefail
cd "$(dirname "$0")"

python3 generate_data.py data
psql -v ON_ERROR_STOP=1 -q -f schema.sql
psql -v ON_ERROR_STOP=1 -q -f load.sql
psql -v ON_ERROR_STOP=1 -f kpi_queries.sql
python3 export_dashboard_data.py
python3 build_dashboard.py
