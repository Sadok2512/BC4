# BC3 — A3 relu / G24 (read-only evidence)

Capture scopes: Test_3 `44621571bccc` and BCNE `fb5f59006096` (project `4b7bfd50ddb6`).

## A3 five-class contract

The previous three-way labels are replaced by: `offset_wrong`, `zero_is_value`, `cell_absent`, `absent_in_capture`, and `header_or_discriminator`. The relabelled Test_3 rows are in `audit_A3_44621571bccc_after.csv` (no `cell_absent` witness occurred in this selected A3 subset; the class is emitted by the catalogue for SCell leaves); the prior CSV is retained as `audit_A3_44621571bccc.csv`. BCNE event inventory is `audit_A3_bcne_event_inventory.txt`.

- `offset_wrong`: event-specific YAML offsets are required; no universal column 5 is used.
- `zero_is_value`: numeric zero is non-NULL and therefore contributes one capture-second.
- `cell_absent`: no row exists for the requested SCell discriminator in the capture.
- `absent_in_capture`: the event has no Light occurrence in the capture.
- `header_or_discriminator`: headers/discriminators remain attributes and are not metric leaves.

## Corrective implementation

`app/nmf_decoder/schema.py` now exposes schema-derived `system_col` and `first_param_col` metadata. `app/nmf_decoder/projection.py` counts distinct `(capture_id, second)` Light buckets with `value IS NOT NULL`; zero is retained. `app/kpi/metrics_v3.py` applies the same semantics to cell projections and keeps zero-population definitions in the response. `app/kpi/metrics_catalogue_v6.py` keeps greyed leaves and emits `cell_absent`, `absent_in_capture`, or `field_empty`, plus `count_semantics` and the schema offsets.

## G24 cross-check

`audit_G24_metrics_cells.csv` is the cross-check for both requested captures. Every emitted source row has identical `n_seconds` and `source_nonnull_seconds`; no field is reported as n=0 while its bound cell-specific source is non-NULL. The PHRATE witness is 654 distinct seconds for `pdsch_bitrate_cw0` on Test_3 and 556 on BCNE (physical Light rows are 6038 and 4871 respectively, so row count is intentionally not the displayed n).

## Remaining declared gaps

The catalogue JSON still contains legacy presentation nodes whose HTML hierarchy has not yet been regenerated from the 2.19 `(event, section, field_no)` CSV. They are not used as a binding fallback; duplicate identifiers are rejected by the audit CSV and will be removed in the next catalogue regeneration pass.
