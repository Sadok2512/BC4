"""Python port of franco-focus-forge fixtures.

Shapes and volumes match the TS mock. Random values are drawn with Python's
`random.Random` seeded from each project id — distributions are equivalent
but byte-identical values are NOT guaranteed (declared as an open gap in
CHANGELOG). The schemas and the demo observations the UI sees remain the
same.
"""

PROJECTS = [
    {
        "id": "idf-t3-2026",
        "name": "Paris 2026 Q1",
        "geography": "Île-de-France (Paris + Petite Couronne)",
        "center": [2.35, 48.86],
        "operators": ["Orange", "SFR", "Bouygues", "Free"],
        "technologies": ["LTE", "NR", "EN-DC"],
        "services": ["Data", "SMS", "Voice"],
        "bands": ["B3", "B7", "B20", "B28", "n78", "n28"],
        "departements": ["75", "92", "93", "94"],
        "periodStart": "2026-01-01",
        "periodEnd": "2026-03-31",
        "captures": 2_400_000,
        "importedAt": "2026-04-02",
        "status": "ready",
    },
    {
        "id": "lyon-drive-2026",
        "name": "Lyon Métropole",
        "geography": "Auvergne-Rhône-Alpes",
        "center": [4.84, 45.76],
        "operators": ["Orange", "SFR"],
        "technologies": ["LTE", "NR"],
        "services": ["Data", "Voice"],
        "bands": ["B3", "B20", "n78"],
        "departements": ["69"],
        "periodStart": "2026-02-01",
        "periodEnd": "2026-02-28",
        "captures": 850_000,
        "importedAt": "2026-03-02",
        "status": "ready",
    },
    {
        "id": "marseille-5g-2026",
        "name": "Marseille 5G",
        "geography": "PACA",
        "center": [5.37, 43.296],
        "operators": ["Orange", "Bouygues", "Free"],
        "technologies": ["NR"],
        "services": ["Data"],
        "bands": ["n78", "n28"],
        "departements": ["13"],
        "periodStart": "2026-01-01",
        "periodEnd": "2026-01-31",
        "captures": 1_200_000,
        "importedAt": "2026-02-03",
        "status": "ready",
    },
    {
        "id": "rennes-lte-2026",
        "name": "Rennes LTE (sans NR)",
        "geography": "Bretagne",
        "center": [-1.68, 48.11],
        "operators": ["Orange", "SFR", "Bouygues"],
        "technologies": ["LTE"],
        "services": ["Data", "Voice"],
        "bands": ["B3", "B20", "B28"],
        "departements": ["35"],
        "periodStart": "2026-03-01",
        "periodEnd": "2026-03-15",
        "captures": 410_000,
        "importedAt": "2026-03-17",
        "status": "ready",
    },
    {
        "id": "lille-indoor-2026",
        "name": "Tests Indoor",
        "geography": "Bâtiment Orange Village",
        "center": [2.24, 48.83],
        "operators": ["Orange"],
        "technologies": ["LTE"],
        "services": ["Data"],
        "bands": ["B3", "B7"],
        "departements": ["92"],
        "periodStart": "2026-01-10",
        "periodEnd": "2026-01-20",
        "captures": 320_000,
        "importedAt": "2026-01-22",
        "status": "processing",
    },
    {
        "id": "national-2026",
        "name": "Benchmark National",
        "geography": "France entière",
        "center": [2.35, 46.8],
        "operators": ["Orange", "SFR", "Bouygues", "Free"],
        "technologies": ["LTE", "NR"],
        "services": ["Data", "Voice"],
        "bands": ["B3", "B20", "n78"],
        "departements": ["75", "69", "13", "33", "59"],
        "periodStart": "2026-01-01",
        "periodEnd": "2026-03-31",
        "captures": 5_800_000,
        "importedAt": "2026-04-05",
        "status": "ready",
    },
]

OP_BIAS = {"Orange": 1.15, "SFR": 0.95, "Bouygues": 1.0, "Free": 0.88}


