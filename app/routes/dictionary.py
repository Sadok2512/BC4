"""Routes `/projects/{id}/dict/*`.

Deux générations cohabitent :

- **B0 historique** (`/dict`, `/dict/param`) : s'appuient sur les tables
  seedées `dict_messages` / `dict_params` / `rrc_observations`. Contrat
  Zod existant (G2/G3/G4). Non touchées par 0.12.0.
- **0.12.0 — dictionnaire complet RRC LTE+NR** : s'appuie sur la table
  `param_occurrence` peuplée depuis `stg_event.payload_hex` via pycrate.
  Les routes `/dict/tree`, `/dict/params`, `/dict/param/map` sont
  **dispatchées par présence/forme de query parameters** :
    - `GET /dict/tree`                         → nouvelle logique (0.12.0),
      arbre LTE/NR → message → path.
      Rétro-compat G2/G3 : si `param_occurrence` est VIDE pour le projet
      (projets seedés B0 sans RRCSM), on retombe sur l'arbre B0
      construit depuis `rrc_observations`.
    - `GET /dict/params?system=…`             → nouvelle logique (0.12.0).
    - `GET /dict/params?msg_id=…`             → logique B0 historique.
    - `GET /dict/param/map?path=…&system=…`   → nouvelle logique (0.12.0).
    - `GET /dict/param/map?param_id=…`        → logique B0 historique.

JWT exigé sur toutes les routes du routeur (`Depends(get_current_user)`),
cf. `router.dependencies` ci-dessous.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Project
from app.schemas.common import FilterContext
from app.schemas.dictionary import (
    DictProject,
    DictTree,
    DictTreeBranch,
    DictTreeMessage,
    DictTreeParam,
    DictTreeV2,
    ParamBucket,
    ParamDetail,
    ParamList,
    ParamListV2,
    ParamMap,
    ParamMapPoint,
    ParamMapV2,
    ParamRow,
    ValueBucket,
    ValueMatrixCell,
)
from app.dict.queries import (
    UNASSIGNED_LABEL,
    compute_value_distribution,
    compute_value_matrix,
)
from app.services.dict_service import (
    build_dict_project,
    build_dict_tree,
    build_param_detail,
    build_param_list,
    build_param_map,
)
from app.services.filters import parse_csv_list

router = APIRouter(
    prefix="/projects",
    tags=["dictionary"],
    dependencies=[Depends(get_current_user)],
)

# Bornes du paramètre `limit` sur /dict/param/map.
# Externalisées pour satisfaire G5 (aucun littéral numérique dans un
# handler ; cf. tests/test_g5_db_sourced.py).
from app.services.dict_limits import DICT_MAP_LIMIT_DEFAULT, DICT_MAP_LIMIT_MIN, DICT_MAP_LIMIT_MAX


def _filters_from_query(op, tech, svc, band, dep) -> FilterContext:
    return FilterContext(
        op=parse_csv_list(op),
        tech=parse_csv_list(tech),
        svc=parse_csv_list(svc),
        band=parse_csv_list(band),
        dep=parse_csv_list(dep),
    )


def _get_project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return p


def _project_has_param_occurrence(db: Session, project_id: str) -> bool:
    n = db.execute(
        text("SELECT COUNT(*) FROM param_occurrence WHERE project_id = :pid"),
        {"pid": project_id},
    ).scalar()
    return (n or 0) > 0


# --------------------------------------------------------------------- #
# Routes B0 historiques (inchangées)
# --------------------------------------------------------------------- #


@router.get("/{project_id}/dict", response_model=DictProject)
def get_dict_project(project_id: str, db: Session = Depends(get_db)) -> DictProject:
    return build_dict_project(_get_project(db, project_id))


# --------------------------------------------------------------------- #
# 0.12.0 — Arbre dictionnaire (LTE/NR → message → path/param)
# --------------------------------------------------------------------- #


def _disambiguate_leaf_labels(paths: list[str]) -> list[str]:
    """Désambigüise les feuilles au sein d'un groupe `(system, message)`.

    Chaque entrée de `paths` est un path complet
    (ex. `"measurementReport/.../measResultPCell/rsrpResult"`). Retourne
    une liste `labels` de même longueur :

    - Si la feuille (`seg[-1]`) est unique dans `paths` → `label = feuille`
      (ex. `"q-RxLevMin"`, `"a3-Offset"`).
    - Sinon → `label = "<feuille> (<ancêtres distinctifs>)"`. Les
      ancêtres sont choisis en remontant depuis la feuille jusqu'à
      obtenir une signature unique dans le groupe de collision. Le plus
      souvent 1 segment suffit (ex. `"rsrpResult (measResultPCell)"` vs
      `"rsrpResult (measResult)"`). Si deux paths colliders partagent
      aussi le même parent direct (cas `release` sous deux
      `ue-TransmitAntennaSelection` différents sous
      `antennaInfo/explicitValue` vs `antennaInfo-r10/explicitValue-r10`),
      on remonte jusqu'à ce que la signature diverge.

    Dérivé 100% du path — jamais inventé. Si deux paths sont strictement
    identiques (impossible dans `param_occurrence` grâce à l'UNIQUE
    `(project_id, stg_event_id, path)` + GROUP BY path), on retombe sur
    le path complet entre parenthèses pour prévenir la coïncidence
    silencieuse.
    """
    segs = [p.split("/") for p in paths]
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(segs):
        buckets[s[-1]].append(i)
    labels: list[str] = [""] * len(paths)
    for leaf, idxs in buckets.items():
        if len(idxs) == 1:
            labels[idxs[0]] = leaf
            continue
        # Collision — remonter depuis seg[-2] jusqu'à obtenir une
        # signature unique par path dans le groupe.
        depth = 1
        max_depth = max(len(segs[i]) - 1 for i in idxs)
        resolved = False
        while depth <= max_depth and not resolved:
            keys: dict[tuple[str, ...], list[int]] = defaultdict(list)
            for i in idxs:
                s = segs[i]
                start = max(0, len(s) - 1 - depth)
                ctx = tuple(s[start:-1])
                keys[ctx].append(i)
            if all(len(v) == 1 for v in keys.values()):
                for ctx, [i] in keys.items():
                    # Un path collider sans ancêtres (feuille à la racine
                    # du message) → sentinelle `(racine)` : on garde
                    # l'invariant « tous les colliders portent un suffixe
                    # entre parenthèses, mutuellement distincts ».
                    suffix = "/".join(ctx) if ctx else "racine"
                    labels[i] = f"{leaf} ({suffix})"
                resolved = True
            else:
                depth += 1
        if not resolved:
            # Deux paths colliders avec la MÊME chaîne d'ancêtres —
            # impossible après le GROUP BY ci-dessus (clé unique). Filet
            # de sécurité : suffixer par le path parent complet.
            for i in idxs:
                suffix = "/".join(segs[i][:-1])
                labels[i] = f"{leaf} ({suffix})" if suffix else leaf
    return labels


def _build_tree_v2(db: Session, project_id: str) -> DictTreeV2:
    """Arbre à 2 branches racines (LTE / NR) depuis `param_occurrence`.
    `count` à chaque niveau = COUNT(*) agrégé.

    0.22.3 — chaque `param` porte en plus un `label` désambigué (feuille
    seule si unique, feuille + ancêtre distinctif sinon). Front n'a qu'à
    préférer `label` à `leafOf(param)` quand disponible — non-breaking,
    Zod additif.
    """
    rows = db.execute(
        text(
            """
            SELECT system, message, path, COUNT(*) AS n
            FROM param_occurrence
            WHERE project_id = :pid
            GROUP BY system, message, path
            ORDER BY system, message, path
            """
        ),
        {"pid": project_id},
    ).all()

    # system → message → list[(path, count)]
    nested: dict[str, dict[str, list[tuple[str, int]]]] = {
        "LTE": defaultdict(list),
        "NR": defaultdict(list),
    }
    for r in rows:
        system = (r.system or "").upper()
        if system not in nested:
            continue
        nested[system][r.message].append((r.path, int(r.n)))

    branches: list[DictTreeBranch] = []
    for sys_name in ("LTE", "NR"):
        messages: list[DictTreeMessage] = []
        total_sys = 0
        for msg_name, paths in nested[sys_name].items():
            path_strs = [p for p, _ in paths]
            labels = _disambiguate_leaf_labels(path_strs)
            params = [
                DictTreeParam(param=p, label=lbl, count=c)
                for (p, c), lbl in zip(paths, labels)
            ]
            total_msg = sum(c for _, c in paths)
            messages.append(
                DictTreeMessage(message=msg_name, count=total_msg, params=params)
            )
            total_sys += total_msg
        branches.append(
            DictTreeBranch(system=sys_name, count=total_sys, messages=messages)  # type: ignore[arg-type]
        )
    return DictTreeV2(branches=branches)


@router.get("/{project_id}/dict/tree")
def get_dict_tree(
    project_id: str,
    op: str | None = Query(default=None),
    tech: str | None = Query(default=None),
    svc: str | None = Query(default=None),
    band: str | None = Query(default=None),
    dep: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Dispatch : si le projet a des `param_occurrence`, nouvelle logique
    (shape V2). Sinon, rétro-compat B0 (shape G2/G3 branches/channels)."""
    project = _get_project(db, project_id)
    if _project_has_param_occurrence(db, project_id):
        return _build_tree_v2(db, project_id)
    # Fallback B0 — ne change rien pour les projets seedés sans RRCSM.
    return build_dict_tree(
        db, project, _filters_from_query(op, tech, svc, band, dep)
    )


