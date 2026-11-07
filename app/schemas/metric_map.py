"""Shared optional geographic contract for metric map points."""
from typing import Literal

from pydantic import BaseModel, Field


class RadioCellLink(BaseModel):
    """A proven or explicitly probable radio match against ``cell_ref``.

    The measurement keeps its exact ARFCN. ``reference_channel`` preserves
    the historical field but now contains the same exact LTE EARFCN or
    NR-ARFCN as ``arfcn``. Distance only disambiguates duplicate exact
    channel+PCI candidates.
    """

    system: Literal["LTE", "NR"]
    arfcn: int
    reference_channel: int
    pci: int | None
    cell_type: int
    cell_ref_id: str
    site_id: str | None = None
    site_name: str | None = None
    lat: float
    lng: float
    distance_m: float
    max_distance_m: float
    candidate_count: int
    confidence: Literal[
        "radio_arfcn_pci_unique",
        "radio_arfcn_pci_nearest_within_25000m",
        "probable",
    ]
    link_method: Literal["band_proximity_pci", "band_proximity"] | None = None
    band_mhz: int | None = None
    measured_strength_dbm: float | None = None


class MetricMapPoint(BaseModel):
    seq: int
    lat: float
    lng: float
    code: str
    value: float | str
    t_rel_s: float | None
    tooltip: str
    position_source: Literal["exact", "previous_fix"] | None = None
    delta_seq: int | None = None
    position_fix_seq: int | None = None
    serving_cell_id: str | None = None
    serving_cell_seq: int | None = None
    serving_cell_ref_id: str | None = None
    serving_site_id: str | None = None
    serving_site_name: str | None = None
    serving_cell_lat: float | None = None
    serving_cell_lng: float | None = None
    serving_cell_role: str | None = None
    serving_cell_pci: int | None = None
    serving_cell_arfcn: int | None = None
    serving_cell_source: Literal["chi_previous_seq_cell_ref_exact"] | None = None
    neighbour_links: list[RadioCellLink] = Field(default_factory=list)
    nr_anchor_link: RadioCellLink | None = None
    # 0.117.0 BC3 — Lien 'probable' pour la cellule serving quand le
    # référentiel n'a pas d'EARFCN exact + PCI sur la zone (cas
    # Hénin-Beaumont / Test_6). Match par bande MHz dérivée du cell_ch
    # mesuré + PCI mesuré (prioritaire) ou bande seule (fallback) +
    # site le plus proche dans un rayon <= 10 km. Jamais présenté
    # comme prouvé — distance et bande toujours exposées.
    link_method: Literal[
        "eci", "earfcn_pci", "band_proximity_pci", "band_proximity", "none"
    ] | None = None
    confidence: Literal["proven", "probable", "none"] | None = None
    probable_serving_cell_ref_id: str | None = None
    probable_serving_site_id: str | None = None
    probable_serving_site_name: str | None = None
    probable_serving_cell_lat: float | None = None
    probable_serving_cell_lng: float | None = None
    probable_serving_distance_m: float | None = None
    probable_serving_band_mhz: int | None = None
    probable_serving_pci: int | None = None
    probable_link_max_distance_m: float | None = None
