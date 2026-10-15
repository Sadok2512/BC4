"""Bornes du paramètre `limit` sur `GET /dict/param/map` (0.12.0).

Externalisées pour satisfaire G5 (`test_routes_have_no_data_literals`) :
aucun littéral numérique dans les handlers de route. Les trois constantes
ci-dessous sont lues depuis les variables d'env `BC4_DICT_MAP_LIMIT_*`
si fournies — sinon valeurs par défaut raisonnables pour une
visualisation cartographique côté front.
"""
from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


DICT_MAP_LIMIT_DEFAULT = _env_int("BC4_DICT_MAP_LIMIT_DEFAULT", 10_000)
DICT_MAP_LIMIT_MIN = _env_int("BC4_DICT_MAP_LIMIT_MIN", 1)
DICT_MAP_LIMIT_MAX = _env_int("BC4_DICT_MAP_LIMIT_MAX", 100_000)
