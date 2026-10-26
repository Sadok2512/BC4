"""CAPTURE resolver for /metrics/table — 2.53.0 Phase 2.

Les 27 feuilles de la racine `CAPTURE` du catalogue 2.53.0 sont résolues
ici (CONST par capture, SERIES par (capture_id, seq), MASKED gris).

Dispatch dans `app/kpi/metrics_v3.py::Dataset.load()` sur préfixe `cap_`.

Mapping leaf → source (2.53.1 — Test script file + headers depuis .nmf) :
  - CONST (File) : nmf_file.* / nmf_capture.* + headers `#ID #FF #DN
    #UNITID #PROJECT #START+#UT #TS` lus **tels quels** depuis le .nmf
    source (text header NFF `#TAG,,,"value"`). Jamais redacted.
  - SERIES (Device, DEVI) : stg_event_raw raw_fields.c{col} (col = field_no+2).
  - SERIES (Task, CMDREQ/CMDCOMP) : fenêtre open-until-CMDCOMP.
  - MASKED (Identity) : NULL + privacy reason, non-selectable (déjà bloqué
    par metrics_catalog_v4).

Toute valeur manquante → NULL + reason dans la row, JAMAIS inventée.
"""
from __future__ import annotations

import re
from functools import lru_cache
from sqlalchemy import text