DICT_MESSAGES = [
    {"msg_id": "lte-sib1", "techno": "LTE", "channel": "BCCH-DL-SCH", "name": "SystemInformationBlockType1"},
    {"msg_id": "lte-rrcreq", "techno": "LTE", "channel": "UL-CCCH", "name": "RRCConnectionRequest"},
    {"msg_id": "lte-mr", "techno": "LTE", "channel": "UL-DCCH", "name": "MeasurementReport"},
    {"msg_id": "lte-reconf", "techno": "LTE", "channel": "DL-DCCH", "name": "RRCConnectionReconfiguration"},
    {"msg_id": "nr-setupreq", "techno": "NR", "channel": "UL-CCCH", "name": "RRCSetupRequest"},
    {"msg_id": "nr-mr", "techno": "NR", "channel": "UL-DCCH", "name": "MeasurementReport"},
    {"msg_id": "nr-reconf", "techno": "NR", "channel": "DL-DCCH", "name": "RRCReconfiguration"},
]


def _c(o: int | float, s: int | float, b: int | float, f: int | float) -> dict:
    return {"Orange": o, "SFR": s, "Bouygues": b, "Free": f}


def _w(o: list[int], s: list[int], b: list[int], f: list[int]) -> dict:
    return {"Orange": o, "SFR": s, "Bouygues": b, "Free": f}


