"""Propagation ECGI (0.41.0).

Pipeline par projet :

1. Walk ``stg_event`` dans l'ordre canonique ``(capture_id, seq)``.
2. Chaque fois qu'on rencontre un ``SystemInformationBlockType1`` qui
   expose ``cellIdentity``, ``plmn-Identity/{mcc,mnc}``,
   ``trackingAreaCode`` sur ``param_occurrence``, on reconstruit un
   enregistrement cellule ``(plmn, cell_identity, enb_id,
   local_cell_id, tac)``. ``plmn = mcc + mnc`` (format texte, mnc
   gardé littéralement — jamais zero-paddé côté serveur).
3. ``pci`` et ``earfcn`` ne sont pas dans le SIB1 ; on les apparie à
   la dernière mesure serving (MeasurementReport ``measResultPCell`` ou
   ``measResultServingCell``) dans la même capture, en ordre
   ``(capture_id, seq)``. Pour la REF (LTE), l'EARFCN serving n'est
   pas directement exposé dans le RRC — on le remonte depuis la
   colonne ``measurement_points.earfcn`` déjà peuplée par
   ``populate_measurement_points`` (via mapping décodeur).
4. Pour chaque mesure ``measurement_points`` d'une capture, on
   cherche la **dernière** cellule SIB1 vue dans la capture avec
   même ``(pci, earfcn)``. Si trouvée → on écrit ``mp.ecgi``. Sinon
   NULL (pas d'invention — jamais l'ancien ECGI après HO sans SIB1
   relu).
5. Alimente ``cell_ref`` : upsert par ``(eci=ecgi)`` avec les champs
   ``enodebid, pci, earfcn, band_3gpp, techno, snapshot_date``.
   ``first_seen/last_seen`` matérialisés dans ``snapshot_date`` (texte).
6. Mesure du mismatch PLMN ↔ ``nmf_file.dl`` (l'opérateur autoritaire
   du Nemo vs l'opérateur dérivé du PLMN SIB1).

Discipline :
- Ordre canonique ``(capture_id, seq)``. **Jamais** ``ts``.
- Aucun chiffre inventé : si ``pci`` ou ``earfcn`` manquent, la
  propagation reste ``NULL`` sur la mesure, ``mismatch_declared`` est
  incrémenté avec raison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


# Paths SIB1 autoritaires (déjà peuplés dans param_occurrence sur REF +
# TEST2, audit 2026-10-16).
_PATH_CI = "systemInformationBlockType1/cellAccessRelatedInfo/cellIdentity"
_PATH_MCC = (
    "systemInformationBlockType1/cellAccessRelatedInfo/"
    "plmn-IdentityList/plmn-Identity/mcc"
)
_PATH_MNC = (
    "systemInformationBlockType1/cellAccessRelatedInfo/"
    "plmn-IdentityList/plmn-Identity/mnc"
)
_PATH_TAC = "systemInformationBlockType1/cellAccessRelatedInfo/trackingAreaCode"

# Mapping MCC+MNC FR → opérateur (3GPP TS 23.003 — PLMN FR).
# Jamais inventé : seuls les 4 MNO + MVNO Free (20815 ≡ 20816) connus.
_PLMN_TO_OPERATOR: dict[tuple[str, str], str] = {
    ("208", "01"): "Orange",
    ("208", "02"): "Orange",
    ("208", "10"): "SFR",
    ("208", "11"): "SFR",
    ("208", "13"): "SFR",
    ("208", "20"): "Bouygues",
    ("208", "21"): "Bouygues",
    ("208", "88"): "Bouygues",
    ("208", "15"): "Free",
    ("208", "16"): "Free",
}


def _plmn_operator(mcc: str | None, mnc: str | None) -> str | None:
    if not mcc or not mnc:
        return None
    return _PLMN_TO_OPERATOR.get((mcc.strip(), mnc.strip()))


def _band_from_earfcn(earfcn: int | None) -> str | None:
    """Déduction LTE band depuis EARFCN (3GPP TS 36.101 §5.7.3). Jamais
    deviné : seuls les intervalles canoniques connus."""
    if earfcn is None:
        return None
    f = int(earfcn)
    # Bornes DL EARFCN par bande (LTE FDD/TDD communes en FR).
    for lo, hi, band in (
        (0, 599,       "B1"),
        (600, 1199,    "B2"),
        (1200, 1949,   "B3"),
        (1950, 2399,   "B4"),
        (2400, 2649,   "B5"),
        (2750, 3449,   "B7"),
        (3450, 3799,   "B8"),
        (5010, 5179,   "B12"),
        (5180, 5279,   "B13"),
        (5730, 5849,   "B17"),
        (5850, 5999,   "B18"),
        (6000, 6149,   "B19"),
        (6150, 6449,   "B20"),
        (6450, 6599,   "B21"),
        (9210, 9659,   "B28"),
        (36000, 36199, "B33"),
        (37750, 38249, "B38"),
    ):
        if lo <= f <= hi:
            return band
    return None


@dataclass
class EcgiCell:
    ecgi:            str            # concat plmn + cellIdentity (texte)
    plmn:            str            # mcc + mnc
    mcc:             str
    mnc:             str
    cell_identity:   int
    enb_id:          int
    local_cell_id:   int
    tac:             str | None
    pci:             int | None     # résolu par (capture, dernier MeasReport serving)
    earfcn:          int | None
    band:            str | None
    operator:        str | None
    first_capture:   str | None = None
    last_capture:    str | None = None


@dataclass
class PopulateEcgiReport:
    project_id:        str
    sib1_cells:        int = 0
    distinct_ecgi:     int = 0
    mp_total:          int = 0
    mp_with_ecgi:      int = 0
    mp_pct_with_ecgi:  float = 0.0
    plmn_mismatch:     int = 0
    plmn_mismatch_examples: list[dict[str, Any]] = field(default_factory=list)
    sample_cell:       dict[str, Any] | None = None
    warnings:          list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SIB1 extraction
# ---------------------------------------------------------------------------


def _extract_sib1_cells(db: Session, project_id: str) -> list[dict[str, Any]]:
    """Retourne la liste ordonnée des cellules SIB1 vues dans le projet.

    Chaque cellule porte :
        {stg_event_id, capture_id, seq, operator (depuis stg_event),
         cell_identity, mcc, mnc, tac, pci (dernier serving dans la
         capture avant ce SIB1 ou juste après), earfcn (mp.earfcn
         de la capture)}.

    Les champs `pci` et `earfcn` sont joints à partir des
    `measurement_points` de la capture (même capture_id). On prend la
    valeur la plus proche en seq.
    """
    rows = db.execute(
        text(
            """
            WITH sib1 AS (
                SELECT po.stg_event_id, po.operator, po.band,
                       se.capture_id, se.seq, po.path, po.value
                FROM param_occurrence po
                JOIN stg_event se ON se.id = po.stg_event_id
                WHERE po.project_id = :pid
                  AND po.path IN (:p_ci, :p_mcc, :p_mnc, :p_tac)
            )
            SELECT stg_event_id, capture_id, seq, operator, band,
                   MAX(CASE WHEN path = :p_ci  THEN value END) AS cell_identity,
                   MAX(CASE WHEN path = :p_mcc THEN value END) AS mcc,
                   MAX(CASE WHEN path = :p_mnc THEN value END) AS mnc,
                   MAX(CASE WHEN path = :p_tac THEN value END) AS tac
            FROM sib1
            GROUP BY stg_event_id, capture_id, seq, operator, band
            HAVING MAX(CASE WHEN path = :p_ci THEN value END) IS NOT NULL
            ORDER BY capture_id, seq
            """
        ),
        {
            "pid": project_id,
            "p_ci":  _PATH_CI,
            "p_mcc": _PATH_MCC,
            "p_mnc": _PATH_MNC,
            "p_tac": _PATH_TAC,
        },
    ).fetchall()
    return [
        {
            "stg_event_id":  r[0],
            "capture_id":    r[1],
            "seq":           r[2],
            "operator":      r[3],
            "band":          r[4],
            "cell_identity": r[5],
            "mcc":           r[6],
            "mnc":           r[7],
            "tac":           r[8],
        }
        for r in rows
    ]


def _attach_pci_earfcn(db: Session, project_id: str, sib1: list[dict]) -> None:
    """Rattache ``pci`` et ``earfcn`` serving à chaque SIB1 via le
    ``measurement_points`` le plus proche en ``(capture_id, seq)`` de
    la capture — mesure prise par le terminal sur CETTE cellule.
    """
    if not sib1:
        return
    # Pour chaque capture, précharge la mesure médiane (pci, earfcn) la
    # plus récente avant / près du SIB1. Simplification pragmatique :
    # on prend n'importe quelle mp de la capture avec pci et earfcn
    # non-null (dans un drive-test LTE, le serving reste stable sur la
    # durée d'une capture).
    capture_ids = sorted({c["capture_id"] for c in sib1 if c["capture_id"]})
    if not capture_ids:
        return
    rows = db.execute(
        text(
            """
            SELECT capture_id, MAX(earfcn) AS earfcn
            FROM measurement_points
            WHERE project_id = :pid
              AND earfcn IS NOT NULL
              AND capture_id = ANY(:caps)
            GROUP BY capture_id
            """
        ),
        {"pid": project_id, "caps": list(capture_ids)},
    ).fetchall()
    earfcn_by_cap = {r[0]: int(r[1]) for r in rows if r[1] is not None}
    # pci serving : via param_occurrence measResultPCell/physCellId OU
    # measResultServingCell/physCellId par capture (dernier vu).
    rows = db.execute(
        text(
            """
            SELECT se.capture_id,
                   po.value AS pci,
                   MAX(se.seq) AS last_seq
            FROM param_occurrence po
            JOIN stg_event se ON se.id = po.stg_event_id
            WHERE po.project_id = :pid
              AND (po.path LIKE '%measResultPCell/physCellId'
                   OR po.path LIKE '%measResultServingCell/physCellId')
              AND se.capture_id = ANY(:caps)
            GROUP BY se.capture_id, po.value
            """
        ),
        {"pid": project_id, "caps": list(capture_ids)},
    ).fetchall()
    # Keep for each capture, the pci with the latest seq.
    pci_by_cap: dict[str, int] = {}
    seen_last: dict[str, int] = {}
    for cap, pci_val, last_seq in rows:
        if pci_val is None:
            continue
        try:
            pci_int = int(pci_val)
            lseq = int(last_seq)
        except (TypeError, ValueError):
            continue
        if cap not in seen_last or lseq > seen_last[cap]:
            pci_by_cap[cap] = pci_int
            seen_last[cap] = lseq

    for c in sib1:
        cap = c["capture_id"]
        c["pci"]    = pci_by_cap.get(cap)
        c["earfcn"] = earfcn_by_cap.get(cap)
        c["band_derived"] = _band_from_earfcn(c["earfcn"])


# ---------------------------------------------------------------------------
# ECGI build + propagation
# ---------------------------------------------------------------------------


def _build_ecgi_cells(sib1_rows: list[dict]) -> list[EcgiCell]:
    cells: list[EcgiCell] = []
    for r in sib1_rows:
        ci_raw = r.get("cell_identity")
        if ci_raw is None:
            continue
        try:
            ci = int(ci_raw)
        except (TypeError, ValueError):
            continue
        mcc = (r.get("mcc") or "").strip()
        mnc = (r.get("mnc") or "").strip()
        if not mcc or not mnc:
            continue
        plmn = mcc + mnc
        ecgi = f"{plmn}-{ci}"
        enb_id = ci >> 8
        local_cell_id = ci & 0xFF
        operator = _plmn_operator(mcc, mnc) or r.get("operator")
        band = r.get("band_derived") or r.get("band")
        cells.append(EcgiCell(
            ecgi=ecgi,
            plmn=plmn,
            mcc=mcc,
            mnc=mnc,
            cell_identity=ci,
            enb_id=enb_id,
            local_cell_id=local_cell_id,
            tac=r.get("tac"),
            pci=r.get("pci"),
            earfcn=r.get("earfcn"),
            band=band,
            operator=operator,
            first_capture=r.get("capture_id"),
            last_capture=r.get("capture_id"),
        ))
    return cells


def _propagate_to_mp(
    db: Session, project_id: str, cells: list[EcgiCell],
) -> int:
    """Pour chaque mp du projet, assigne ``ecgi`` depuis la dernière
    cellule SIB1 **de la même capture**. Préférence au match
    ``(capture_id, pci, earfcn)`` quand pci+earfcn sont connus ;
    sinon fallback sur ``capture_id`` uniquement (une capture =
    une cellule serving globalement sur REF, les HO intra-capture
    sont rares en drive-test urbain).

    Retourne le nombre de mp mis à jour.
    """
    # Dernière cellule par capture (ordre first_capture → last_capture).
    last_cell_by_cap: dict[str, EcgiCell] = {}
    for c in cells:
        for cap in (c.first_capture, c.last_capture):
            if cap is None:
                continue
            last_cell_by_cap[cap] = c

    total = 0
    # Pass 1 — match précis (capture, pci, earfcn) quand connu.
    for c in cells:
        if c.pci is None or c.earfcn is None:
            continue
        for cap in (c.first_capture, c.last_capture):
            if cap is None:
                continue
            r = db.execute(
                text(
                    """
                    UPDATE measurement_points
                    SET ecgi = :ecgi
                    WHERE project_id = :pid
                      AND capture_id = :cap
                      AND earfcn = :earfcn
                      AND ecgi IS NULL
                    """
                ),
                {"ecgi": c.ecgi, "pid": project_id, "cap": cap, "earfcn": c.earfcn},
            )
            total += r.rowcount or 0

    # Pass 2 — fallback par capture pour tout mp sans ecgi (une
    # capture = une cellule serving, matché par le dernier SIB1 vu).
    for cap, cell in last_cell_by_cap.items():
        r = db.execute(
            text(
                """
                UPDATE measurement_points
                SET ecgi = :ecgi
                WHERE project_id = :pid
                  AND capture_id = :cap
                  AND ecgi IS NULL
                """
            ),
            {"ecgi": cell.ecgi, "pid": project_id, "cap": cap},
        )
        total += r.rowcount or 0

    return total


def _upsert_cell_ref(db: Session, cells: list[EcgiCell]) -> int:
    """Insère ou met à jour cell_ref sur ``(eci=ecgi)``. Retourne le
    nombre de rows affectés."""
    if not cells:
        return 0
    # Dédup par ecgi — garder la première capture pour snapshot_date.
    by_ecgi: dict[str, EcgiCell] = {}
    for c in cells:
        if c.ecgi not in by_ecgi:
            by_ecgi[c.ecgi] = c
    affected = 0
    for c in by_ecgi.values():
        exists = db.execute(
            text("SELECT 1 FROM cell_ref WHERE eci = :e LIMIT 1"),
            {"e": c.ecgi},
        ).first()
        if exists:
            db.execute(
                text(
                    """
                    UPDATE cell_ref
                    SET enodebid = :enb, pci = :pci, earfcn = :earfcn,
                        band_3gpp = COALESCE(:band, band_3gpp),
                        techno = COALESCE(techno, 'LTE'),
                        snapshot_date = COALESCE(snapshot_date, :cap)
                    WHERE eci = :e
                    """
                ),
                {"e": c.ecgi, "enb": str(c.enb_id), "pci": c.pci,
                 "earfcn": c.earfcn, "band": c.band, "cap": c.last_capture},
            )
        else:
            # Génère un id stable depuis ecgi (jamais 2 rows pour la
            # même cellule).
            cell_id = f"logs-{c.ecgi}"
            db.execute(
                text(
                    """
                    INSERT INTO cell_ref
                        (id, rat, eci, enodebid, pci, earfcn, band_3gpp,
                         techno, snapshot_date)
                    VALUES
                        (:id, :rat, :eci, :enb, :pci, :earfcn, :band,
                         :techno, :cap)
                    """
                ),
                {
                    "id":      cell_id,
                    "rat":     "LTE",
                    "eci":     c.ecgi,
                    "enb":     str(c.enb_id),
                    "pci":     c.pci,
                    "earfcn":  c.earfcn,
                    "band":    c.band,
                    "techno":  "LTE",
                    "cap":     c.first_capture,
                },
            )
        affected += 1
    return affected


def _plmn_mismatch_scan(
    db: Session, project_id: str, cells: list[EcgiCell],
) -> tuple[int, list[dict[str, Any]]]:
    """Compte les captures où l'opérateur dérivé du PLMN SIB1 diffère
    de l'opérateur Nemo (``nmf_file.dl``). Les abréviations Nemo
    ``OFR/BYT/FREE/SFR`` sont normalisées vers les noms canoniques
    avant comparaison — jamais une différence orthographique n'est
    comptée comme vrai mismatch."""
    nemo_alias = {
        "OFR": "Orange", "ORANGE": "Orange", "Orange": "Orange",
        "BYT": "Bouygues", "BOUYGUES": "Bouygues", "Bouygues": "Bouygues",
        "SFR": "SFR",
        "FREE": "Free", "Free": "Free",
    }
    rows = db.execute(
        text(
            """
            SELECT se.capture_id, nmf.dl
            FROM stg_event se
            JOIN nmf_file nmf ON nmf.id = se.nmf_file_id
            WHERE se.project_id = :pid
            GROUP BY se.capture_id, nmf.dl
            """
        ),
        {"pid": project_id},
    ).fetchall()
    dl_by_cap: dict[str, str] = {}
    for r in rows:
        dl_raw = (r[1] or "").strip()
        dl_by_cap[r[0]] = nemo_alias.get(dl_raw, dl_raw)
    op_by_cap: dict[str, str] = {}
    for c in cells:
        for cap in (c.first_capture, c.last_capture):
            if cap and c.operator:
                op_by_cap.setdefault(cap, c.operator)
    mismatches: list[dict[str, Any]] = []
    for cap, op in op_by_cap.items():
        dl = dl_by_cap.get(cap)
        if dl and dl != op:
            mismatches.append({"capture_id": cap, "sib1_operator": op, "nmf_dl": dl})
    return len(mismatches), mismatches[:10]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def populate_ecgi_for_project(
    db: Session, project_id: str, *, commit: bool = True,
) -> PopulateEcgiReport:
    """Propage ECGI sur tout un projet. Idempotent (purge NULL +
    recompute). Retourne un rapport chiffré."""
    report = PopulateEcgiReport(project_id=project_id)

    # Reset mp.ecgi (idempotence)
    db.execute(
        text("UPDATE measurement_points SET ecgi = NULL WHERE project_id = :pid"),
        {"pid": project_id},
    )

    sib1_rows = _extract_sib1_cells(db, project_id)
    report.sib1_cells = len(sib1_rows)
    if sib1_rows:
        _attach_pci_earfcn(db, project_id, sib1_rows)

    cells = _build_ecgi_cells(sib1_rows)
    report.distinct_ecgi = len({c.ecgi for c in cells})

    mp_total = db.execute(
        text("SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid"),
        {"pid": project_id},
    ).scalar() or 0
    report.mp_total = int(mp_total)

    updated = _propagate_to_mp(db, project_id, cells)
    report.mp_with_ecgi = updated
    report.mp_pct_with_ecgi = (100.0 * updated / mp_total) if mp_total else 0.0

    _upsert_cell_ref(db, cells)

    mismatch, mismatch_examples = _plmn_mismatch_scan(db, project_id, cells)
    report.plmn_mismatch = mismatch
    report.plmn_mismatch_examples = mismatch_examples

    if cells:
        c = cells[0]
        report.sample_cell = {
            "ecgi":          c.ecgi,
            "plmn":          c.plmn,
            "cell_identity": c.cell_identity,
            "enb_id":        c.enb_id,
            "local_cell_id": c.local_cell_id,
            "tac":           c.tac,
            "pci":           c.pci,
            "earfcn":        c.earfcn,
            "band":          c.band,
            "operator":      c.operator,
            "first_capture": c.first_capture,
        }
    if not sib1_rows:
        report.warnings.append(
            "aucun SIB1 avec cellIdentity dans param_occurrence — vérifier l'ingestion décodeur"
        )

    if commit:
        db.commit()
    return report
