"""Compact one-row-per-record storage helpers for Light captures."""
from __future__ import annotations

from app.config import settings


REASON_BITS = {
    reason: 1 << index for index, reason in enumerate((
        "context_layout_unsupported", "csv_malformed", "event_undocumented",
        "fields_truncated", "format_extensions_unproven", "format_unknown",
        "format_unsupported", "identity_header_redacted",
        "parameter_type_undocumented", "system_missing",
        "system_undocumented", "time_missing", "time_regression",
        "unknown_fields",
    ))
}

NATIVE_COLUMNS = [
    "project_id", "capture_id", "seq", "event_code", "system", "t_rel_s",
    "partial", "reason_mask", "reason_extra", "unknown_cols", "context_id",
    "context_ids", "values", "groups", "x_2154", "y_2154",
    "position_source", "position_gap_s", "position_reason",
]


def _compact_values(values):
    result = {key: value for key, value in values.items() if value is not None}
    return result or None


def _compact_groups(groups):
    result = []
    for group in groups:
        values = _compact_values(group["values"])
        if values:
            result.append([group["group_name"], group["set_index"], values])
    return result or None


def exact_position(record):
    lon = record.values.get("gps_lon", record.values.get("posi_lon"))
    lat = record.values.get("gps_lat", record.values.get("posi_lat"))
    if (lon is None or lat is None) and record.event_code == "GPS" and len(record.tokens) >= 5:
        try: lon, lat = float(record.tokens[3]), float(record.tokens[4])
        except (TypeError, ValueError): lon = lat = None
    if (lon is None or lat is None) and record.event_code == "POSI" and len(record.tokens) >= 8:
        try: lon, lat = float(record.tokens[6]), float(record.tokens[7])
        except (TypeError, ValueError): lon = lat = None
    if lon is None or lat is None:
        return None
    lon, lat = float(lon), float(lat)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or (lon == 0 and lat == 0):
        return None
    return lon, lat


def native_row(project_id, record, position_state):
    exact = exact_position(record)
    source = None; gap = None; reason = None; position = None
    if exact is not None:
        position = exact; source = "exact"; gap = 0.0
        if record.t_rel_s is not None:
            position_state["fix"] = (record.t_rel_s, exact[0], exact[1])
    elif record.t_rel_s is None:
        reason = "time_missing"
    elif position_state.get("fix") is None:
        reason = "no_previous_fix"
    else:
        fix_t, lon, lat = position_state["fix"]
        candidate_gap = abs(record.t_rel_s - fix_t)
        if candidate_gap <= settings.spatial_fix_max_gap_s:
            position = (lon, lat); source = "previous_fix"; gap = candidate_gap
        else:
            reason = "fix_gap_exceeded"
    reasons = record.reasons
    unknown = [
        int(code.rsplit("_", 1)[1]) for code in record.field_codes
        if code.startswith("unk_") and code.rsplit("_", 1)[1].isdigit()
    ] or None
    return {
        "project_id": project_id, "capture_id": record.capture_id,
        "seq": record.seq, "event_code": record.event_code,
        "system": record.system, "t_rel_s": record.t_rel_s,
        "partial": record.decode_status == "partial",
        "reason_mask": sum(REASON_BITS.get(item, 0) for item in reasons),
        "reason_extra": [item for item in reasons if item not in REASON_BITS] or None,
        "unknown_cols": unknown, "context_id": record.context_id,
        "context_ids": record.context_ids or None,
        "values": _compact_values(record.values),
        "groups": _compact_groups(record.groups),
        # WGS84 is transformed in-place after COPY; names describe final state.
        "x_2154": position[0] if position else None,
        "y_2154": position[1] if position else None,
        "position_source": source, "position_gap_s": gap,
        "position_reason": reason,
    }