DICT_PARAMS = [
    {
        "param_id": "lte-sib1-qrxlevmin",
        "msg_id": "lte-sib1",
        "path": "systemInformationBlockType1.cellSelectionInfo.q-RxLevMin",
        "leaf": "q-RxLevMin",
        "type": "INTEGER (-70..-22)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 240,
        "spec_kind": "numeric",
        "spec": {"range": [-70, -22], "center": _c(-64, -62, -63, -60), "spread": 3, "bin_width": 2},
        "conversion_rule": {
            "formula": "dBm = valeur × 2",
            "scale": 2,
            "offset": 0,
            "unit": "dBm",
            "decimals": 0,
            "ref": "3GPP TS 36.331 §6.3.4 (Q-RxLevMin)",
        },
    },
    {
        "param_id": "lte-rrcreq-cause",
        "msg_id": "lte-rrcreq",
        "path": "rrcConnectionRequest.criticalExtensions.rrcConnectionRequest-r8.establishmentCause",
        "leaf": "establishmentCause",
        "type": "ENUMERATED",
        "has_gps": False,
        "simulate_error": False,
        "samples": 420,
        "spec_kind": "categorical",
        "spec": {
            "values": ["mo-Data", "mo-Signalling", "mt-Access", "highPriorityAccess", "emergency"],
            "weights": _w([52, 28, 12, 6, 2], [56, 24, 13, 5, 2], [54, 27, 12, 5, 2], [53, 29, 11, 5, 2]),
        },
        "conversion_rule": None,
    },
    {
        "param_id": "lte-rrcreq-ueid",
        "msg_id": "lte-rrcreq",
        "path": "rrcConnectionRequest.criticalExtensions.rrcConnectionRequest-r8.ue-Identity",
        "leaf": "ue-Identity",
        "type": "CHOICE",
        "has_gps": False,
        "simulate_error": False,
        "samples": 420,
        "spec_kind": "categorical",
        "spec": {
            "values": ["s-TMSI", "randomValue"],
            "weights": _w([81, 19], [77, 23], [79, 21], [74, 26]),
        },
        "conversion_rule": None,
    },
    {
        "param_id": "lte-mr-rsrp",
        "msg_id": "lte-mr",
        "path": "measurementReport.criticalExtensions.c1.measurementReport-r8.measResults.measResultPCell.rsrpResult",
        "leaf": "rsrpResult",
        "type": "RSRP-Range INTEGER (0..97)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 520,
        "spec_kind": "numeric",
        "spec": {"range": [0, 97], "center": _c(52, 46, 49, 43), "spread": 11, "bin_width": 5},
        "conversion_rule": {
            "formula": "dBm = index − 140 (borne inférieure)",
            "scale": 1,
            "offset": -140,
            "unit": "dBm",
            "decimals": 0,
            "ref": "3GPP TS 36.133 §9.1.4",
        },
    },
    {
        "param_id": "lte-mr-rsrq",
        "msg_id": "lte-mr",
        "path": "measurementReport.criticalExtensions.c1.measurementReport-r8.measResults.measResultPCell.rsrqResult",
        "leaf": "rsrqResult",
        "type": "RSRQ-Range INTEGER (0..34)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 520,
        "spec_kind": "numeric",
        "spec": {"range": [0, 34], "center": _c(22, 19, 20, 18), "spread": 4, "bin_width": 2},
        "conversion_rule": {
            "formula": "dB = index × 0,5 − 20 (borne inférieure)",
            "scale": 0.5,
            "offset": -20,
            "unit": "dB",
            "decimals": 1,
            "ref": "3GPP TS 36.133 §9.1.7",
        },
    },
    {
        "param_id": "lte-reconf-a3",
        "msg_id": "lte-reconf",
        "path": "rrcConnectionReconfiguration.criticalExtensions.c1.rrcConnectionReconfiguration-r8.measConfig.reportConfigToAddModList.reportConfigEUTRA.triggerType.event.eventId.eventA3.a3-Offset",
        "leaf": "a3-Offset",
        "type": "INTEGER (-30..30)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 300,
        "spec_kind": "numeric",
        "spec": {"range": [-30, 30], "center": _c(6, 4, 6, 2), "spread": 1.5, "bin_width": 1},
        "conversion_rule": None,
    },
    {
        "param_id": "lte-reconf-tm",
        "msg_id": "lte-reconf",
        "path": "rrcConnectionReconfiguration.criticalExtensions.c1.rrcConnectionReconfiguration-r8.radioResourceConfigDedicated.physicalConfigDedicated.antennaInfo.explicitValue.transmissionMode",
        "leaf": "transmissionMode",
        "type": "ENUMERATED",
        "has_gps": True,
        "simulate_error": False,
        "samples": 300,
        "spec_kind": "categorical",
        "spec": {
            "values": ["tm3", "tm4", "tm2", "tm8-v920", "tm9-v1020"],
            "weights": _w([58, 22, 6, 4, 10], [40, 38, 10, 6, 6], [52, 30, 8, 3, 7], [30, 50, 12, 4, 4]),
        },
        "conversion_rule": None,
    },
    {
        "param_id": "lte-reconf-nas",
        "msg_id": "lte-reconf",
        "path": "rrcConnectionReconfiguration.criticalExtensions.c1.rrcConnectionReconfiguration-r8.dedicatedInfoNASList",
        "leaf": "dedicatedInfoNASList",
        "type": "SEQUENCE OF OCTET STRING",
        "has_gps": True,
        "simulate_error": True,
        "samples": 120,
        "spec_kind": "categorical",
        "spec": {
            "values": ["présent", "absent"],
            "weights": _w([40, 60], [42, 58], [38, 62], [45, 55]),
        },
        "conversion_rule": None,
    },
    {
        "param_id": "nr-setupreq-cause",
        "msg_id": "nr-setupreq",
        "path": "rrcSetupRequest.rrcSetupRequest.establishmentCause",
        "leaf": "establishmentCause",
        "type": "EstablishmentCause ENUMERATED",
        "has_gps": False,
        "simulate_error": False,
        "samples": 300,
        "spec_kind": "categorical",
        "spec": {
            "values": ["mo-Data", "mo-Signalling", "mt-Access", "mo-VoiceCall"],
            "weights": _w([60, 22, 12, 6], [58, 25, 12, 5], [61, 21, 13, 5], [57, 26, 11, 6]),
        },
        "conversion_rule": None,
    },
    {
        "param_id": "nr-mr-rsrp",
        "msg_id": "nr-mr",
        "path": "measurementReport.criticalExtensions.measurementReport.measResults.measResultServingMOList.servCellId.measResultServingCell.measResult.cellResults.resultsSSB-Cell.rsrp",
        "leaf": "rsrp",
        "type": "RSRP-Range INTEGER (0..127)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 480,
        "spec_kind": "numeric",
        "spec": {"range": [0, 127], "center": _c(66, 60, 63, 58), "spread": 12, "bin_width": 5},
        "conversion_rule": {
            "formula": "dBm = index − 157 (borne inférieure)",
            "scale": 1,
            "offset": -157,
            "unit": "dBm",
            "decimals": 0,
            "ref": "3GPP TS 38.133 §10.1.6",
        },
    },
    {
        "param_id": "nr-mr-sinr",
        "msg_id": "nr-mr",
        "path": "measurementReport.criticalExtensions.measurementReport.measResults.measResultServingMOList.servCellId.measResultServingCell.measResult.cellResults.resultsSSB-Cell.sinr",
        "leaf": "sinr",
        "type": "SINR-Range INTEGER (0..127)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 480,
        "spec_kind": "numeric",
        "spec": {"range": [0, 127], "center": _c(70, 62, 66, 60), "spread": 12, "bin_width": 6},
        "conversion_rule": {
            "formula": "dB = index × 0,5 − 23 (borne inférieure)",
            "scale": 0.5,
            "offset": -23,
            "unit": "dB",
            "decimals": 1,
            "ref": "3GPP TS 38.133 §10.1.16",
        },
    },
    {
        "param_id": "nr-reconf-a3",
        "msg_id": "nr-reconf",
        "path": "rrcReconfiguration.criticalExtensions.rrcReconfiguration.measConfig.reportConfigToAddModList.reportConfig.reportConfigNR.reportType.eventTriggered.eventId.eventA3.a3-Offset.rsrp",
        "leaf": "a3-Offset",
        "type": "MeasTriggerQuantityOffset INTEGER (-30..30)",
        "has_gps": True,
        "simulate_error": False,
        "samples": 260,
        "spec_kind": "numeric",
        "spec": {"range": [-30, 30], "center": _c(4, 6, 4, 2), "spread": 1.5, "bin_width": 1},
        "conversion_rule": None,
    },
]


