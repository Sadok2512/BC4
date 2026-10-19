"""Compatibility entry point for stage E; positional metric_def decoding has been retired."""
def populate_metric_samples(db,project_id):
    from app.nmf_decoder.projection import refresh_projections
    return refresh_projections(db,project_id)
