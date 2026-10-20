"""Patche catalog_v2.json : bascule les KPI LTE always_unavailable qui
ont une correspondance stricte au décodeur NMF vers `nmf_metric`.

Chaque mapping est **traçable** à un champ du décodeur (``fields()``)
avec ``agg != None`` et une sémantique sans ambiguïté. Les NR restent
``always_unavailable`` : le décodeur n'expose pas d'événements NR
distincts (CELLMEAS, MACRATE, PHRATE sont LTE-only), un mapping NR →
champ LTE serait de la **mis-attribution** (règle n°1 BC4).

À exécuter depuis le conteneur bc4-api-1 :

    docker exec bc4-api-1 python scripts/patch_kpi_catalog_nmf_metrics.py

Diff direct sur ``app/kpi/catalog_v2.json`` + bump de ``catalog_version``
pour signaler la divergence vis-à-vis du xlsx source. L'opération est
idempotente (relancer n'ajoute rien si les mappings sont déjà posés).
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date


# Mapping curé : KPI code → (NMF arg, unit affiché, justification courte).
#  - ``arg`` est le ``code`` normalisé du décodeur (fields()[arg]).
#  - ``unit`` est celui exposé dans le catalogue KPI ; les débits en
#    ``bit/s`` sont automatiquement convertis en ``Mbit/s`` par
#    ``metric_catalog(db)`` (cf. ``app/kpi/metrics.py`` lignes 25-26).
MAPPINGS: dict[str, tuple[str, str, str]] = {
    # MCS (modulation and coding scheme)
    "LTE_DL_MCS":            ("plaid_mcs0",         "index",   "PDSCH MCS codeword 0 (PLAID.mcs0)"),
    "LTE_UL_MCS":            ("plaiu_mcs0",         "index",   "PUSCH MCS codeword 0 (PLAIU.mcs0)"),
    # BLER UL
    "LTE_UL_BLER":           ("mac_ul_residual_bler", "%",     "MAC UL residual BLER (MACRATEU)"),
    # Débits par couche
    "LTE_DL_MAC_THR":        ("mac_dl_bitrate",     "Mbit/s", "MAC DL throughput (MACRATE)"),
    "LTE_UL_MAC_THR":        ("mac_ul_bitrate",     "Mbit/s", "MAC UL throughput (MACRATEU)"),
    "LTE_DL_RLC_THR":        ("rlc_dl_bitrate",     "Mbit/s", "RLC DL throughput (RLCRATE)"),
    "LTE_UL_RLC_THR":        ("rlc_ul_bitrate",     "Mbit/s", "RLC UL throughput (RLCRATEU)"),
    "LTE_DL_PDCP_THR":       ("pdcp_dl_bitrate",    "Mbit/s", "PDCP DL throughput (PDCPRATED)"),
    "LTE_UL_PDCP_THR":       ("pdcp_ul_bitrate",    "Mbit/s", "PDCP UL throughput (PDCPRATEU)"),
    "LTE_DL_PHY_THR":        ("pdsch_bitrate",      "Mbit/s", "PDSCH throughput (PHRATE)"),
    "LTE_UL_PHY_THR":        ("pusch_bitrate",      "Mbit/s", "PUSCH throughput (PHRATE)"),
    # PRB utilisation
    "LTE_DL_PRB_UTILIZATION": ("plaid_prb_util_dl", "%",      "PRB utilization DL (PLAID)"),
    "LTE_UL_PRB_UTILIZATION": ("plaiu_prb_util_ul", "%",      "PRB utilization UL (PLAIU)"),
}


def _validate_decoder_fields(mappings: dict[str, tuple[str, str, str]]) -> None:
    """Vérifie que chaque arg NMF existe dans le schéma décodeur et
    porte ``agg != None`` (sinon il n'est pas servi par metric_catalog)."""
    from app.nmf_decoder.schema import fields
    nmf = fields()
    missing: list[str] = []
    for kpi, (arg, _unit, _just) in mappings.items():
        f = nmf.get(arg)
        if not f:
            missing.append(f"{kpi} → {arg}: field inexistant")
        elif f.get("agg") is None:
            missing.append(f"{kpi} → {arg}: agg=None (non charté)")
    if missing:
        raise SystemExit("Mappings invalides :\n  - " + "\n  - ".join(missing))


def main() -> None:
    _validate_decoder_fields(MAPPINGS)

    path = Path("/app/app/kpi/catalog_v2.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    patched: list[str] = []
    unchanged: list[str] = []
    not_found: list[str] = []

    for entry in data["entries"]:
        code = entry["code"]
        if code not in MAPPINGS:
            continue
        arg, unit, just = MAPPINGS[code]
        current = (entry.get("available_check") or {}).get("kind")
        if current == "nmf_metric" and (entry.get("available_check") or {}).get("arg") == arg:
            unchanged.append(code)
            continue
        entry["available_check"] = {"kind": "nmf_metric", "arg": arg}
        if unit:
            entry["unit"] = unit
        entry.setdefault("source", "nmf_decoder " + arg + " (BC2 patch)")
        patched.append(code)

    for code in MAPPINGS:
        if not any(e["code"] == code for e in data["entries"]):
            not_found.append(code)

    # Divergence xlsx signalée dans la version catalogue.
    today = date.today().isoformat()
    base_version = str(data.get("catalog_version") or "")
    tag = f"-bc2-nmf-{today}"
    if tag not in base_version:
        data["catalog_version"] = (base_version.split("-bc2-")[0] or base_version) + tag
    data["patch_notes"] = (
        "0.61.0 BC2 : bascule des KPI LTE always_unavailable vers nmf_metric "
        "quand le décodeur Nemo expose un champ homonyme (voir "
        "scripts/patch_kpi_catalog_nmf_metrics.py MAPPINGS). Divergence "
        "vis-à-vis du xlsx source — à ré-aligner au prochain ré-import."
    )

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("Patchés :  ", patched)
    print("Inchangés :", unchanged)
    if not_found:
        print("Introuvables (KPI absent du catalogue):", not_found)
    print(f"catalog_version → {data['catalog_version']}")


if __name__ == "__main__":
    main()
