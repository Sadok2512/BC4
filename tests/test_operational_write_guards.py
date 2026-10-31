from pathlib import Path


GUARDED_OPERATIONAL_WRITERS = (
    "app/scripts/backfill_capture_kind.py",
    "app/scripts/backfill_cell_identity.py",
    "app/scripts/backfill_dict_network_catalog.py",
    "app/scripts/backfill_probable_cell_links.py",
    "app/scripts/backfill_signaling_materialized.py",
    "app/scripts/backfill_utc_offset_min.py",
    "app/scripts/delete_capture.py",
    "app/scripts/project_cell_second.py",
    "app/scripts/reparse_capture.py",
    "app/scripts/reimport_cell_reference.py",
    "app/scripts/requeue_import_decoder_172_failures.py",
    "app/scripts/requeue_import_schema_failures.py",
    "scripts/_oneshot_populate_full.py",
    "scripts/_oneshot_populate_mp_ref.py",
    "scripts/_oneshot_populate_mp_ref_purge.py",
    "scripts/backfill_measurements.py",
    "scripts/backfill_system.py",
    "scripts/catalog/redecode_corpus.py",
    "scripts/mirror_ingest_to_b0.py",
    "scripts/populate_dict_for_all_projects.py",
    "scripts/re_refresh_after_plmn_extension.py",
    "scripts/repair_cellmeas_0543.py",
    "scripts/admin/reset_admin_password.py",
    "app/scripts/invalidate_catalog_cache.py",
)


def test_all_operational_database_writers_use_deploy_guard():
    missing = [
        path for path in GUARDED_OPERATIONAL_WRITERS
        if not any(
            guard_name in Path(path).read_text(encoding="utf-8")
            for guard_name in ("guard_bc3_deploy_lock", "require_bc3_deploy_lock")
        )
    ]
    assert missing == []


def test_legacy_catalog_commit_path_is_fail_closed():
    source = Path("scripts/catalog/rebuild_2_50_5_uniqueids.py").read_text(
        encoding="utf-8"
    )
    assert "catalog_database_writes_require_bootstrap_catalog_release" in source
    assert "UPDATE catalog_release" not in source
