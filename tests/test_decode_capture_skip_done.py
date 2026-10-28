"""Snapshot de capture immuable — gate `app/nmf_decoder/store.py` ligne 78.

Vérifie qu'une capture déjà présente dans `nmf_capture` (`old` non-None)
est TOUJOURS skippée par `decode_capture()`, sauf `force=True`. Le test
est pur-mock : aucune DB réelle n'est touchée, aucun fichier NMF n'est lu.
Il isole la seule logique du gate.

Pattern : mock minimal de `db` et de la requête `SELECT * FROM nmf_capture`.
Le reste du code (`records()`, `copy_rows`, `write_light`) n'est jamais
atteint parce que le gate retourne avant.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.nmf_decoder import store


class _Mapping(dict):
    """Objet avec `.mappings().first()` → dict (comme SQLAlchemy Result)."""


def _mock_db(old_row: dict | None):
    db = MagicMock()
    advisory_result = MagicMock()
    old_result = MagicMock()
    old_result.mappings.return_value.first.return_value = old_row
    # Pas de 2e appel attendu si le gate skip ; mais au cas où le code
    # du gate évolue, on configure une seconde réponse (project_parsing).
    project_parsing = MagicMock()
    project_parsing.mappings.return_value.one.return_value = {
        "binning_mode": "temporal",
        "temporal_resolution": "native",
        "spatial_bin_m": None,
        "aggregation_contract_version": "query-binning-v1",
    }
    # Séquence : advisory_lock → SELECT nmf_capture → (projet si pas old).
    db.execute.side_effect = [advisory_result, old_result, project_parsing]
    return db


def test_skip_when_capture_already_present_decoder_version_identical():
    """Historique : avant 2026-10-28 le gate skippait seulement si
    `decoder_version==DECODER_VERSION`. On garde le test de ce cas pour
    assurer la non-régression (ce cas doit toujours skip)."""
    old = {
        "decoder_version": store.DECODER_VERSION,
        "decode_level": "deep",
    }
    db = _mock_db(old)
    result = store.decode_capture(db, "pid-X", "cap-X", "deep")
    assert result["skipped"] is True
    assert result["reason"] == "snapshot_immuable"
    assert result["kept_decoder_version"] == store.DECODER_VERSION
    db.commit.assert_called_once()


def test_skip_when_capture_already_present_decoder_version_older():
    """Nouveau contrat 2026-10-28 : même si `old['decoder_version']` est
    une version antérieure (ex. '1.7.1'), on NE re-décode pas. C'est le
    cas qui corrige l'incident Test_5 (ensure_light propageait silencieu-
    sement 1.7.1 → DECODER_VERSION live sur les 22 captures)."""
    old = {
        "decoder_version": "1.7.1",  # ≠ DECODER_VERSION live
        "decode_level": "deep",
    }
    db = _mock_db(old)
    result = store.decode_capture(db, "pid-X", "cap-X", "deep")
    assert result["skipped"] is True
    assert result["kept_decoder_version"] == "1.7.1"


def test_skip_when_capture_already_present_level_differs():
    """Avant 2026-10-28, un `old['decode_level']='light'` + `level='deep'`
    déclenchait une promotion light→deep. Le nouveau contrat refuse
    aussi ce chemin implicite — un passage deep se demande via
    reparse_capture --force."""
    old = {
        "decoder_version": store.DECODER_VERSION,
        "decode_level": "light",
    }
    db = _mock_db(old)
    result = store.decode_capture(db, "pid-X", "cap-X", "deep")
    assert result["skipped"] is True


def test_force_true_bypasses_the_gate():
    """Seule porte de sortie : `force=True`. Vérifie que le gate NE skip
    pas et que l'exécution continue (donc provoque un AttributeError sur
    les mocks suivants, parce qu'on n'a pas tout préparé — c'est la
    preuve que le code est passé par-dessus le gate)."""
    old = {
        "decoder_version": "1.7.1",
        "decode_level": "deep",
    }
    db = _mock_db(old)
    # Un `records(...)` réel ouvrirait un fichier ; on s'attend donc à
    # une erreur quand on continue au-delà du gate avec `force=True`.
    import pytest
    with pytest.raises(Exception):
        store.decode_capture(db, "pid-X", "cap-X", "deep", force=True)
    # Au moins l'advisory_lock + SELECT nmf_capture ont été exécutés.
    assert db.execute.call_count >= 2


def test_decode_when_capture_absent():
    """Première ingestion : `old` est None, le gate laisse passer et le
    code atteint le fetch du fichier (où le mock lève)."""
    db = _mock_db(None)
    import pytest
    with pytest.raises(Exception):
        store.decode_capture(db, "pid-X", "cap-X", "deep")
    # Advisory lock + SELECT nmf_capture + SELECT project_parsing.
    assert db.execute.call_count >= 3