# Mapping cap_<group>_<slug> → spec (kind + source_hint).
# Garde-fou : si une ligne est ajoutée côté categories.yaml / build_catalog.py
# sans entrée correspondante ici, le resolver fallback à NULL+reason explicite.
CAPTURE_SPEC: dict[str, dict] = {
    # --- File group (CONST) : 11 leaves ---
    # 2.53.1 — Headers `#ID #FF #DN #UNITID #PROJECT #START #UT #TS` lus
    # depuis le .nmf text header (source primaire NFF). Les colonnes DB
    # `nmf_file.*` restent utilisées pour filename, size et device_name
    # (dérivés fiables au moment de l'ingest).
    "cap_file_log_file_name":        {"kind": "CONST", "src": "db:nmf_file.filename",            "col": "filename",         "unit": None,  "label": "Log file name",         "python_kind": "categorical"},
    "cap_file_file_size":            {"kind": "CONST", "src": "derived:nmf_file_size_mb",         "col": "size_bytes",       "unit": "MB",  "label": "File size",             "python_kind": "numeric"},
    "cap_file_file_format_version":  {"kind": "CONST", "src": "hdr:#FF",                          "col": None,               "unit": None,  "label": "File format version",   "python_kind": "categorical"},
    "cap_file_measurement_id":       {"kind": "CONST", "src": "hdr:#ID",                          "col": None,               "unit": None,  "label": "Measurement ID",        "python_kind": "categorical"},
    "cap_file_unit_id":              {"kind": "CONST", "src": "hdr:#UNITID",                      "col": None,               "unit": None,  "label": "Unit ID",               "python_kind": "categorical"},
    "cap_file_project_id":           {"kind": "CONST", "src": "hdr:#PROJECT.0",                   "col": None,               "unit": None,  "label": "Project ID",            "python_kind": "categorical"},
    "cap_file_session_id":           {"kind": "CONST", "src": "hdr:#PROJECT.1",                   "col": None,               "unit": None,  "label": "Session ID",            "python_kind": "categorical"},
    "cap_file_device_name":          {"kind": "CONST", "src": "hdr:#DN",                          "col": None,               "unit": None,  "label": "Device name",           "python_kind": "categorical"},
    "cap_file_measurement_start":    {"kind": "CONST", "src": "hdr:#START+#UT",                   "col": None,               "unit": None,  "label": "Measurement start",     "python_kind": "categorical"},
    "cap_file_decoder_version":      {"kind": "CONST", "src": "db:nmf_capture.decoder_version",   "col": "decoder_version",  "unit": None,  "label": "Decoder version",       "python_kind": "categorical"},
    "cap_file_decode_level":         {"kind": "CONST", "src": "db:nmf_capture.decode_level",      "col": "decode_level",     "unit": None,  "label": "Decode level",          "python_kind": "categorical"},
    # --- Script group (CONST) : 4 leaves ---
    "cap_script_test_script_file":                  {"kind": "CONST", "src": "hdr:#TS",                           "col": None,         "unit": None,  "label": "Test script file",                     "python_kind": "categorical"},
    "cap_script_test_script_version":               {"kind": "CONST", "src": "stg:SCRIPT.c3",                           "col": None,         "unit": None,  "label": "Test script version",                  "python_kind": "categorical"},
    "cap_script_test_script_repeats":               {"kind": "CONST", "src": "stg:SCRIPT.c4",                           "col": None,         "unit": None,  "label": "Test script repeats",                  "python_kind": "numeric"},
    "cap_script_number_of_commands_in_test_script": {"kind": "CONST", "src": "stg:SCRIPT.c6",                           "col": None,         "unit": None,  "label": "Number of commands in test script",    "python_kind": "numeric"},
    # --- Task group (SERIES) : 5 leaves ---
    # CMDREQ raw_fields : {service_action, cmd_index, payload_b64, system_code, ts}
    # CMDCOMP raw_fields : {c3 (duration ms? ou cmd_index), c4 (result), ts}
    # Window = [CMDREQ.seq, CMDCOMP.seq] matched by cmd_index (ou chaîné FIFO).
    "cap_task_test_script_command_name":      {"kind": "SERIES_TASK", "src": "series:CMDREQ.service_action",          "field": "service_action",  "unit": None,  "label": "Test script command name",         "python_kind": "categorical"},
    "cap_task_test_script_command_index":     {"kind": "SERIES_TASK", "src": "series:CMDREQ.cmd_index",               "field": "cmd_index",       "unit": None,  "label": "Test script command index",        "python_kind": "numeric"},
    "cap_task_test_script_command_arguments": {"kind": "SERIES_TASK", "src": "series:CMDREQ.payload_b64_masked",      "field": "payload_b64",     "unit": None,  "label": "Test script command arguments",    "python_kind": "categorical"},
    "cap_task_test_script_command_result":    {"kind": "SERIES_TASK", "src": "series:CMDCOMP.c4",                     "field": "c4",              "unit": None,  "label": "Test script command result",       "python_kind": "numeric"},
    "cap_task_command_duration":              {"kind": "SERIES_TASK", "src": "series:CMDCOMP.ts-CMDREQ.ts",           "field": "duration",        "unit": "s",   "label": "Command duration",                 "python_kind": "numeric"},
    # --- Device group (SERIES DEVI) : 6 leaves ---
    # DEVI raw_fields : c{col} où col = field_no + 2 (YAML DEVI.col=4..12 pour fields 1..9).
    "cap_device_battery_temperature":    {"kind": "SERIES_DEVI", "src": "series:DEVI.c3",  "devi_key": "c3",  "unit": "°C", "label": "Battery temperature",       "python_kind": "numeric"},
    "cap_device_device_cpu_temperature": {"kind": "SERIES_DEVI", "src": "series:DEVI.c9",  "devi_key": "c9",  "unit": "°C", "label": "Device CPU temperature",    "python_kind": "numeric"},
    "cap_device_battery_charge":         {"kind": "SERIES_DEVI", "src": "series:DEVI.c4",  "devi_key": "c4",  "unit": "%",  "label": "Battery charge",            "python_kind": "numeric"},
    "cap_device_battery_status":         {"kind": "SERIES_DEVI", "src": "series:DEVI.c5",  "devi_key": "c5",  "unit": None, "label": "Battery status",            "python_kind": "numeric"},
    "cap_device_device_battery_voltage": {"kind": "SERIES_DEVI", "src": "series:DEVI.c11", "devi_key": "c11", "unit": "V",  "label": "Device battery voltage",    "python_kind": "numeric"},
    "cap_device_device_battery_current": {"kind": "SERIES_DEVI", "src": "series:DEVI.c7",  "devi_key": "c7",  "unit": "A",  "label": "Device battery current",    "python_kind": "numeric"},
    # --- Identity group (MASKED) : 1 leaf ---
    "cap_identity_subscriber_identity":  {"kind": "MASKED",       "src": "masked:#EI,#SI,phone_numbers", "unit": None, "label": "Subscriber identity", "python_kind": "categorical"},
}