# --------------------------------------------------------------------- #
# 0.12.0 — Liste des paramètres pour un message / un système
# --------------------------------------------------------------------- #


def _build_param_list_v2(
    db: Session,
    project_id: str,
    system: str,
    message: str | None,
    operator: str | None,
    band: str | None,
) -> ParamListV2:
    conds = ["project_id = :pid", "system = :sys"]
    params: dict = {"pid": project_id, "sys": system}
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

    # Agrégat principal + unit_converted représentative (first non-null).
    main_rows = db.execute(
        text(
            f"""
            SELECT system, message, path,
                   COUNT(*) AS n,
                   MAX(unit_converted) AS unit_converted,
                   AVG(NULLIF(regexp_replace(value_converted, '[^0-9eE\\.\\-+]', '', 'g'), '')::float)
                     FILTER (WHERE value_converted IS NOT NULL) AS avg_overall
            FROM param_occurrence
            WHERE {where}
            GROUP BY system, message, path
            ORDER BY system, message, path
            """
        ),
        params,
    ).all()

    if not main_rows:
        return ParamListV2(params=[])

    # Buckets (operator, band) par (system, message, path).
    # 0.18.0 — `COALESCE('non attribué')` sur operator ET band : les events
    # sans SIB1 avant (operator NULL) OU sans band résolue étaient
    # silencieusement omis des buckets. On les expose maintenant sous un
    # bucket explicite — alignement avec `value_matrix`.
    bucket_params = {**params, "unassigned": UNASSIGNED_LABEL}
    bucket_rows = db.execute(
        text(
            f"""
            SELECT system, message, path,
                   COALESCE(operator, :unassigned) AS operator,
                   COALESCE(band, :unassigned) AS band,
                   COUNT(*) AS n,
                   AVG(NULLIF(regexp_replace(value_converted, '[^0-9eE\\.\\-+]', '', 'g'), '')::float)
                     FILTER (WHERE value_converted IS NOT NULL) AS avg_c
            FROM param_occurrence
            WHERE {where}
            GROUP BY system, message, path,
                     COALESCE(operator, :unassigned),
                     COALESCE(band, :unassigned)
            ORDER BY system, message, path, operator, band
            """
        ),
        bucket_params,
    ).all()
    buckets_by_key: dict[tuple[str, str, str], list[ParamBucket]] = defaultdict(list)
    for b in bucket_rows:
        buckets_by_key[(b.system, b.message, b.path)].append(
            ParamBucket(
                operator=b.operator,
                band=b.band,
                count=int(b.n),
                avg_converted=float(b.avg_c) if b.avg_c is not None else None,
            )
        )

    out: list[ParamRow] = []
    for r in main_rows:
        # 0.15.0 — distribution par valeur du paramètre (filtres opérateur
        # / bande / message RÉinjectés pour que la distribution respecte
        # strictement le périmètre affiché).
        vd_items, vd_mode = compute_value_distribution(
            db,
            project_id=project_id,
            system=system,
            message=r.message,
            path=r.path,
            operator=operator,
            band=band,
        )
        # 0.18.0 — table croisée value × operator × band (NULL → "non
        # attribué", jamais inventé). Même périmètre de filtres que
        # buckets / value_distribution.
        vm_items = compute_value_matrix(
            db,
            project_id=project_id,
            system=system,
            path=r.path,
            message=r.message,
            operator=operator,
            band=band,
        )
        out.append(
            ParamRow(
                system=r.system,  # type: ignore[arg-type]
                message=r.message,
                path=r.path,
                count=int(r.n),
                unit_converted=r.unit_converted,
                buckets=buckets_by_key.get((r.system, r.message, r.path), []),
                value_distribution=[ValueBucket(**item) for item in vd_items],
                value_distribution_mode=vd_mode,  # type: ignore[arg-type]
                value_matrix=[ValueMatrixCell(**item) for item in vm_items],
            )
        )
    return ParamListV2(params=out)


