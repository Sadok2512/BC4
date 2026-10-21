# Nemo decoder changelog

Version independent of the API. Patch: corrected position/unit or additional documented field. Minor: new event/system. Major: changed meaning of an existing field, requiring re-decode.

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
