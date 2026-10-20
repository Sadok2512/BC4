"""F1 (0.64.0) — Patche catalog_v2.json pour les 10 KPI prioritaires F4.

Chaque KPI reçoit ``available_check: {kind: "events_present", arg: [events]}``
→ permet le calcul dynamique de disponibilité (événements NMF présents
dans le projet) tout en gardant le statut PENDING "calcul non implémenté
(F4)" tant que le code F4 n'est pas livré.

Idempotent : relancer ne touche pas une entrée déjà convertie.
"""
from __future__ import annotations

import json
from pathlib import Path


MAPPINGS: dict[str, list[str]] = {
    # 1 — RRC Setup Success Rate = RRC/RRA (cause dans RRD)
    "LTE_RRC_SETUP_SR":        ["RRA", "RRC", "RRD"],
    "LTE_RRC_SETUP_LATENCY":   ["RRA", "RRC"],
    # 2 — Call Setup Success Rate / Time (VoLTE)
    "LTE_VOLTE_CALL_SETUP_SR": ["CAA", "CAC"],
    # 3 — Call Drop Rate
    "LTE_CALL_DROP_SR":        ["CAC", "CAD"],
    # 4 — Data Session SR / Drop déjà mp-based en 2.0.0 ; skip
    # 5 — Débit DL/UL app = AGG_APP_DL/UL_THR (transfers_table, déjà actif)
    # 6 — HO Success Rate (intra, inter, inter-RAT)
    "LTE_HO_INTRA_SR":         ["HOA", "HOS"],
    "LTE_HO_INTER_SR":         ["HOA", "HOS"],
    "LTE_HO_IRAT_SR":          ["HOA", "HOS"],
    "LTE_HO_INTRA_SUCCESS":    ["HOS"],
    "LTE_HO_INTER_SUCCESS":    ["HOS"],
    "LTE_HO_IRAT_SUCCESS":     ["HOS"],
    # 7 — MOS DL : AQDL déjà serveur en mp_metric aqdl_mos ; skip
    # 8 — Ping RTT P50/P90 : KPI probable LTE_LATENCY_PING_* (hors catalog v2 actuel)
    # 9 — RSRP ≥ -105 dBm : LTE_RF_RSRP (mp_metric) sert la source — seuillage ∈ F4
    # 10 — SINR ≥ 10 dB : LTE_RF_SINR idem
    #
    # NR homologues (restent always_unvalidated car NR non décodé par Nemo
    # pour l'instant, mais candidats F4 quand BC1 livre les paths NR)
    "NR_RRC_SETUP_SR":         ["RRA", "RRC"],
    "NR_HO_INTRA_SR":          ["HOA", "HOS"],
    "NR_HO_INTER_SR":          ["HOA", "HOS"],
    "NR_HO_IRAT_SR":           ["HOA", "HOS"],
    "NR_CALL_DROP_SR":         ["CAC", "CAD"],
    "NR_VONR_CALL_SETUP_SR":   ["CAA", "CAC"],
}


def main() -> None:
    path = Path("/app/app/kpi/catalog_v2.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    by_code = {e["code"]: e for e in data["entries"]}

    patched: list[str] = []
    not_found: list[str] = []

    for code, events in MAPPINGS.items():
        entry = by_code.get(code)
        if not entry:
            not_found.append(code)
            continue
        current = (entry.get("available_check") or {}).get("kind")
        if current == "events_present":
            continue  # already patched
        # On accepte de patcher les KPI dont la règle est unavailable
        # ou unvalidated (= pas de calcul réel). On ne touche jamais les
        # règles productives (nmf_metric, mp_metric, transfers_table,
        # param_message_eq…).
        if current not in {"always_unavailable", "always_unvalidated"}:
            continue
        entry["available_check"] = {"kind": "events_present", "arg": events}
        patched.append(code)

    base = str(data.get("catalog_version") or "")
    tag = "-bc2-f4-events-2026-10-20"
    if tag not in base:
        data["catalog_version"] = base.split("-bc2-f4-")[0] + tag
    data["patch_notes_f4"] = (
        "F1 (0.64.0) : 10 KPI prioritaires F4 convertis vers "
        "events_present pour calcul dynamique de disponibilité. "
        "Formule et code service_v2 à livrer en F4."
    )
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"patchés  : {patched}")
    print(f"introuvables (KPI absents de catalog_v2) : {not_found}")
    print(f"catalog_version = {data['catalog_version']}")


if __name__ == "__main__":
    main()
