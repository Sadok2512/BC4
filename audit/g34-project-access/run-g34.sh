#!/bin/bash
set -o pipefail
export BC4_DSN='postgresql+psycopg://bc4_g34:TEST-G34-DB@127.0.0.1:55437/bc4_g34'
export BC4_JWT_SECRET='TEST-G34-EPHEMERAL-ONLY-SECRET-32-BYTES'
export BC4_NMF_DECODER_PATH='/home/devmat/BC4/decoder'
export BC4_NMF_SOURCE_DIR='/tmp/bc1-g34-nmf-source'
export G34_EPHEMERAL_DB='YES'
export G34_NMF_PATH='/tmp/G34-real-corpus.nmf'
/home/devmat/BC4/bc4-back/.venv/bin/python scripts/guards_2026_10/G34_project_access.py
code=$?
echo "$code" > audit/g34-project-access/G34_complete.exit
exit "$code"
