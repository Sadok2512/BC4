# HANDOFF — Phase 2.51.0 1b CLOS

Fermé par BC3 le 2026-10-25 ~21:55Z.
Branche `feat/bc3-catalog-2.51` mergée dans `main` (merge commit `b505076`).
Back **0.81.0** / decoder **1.7.0** live. Catalog **2.51.0** `is_current=TRUE`.

## Livrables

### Decoder 1.7.0 (`aa4c05b`, `c7e5596`, `dfbf4bf`, `d8eba79`)

- `schema_for(event, system)` : dispatch LTE/NR via `_variants[9]`
  posés depuis les YAMLs `*_NR` (CELLMEAS, MIMOMEAS, TAD, TXPC, PHRATE).
- `txpc_cell_type()` RESTRICTE à LTE (`r.system==7`). NR via header
  dimension `txpc.cell_type` dans TXPC_NR.yaml (observations 101, 108,
  117, 199 sur 723547b196b3).
- `RANGE_VIOLATIONS` counter global + `reset_range_violations()`.
- PHRATE_NR.yaml créé (4 fields : hdr_n, scope, cell_type dimension,
  pdsch_sch_bitrate).
- CELLMEAS_NR / MIMOMEAS_NR : `start: INT` corrigé (col absolue de count,
  pas `header_col` avec préfixe variable).
- `cells.py` SKIP NR CELLMEAS pour éviter pkey violation
  `nmf_cell_second` (pkey ne distingue pas LTE PCell=0 de NR PCell=0 ;
  migration pkey+system = lot ultérieur). Series cells NR via
  `nmf_event_light_group.cell_type`.
- Light.add neighbors CELLMEAS SKIP NR (sémantique LTE 1.5.1 seule).
- `schemas-2.50/PHRATE.yaml` SUPPRIMÉ (partiel 1 header, écrasait le
  1.5.1 complet 17 headers → PDSCH/PBCH/PUSCH fields NULL depuis Phase
  2.2a). Decoder retombe sur schemas/PHRATE.yaml 1.5.1 + PHRATE_NR.yaml.

### Alembic 0053 + 0054

- 0053 : +19 cols NR headers dans `nmf_event_light` + `nmf_event_deep`,
  +14 cols NR cells/measurements dans `nmf_event_light_group` +
  `nmf_event_group`.
- 0054 : +14 cols NR cells dans `nmf_event_light` (codes propagés au
  bucket Light principal par la boucle sans `aggregate_selection=first`).

### Catalog 2.51.0 (`d8eba79`, posé par build_catalog.py --commit)

- sha256 **`8dc4bcf8222630fab696c9ce54685a076597f0f23de0ee7bca5cbcd72c2751cd`**.
- 8690 leaves (3419 metrics + 5271 cell), decoder_min_version=1.7.0.
- `is_current=TRUE` dans table `catalog_release`.
- **7 feuilles cellule canoniques** par event cell-scoped : PCell (0),
  SCell 1-4, PSCell NR (199), SCell NR 100+. `selectable=false` +
  `reason` si cell_type jamais observé. Les champs `extra_N` / `*_fil`
  (FF 2.62 par contenu) sont posés `selectable=false`.
- `build_catalog.corpus_cell_types()` lit cell_types depuis
  `nmf_event_light_group` (groupes `cells`, `measurements`) en plus de
  `nmf_event_light.dimension` (couverture NR via groupes).

### Redécode UE 83 captures (1.7.0)

- PID=9159 lancé 2026-10-25 18:05, DONE 21:31. Durée totale **~3h26**.
- 83 captures OK, 0 failed.
- **Moyenne elapsed par capture = 148.9 s**.
- Min 20 s, max 644 s (deep 134af70a06eb/723547b196b3 83028 records).
- `SELECT decoder_version, kind, COUNT(*) FROM nmf_capture GROUP BY 1,2`
  = **1.7.0 ue 83** + **1.6.0 scanner 10**. (Les 10 scanners ne font
  pas partie du scope ue et restent en 1.6.0 — hors cell-scoped NR.)

### Cause lenteur initiale

Les 5 premières captures ont pris moyenne 420s (vs attendu 150s).
Cause : 5 instances orphelines de `G28_ranges_corpus.py` lancées lors
de debugging consommaient 500+ queries `SELECT COUNT()` concurrentes
→ CPU bc4-api-1 saturé → le redécode partageait le CPU. Nettoyage à
18:07 (`pkill -9 G28`) → vitesse normale restaurée (moyenne stable
~130s/capture ensuite).

