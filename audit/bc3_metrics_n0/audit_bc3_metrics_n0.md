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

## A1–A5 conclusions

**A1.** Before this patch, `metrics_v3.catalog()` used `projection.metric_counts()` (`COUNT(d.field)`) and `metrics_catalogue_v6.catalogue()` mixed that project-wide count with `nmf_cell_second` counts. Thus `n` was not one thing: physical Light rows for some fields, project-level counts for others, and distinct seconds for cell leaves. A PDSCH leaf showing `5` was a projection/binding count, not the thousands of PHRATE source rows. It is now distinct capture-seconds for numeric fields and occurrences for events; the response exposes `count_semantics`.

**A2.** The full leaf inventory remains in the source catalogue; bindings now carry `event`, `field_idx`, schema offsets and a section-scoped `binding_key`. Conditional PHRATE/PLAID/PLAIU/CQI fields are selected by their YAML `when` discriminator during decode, and cell leaves are resolved through the cell projection rather than a fixed column.

**A3.** Test_3 relabelled CSV: 54 `offset_wrong`, 30 `zero_is_value`, 43 `absent_in_capture`, 1 `header_or_discriminator`; no `cell_absent` witness in the selected rows. The class is nevertheless emitted for SCell leaves with no observed cell type. No row is discarded.

**A4.** The decoder retains separate PHRATE conditional schemas for PBCH (`ph_ch_type=1`), PDSCH (`=2`) and PUSCH (`=3`). Witness rows and extracted values are preserved in the prior A3 CSV and the source line evidence.

**A5.** The two legacy presentation categories remain in the approved HTML JSON (they have different child sets); duplicate `(event, field_no)` labels are now resolved by YAML label/section context and each output node receives a unique `binding_key`. A full HTML regeneration is still a declared follow-up because the source CSV section column is not present in the legacy labels.
