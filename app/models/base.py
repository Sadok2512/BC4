from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    login: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class AppUser(Base):
    """Table d'auth B2. Rôles canoniques : admin / ingenieur / lecteur
    (CHECK en migration). Un mapping vers le vocabulaire Zod existant
    (admin / editor / viewer) est fait au bord de l'API dans
    `deps.get_actor`, pour ne pas casser les routes B0/B1."""

    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # admin|ingenieur|lecteur
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    geography: Mapped[str] = mapped_column(String, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    operators: Mapped[list] = mapped_column(JSON, nullable=False)
    technologies: Mapped[list] = mapped_column(JSON, nullable=False)
    services: Mapped[list] = mapped_column(JSON, nullable=False)
    bands: Mapped[list] = mapped_column(JSON, nullable=False)
    departements: Mapped[list] = mapped_column(JSON, nullable=False)
    period_start: Mapped[str] = mapped_column(String, nullable=False)
    period_end: Mapped[str] = mapped_column(String, nullable=False)
    captures: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # B1-ingest : résumé rempli à l'ingestion NMF (nullable pour les projets seedés B0).
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    status_ingest: Mapped[str | None] = mapped_column(String, nullable=True)  # draft/importing/ready/error
    operators_plmn: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    technos_seen: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    n_captures_ingest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_events_ingest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gps_coverage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # B2 (0.12.0) : agrégat géo issu de la jointure cells Orange ↔ cell_ref
    # (DOR / DR / plaque / arcep). JSON nullable — resté `null` tant
    # qu'aucune cellule Orange n'a été jointe (déclaré, pas N/A).
    perimeter: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NmfFile(Base):
    __tablename__ = "nmf_file"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_nmf_file_project_sha"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # pending/decoding/done/error
    decoder_version: Mapped[str | None] = mapped_column(String, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    n_captures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_gps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StgEvent(Base):
    """Staging aplatie du décodeur NMF. Ordre canonique `(capture_id, seq)`.
    JAMAIS trié ou comparé par `ts`. Aucune identité d'abonné.
    """

    __tablename__ = "stg_event"
    __table_args__ = (
        Index("ix_stg_event_capture_seq", "project_id", "capture_id", "seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nmf_file_id: Mapped[str] = mapped_column(
        ForeignKey("nmf_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capture_id: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # `ts` : ATTRIBUT seulement — JAMAIS utilisé pour trier/comparer.
    ts: Mapped[str | None] = mapped_column(String, nullable=True)
    event_code: Mapped[str | None] = mapped_column(String, nullable=True)
    system: Mapped[str | None] = mapped_column(String, nullable=True)  # LTE / NR
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    freq: Mapped[str | None] = mapped_column(String, nullable=True)  # EARFCN/UARFCN/ARFCN
    pci: Mapped[str | None] = mapped_column(String, nullable=True)   # PCI/PSC
    payload_hex: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)


class MeasurementPoint(Base):
    __tablename__ = "measurement_points"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    operator: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tech: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service: Mapped[str] = mapped_column(String, nullable=False, index=True)
    band: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dep: Mapped[str] = mapped_column(String, nullable=False, index=True)
    site: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[str] = mapped_column(String, nullable=False)
    dl: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    sinr: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency: Mapped[float | None] = mapped_column(Float, nullable=True)
    capture_id: Mapped[str | None] = mapped_column(String, nullable=True)
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DictMessage(Base):
    __tablename__ = "dict_messages"

    msg_id: Mapped[str] = mapped_column(String, primary_key=True)
    techno: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


class DictParam(Base):
    __tablename__ = "dict_params"

    param_id: Mapped[str] = mapped_column(String, primary_key=True)
    msg_id: Mapped[str] = mapped_column(ForeignKey("dict_messages.msg_id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    leaf: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    has_gps: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    simulate_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    spec_kind: Mapped[str] = mapped_column(String, nullable=False)  # "numeric" | "categorical"
    spec: Mapped[dict] = mapped_column(JSON, nullable=False)

    message = relationship("DictMessage", backref="params")


class ConversionRule(Base):
    __tablename__ = "conversion_rule"

    param_id: Mapped[str] = mapped_column(ForeignKey("dict_params.param_id"), primary_key=True)
    formula: Mapped[str] = mapped_column(String, nullable=False)
    scale: Mapped[float] = mapped_column(Float, nullable=False)
    offset: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    ref: Mapped[str] = mapped_column(String, nullable=False)


class RrcObservation(Base):
    __tablename__ = "rrc_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    param_id: Mapped[str] = mapped_column(ForeignKey("dict_params.param_id"), nullable=False, index=True)
    operator: Mapped[str] = mapped_column(String, nullable=False, index=True)
    band: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dep: Mapped[str] = mapped_column(String, nullable=False, index=True)
    raw_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_str: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    capture_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


class KpiCatalogItem(Base):
    __tablename__ = "kpi_catalog"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(String, nullable=False)
    tech: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_events: Mapped[list] = mapped_column(JSON, nullable=False)
    history: Mapped[list] = mapped_column(JSON, nullable=False)


class KpiCatalogGroup(Base):
    __tablename__ = "kpi_catalog_groups"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class KpiRrcSummary(Base):
    """Headline KPI returned alongside the catalogue (fixtures.KPI_RRC)."""

    __tablename__ = "kpi_rrc_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False)
    techs: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    by_op: Mapped[dict] = mapped_column(JSON, nullable=False)


class AppearanceRow(Base):
    __tablename__ = "settings_appearance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    org_primary_hex: Mapped[str | None] = mapped_column(String, nullable=True)


class OrganizationRow(Base):
    __tablename__ = "settings_organization"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    short_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    logo_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_contact: Mapped[str] = mapped_column(String, nullable=False, default="")
    domain: Mapped[str] = mapped_column(String, nullable=False, default="")
    show_in_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_in_exports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    name_max: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    logo_max_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=300_000)
    logo_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class PasswordPolicyRow(Base):
    __tablename__ = "settings_password_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    min_length: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    require_digit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_upper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ApiPermissionsRow(Base):
    __tablename__ = "settings_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    editor_can_edit_geo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    editor_can_edit_kpi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AiConfigRow(Base):
    __tablename__ = "settings_ai"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    endpoint_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    model_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String, nullable=False, default="")
    providers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    auth_method: Mapped[str] = mapped_column(String, nullable=False, default="api_key")
    has_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    saved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    connection: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ExecStepRow(Base):
    __tablename__ = "assistant_exec_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class CellRef(Base):
    __tablename__ = "cell_ref"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_date: Mapped[str | None] = mapped_column(String, nullable=True)
    rat: Mapped[str] = mapped_column(String, nullable=False, index=True)
    vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    eci: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    nci: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    enodebid: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    pci: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band_src: Mapped[str | None] = mapped_column(String, nullable=True)
    band_3gpp: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    techno: Mapped[str | None] = mapped_column(String, nullable=True)
    earfcn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    azimuth: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[str | None] = mapped_column(String, nullable=True)
    cell_class: Mapped[str | None] = mapped_column(String, nullable=True)
    etat: Mapped[str | None] = mapped_column(String, nullable=True)
    dor: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    dr: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    plaque: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    site_name: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    cell_op_leader: Mapped[str | None] = mapped_column(String, nullable=True)
    # Zone ARCEP (dimension orthogonale à la géo). Libellé source persisté
    # LITTÉRALEMENT depuis `cat_arcep_code` (11 catégories réelles) ou NULL
    # si la source vaut `""` / `"(null)"`. Jamais `"(null)"` en base.
    arcep_zone: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    reference_import_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # `geom` is PostGIS GEOMETRY(POINT, 4326) — not mapped as ORM column to
    # keep the model free of GeoAlchemy2 at runtime; the ingestion service
    # writes it via raw SQL + ST_SetSRID.


class ReferenceImport(Base):
    __tablename__ = "reference_import"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_date: Mapped[str | None] = mapped_column(String, nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False)
    report: Mapped[dict] = mapped_column(JSON, nullable=False)


class GeoReference(Base):
    __tablename__ = "geo_references"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    imported_at: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ParamOccurrence(Base):
    """Occurrence d'un paramètre RRC décodé depuis `stg_event.payload_hex`.

    Scope strict `project_id`. Ordre canonique via `stg_event_id` → l'event
    source conserve `(capture_id, seq)`. Deny-list identités appliquée AU
    POPULATE : jamais une ligne qui matche DENY n'arrive ici.
    """

    __tablename__ = "param_occurrence"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "stg_event_id", "path", name="uq_param_occ_event_path"
        ),
        Index(
            "ix_param_occ_sys_msg_path",
            "project_id", "system", "message", "path",
        ),
        Index("ix_param_occ_op_band", "project_id", "operator", "band"),
        Index("ix_param_occ_path", "project_id", "path"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    stg_event_id: Mapped[int] = mapped_column(
        ForeignKey("stg_event.id", ondelete="CASCADE"), nullable=False
    )
    system: Mapped[str] = mapped_column(String, nullable=False)  # LTE | NR
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_converted: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_converted: Mapped[str | None] = mapped_column(String, nullable=True)
    operator: Mapped[str | None] = mapped_column(String, nullable=True)
    band: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