### PNG #2 et #3

- **PNG #2** `/home/devmat/BC4/exports/png2_phrate_pdsch_bitrate_cw0_pcell.png`
  : PHRATE PDSCH bitrate cw0 PCell sur 44621571bccc. 589 points,
  max 96.5 Mbit/s. Dispatch `phrate_ph_ch_type=2` + filtre dim
  `pdsch.cell_type=0`.
- **PNG #3** `/home/devmat/BC4/exports/png3_cellmeas_nr_rsrp_mt1_ct199.png`
  : CELLMEAS NR RSRP meas_type=1 cell_type=199 (PSCell) sur
  723547b196b3. 579 points, RSRP ∈ [-112, -73] dBm, p50 -91. Join
  `nmf_event_light × nmf_event_light_group` groupe `cells`.
- **Arbre NR non vide** prouvé : CELLMEAS NR expose cell_type ∈
  {117, 199, 1000} meas_type=1 avec 2397 / 6147 / 17907 lignes RSRP
  non-NULL.

### Gardes post-redécode

- **G20** scanner-only : **PASS** (0 scan events sur captures UE,
  479943 scan events sur 10 scanner captures).
- **G25** catalogue : **PASS** 0 orphans / 0 dup node_ids / 0 dup
  metric codes (après truncate `metrics_catalog_cache` + GET /metrics
  warm).
- **G18b** parity cache↔fresh : **PASS** 0 divergent après invalidation.
- **G24** false_zeros witness 134af70a06eb : **PASS** 0 false_zeros
  sur 281 colonnes recomptées (507 candidates, 281 avec `source_column`
  non vide dans Light).
- **G28** ranges corpus : **PASS 1.7.0** après fix tad_ta range NR
  (0..1282 LTE → 0..3846 NR union, NFF 2.50 §TAD NR).
- **G29** file vs db : tableaux par event par capture témoin produits.

### Tests back

`python3 -m pytest tests/test_nmf_decoder.py tests/test_nmf_cells_context.py`
= **10 passed / 12 failed**. Les 12 fails sont la **dette baseline
Phase 2.2a** (YAMLs 2.50 partiels écrasent 1.5.1 pour PHRATE/MACRATE/
CI/TXPC/CQI). Pas de régression introduite par le lot 1b. Fix dette =
build_yamls.py reconstruit toutes les sections d'un event multi-section
(scope ultérieur).

## Commits BC3 posés (feat/bc3-catalog-2.51 → main)

```
b505076 Merge feat/bc3-catalog-2.51 → main
d8eba79 Suppression PHRATE.yaml 2.50 partiel + catalog 2.51.0 posé
8ac12b8 Redécode : témoins (723547b196b3, 44621571bccc) prioritaires
975abb0 HANDOFF 1b mi-course — PID=4513
dfbf4bf Fix YAMLs NR start=INT + cells.py skip NR + build_catalog group
c7e5596 Alembic 0054 — cell_* NR cols dans nmf_event_light (fix 0053)
aa4c05b 0.81.0 — Decoder 1.7.0 NR dispatch + alembic 0053 + PHRATE_NR
3a8a0b2 Audit 1a Phase 2.51.0 + YAMLs NR + HANDOFF 1b (préalable)
```

## Dettes connues à acter

1. **nmf_cell_second absent pour NR** — pkey ne distingue pas LTE
   PCell=0 de NR PCell=0. Lot ultérieur : migration `ALTER TABLE
   nmf_cell_second ADD COLUMN system int` + inclusion dans pkey +
   cells.py génère NR aussi + /metrics v3 propage system.
2. **Tests back 12 fails baseline** — dette Phase 2.2a, scope séparé.
3. **RANGE_VIOLATIONS non persisté** — counter in-process, perdu au
   restart container. Patch script redecode_corpus.py pour dumper en
   fin de run (TODO lot ultérieur).
4. **Scanner captures en 1.6.0** — 10 captures scanner-only n'ont pas
   été incluses dans le --kind ue. Reste à décider si on les redécode
   (pas d'intérêt NR car scanner ≠ UE).

## DEPLOY_LOCK

Libéré 2026-10-25 ~21:55Z. Lot 1b CLOS.

— Agent BC3
