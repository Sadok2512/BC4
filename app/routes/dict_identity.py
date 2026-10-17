"""Section « Identité cellule » du dictionnaire (D du lot audit G0-G11).

Expose les feuilles ASN.1 natives SIB1 (LTE + NR) qui portent l'identité
d'une cellule : mcc, mnc, cellIdentity, trackingAreaCode. Expose aussi
les grandeurs **dérivées** (`ECGI`, `enb_id`, `local_cell_id`,
`NCGI`, `gnb_id`) avec la marque `dérivé SIB1`. Les aliases de
recherche (ecgi, eci, enb, enodeb, cell id, tac, plmn) sont déclarés.

NR : SIB1 NR fournit `cellIdentity` 36 bits + `TAC` 24 bits + `ranac`.
Si **aucun SIB1 NR** n'est présent (cas EN-DC pur), la section NR est
marquée `ABSENT_DU_PERIMETRE` avec la raison :
« EN-DC : PSCell = PCI NR + ARFCN ; NCGI en SA seulement ». À la place
on expose le concept **PSCell** = (`pci_nr`, `arfcn_nr`, `ecgi_ancre_LTE`)
calculé depuis `measurement_points` quand le projet a des mesures NR.

Compteurs projet : n SIB1 LTE, n SIB1 NR, n ECGI distincts, n PSCell
distincts.

Les réponses sont **typées Pydantic** → shape visible dans
`/openapi.json`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, with_statement_timeout_60s
from app.models import Project


router = APIRouter(
    prefix="/projects",
    tags=["dictionary"],
    # 0.48.0 — statement_timeout 60 s (cf. project_kpi.router).
    dependencies=[Depends(get_current_user), Depends(with_statement_timeout_60s)],
)


# --------------------------------------------------------------------
# Schémas Pydantic (shape stable visible dans /openapi.json).
# --------------------------------------------------------------------

class IdentityLeaf(BaseModel):
    """Feuille ASN.1 d'identité cellule."""
    path: str = Field(..., description="Chemin ASN.1 depuis SIB1.")
    label: str = Field(..., description="Libellé court lisible.")
    unit: str | None = Field(None, description="Unité ou format (ex. 'bits:28', 'MCC', 'MNC').")
    kind: str = Field(..., description="'natif' (feuille SIB1 brute) ou 'dérivé SIB1'.")
    description: str = Field(..., description="Rôle 3GPP + convention de valeur.")
    aliases: list[str] = Field(default_factory=list)


class IdentitySection(BaseModel):
    """Section d'identité par technologie."""
    techno: str = Field(..., description="LTE | NR")
    status: str = Field(..., description="PRESENT | ABSENT_DU_PERIMETRE")
    reason: str | None = Field(None)
    leaves: list[IdentityLeaf] = Field(default_factory=list)
    pscell: dict | None = Field(None, description="PSCell = (pci_nr, arfcn_nr, ecgi_ancre_LTE) si NR via ancre.")


class IdentityCounters(BaseModel):
    sib1_lte: int = 0
    sib1_nr: int = 0
    ecgi_distinct: int = 0
    pscell_distinct: int = 0


class ProjectIdentityDict(BaseModel):
    project_id: str
    sections: list[IdentitySection]
    counters: IdentityCounters
    search_aliases: list[str] = Field(
        default_factory=lambda: [
            "ecgi", "eci", "enb", "enodeb", "cell id", "cellid",
            "cell identity", "tac", "trackingareacode", "plmn",
            "mcc", "mnc", "ncgi", "gnb", "gnb id", "pscell",
        ],
    )


# --------------------------------------------------------------------
# Définitions statiques des feuilles ASN.1 d'identité cellule.
# --------------------------------------------------------------------

