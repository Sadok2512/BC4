"""`app.scripts.reparse_capture` — contrat CLI et audit JSON.

Vérifie :
- `--reason` est obligatoire ;
- la commande refuse si l'advisory lock du worker ne peut pas être pris ;
- la commande imprime les 10 colonnes de snapshot before/after.

Pur-mock : la connexion `engine.connect()` / `SessionLocal()` et
`decode_capture()` sont mockés. Aucune DB touchée.
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest


def test_requires_reason_argument():
    """argparse doit refuser l'appel sans --reason."""
    from app.scripts import reparse_capture

    with patch("sys.argv", ["reparse_capture", "pid-1", "cap-1"]):
        with pytest.raises(SystemExit) as exc:
            reparse_capture.main()
        # argparse exit code 2 pour missing required arg.
        assert exc.value.code == 2


def test_refuses_when_worker_lock_held():
    """Si pg_try_advisory_lock renvoie False → exit 1, pas de decode."""
    from app.scripts import reparse_capture

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_engine.connect.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.scalar.return_value = False  # lock refusé

    with patch.object(reparse_capture, "engine", fake_engine), \
         patch.object(reparse_capture, "guard_bc3_deploy_lock", return_value=True), \
         patch.object(reparse_capture, "decode_capture") as fake_decode, \
         patch("sys.argv", ["reparse_capture", "pid-1", "cap-1",
                            "--reason", "manual re-parse pour test"]):
        rc = reparse_capture.main()
        assert rc == 1
        fake_decode.assert_not_called()


def test_writes_before_after_audit_json(tmp_path):
    """Après succès, l'audit JSON contient before/after/reason/op_id."""
    from app.scripts import reparse_capture

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_engine.connect.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.scalar.return_value = True  # lock pris

    fake_db = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__.return_value = fake_db

    before_row = {
        "project_id": "pid-1", "capture_id": "cap-1",
        "decode_level": "deep", "decoder_version": "1.7.1",
        "schema_version": "1.7.1", "format_version": "2.59",
        "binning_mode": "temporal", "temporal_resolution": "native",
        "spatial_bin_m": None, "aggregation_contract_version": "query-binning-v1",
        "n_records": 100, "n_partial": 100,
    }
    after_row = {**before_row, "decoder_version": "1.7.2", "schema_version": "1.7.2"}
    # 1er appel SELECT snapshot BEFORE → row ; 2e appel AFTER → row2.
    fake_db.execute.return_value.mappings.return_value.first.side_effect = [
        before_row, after_row,
    ]

    with patch.object(reparse_capture, "engine", fake_engine), \
         patch.object(reparse_capture, "guard_bc3_deploy_lock", return_value=True), \
         patch.object(reparse_capture, "SessionLocal", lambda: fake_session), \
         patch.object(reparse_capture, "decode_capture") as fake_decode, \
         patch.object(reparse_capture, "_audit_dir", lambda: tmp_path), \
         patch("sys.argv", ["reparse_capture", "pid-1", "cap-1",
                            "--reason", "unit test re-parse"]):
        fake_decode.return_value = {"capture_id": "cap-1", "level": "deep",
                                     "n_records": 100, "n_partial": 100,
                                     "elapsed_s": 1.5, "kind": "ue"}
        rc = reparse_capture.main()
        assert rc == 0
        fake_decode.assert_called_once()
        # L'appel passe bien force=True (seul point qui court-circuite le gate).
        kwargs = fake_decode.call_args.kwargs
        assert kwargs.get("force") is True

    files = list(tmp_path.glob("*_cap-1.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["reason"] == "unit test re-parse"
    assert payload["before"]["decoder_version"] == "1.7.1"
    assert payload["after"]["decoder_version"] == "1.7.2"
    assert "op_id" in payload and payload["project_id"] == "pid-1"
