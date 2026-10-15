"""Requêtes agrégées sur `param_occurrence` partagées par les routes dict.

0.15.0 — `compute_value_distribution` : distribution par valeur d'un
paramètre, groupée par `(value_raw, value_converted)` (numérique) ou
par `value_raw` (enum). Les filtres du périmètre (`operator`, `band`,
`message`) sont réinjectés avant l'agrégation pour que la distribution
reste cohérente avec le reste du handler `/dict/params`.

Règles :
- **Numérique** (unit_converted non null) : tri par `value_converted`
  cast en float. Si le nombre de valeurs distinctes > seuil
  (`VALUE_DISTRIBUTION_BINNING_THRESHOLD`), on bin par pas = `BIN_WIDTH`
  (1 unité dans l'unité convertie — ex. 1 dBm pour rsrp). Les buckets
  binnés exposent `value_raw = value_converted = "[lo, hi)"`.
- **Enum** (unit_converted null) : tri alpha ascendant sur `value_raw`.
- **0 occurrence** → liste vide, `mode = "exact"`. Aucune invention.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# Au-delà de ce nombre de valeurs numériques distinctes, on bin par pas
# régulier pour éviter d'exploser le payload. Documenté dans le CHANGELOG
# 0.15.0.
VALUE_DISTRIBUTION_BINNING_THRESHOLD = 100
# Pas de bin par défaut (en unité convertie). 1 dBm = 1 unité pour rsrp /
# threshold-RSRP / s-Measure ; 0.5 pour rsrq / a3-Offset ; ici on choisit
# 1 par défaut (le binning ne se déclenche que si le domaine est très
# large, auquel cas 1 reste raisonnable).
BIN_WIDTH = 1.0


def _parse_float(s: Any) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s))
    except (TypeError, ValueError):
        return None


def compute_value_distribution(
    db: Session,
    project_id: str,
    system: str,
    message: str | None,
    path: str,
    operator: str | None,
    band: str | None,
) -> tuple[list[dict], str]:
    """Calcule la distribution par valeur d'un paramètre.

    Retourne `(items, mode)` où :
    - `items` : liste `[{"value_raw": str, "value_converted": str|None,
      "count": int}, ...]`, triée (numérique asc par value_converted,
      enum asc par value_raw).
    - `mode` : `"exact"` ou `"binned"`.

    Les filtres `operator` / `band` / `message` RESTREIGNENT la requête
    (strict GROUP BY sur le périmètre, pas de pré-calcul global).
    """
    conds = [
        "project_id = :pid",
        "system = :sys",
        "path = :path",
    ]
    params: dict[str, Any] = {"pid": project_id, "sys": system, "path": path}
    if message:
        conds.append("message = :msg")
        params["msg"] = message
    if operator:
        conds.append("operator = :op")
        params["op"] = operator
    if band:
        conds.append("band = :band")
        params["band"] = band
    where = " AND ".join(conds)

    rows = db.execute(
        text(
            f"""
            SELECT value AS value_raw,
                   value_converted,
                   MAX(unit_converted) AS unit_converted,
                   COUNT(*) AS n
            FROM param_occurrence
            WHERE {where}
            GROUP BY value, value_converted
            """
        ),
        params,
    ).all()

    if not rows:
        return [], "exact"

    # Un paramètre est "numérique" si au moins une occurrence porte un
    # value_converted non null ET une unit_converted non null. On
    # considère le path numérique dès lors qu'une majorité le prouve
    # (en pratique : règle 3GPP uniforme sur un path donné). Faute de
    # value_converted parsable, on retombe en enum pour ne jamais
    # inventer un ordre numérique faux.
    numeric_entries: list[tuple[str, str, float, int]] = []  # (raw, conv, conv_float, n)
    enum_entries: list[tuple[str, int]] = []  # (raw, n)
    has_any_unit = any((r.unit_converted is not None) for r in rows)

    for r in rows:
        raw = r.value_raw if r.value_raw is not None else ""
        conv = r.value_converted
        conv_f = _parse_float(conv) if has_any_unit else None
        n = int(r.n)
        if has_any_unit and conv_f is not None:
            numeric_entries.append((str(raw), str(conv), conv_f, n))
        else:
            # Soit c'est un enum, soit c'est une valeur non convertible
            # (edge case). On la mappe en enum entry pour ne rien perdre.
            enum_entries.append((str(raw), n))

    # Cas 1 : paramètre numérique dominant.
    if has_any_unit and numeric_entries:
        # Les enum_entries résiduels (valeurs hors domaine 3GPP qui n'ont
        # pas été converties) sont rares — on les laisse à part en les
        # ignorant du total numérique SAUF si on veut 100% de couverture.
        # Choix : on les intègre en fin de liste comme buckets "non
        # convertibles" (value_converted=null), pour qu'aucun comptage
        # ne disparaisse silencieusement.
        distinct = len(numeric_entries)
        if distinct > VALUE_DISTRIBUTION_BINNING_THRESHOLD:
            # Binning sur `conv_f` par pas BIN_WIDTH.
            bins: dict[tuple[float, float], int] = {}
            for _raw, _conv, cf, n in numeric_entries:
                lo = math.floor(cf / BIN_WIDTH) * BIN_WIDTH
                hi = lo + BIN_WIDTH
                bins[(lo, hi)] = bins.get((lo, hi), 0) + n
            out = [
                {
                    "value_raw": _fmt_bin(lo, hi),
                    "value_converted": _fmt_bin(lo, hi),
                    "count": n,
                }
                for (lo, hi), n in sorted(bins.items(), key=lambda kv: kv[0][0])
            ]
            # Non-convertibles résiduels en queue (si existants).
            for raw, n in sorted(enum_entries, key=lambda t: t[0]):
                out.append({"value_raw": raw, "value_converted": None, "count": n})
            return out, "binned"
        else:
            out = [
                {"value_raw": raw, "value_converted": conv, "count": n}
                for raw, conv, _cf, n in sorted(numeric_entries, key=lambda t: t[2])
            ]
            for raw, n in sorted(enum_entries, key=lambda t: t[0]):
                out.append({"value_raw": raw, "value_converted": None, "count": n})
            return out, "exact"

    # Cas 2 : paramètre enum (unit_converted null partout).
    enum_entries_sorted = sorted(enum_entries, key=lambda t: t[0])
    out = [
        {"value_raw": raw, "value_converted": None, "count": n}
        for raw, n in enum_entries_sorted
    ]
    return out, "exact"


def _fmt_bin(lo: float, hi: float) -> str:
    """Formate `[lo, hi)` en évitant les .0 inutiles."""
    def fmt(x: float) -> str:
        if x == int(x):
            return str(int(x))
        return f"{x:g}"
    return f"[{fmt(lo)}, {fmt(hi)})"
