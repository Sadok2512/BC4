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
