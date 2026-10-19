"""Closed semantic axis catalog, no arbitrary SQL identifiers."""
AXES = {
    'task_time': {'label': 'Task Time', 'unit': 's', 'source': 'task_sample.t_rel_s'},
    'rsrp': {'label': 'RSRP', 'unit': 'dBm', 'source': 'measurement_points.rsrp'},
    'sinr': {'label': 'SINR', 'unit': 'dB', 'source': 'measurement_points.sinr'},
    'cqi': {'label': 'CQI', 'unit': 'index', 'source': 'measurement_points.cqi'},
    'capture_time': {'label': 'Heure capture (secondes depuis minuit)', 'unit': 's', 'source': 'DRATE.ts capture-local'},
}
