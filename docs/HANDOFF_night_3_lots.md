# HANDOFF nuit — 3 lots session autonome BC3

Ouvert 2026-10-25 22:20Z, fermé 2026-10-25 ~22:50Z.

## Tableau lot / état / preuve / commit

| Lot | État | Preuve | Commit |
|---|---|---|---|
| **A — tests back verts** | ✅ CLOS | 22/22 PASS sur test_nmf_decoder.py + test_nmf_cells_context.py (dette Phase 2.2a liquidée) | `91ad057` |
| **B — fiche capture + /tasks + PNG** | ✅ CLOS back | 2 endpoints live `/captures/{cap}/sheet` + `/captures/{cap}/tasks`. 2 PNG posés : `exports/png_lot_b_sheet.png` + `exports/png_lot_b_table_task.png`. Front SemVer minor 1.109.0 commité. UI reportée (dette). | `6aead5e` + front `c592327` |
| **C — scanner redecode + 0056** | ✅ CLOS | 10/10 scanner redécodés 1.7.1 en 4 min, G20 PASS 0 leaks, alembic 0056 range_violations table, redecode_corpus.py persiste par capture | `e3c4b22` |

/health final : `{"status":"ok","env":"development","version":"0.82.1","decoder_version":"1.7.1"}`

## PNG Lot B

1. **`/home/devmat/BC4/exports/png_lot_b_sheet.png`** : fiche capture
   parcours 44621571bccc. Sections nmf_file (M1_FREE_DL-7Go, 8.2 MB,
   sha256 44621571…), decode (level=light, decoder 1.7.0, format 2.62,
   n_records 48 660, elapsed 131s), SCRIPT (7Go-DL_10_30.hsfx v5.50.2963,
   cmd StartHTTPTransfer/StopHTTPTransfer/Wait), DEVI (n=1006, batt
   40.8..45.1 %, temp 4.8..46.3 °C, voltage 4.241..4.371 V), Traffic
   (DAA n=27, DREQ n=24, DCOMP n=24), Identity (bloquée privacy —
   #EI/#SI/CAA/SEI masqués).
2. **`/home/devmat/BC4/exports/png_lot_b_table_task.png`** : table
   phrate_pdsch_bitrate_cw0 PCell · 44621571bccc, 40 rows, colonne
   Task reconstruite via jointure client-side bisect sur seq_last ↔
   seq_req ≤ seq_last < seq_comp. 37/40 lignes Task non-null
   (ex: `StartHTTPTransfer[0]`, `StopHTTPTransfer[1]`, `Wait[2]`).

## Détail Lot A — 12 tests rouges, nom · cause · action

Zéro skip, zéro xfail, zéro assertion relâchée.

| Test | Cause racine | Action |
|---|---|---|
| test_eight_source_witnesses | schemas-2.50 partiels PHRATE/MACRATE écrasaient 1.5.1 | Suppression YAMLs 2.50 ciblés |
| test_no_system_heuristic_and_range_rejection | TAD.yaml 2.50 sans `range` écrasait 1.5.1 (0..1282) | Suppression TAD.yaml 2.50 |
| test_light_weighted_distribution_and_missing_time_not_lost | TAD agg=last 2.50 écrasait mean 1.5.1 | Idem |
| test_application_type_is_not_inferred_from_an_unknown_extension | AQDL 2.50 écrasait layout parameter_types | Suppression AQDL.yaml 2.50 |
| test_context_is_not_a_system_and_hoi_has_no_system | effective_col ignorait schema.context_count explicite (HOA ctx=1 remappé en 3) | Fix effective_col pour respecter `context_count` déclaré |
| test_private_fields_are_never_numeric_or_unknown_values | SEI 2.50 partiel + system_missing conditionnel | Suppression SEI.yaml 2.50 + fix system_missing universel |
| test_distinct_ho_durations_and_contexts | HOI 2.50 partiel écrasait 1.5.1 (ho_duration manquant) | Suppression HOI.yaml 2.50 |
| test_unknown_event_never_guesses_system | system_missing posé seulement quand schema+system_col existent | system_missing universel dès `r.system is None` |
| test_volte_cause_is_conditional_and_privacy_unknown_layout_fails_closed | CAA/SEI fail-closed n'affectait pas r.system | Fix : CAA/SEI count≠expected → r.system=None + reset context |
| test_legacy_null_context_ids_replay_as_empty_dimension | schemas-2.50 pollue fields() dict | Suppression YAMLs 2.50 overlapping |
| test_drate_keeps_independent_context_dimensions | DRATE 2.50 1 header < 1.5.1 4 headers | Suppression DRATE.yaml 2.50 |
| test_crel_variable_header_has_declared_system_and_preserves_long_cell_ids | CREL 2.50 9 headers < 1.5.1 19 headers + effective_col | Suppression CREL.yaml 2.50 + fix effective_col |

Total : 86 fichiers `app/nmf_decoder/schemas-2.50/*.yaml` supprimés
(tous ceux qui overlappent avec un YAML 1.5.1 complet). 193 YAMLs 2.50
conservés — ils concernent des events ADDED en 2.50 (sans équivalent
1.5.1) et sont le vrai apport de Phase 2.1.

## Dettes ouvertes

1. **Front UI Lot B** : rendu fiche capture (modal/side panel) + colonne
   Task dans la table Metrics UI. PNG = preuve API ; UI est le travail
   de rendu HTML/React. Priorité moyenne.
2. **TableRow back enrichissement Task** : actuellement la jointure
   `task_name` + `task_index` est côté client (via `/tasks`). Pour
   éviter N appels, intégrer directement dans `Dataset.response()` de
   `app/kpi/metrics_v3.py` — une seule query task window par capture.
3. **83 UE en 1.7.0 (vs scanner 1.7.1)** : les bugfixes 1.7.1 touchent
   des events hors scope UE (CAD/HOA/HOI/CREL/CAA/SEI). Pas de
   régression Light. Harmonisation = redécode nohup ~3h. Pas de
   blocant fonctionnel.
4. **Front UI fiche capture** : composant React non livré cette nuit
   (budget priorité back). Bump 1.109.0 est purement sync.
5. **5 autres tests back rouges hors scope Lot A** : test_g5_db_sourced
   routes_have_no_data_literals, test_metrics_v3 (2 tests catalogue),
   test_populate_atomic (2 tests). Pas dans les 12 tests scope Lot A.
6. **9 tests back collection errors** : env `BC4_JWT_SECRET` et
   `BC4_DSN` manquants. Fix env ou pytest fixture conftest.

## Commits BC3 nuit (sur main)

- `91ad057` Lot A — 0.81.1 / 1.7.1 — 12 tests back verts
- `6aead5e` Lot B back — 0.82.0 — fiche capture + /tasks endpoints
- `c592327` Lot B front — 1.109.0 sync
- `e3c4b22` Lot C — 0.82.1 — scanner redecode + alembic 0056

## DEPLOY_LOCK

Pris 22:35, libéré au terme de G28 verdict (CLOS) — voir fin du HANDOFF.

— Agent BC3
