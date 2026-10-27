from pathlib import Path


def test_recovery_marker_is_exact_decoder_failure() -> None:
    script = Path("app/scripts/requeue_import_schema_failures.py").read_text()
    assert 'column "dci_dci_count" of relation "nmf_event_light" does not exist' in script
    migration = Path("alembic/versions/0060_light_dci_count_repair.py").read_text()
    assert 'ADD COLUMN IF NOT EXISTS "dci_dci_count" DOUBLE PRECISION' in migration
