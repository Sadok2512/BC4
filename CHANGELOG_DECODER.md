# CHANGELOG_DECODER

## 1.7.1 (patch) — 2026-10-25 — Lot A : 12 tests back verts (Agent BC3)

Bug fixes identifiés par les 12 tests rouges sur main. Zéro skip,
zéro xfail, zéro assertion relâchée.

- `effective_col()` respecte `schema.context_count` déclaré explicitement
  (events 1.5.1 HOA, CAD, CREL) avant de dériver depuis `system_col`.
  Preuve : HOA avec `context_count=1` + `system_col=7` → system à
  tokens[6] (pas tokens[4]).
- `system_missing` ajouté dès que `r.system is None` (plus seulement
  quand schema+system_col existent). Couvre HOI (`systems: any_numeric`,
  `system_col: null`) et les events unknown.
- CAA/SEI fail-closed : si `context_count` dévie du layout documenté
  (CAA attendu 1, SEI attendu 0), on supprime `r.system` en plus
  de `r.context_id`/`r.context_ids`. Preuve : CAA count=2 → aucune
  identité ni system retenus.
- Suppression de **23 schemas-2.50/*.yaml** qui écrasaient leurs
  équivalents 1.5.1 plus complets (TAD, HOA, CAD, SEI, CREL, DRATE,
  AQDL, etc.). build_yamls.py Phase 2.1 générait des YAMLs partiels
  sans groups ni ranges. Le decoder retombe sur les 1.5.1 complets.
- Suppression de 63 autres schemas-2.50/*.yaml partiels (header count
  < 1.5.1 OU groups manquants) — cf. commit du Lot 1b précédent sur
  PHRATE, étendu à MACRATE, CI, TXPC, CQI, PLAID, PLAIU, etc.

Tests : `python3 -m pytest tests/test_nmf_decoder.py tests/test_nmf_cells_context.py`
= **22 passed, 0 failed**.

## 1.7.0 (minor) — 2026-10-25 — Phase 2.51.0 1b : dispatch NR + sentinelles (Agent BC3)

Objet : lever le hack 2.62 `txpc_cell_type()` qui clampait 0-4 et rendait
NR invisible (cell_type observés 101, 108, 117, 199 sur 723547b196b3),
activer le dispatch LTE/NR pour les events partagés, instrumenter les
violations de plage.

- `DECODER_VERSION` 1.6.0 → 1.7.0.
- `app/nmf_decoder/schema.py` :
  - Nouveau helper `schema_for(event, system)` : les YAMLs à suffixe
    `_NR` (CELLMEAS_NR, MIMOMEAS_NR, TAD_NR, TXPC_NR, PHRATE_NR) sont
    chargés sous `_variants[9]` du schema de base et sélectionnés quand
    `system==9`. Les YAMLs LTE restent la base pour `system==7`.
  - `fields()` collecte header + groups des variants NR.
- `app/nmf_decoder/light.py` : `txpc_cell_type()` RESTRICTE à LTE
  (`r.system==7`) — pour NR, cell_type est lu via header `txpc.cell_type`
  (`dimension: true` dans TXPC_NR.yaml) ; le clamp 0-4 reste pour LTE
  (compat 2.59/2.62 content-proven). `dimensions()` et `Light.add()`
  lisent le schema via `schema_for(code, r.system)` pour propager
  `cell_type` depuis les headers marqués `dimension: true`
  (TAD/TXPC/PHRATE/PLAID — LTE **et** NR).
- `app/nmf_decoder/cells.py` : la projection `cell_rows()` lève la
  restriction `cell_index ∈ range(5)` et accepte les codes NR bruts
  (101, 108, 117, 199) comme `cell_index` pour `system=9` — pas de
  mapping inventé, chaque code expose sa feuille distincte dans le
  catalog 2.51.0 (gris + raison si jamais observé).
- `app/nmf_decoder/decoder.py` :
  - Compteur global `RANGE_VIOLATIONS: dict[field_code → int]` incrémenté
    quand une valeur viole `range` ou `enum` (déjà → NULL + partial, désormais
    aussi compté). `reset_range_violations()` au début de chaque run.
  - Dispatch NR : après résolution de `r.system`, bascule sur la variante
    `_variants[9]` si elle existe (ex: TXPC_NR.yaml).
- `app/nmf_decoder/schemas/PHRATE_NR.yaml` CRÉÉ : 4 fields (hdr_n, scope,
  cell_type `dimension:true`, pdsch_sch_bitrate). Spec NFF 2.50 §PHRATE
  Parameters for NR.
- `app/nmf_decoder/schemas/{CELLMEAS,MIMOMEAS}_NR.yaml` corrigés :
  `start.header_col`, `count_code`, `params_code` ajoutés pour que
  `decoder.decode()` lise correctement le count/width du group cells.
- Alembic 0053_decoder_1_7_0_nr_cols :
  - `nmf_event_light` + `nmf_event_deep` : 19 colonnes headers NR
    (cellmeas_scope, mimomeas_hdr_n, mimomeas_params_per_measurement,
    phrate_{cell_type,hdr_n,pdsch_sch_bitrate,scope}, tad_scope,
    txpc_{cell_type,f_il,g_il,n_pusch_tpc,pucch_pl,pusch_ph,pusch_pl,
    scope,srs_tx_power,tx_power,ul_type}).
  - `nmf_event_light_group` + `nmf_event_group` : 14 colonnes cells NR
    (cell_bi, cell_extra_{1,2}, cell_meas_type, cell_port,
    cell_{rsrp,rsrq,sinr}_fil, cell_{rsrp,rsrq,sinr,rssi}_p, cell_sinr,
    cell_to).
  - Tous en `double precision`, nullable, `ADD COLUMN IF NOT EXISTS`.

Sentinelles connues (à dumper post-redécode dans
`exports/decoder_1_7_0_sentinels.log`) :
- CELLMEAS NR cell.band = 99999, cell.pci = 99999 (observation audit 1a).

Les colonnes nommées `extra_N` et `*_fil` sortent avec
`selectable=false` + `reason="FF 2.62 non documenté 2.50 — nommage par
contenu BC3 2026-10-25"` dans le catalog 2.51.0.

## 1.6.0 — 2026-10-24 — Phase 2.2a (Agent BC3)

- `DECODER_VERSION` bumped 1.5.1 → 1.6.0.
- `app/nmf_decoder/schema.py` : charge `schemas-2.50/` pour les 98 SIMPLE
  events du corpus (fichier scope `corpus_events_2_2a.txt`, 113 events),
  fallback `schemas/` 1.5.1 pour les 12 COMPLEX events (header+group
  préservés) + non-corpus.
- `app/nmf_decoder/source.py` : skip binary NMFS header pour futur support
  Keysight `.nmfs` (oracle hors chemin critique Phase 2.2a).
- `scripts/catalog/build_yamls.py` : filtre structurels synchro avec audit
  (Measured system, #Header params, #Cells, #Params/*, Scope, counters #).
- Alembic 0049_nmf_event_light_ext : table narrow jsonb pour events hors
  corpus (futur dual-write si besoin).
- Alembic 0050_light_2_50_cols : ADD COLUMN × 261 non-structurels pour
  les 98 SIMPLE events corpus. nmf_event_light : 393 → 654 cols.
- Gap manuel : `dci_dci_count` ADD COLUMN ad-hoc (audit regex `_count$`
  trop agressif — DCI count est métrique, pas compteur).

Test TEST_1_6 44621571bccc :
- n_records = 48 660, light = 22 187 (vs 27 651 en 1.5.1, agg 2.50 différente),
- RRCSM = 2389, L3SM = 31 (contrats BC3 exacts),
- 53/261 nouvelles colonnes 2.50 enrichies de data.
# Nemo decoder changelog

Version independent of the API. Patch: corrected position/unit or additional documented field. Minor: new event/system. Major: changed meaning of an existing field, requiring re-decode.

## 1.3.0 (minor) — 2026-10-21 (Agent BC1)

- Preserve the CELLMEAS repeated-cell discriminator in the per-second cell projection: type 0 is PCell and content-proven types 10–13 are SCell1–4.
- Leave neighbour/type-1 and observed codes 14/15 outside serving-cell series. NR PSCell/SCell leaves remain visible with `proof=open` until P4 is closed.

## 1.2.2 (patch) — 2026-10-21 (Agent BC2)

- Correct documented CREL positions for header sizes 1 and 2; reject unproved mixed-system layouts instead of guessing a system.
- Add documented LOCK attributes and repeated variable-size forcing blocks. Preserve extensions as unknown; Light uses the last full snapshot.

## 1.2.1 (patch) — 2026-10-21 (Agent BC2)

- Emit neighbor snapshots only when the CELLMEAS group count was decoded. Unknown NR layouts yield no inferred zero and cannot collide with LTE in a second.

## 1.2.0 (minor) — 2026-10-21 (Agent BC2)

- Event schemas declare physical system columns and expected context count. Context IDs are separate typed attributes. System-less events remain partial/system_missing while documented attributes are decoded.
- Corrected HOA/HOI and context-bearing event positions; explicit occurrence-only schemas for unproved events. Corrected CAA/SEI privacy positions, including numeric and hexadecimal values.
- Serving index 0–4 discriminants on documented LTE PHRATE/MACRATE/PLAID/CQI/CI; no guessed MACRATEU/PLAIU cell index. Per-cell and total projections use the same Light accumulators.
- Both HO clocks retained: state-event difference versus NFF 2.19 p266 RRC-to-RACH duration. Old captures require deterministic replay to acquire the new attributes and projections.
- Unproved CELLMEAS secondary-cell mapping, CQI total weighting, configured-CA occupation time and SCell band/add/remove attribution remain unavailable.

## 1.0.0 — 2026-10-19 (Agent BC2)

- Declarative NFF 2.19 schemas seeded from the supplied 95-row CSV, extended with documented repeated groups and common application metrics. 1-based columns; dynamic header/group counts. Source format is recorded; later formats and NR remain explicitly partial.
- Total non-RRC parsing: physical line number and canonical capture/seq, typed values, invalid values retained but never exposed as valid metrics, unknown numeric tokens retained verbatim. Unknown strings (including quoted numbers) become SHA-256 prefixes (16 hex characters) with unk_string flags. #EI/#SI/#DN are excluded; CMDREQ uses the existing redactor. ASN.1 is unchanged.
- Partitioned typed Deep, typed repeated groups, deterministic per-second Light and Light group summaries. Deep replay uses the same aggregation as streaming ingestion. First reported cell/port is the default radio projection; all groups remain in storage. Weighted PLA/CQI distribution summaries use the declared weights. No interpolation.
- Admin replay jobs use the existing import worker. Idempotent capture-level commits and versioned status. Metrics derive from schemas and decoded tables; obsolete positional metric extraction is retired.
- Seed discrepancy corrected from PDF p136: MIMOMEAS antenna-port channels 100..133 are an explicit enumeration in addition to ports 0..3.

## 1.3.0 maintenance — 2026-10-23

- Metrics population uses distinct capture-seconds with non-NULL values; numeric zero is preserved.
- Schema metadata exposes authoritative `system_col` and `first_param_col` offsets for catalogue/audit consumers.
## 1.4.0 (minor) — 2026-10-23 — Context offsets and documented strings (BC2)

- Context count is read per record and applied to schema-declared offsets.
- NFF 2.59/2.62 documented columns are decoded; extension tails remain
  `unk_` and are never shifted into documented fields.
- Documented textual parameters are retained; privacy redaction remains active
  for identity headers and private event fields.