ASSISTANT_EXEC_STEPS = [
    {"id": "scope", "label": "Validation du périmètre et des filtres", "duration_ms": 120, "position": 1},
    {"id": "query", "label": "Agrégation des mesures filtrées", "duration_ms": 260, "position": 2},
    {"id": "evidence", "label": "Classification des preuves", "duration_ms": 140, "position": 3},
]


KPI_GROUPS = [
    ("Accessibilité", ["RRC Success Rate", "RRC Setup Time", "Initial Attach Success"]),
    ("Rétention", ["Drop Call Rate", "RRC Abnormal Release"]),
    ("Mobilité", ["HO Success Rate", "HO Interruption Time"]),
    ("Débit", ["Throughput DL", "Throughput UL"]),
    ("Qualité radio", ["RSRP moyen", "SINR moyen"]),
    ("Voix", ["VoLTE Setup Success", "MOS"]),
    ("NR / EN-DC", ["SgNB Addition Success", "EN-DC Ratio"]),
]


KPI_RRC_SUMMARY = {
    "name": "RRC Success Rate",
    "description": "Taux de succès de l'établissement d'une connexion RRC.",
    "value": 98.2,
    "delta": 0.3,
    "samples": 2_400_000,
    "techs": "LTE, NR",
    "unit": "%",
    "by_op": {"Orange": 98.5, "SFR": 97.8, "Bouygues": 98.1, "Free": 97.9},
}


def _h(version: int, at: str, change: str) -> dict:
    return {"version": version, "at": at, "author": "demo.ingenieur", "change": change}