_LTE_LEAVES: list[IdentityLeaf] = [
    IdentityLeaf(
        path="systemInformationBlockType1/cellAccessRelatedInfo/plmn-IdentityList/plmn-Identity/mcc",
        label="PLMN · MCC",
        unit="MCC (3 digits, int)",
        kind="natif",
        description="Mobile Country Code primaire du PLMN (TS 36.331). "
                    "Décoder en entier (ex. 208 = France), pas en littéral `0b…`.",
        aliases=["mcc", "plmn"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1/cellAccessRelatedInfo/plmn-IdentityList/plmn-Identity/mnc",
        label="PLMN · MNC",
        unit="MNC (2 ou 3 digits, int)",
        kind="natif",
        description="Mobile Network Code primaire du PLMN. Longueur 2 ou 3 "
                    "digits ; **ne pas** zero-padder côté serveur.",
        aliases=["mnc", "plmn"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1/cellAccessRelatedInfo/cellIdentity",
        label="Cell Identity (ECI)",
        unit="bits:28, int",
        kind="natif",
        description="E-UTRAN Cell Identifier 28 bits = `enb_id × 2^(28-local_bits) "
                    "+ local_cell_id`. Doit être décodé en entier, jamais en "
                    "littéral `0b…`.",
        aliases=["eci", "cell id", "cellid", "cell identity"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1/cellAccessRelatedInfo/trackingAreaCode",
        label="Tracking Area Code (TAC)",
        unit="bits:16, int",
        kind="natif",
        description="TAC 16 bits (LTE). Décodé en entier (ex. 39233), "
                    "jamais `0b…`.",
        aliases=["tac", "trackingareacode"],
    ),
    IdentityLeaf(
        path="(dérivé) ecgi = mcc·mnc·eci",
        label="ECGI (canonique)",
        unit="texte 'MCC(3)MNC(2|3)-eci_decimal' ex. '20801-23658243'",
        kind="dérivé SIB1",
        description="Clé canonique projet-wide. Jamais fabriquée : construite "
                    "quand mcc, mnc ET cellIdentity sont présents dans le même "
                    "SIB1.",
        aliases=["ecgi", "cgi"],
    ),
    IdentityLeaf(
        path="(dérivé) enb_id = eci >> local_bits",
        label="eNB ID",
        unit="int (14 à 20 bits selon LCID length)",
        kind="dérivé SIB1",
        description="Identifiant eNodeB ; nécessite de connaître la longueur "
                    "de local_cell_id (fournie dans la lecture ASN.1). Si "
                    "longueur inconnue, enb_id n'est **pas** dérivé.",
        aliases=["enb", "enodeb", "enb id"],
    ),
    IdentityLeaf(
        path="(dérivé) local_cell_id = eci - (enb_id << local_bits)",
        label="Local Cell ID",
        unit="int (0..255 typiquement)",
        kind="dérivé SIB1",
        description="Identifiant de secteur sur l'eNodeB. Dérivé seulement si "
                    "`local_bits` connu.",
        aliases=["local cell id", "sector"],
    ),
]

_NR_LEAVES_IF_PRESENT: list[IdentityLeaf] = [
    IdentityLeaf(
        path="systemInformationBlockType1_NR/cellAccessRelatedInfo/plmn-IdentityInfoList/plmn-IdentityList/plmn-Identity/mcc",
        label="PLMN · MCC (NR)",
        unit="MCC (3 digits, int)",
        kind="natif",
        description="MCC du PLMN primaire NR (TS 38.331).",
        aliases=["mcc", "plmn"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1_NR/cellAccessRelatedInfo/plmn-IdentityInfoList/plmn-IdentityList/plmn-Identity/mnc",
        label="PLMN · MNC (NR)",
        unit="MNC (2 ou 3 digits, int)",
        kind="natif",
        description="MNC du PLMN primaire NR.",
        aliases=["mnc", "plmn"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1_NR/cellAccessRelatedInfo/cellIdentity",
        label="Cell Identity NR (NCI)",
        unit="bits:36, int",
        kind="natif",
        description="NR Cell Identity 36 bits = `gnb_id × 2^(36-gnb_id_len) "
                    "+ local_cell_id`. Décoder en entier.",
        aliases=["nci", "cell id", "cell identity"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1_NR/cellAccessRelatedInfo/trackingAreaCode",
        label="Tracking Area Code (TAC NR)",
        unit="bits:24, int",
        kind="natif",
        description="TAC NR 24 bits (TS 38.331 §6.2.2).",
        aliases=["tac", "trackingareacode"],
    ),
    IdentityLeaf(
        path="systemInformationBlockType1_NR/cellAccessRelatedInfo/ranac",
        label="RAN Area Code (RANAC)",
        unit="int (0..255)",
        kind="natif",
        description="RAN Area Code (optionnel NR). Jamais inventé.",
        aliases=["ranac"],
    ),
    IdentityLeaf(
        path="(dérivé) ncgi = mcc·mnc·nci",
        label="NCGI (canonique)",
        unit="texte 'MCC(3)MNC(2|3)-nci_decimal'",
        kind="dérivé SIB1",
        description="NR CGI canonique. Construit SEULEMENT si SIB1 NR présent.",
        aliases=["ncgi"],
    ),
    IdentityLeaf(
        path="(dérivé) gnb_id = nci >> (36 - gnb_id_len)",
        label="gNB ID",
        unit="int (22 à 32 bits selon longueur)",
        kind="dérivé SIB1",
        description="Identifiant gNB ; nécessite `gnb_id_len`. Jamais dérivé "
                    "sans cette longueur.",
        aliases=["gnb", "gnb id", "gnodeb"],
    ),
]


# --------------------------------------------------------------------
# Compteurs projet (SQL stricts, 1 chiffre = 1 requête).
# --------------------------------------------------------------------

def _count_sib1_lte(db: Session, project_id: str) -> int:
    """Nombre d'events RRC SIB1 LTE décodés sur ce projet.

    Un SIB1 LTE = `param_occurrence.message` contient
    'SystemInformationBlockType1' (sans 'NR'), DISTINCT par
    `stg_event_id`.
    """
    row = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT stg_event_id) FROM param_occurrence
            WHERE project_id = :pid
              AND message ILIKE '%SystemInformationBlockType1%'
              AND message NOT ILIKE '%NR%'
            """
        ),
        {"pid": project_id},
    ).scalar()
    return int(row or 0)


def _count_sib1_nr(db: Session, project_id: str) -> int:
    """Nombre d'events SIB1 NR décodés. 0 si projet EN-DC pur."""
    row = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT stg_event_id) FROM param_occurrence
            WHERE project_id = :pid
              AND (message ILIKE '%SIB1%NR%'
                   OR message ILIKE '%SystemInformationBlockType1_NR%'
                   OR message ILIKE '%NR_SIB1%')
            """
        ),
        {"pid": project_id},
    ).scalar()
    return int(row or 0)


def _count_ecgi_distinct(db: Session, project_id: str) -> int:
    row = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT ecgi) FROM measurement_points
            WHERE project_id = :pid AND ecgi IS NOT NULL
            """
        ),
        {"pid": project_id},
    ).scalar()
    return int(row or 0)


def _count_pscell_distinct(db: Session, project_id: str) -> int:
    """PSCell distinct = (pci_nr, arfcn_nr) sur mesures NR du projet.

    En EN-DC, le PSCell est identifié par (PCI, ARFCN) côté NR + l'ECGI
    de l'ancre LTE. On ne compte ici que les paires PCI/ARFCN distinctes
    côté NR. 0 si aucune mesure NR dans le projet.
    """
    row = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT (pci_nr || '|' || arfcn_nr))
            FROM (
                SELECT CAST(raw_fields->>'nr_pci' AS text) AS pci_nr,
                       CAST(raw_fields->>'nr_arfcn' AS text) AS arfcn_nr
                FROM stg_event_raw
                WHERE project_id = :pid
                  AND raw_fields->>'nr_pci' IS NOT NULL
                  AND raw_fields->>'nr_arfcn' IS NOT NULL
            ) q
            """
        ),
        {"pid": project_id},
    ).scalar()
    return int(row or 0)


def _pscell_summary(db: Session, project_id: str) -> dict | None:
    """Résumé PSCell pour EN-DC : (pci_nr, arfcn_nr) + ecgi ancre LTE.

    Retourne None si aucun échantillon NR exploitable.
    """
    rows = db.execute(
        text(
            """
            SELECT raw_fields->>'nr_pci' AS pci,
                   raw_fields->>'nr_arfcn' AS arfcn,
                   COUNT(*) AS n
            FROM stg_event_raw
            WHERE project_id = :pid
              AND raw_fields->>'nr_pci' IS NOT NULL
              AND raw_fields->>'nr_arfcn' IS NOT NULL
            GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10
            """
        ),
        {"pid": project_id},
    ).all()
    if not rows:
        return None
    # L'ancre LTE n'est pas directement liée à un (pci_nr, arfcn_nr) sans
    # join (capture_id, seq) ; on remonte juste le top-N PSCell + une
    # référence vers mp.ecgi pour le projet.
    return {
        "topN_pscell": [
            {"pci_nr": r[0], "arfcn_nr": r[1], "n_events": int(r[2])}
            for r in rows
        ],
        "note": "L'ancre LTE est l'ECGI serving au même (capture_id, seq). "
                "Voir mp.ecgi pour résolution per-measurement.",
    }


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------

def _require_project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(
            404, {"code": "NOT_FOUND", "message": "Projet introuvable"}
        )
    return p


@router.get(
    "/{project_id}/dict/identity",
    response_model=ProjectIdentityDict,
    summary="Section Identité cellule du dictionnaire (LTE + NR, dérivés, aliases, compteurs)",
)
def get_project_identity_dict(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectIdentityDict:
    _require_project(db, project_id)
    n_sib1_lte = _count_sib1_lte(db, project_id)
    n_sib1_nr = _count_sib1_nr(db, project_id)
    n_ecgi = _count_ecgi_distinct(db, project_id)
    n_pscell = _count_pscell_distinct(db, project_id)

    # Section LTE : toujours exposée. ABSENT_DU_PERIMETRE si aucune SIB1
    # LTE n'a été décodée (projet potentiellement SA NR pur).
    lte_section = IdentitySection(
        techno="LTE",
        status="PRESENT" if n_sib1_lte > 0 else "ABSENT_DU_PERIMETRE",
        reason=None if n_sib1_lte > 0 else "aucun SIB1 LTE décodé dans ce projet",
        leaves=_LTE_LEAVES,
        pscell=None,
    )

    # Section NR : si pas de SIB1 NR → EN-DC pur, on expose PSCell à la
    # place.
    if n_sib1_nr == 0:
        nr_section = IdentitySection(
            techno="NR",
            status="ABSENT_DU_PERIMETRE",
            reason="EN-DC : PSCell = PCI NR + ARFCN ; NCGI en SA seulement",
            leaves=[],
            pscell=_pscell_summary(db, project_id),
        )
    else:
        nr_section = IdentitySection(
            techno="NR",
            status="PRESENT",
            reason=None,
            leaves=_NR_LEAVES_IF_PRESENT,
            pscell=None,
        )

    return ProjectIdentityDict(
        project_id=project_id,
        sections=[lte_section, nr_section],
        counters=IdentityCounters(
            sib1_lte=n_sib1_lte,
            sib1_nr=n_sib1_nr,
            ecgi_distinct=n_ecgi,
            pscell_distinct=n_pscell,
        ),
    )