def capture_definitions() -> dict[str, dict]:
    """Codes CAPTURE à injecter dans `definitions()` de metrics_v3.

    Compatible shape : `code`, `label`, `unit`, `source_table`,
    `source_tables`, `source_column`, `tech`, `kind`, `event`,
    `event_code`, `category`, `category_label`, `cell_scoped`,
    `cells`, `cell_options`, `attributes`, `proof`, `proof_ref`,
    `decoder_version`, `n_in_project`, `available`, `reason`,
    `alias_of`, `agg`, `weighted`, `sql`.
    """
    from app.nmf_decoder import DECODER_VERSION
    out = {}
    for code, spec in CAPTURE_SPEC.items():
        out[code] = dict(
            code=code,
            label=spec["label"],
            unit=spec["unit"] or "",
            source_table="capture",
            source_tables=["nmf_file", "nmf_capture", "stg_event_raw"],
            source_column=code,
            tech="CAPTURE",
            kind=spec["python_kind"],
            event="CAPTURE",
            event_code="CAPTURE",
            category="capture",
            category_label="CAPTURE",
            cell_scoped=False,
            cells=[],
            cell_options=[],
            attributes=[],
            proof="documented-2.50",
            proof_ref="BC4 catalog 2.53.0 CAPTURE",
            decoder_version=DECODER_VERSION,
            n_in_project=0,
            available=True,
            reason=None,
            alias_of=None,
            agg="last",
            weighted=False,
            sql="",  # unused; CAPTURE goes through dedicated resolver
            # extras utilisées par le dispatcher :
            _cap_kind=spec["kind"],
            _cap_src=spec["src"],
            _cap_field=spec.get("field") or spec.get("devi_key") or spec.get("col"),
        )
    return out


def load_capture(dataset, m: dict) -> list[dict]:
    """Resolver CAPTURE : retourne des rows `{seq, value, ...}` compatibles
    avec `Dataset.load()`.

    `dataset` : instance Dataset (dataset.db, dataset.pid, dataset.cap,
    dataset.times — map seq→t_rel_s, dataset.file_meta).
    `m` : dict metric avec clés `_cap_kind`, `_cap_src`, `_cap_field`.
    """
    db, pid, cap = dataset.db, dataset.pid, dataset.cap
    cap_kind = m.get("_cap_kind")
    if cap_kind == "MASKED":
        return []  # jamais exposé (filtré en amont par selectable=False)

    # Les CONST retournent une valeur unique répétée pour chaque seq
    # observé (times.keys). Les SERIES retournent une valeur par seq.
    if cap_kind == "CONST":
        value = _resolve_const(db, pid, cap, m)
        if value is None:
            return []
        return [
            dict(seq=seq, value=value, seq_last=seq)
            for seq in sorted(dataset.times.keys())
        ]
    if cap_kind == "SERIES_DEVI":
        return _resolve_devi(db, pid, cap, m, dataset.times)
    if cap_kind == "SERIES_TASK":
        return _resolve_task(db, pid, cap, m, dataset.times)
    return []


def _nmf_source_path(db, pid, cap) -> str | None:
    r = db.execute(text(
        "SELECT nf.source_path FROM nmf_file nf JOIN nmf_capture nc "
        "ON nc.nmf_file_id=nf.id WHERE nc.project_id=:pid AND nc.capture_id=:cap"
    ), {"pid": pid, "cap": cap}).scalar_one_or_none()
    return r


_HDR_LINE_RE = re.compile(r'^#([A-Z]+)(?:,,,|,)(.*)$')