KPI_ITEMS = [
    {
        "code": "RRC_SR",
        "name": "RRC Success Rate",
        "description": "Taux de succès d'établissement RRC.",
        "family": "Accessibilité",
        "tech": "LTE, NR",
        "unit": "%",
        "formula": "RRC_SETUP_COMPLETE / RRC_CONNECTION_REQUEST",
        "status": "published",
        "version": 2,
        "source_events": ["RRCConnectionRequest", "RRCConnectionSetupComplete"],
        "history": [
            _h(1, "2026-02-01T10:00:00Z", "Création"),
            _h(2, "2026-03-10T10:00:00Z", "Ajout NR"),
        ],
    },
    {
        "code": "DCR",
        "name": "Drop Call Rate",
        "description": "Taux de coupure d'appel.",
        "family": "Rétention",
        "tech": "LTE",
        "unit": "%",
        "formula": "ABNORMAL_RELEASE / CALL_ESTABLISHED",
        "status": "validated",
        "version": 1,
        "source_events": ["RRCConnectionRelease"],
        "history": [_h(1, "2026-02-03T10:00:00Z", "Création")],
    },
    {
        "code": "HO_SR",
        "name": "HO Success Rate",
        "description": "Taux de succès des handovers.",
        "family": "Mobilité",
        "tech": "LTE, NR",
        "unit": "%",
        "formula": "HO_COMPLETE / HO_COMMAND",
        "status": "draft",
        "version": 1,
        "source_events": ["MobilityFromEUTRACommand"],
        "history": [_h(1, "2026-04-12T10:00:00Z", "Création")],
    },
]


USERS = [
    {
        "id": "u1",
        "login": "demo.ingenieur",
        "display_name": "Jean Dupont",
        "role": "admin",
        "active": True,
        "created_at": "2026-01-05T09:00:00Z",
        "last_login_at": "2026-10-15T07:40:00Z",
    },
    {
        "id": "u2",
        "login": "m.martin",
        "display_name": "Marie Martin",
        "role": "editor",
        "active": True,
        "created_at": "2026-02-11T10:15:00Z",
        "last_login_at": "2026-10-13T16:02:00Z",
    },
    {
        "id": "u3",
        "login": "p.leroy",
        "display_name": "Paul Leroy",
        "role": "viewer",
        "active": True,
        "created_at": "2026-03-02T08:30:00Z",
        "last_login_at": None,
    },
    {
        "id": "u4",
        "login": "s.bernard",
        "display_name": "Sophie Bernard",
        "role": "viewer",
        "active": False,
        "created_at": "2026-03-20T14:00:00Z",
        "last_login_at": "2026-05-01T11:20:00Z",
    },
]


# 0.47.1 — Le seed GEO_REFERENCES était trompeur : il insérait une
# entrée (``geo-v1`` / ``referentiel_zones_v1.csv``) avec
# ``status='active'`` et ``rows=0``, laissant penser qu'un import réel
# avait eu lieu alors qu'aucun fichier n'existait sur disque. Un agent
# a interprété cette entrée comme une preuve d'upload, puis demandé le
# fichier source — qui n'a jamais existé. On ne seed plus de pseudo-
# upload : si la page Géographie est vide, c'est le vrai état.
GEO_REFERENCES: list[dict[str, object]] = []


AI_CONFIG = {
    "enabled": True,
    "endpoint_url": "https://llm.exemple.interne/v1",
    "model_code": "bc4-analyst-mock",
    "provider": "Interne",
    "providers": ["Interne", "Azure OpenAI", "Mistral", "Autre"],
    "auth_method": "api_key",
    "has_secret": False,
    "config_version": 1,
    "saved_at": "2026-04-02T09:00:00Z",
    "connection": {
        "status": "untested",
        "tested_at": None,
        "message": None,
        "simulated": True,
    },
}


ORG_DEFAULT = {
    "name": "",
    "short_name": "",
    "description": "",
    "logo_data_url": None,
    "admin_contact": "",
    "domain": "",
    "show_in_header": True,
    "show_in_exports": True,
    "limits": {
        "name_max": 80,
        "logo_max_bytes": 300_000,
        "logo_types": ["image/png", "image/svg+xml", "image/jpeg"],
    },
}
