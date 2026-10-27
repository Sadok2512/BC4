#!/bin/bash
set -o pipefail
export PGPASSWORD='TEST-G34-DB'
export BC4_DSN='postgresql+psycopg://bc4_g34:TEST-G34-DB@127.0.0.1:55437/bc4_g34'
export BC4_JWT_SECRET='TEST-G34-EPHEMERAL-ONLY-SECRET-32-BYTES'
psql -h 127.0.0.1 -p 55437 -U bc4_g34 -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE bc4_g34 WITH (FORCE)' -c 'CREATE DATABASE bc4_g34 OWNER bc4_g34'
/home/devmat/BC4/bc4-back/.venv/bin/alembic upgrade 0056_range_violations; echo "empty_to_0056_exit=$?"
/home/devmat/BC4/bc4-back/.venv/bin/alembic downgrade 0051_param_occurrence_fk_index; echo "downgrade_0056_to_0051_exit=$?"
/home/devmat/BC4/bc4-back/.venv/bin/alembic upgrade 0056_range_violations; echo "reupgrade_0051_to_0056_exit=$?"
psql -h 127.0.0.1 -p 55437 -U bc4_g34 -d bc4_g34 -P pager=off -c "SELECT column_name,data_type FROM information_schema.columns WHERE table_name='nmf_event_light' AND column_name='dci_dci_count'"