@router.get("/{project_id}/dict/params")
def get_dict_params(
    project_id: str,
    system: str | None = Query(default=None),
    message: str | None = Query(default=None),
    operator: str | None = Query(default=None),
    band: str | None = Query(default=None),
    # Rétro-compat B0 (G2) : `msg_id` → ancienne logique.
    msg_id: str | None = Query(default=None),
    op: str | None = Query(default=None),
    tech: str | None = Query(default=None),
    svc: str | None = Query(default=None),
    band_b0: str | None = Query(default=None, alias="band_b0"),
    dep: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Dispatch :
    - `?system=LTE|NR` (+ filtres facultatifs `message`, `operator`, `band`)
      → nouvelle logique (0.12.0), ParamListV2.
    - `?msg_id=…` → logique B0 historique, ParamList.
    """
    project = _get_project(db, project_id)
    if system is not None:
        if system not in ("LTE", "NR"):
            raise HTTPException(
                400, {"code": "VALIDATION", "message": "system doit être LTE ou NR"}
            )
        return _build_param_list_v2(
            db, project_id, system, message, operator, band
        )
    if msg_id is not None:
        return build_param_list(
            db,
            project,
            msg_id,
            _filters_from_query(op, tech, svc, band_b0, dep),
        )
    raise HTTPException(
        400,
        {
            "code": "VALIDATION",
            "message": "paramètre `system` (0.12.0) ou `msg_id` (B0) requis",
        },
    )


@router.get("/{project_id}/dict/param", response_model=ParamDetail)
def get_dict_param_detail(
    project_id: str,
    param_id: str = Query(...),
    group_by: str = Query("operator"),
    op: str | None = Query(default=None),
    tech: str | None = Query(default=None),
    svc: str | None = Query(default=None),
    band: str | None = Query(default=None),
    dep: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ParamDetail:
    if group_by not in ("operator", "band", "operator,band"):
        raise HTTPException(400, {"code": "VALIDATION", "message": "group_by invalide"})
    try:
        return build_param_detail(
            db,
            _get_project(db, project_id),
            param_id,
            group_by,
            _filters_from_query(op, tech, svc, band, dep),
        )
    except LookupError:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Paramètre inconnu"})
    except RuntimeError:
        raise HTTPException(502, {"code": "UPSTREAM_ERROR", "message": "Erreur simulée (lte-reconf-nas)"})


# --------------------------------------------------------------------- #
# 0.12.0 — Map des occurrences d'un paramètre
# --------------------------------------------------------------------- #


def _build_param_map_v2(
    db: Session,
    project_id: str,
    path: str,
    system: str,
    limit: int,
) -> ParamMapV2:
    rows = db.execute(
        text(
            """
            SELECT lat, lon, value, value_converted, operator, band
            FROM param_occurrence
            WHERE project_id = :pid
              AND path = :path
              AND system = :sys
              AND lat IS NOT NULL
              AND lon IS NOT NULL
            ORDER BY stg_event_id
            LIMIT :lim
            """
        ),
        {"pid": project_id, "path": path, "sys": system, "lim": limit},
    ).all()
    points = [
        ParamMapPoint(
            lat=float(r.lat),
            lon=float(r.lon),
            value_raw=r.value,
            value_converted=r.value_converted,
            operator=r.operator,
            band=r.band,
        )
        for r in rows
    ]
    return ParamMapV2(path=path, system=system, points=points)  # type: ignore[arg-type]


@router.get("/{project_id}/dict/param/map", response_model_exclude_none=True)
def get_dict_param_map(
    project_id: str,
    # Nouvelle logique 0.12.0
    path: str | None = Query(default=None),
    system: str | None = Query(default=None),
    limit: int = Query(default=DICT_MAP_LIMIT_DEFAULT, ge=DICT_MAP_LIMIT_MIN, le=DICT_MAP_LIMIT_MAX),
    # B0 historique
    param_id: str | None = Query(default=None),
    op: str | None = Query(default=None),
    tech: str | None = Query(default=None),
    svc: str | None = Query(default=None),
    band: str | None = Query(default=None),
    dep: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    if path is not None and system is not None:
        if system not in ("LTE", "NR"):
            raise HTTPException(
                400,
                {"code": "VALIDATION", "message": "system doit être LTE ou NR"},
            )
        return _build_param_map_v2(db, project_id, path, system, limit)
    if param_id is not None:
        try:
            return build_param_map(
                db,
                project,
                param_id,
                _filters_from_query(op, tech, svc, band, dep),
            )
        except LookupError:
            raise HTTPException(
                404, {"code": "NOT_FOUND", "message": "Paramètre inconnu"}
            )
        except RuntimeError:
            raise HTTPException(
                502,
                {"code": "UPSTREAM_ERROR", "message": "Erreur simulée (lte-reconf-nas)"},
            )
    raise HTTPException(
        400,
        {
            "code": "VALIDATION",
            "message": "paramètres `path`+`system` (0.12.0) ou `param_id` (B0) requis",
        },
    )