@lru_cache(maxsize=64)
def _parse_nmf_headers(source_path: str) -> dict[str, list[str]]:
    """Parse les headers texte NFF `#TAG,,,"value"` (ou `#TAG,fields...`).

    Lit jusqu'à 65536 bytes (le header texte est toujours au début).
    Retourne dict `{TAG: [raw_fields_after_tag]}` — la liste comporte
    plusieurs entrées si plusieurs occurrences du même tag.

    Les valeurs sont les champs CSV bruts (avec guillemets) ; le caller
    fait l'unquote et sélectionne le field index demandé.
    """
    out: dict[str, list[str]] = {}
    try:
        with open(source_path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return out
    text_bytes = head.decode("utf-8", errors="replace")
    for line in text_bytes.splitlines():
        m = _HDR_LINE_RE.match(line)
        if not m:
            continue
        tag = m.group(1)
        rest = m.group(2)
        out.setdefault(tag, []).append(rest)
    return out


def _hdr_value(headers: dict[str, list[str]], tag: str, field_index: int = 0) -> str | None:
    """Retourne le `field_index`e champ CSV du 1er `#TAG` trouvé.
    Format NFF : `#TAG,,,"value0","value1",…` (3 virgules de padding).
    """
    rows = headers.get(tag)
    if not rows:
        return None
    raw = rows[0]
    # strip leading commas (padding)
    raw = raw.lstrip(",")
    # Split CSV with quotes preserved
    import csv as _csv
    reader = _csv.reader([raw])
    try:
        fields = next(reader)
    except StopIteration:
        return None
    if field_index >= len(fields):
        return None
    v = fields[field_index].strip()
    return v or None


def _resolve_const(db, pid, cap, m):
    """Résout une CONST : valeur unique capture-scoped."""
    src = m["_cap_src"]
    col = m["_cap_field"]
    if src == "derived:nmf_file_size_mb":
        row = db.execute(text(
            "SELECT nf.size_bytes FROM nmf_file nf JOIN nmf_capture nc "
            "ON nc.nmf_file_id=nf.id WHERE nc.project_id=:pid AND nc.capture_id=:cap"
        ), {"pid": pid, "cap": cap}).scalar_one_or_none()
        if row is None:
            return None
        return round(float(row) / (1024 * 1024), 2)
    if src.startswith("hdr:"):
        # 2.53.1 — lecture directe depuis le .nmf text header. Formats :
        #   `hdr:#TAG`          → premier field
        #   `hdr:#TAG.{i}`      → field index i
        #   `hdr:#START+#UT`    → compose "<#START.0> UTC{±offset}"
        source_path = _nmf_source_path(db, pid, cap)
        if not source_path:
            return None
        headers = _parse_nmf_headers(source_path)
        key = src[4:]
        if key == "#START+#UT":
            start = _hdr_value(headers, "START", 0)  # time
            date = _hdr_value(headers, "START", 2)   # date (field 2)
            off_min_raw = _hdr_value(headers, "UT", 0)
            try:
                off_min = int(off_min_raw) if off_min_raw else None
            except (TypeError, ValueError):
                off_min = None
            if not start:
                return None
            composed = (f"{date or ''} {start}").strip()
            if off_min is not None:
                sign = "+" if off_min >= 0 else "-"
                hh, mm = divmod(abs(off_min), 60)
                composed = f"{composed} UTC{sign}{hh:02d}:{mm:02d}"
            return composed
        if "." in key:
            tag, idx_str = key.split(".", 1)
            try:
                idx = int(idx_str)
            except ValueError:
                idx = 0
        else:
            tag, idx = key, 0
        tag = tag.lstrip("#")
        return _hdr_value(headers, tag, idx)
    if src.startswith("db:nmf_file."):
        q = text(
            f"SELECT nf.{col} FROM nmf_file nf JOIN nmf_capture nc "
            f"ON nc.nmf_file_id=nf.id WHERE nc.project_id=:pid AND nc.capture_id=:cap"
        )
        return db.execute(q, {"pid": pid, "cap": cap}).scalar_one_or_none()
    if src.startswith("db:nmf_capture."):
        q = text(
            f"SELECT {col} FROM nmf_capture "
            f"WHERE project_id=:pid AND capture_id=:cap"
        )
        return db.execute(q, {"pid": pid, "cap": cap}).scalar_one_or_none()
    if src.startswith("stg:SCRIPT."):
        # SCRIPT event : premier seq pour cette capture, lire raw_fields[col]
        key = src.split(".", 1)[1]
        row = db.execute(text(
            "SELECT raw_fields->>:k AS v FROM stg_event_raw "
            "WHERE project_id=:pid AND capture_id=:cap AND event_code='SCRIPT' "
            "ORDER BY seq LIMIT 1"
        ), {"pid": pid, "cap": cap, "k": key}).scalar_one_or_none()
        return row
    return None


def _resolve_devi(db, pid, cap, m, times):
    """Join DEVI events par seq : pour chaque row de la table, dernier
    DEVI avec seq ≤ current. Retourne rows `{seq, value, seq_last}`.
    """
    devi_key = m["_cap_field"]
    rows = list(db.execute(text(
        "SELECT seq, (raw_fields->>:k)::text AS v FROM stg_event_raw "
        "WHERE project_id=:pid AND capture_id=:cap AND event_code='DEVI' "
        "ORDER BY seq"
    ), {"pid": pid, "cap": cap, "k": devi_key}).mappings())
    # Rows DEVI directes — chaque seq DEVI porte sa propre valeur.
    out = []
    for r in rows:
        v = r["v"]
        if v is None or v == "":
            continue
        try:
            v = float(v) if m.get("kind") == "numeric" else v
        except (TypeError, ValueError):
            pass
        out.append(dict(seq=r["seq"], value=v, seq_last=r["seq"]))
    return out


def _resolve_task(db, pid, cap, m, times):
    """CMDREQ/CMDCOMP window-based resolver.

    Fenêtres : pour chaque CMDREQ (ouvert), le prochain CMDCOMP suivant
    chronologique (seq) ferme la fenêtre. On émet une row par seq
    (DEVI/CMDREQ/CMDCOMP…) couverte par la fenêtre, portant la valeur
    du champ demandé. Hors fenêtre → pas de row (NULL dans la table).
    """
    cap_src = m["_cap_src"]
    field = m["_cap_field"]
    rows_src = list(db.execute(text(
        "SELECT seq, event_code, raw_fields, ts FROM stg_event_raw "
        "WHERE project_id=:pid AND capture_id=:cap "
        "AND event_code IN ('CMDREQ','CMDCOMP') ORDER BY seq"
    ), {"pid": pid, "cap": cap}).mappings())
    # Build windows : liste de (seq_req, seq_comp, req_fields, comp_fields).
    windows = []
    open_req = None
    for r in rows_src:
        if r["event_code"] == "CMDREQ":
            if open_req is not None:
                windows.append((open_req["seq"], None, open_req["raw_fields"], None, open_req.get("ts")))
            open_req = dict(seq=r["seq"], raw_fields=r["raw_fields"], ts=r["ts"])
        elif r["event_code"] == "CMDCOMP" and open_req is not None:
            windows.append((open_req["seq"], r["seq"], open_req["raw_fields"], r["raw_fields"], open_req.get("ts"), r.get("ts")))
            open_req = None
    if open_req is not None:
        windows.append((open_req["seq"], None, open_req["raw_fields"], None, open_req.get("ts")))

    def _value_for_window(w):
        req_fields = w[2] if len(w) > 2 else None
        comp_fields = w[3] if len(w) > 3 else None
        req_ts = w[4] if len(w) > 4 else None
        comp_ts = w[5] if len(w) > 5 else None
        if cap_src.endswith("CMDCOMP.ts-CMDREQ.ts"):
            if not req_ts or not comp_ts:
                return None
            try:
                return _delta_ts_seconds(req_ts, comp_ts)
            except Exception:
                return None
        if cap_src.endswith("CMDCOMP.c4"):
            if not comp_fields:
                return None
            v = comp_fields.get("c4")
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return v
        if cap_src.endswith("CMDREQ.payload_b64_masked"):
            if not req_fields:
                return None
            v = req_fields.get("payload_b64")
            if v is None:
                return None
            # masquer les chiffres par X
            import re as _re
            return _re.sub(r"\d", "X", str(v))
        if cap_src.endswith("CMDREQ.cmd_index"):
            if not req_fields:
                return None
            v = req_fields.get("cmd_index")
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return v
        if cap_src.endswith("CMDREQ.service_action"):
            if not req_fields:
                return None
            return req_fields.get("service_action")
        return None

    # Émettre une row par seq de la table (dataset.times) couverte par
    # une fenêtre ; valeur = _value_for_window.
    import bisect as _bs
    req_seqs = [w[0] for w in windows]
    out = []
    for seq in sorted(times.keys()):
        i = _bs.bisect_right(req_seqs, seq) - 1
        if i < 0:
            continue
        w = windows[i]
        end = w[1] if w[1] is not None else 10 ** 12
        if seq > end:
            continue
        v = _value_for_window(w)
        if v is None:
            continue
        out.append(dict(seq=seq, value=v, seq_last=seq))
    return out


def _delta_ts_seconds(a: str, b: str) -> float:
    """Delta en secondes entre deux timestamps 'HH:MM:SS.mmm'."""
    def _parse(t):
        hh, mm, rest = t.split(":")
        if "." in rest:
            ss, ms = rest.split(".")
        else:
            ss, ms = rest, "0"
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + float("0." + ms)
    da = _parse(a)
    db = _parse(b)
    delta = db - da
    if delta < 0:
        delta += 86400  # overnight
    return round(delta, 3)
