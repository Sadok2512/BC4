"""Site layer map — endpoint lazy par bbox.

Expose les cellules référentielles de `cell_ref` (458K cellules, 37K sites,
3 technos, 13 bands) sous forme de GeoJSON agrégé zoom-aware. Jamais tout
d'un coup — l'UI MapLibre fetche par `moveend` sur la bbox visible.

Niveaux d'agrégation :
- `zoom < 12`  → sites agrégés par geo-hash grille 0.01° (clusters avec
                  count 4G/5G, bands observées) ; cap 2000 clusters.
- `zoom 12-14` → 1 point par site (centroid des cells du site), tooltip
                  comporte la liste des cellules par (techno, band).
- `zoom ≥ 15`  → 1 point par cellule avec `azimuth`, `tilt`, `band`,
                  pour que le front dessine un secteur orienté.

Cap dur `limit=2000` features par réponse ; 422 au-delà → l'UI demande
à l'utilisateur de zoomer.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/sites", tags=["sites"], dependencies=[Depends(get_current_user)])

MAX_FEATURES = 2000

# Palette couleurs par band (indicative — l'UI peut l'override via style).
# Alignée sur les attributs métier (basses fréquences = couverture, hautes
# fréquences = capacité). Les couleurs sont ensuite servies côté client.
BAND_COLORS: dict[str, str] = {
    "B20": "#1e40af",   # 800 MHz — bleu foncé (couverture)
    "B28": "#3b82f6",   # 700 MHz — bleu
    "B8":  "#06b6d4",   # 900 MHz — cyan
    "B3":  "#10b981",   # 1800 MHz — vert
    "B1":  "#f59e0b",   # 2100 MHz — orange
    "B7":  "#ef4444",   # 2600 MHz — rouge
    "n28": "#60a5fa",   # 700 MHz 5G — bleu clair
    "n1":  "#fcd34d",   # 2100 MHz 5G — jaune
    "n3":  "#34d399",   # 1800 MHz 5G
    "n7":  "#f87171",   # 2600 MHz 5G
    "n75": "#a78bfa",   # 1500 MHz 5G
    "n78": "#8b5cf6",   # 3.5 GHz 5G — violet
    "n258": "#ec4899",  # 26 GHz 5G mmWave — rose
}


class SiteFeature(BaseModel):
    """GeoJSON Feature minimal pour un site (zoom 12-14) ou un cluster (<12)."""
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: dict


class SitesResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SiteFeature]
    aggregation: Literal["cluster", "site", "cell"]
    bbox: list[float] = Field(..., min_length=4, max_length=4)
    n_total_in_bbox: int
    n_returned: int
    reason: str | None = None


def _parse_csv(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    vals = [v.strip() for v in raw.split(",") if v.strip()]
    return vals or None


@router.get("", response_model=SitesResponse)
def sites(
    bbox: str = Query(..., description="lng_min,lat_min,lng_max,lat_max in EPSG:4326"),
    zoom: int = Query(10, ge=0, le=22),
    techno: str | None = Query(None, description="CSV : 4G,5G,LTE"),
    band: str | None = Query(None, description="CSV : B20,n78,… (3GPP labels)"),
    operator: str | None = Query(None, description="CSV : ORF,BYT,SFR,FRM"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    db: Session = Depends(get_db),
) -> dict:
    # Parse bbox strict (4 floats). Jamais inventé.
    try:
        parts = [float(x) for x in bbox.split(",")]
    except ValueError:
        raise HTTPException(422, "bbox must be 4 comma-separated floats")
    if len(parts) != 4:
        raise HTTPException(422, "bbox must be exactly 4 values")
    lng_min, lat_min, lng_max, lat_max = parts
    if lng_min >= lng_max or lat_min >= lat_max:
        raise HTTPException(422, "bbox min must be < max on each axis")

    technos = _parse_csv(techno)
    bands = _parse_csv(band)
    operators = _parse_csv(operator)

    # Prédicats SQL (safe parameter binding).
    conditions = [
        "geom IS NOT NULL",
        "geom && ST_MakeEnvelope(:lng_min, :lat_min, :lng_max, :lat_max, 4326)",
    ]
    params: dict[str, object] = {
        "lng_min": lng_min,
        "lat_min": lat_min,
        "lng_max": lng_max,
        "lat_max": lat_max,
    }
    if technos:
        conditions.append("techno = ANY(:technos)")
        params["technos"] = technos
    if bands:
        conditions.append("band_3gpp = ANY(:bands)")
        params["bands"] = bands
    if operators:
        conditions.append("cell_op_leader = ANY(:operators)")
        params["operators"] = operators
    where = " AND ".join(conditions)

    # Compte total dans la bbox avant d'agréger (pour signaler écart).
    n_total = db.execute(
        text(f"SELECT count(*) FROM cell_ref WHERE {where}"), params
    ).scalar_one()
    if n_total == 0:
        return dict(
            type="FeatureCollection",
            features=[],
            aggregation=("cluster" if zoom < 12 else "site" if zoom < 15 else "cell"),
            bbox=[lng_min, lat_min, lng_max, lat_max],
            n_total_in_bbox=0,
            n_returned=0,
            reason="empty_bbox",
        )

    aggregation = "cluster" if zoom < 12 else "site" if zoom < 15 else "cell"

    if aggregation == "cell":
        # Zoom fin : 1 feature par cellule, avec azimuth/tilt/band.
        rows = db.execute(
            text(
                f"""
                SELECT id, site_id, site_name, techno, band_3gpp AS band, pci,
                       azimuth, tilt, height, cell_op_leader AS operator,
                       ST_X(geom) AS lng, ST_Y(geom) AS lat
                FROM cell_ref WHERE {where}
                LIMIT :lim
                """
            ),
            {**params, "lim": limit + 1},
        ).mappings().all()
    elif aggregation == "site":
        # Zoom moyen : agrégation par site_id. Chaque feature = site.
        rows = db.execute(
            text(
                f"""
                SELECT site_id, site_name, cell_op_leader AS operator,
                       ST_X(ST_Centroid(ST_Collect(geom))) AS lng,
                       ST_Y(ST_Centroid(ST_Collect(geom))) AS lat,
                       count(*) AS n_cells,
                       count(*) FILTER (WHERE techno='4G') AS n_4g,
                       count(*) FILTER (WHERE techno='5G') AS n_5g,
                       count(*) FILTER (WHERE techno='LTE') AS n_lte,
                       array_agg(DISTINCT band_3gpp ORDER BY band_3gpp) FILTER (WHERE band_3gpp IS NOT NULL) AS bands
                FROM cell_ref WHERE {where} AND site_id IS NOT NULL
                GROUP BY site_id, site_name, cell_op_leader
                LIMIT :lim
                """
            ),
            {**params, "lim": limit + 1},
        ).mappings().all()
    else:
        # Zoom large (< 12) : cluster par geo-hash grille 0.01°.
        # ST_SnapToGrid aligne les points sur une grille → GROUP BY le centroid.
        rows = db.execute(
            text(
                f"""
                SELECT ST_X(cell_geom) AS lng, ST_Y(cell_geom) AS lat,
                       count(*) AS n_cells,
                       count(DISTINCT site_id) AS n_sites,
                       count(*) FILTER (WHERE techno='4G') AS n_4g,
                       count(*) FILTER (WHERE techno='5G') AS n_5g
                FROM (
                  SELECT ST_SnapToGrid(geom, 0.01) AS cell_geom, site_id, techno
                  FROM cell_ref WHERE {where}
                ) t
                GROUP BY cell_geom
                LIMIT :lim
                """
            ),
            {**params, "lim": limit + 1},
        ).mappings().all()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    features: list[dict] = []
    if aggregation == "cell":
        for r in rows:
            band = r["band"]
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {
                    "kind": "cell",
                    "id": r["id"],
                    "site_id": r["site_id"],
                    "site_name": r["site_name"],
                    "techno": r["techno"],
                    "band": band,
                    "band_color": BAND_COLORS.get(band or "", "#64748b"),
                    "pci": r["pci"],
                    "azimuth": r["azimuth"],
                    "tilt": r["tilt"],
                    "height": r["height"],
                    "operator": r["operator"],
                },
            })
    elif aggregation == "site":
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {
                    "kind": "site",
                    "site_id": r["site_id"],
                    "site_name": r["site_name"],
                    "operator": r["operator"],
                    "n_cells": r["n_cells"],
                    "n_4g": r["n_4g"],
                    "n_5g": r["n_5g"],
                    "n_lte": r["n_lte"],
                    "bands": list(r["bands"] or []),
                },
            })
    else:  # cluster
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {
                    "kind": "cluster",
                    "n_cells": r["n_cells"],
                    "n_sites": r["n_sites"],
                    "n_4g": r["n_4g"],
                    "n_5g": r["n_5g"],
                },
            })

    reason: str | None = None
    if truncated:
        reason = f"truncated_at_limit_{limit}_of_{n_total}_in_bbox"

    return dict(
        type="FeatureCollection",
        features=features,
        aggregation=aggregation,
        bbox=[lng_min, lat_min, lng_max, lat_max],
        n_total_in_bbox=n_total,
        n_returned=len(features),
        reason=reason,
    )
