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
    # 0.46.0 — Suivi complétude populate_measurement_points (chaînage auto
    # post-ingest). `last_populate_at` est posé à CHAQUE fin de populate
    # réussi ; `n_points` snapshot mp pour ce projet au moment du populate.
    # Un projet avec `nmf_count > 0 AND (last_populate_at IS NULL OR
    # n_points = 0)` est **incomplet** (NMF ingérés mais pas transformés).
    last_populate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    n_points: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # 0.30.0 — câblage `bc4-decoder 2.0.0::decode_nmf_file_full`.
    # Chemin absolu du .nmf source PERSISTÉ (jamais le tempfile). Dossier
    # cible : `/var/lib/bc4/nmf-source/<project_id>/<nmf_file_id>.nmf`
    # (ou `$BC4_NMF_SOURCE_DIR/...`). Volume Docker nommé `bc4_nmf_source`.
    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # file meta (header `#...` du NMF — jamais inventé).
    dl: Mapped[str | None] = mapped_column(String, nullable=True)
    ts_label: Mapped[str | None] = mapped_column(String, nullable=True)
    env: Mapped[str | None] = mapped_column(String, nullable=True)
    start_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # 0.75.0 — NFF 2.19 #UT col 1 ("UTC_to_local", minutes, signe local-UTC).
    # Ex. 120 → local = UTC + 2h (CEST). Null si l'en-tête `#UT` absent.
    utc_offset_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    device_sw: Mapped[str | None] = mapped_column(String, nullable=True)
    # (nmf_file n'a pas de `kind` — c'est sur nmf_capture, voir migration 0043.)
    device_name: Mapped[str | None] = mapped_column(String, nullable=True)
    product: Mapped[str | None] = mapped_column(String, nullable=True)
    imei_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    imsi_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


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


class StgMeasurementRaw(Base):
    """Staging des events `measurement` + `throughput` du décodeur 1.1.0.

    Chaque ligne est une ligne CSV COMPLÈTE du .nmf (`raw_fields`), telle
    que remontée par le décodeur après masquage identité. Le mapping
    `champ CSV → métrique radio (RSRP, RSRQ, SINR, CQI, débit…)` relève
    de la Phase 1 (lot 0.24.0 : infrastructure ; mapping Phase 1 à faire
    sur un NMF témoin). JAMAIS parsé côté SQL.

    Ordre canonique `(capture_id, seq)`. `ts` : attribut seulement.
    Aucune identité abonné (masquage à la source par le décodeur).
    """

    __tablename__ = "stg_measurement_raw"
    __table_args__ = (
        Index("ix_stg_meas_raw_project_code", "project_id", "event_code"),
        Index(
            "ix_stg_meas_raw_project_capture_seq",
            "project_id", "capture_id", "seq",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    nmf_file_id: Mapped[str] = mapped_column(
        ForeignKey("nmf_file.id", ondelete="CASCADE"), nullable=False
    )
    capture_id: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[str | None] = mapped_column(String, nullable=True)
    event_code: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # measurement | throughput
    system: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Ligne CSV complète (JSON array of str). Phase 1 mappe aval.
    raw_fields: Mapped[list] = mapped_column(JSON, nullable=False)


class StgEventRaw(Base):
    """Staging brut des events NON-signalling du décodeur 2.0.0.

    Expose VERBATIM ce que ``decode_nmf_file_full`` renvoie pour les
    catégories ``cellmeas``, ``cmdreq``, ``data_action``, ``data_request``,
    ``data_summary``, ``tx_power``, ``cqi``, ``lock``, ``gps``, ``other``.
    Les events ``signalling`` restent dans ``StgEvent`` (contrat 1.0.0
    préservé — RRC populate continue de lire là).

    ``raw_fields`` est un **dict** nommé par position prouvée (fallback
    ``cN`` pour les positions non prouvées). Zéro parsing SQL : tout est
    lu en Python par ``app/measure/populate.py``.

    Ordre canonique ``(capture_id, seq)``. ``ts`` : attribut seulement.
    Aucune identité abonné (masquage à la source par le décodeur +
    défense en profondeur dans l'ingest).
    """

    __tablename__ = "stg_event_raw"
    __table_args__ = (
        Index(
            "ix_stg_event_raw_project_category",
            "project_id", "category",
        ),
        Index(
            "ix_stg_event_raw_project_capture_seq",
            "project_id", "capture_id", "seq",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    nmf_file_id: Mapped[str] = mapped_column(
        ForeignKey("nmf_file.id", ondelete="CASCADE"), nullable=False
    )
    capture_id: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    event_code: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[str | None] = mapped_column(String, nullable=True)
    system: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    # dict nommé — JSONB côté Postgres. On garde `JSON` ici pour que
    # SQLAlchemy abstraie (SQLite fallback des tests utilise JSON).
    raw_fields: Mapped[dict] = mapped_column(JSON, nullable=False)


class MeasurementPoint(Base):
    __tablename__ = "measurement_points"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    # 0.47.3 — lat/lng NULL autorisé : une mesure radio/data sans fix GPS
    # est CONSERVÉE (règle « jamais une mesure jetée ») mais sans position
    # inventée. Elle sort des cartes et de la voie géo « position » (chip
    # Géo = none), pas des KPI radio.
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0.47.3 — Origine de la position : NULL = indoor / perte de fix,
    # 'gps_fix' = dernier GPS event, 'ecgi_cell_centroid' = future
    # propagation depuis cell_ref.
    geo_source: Mapped[str | None] = mapped_column(String, nullable=True)
    # 0.24.0 — operator/tech/service/dep/site/band deviennent nullable
    # pour accueillir les points issus de `stg_measurement_raw` (NMF).
    # Pattern populate.py : NULL en base, COALESCE("non attribué") au SELECT.
    # Les seeds historiques ont toujours tout renseigné — pas de régression.
    operator: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    tech: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    service: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    band: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    dep: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    site: Mapped[str | None] = mapped_column(String, nullable=True)
    ts: Mapped[str] = mapped_column(String, nullable=False)
    dl: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    sinr: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency: Mapped[float | None] = mapped_column(Float, nullable=True)
    capture_id: Mapped[str | None] = mapped_column(String, nullable=True)
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0.24.0 Keystone — colonnes métriques (NULL tant que mapping Phase 1
    # non prouvé). `event_code` identifie la famille source (CELLMEAS,
    # CQI, PHRATE…) ; les métriques ne sont peuplées QUE pour les codes
    # dont le mapping est validé par preuve (plage 3GPP + croisement RRC).
    rsrq: Mapped[float | None] = mapped_column(Float, nullable=True)
    rssi: Mapped[float | None] = mapped_column(Float, nullable=True)
    cqi: Mapped[float | None] = mapped_column(Float, nullable=True)
    mimo_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    thrpt_ul: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # 0.30.0 — câblage `bc4-decoder 2.0.0::decode_nmf_file_full`. Colonnes
    # enrichies additives (non-breaking) : `operator` reste AUTORITAIRE
    # depuis #DL (meta.dl). `operator_source` déclare l'origine. Pas
    # d'invention : positions non prouvées côté décodeur = NULL.
    operator_source: Mapped[str | None] = mapped_column(String, nullable=True)
    operator_mismatch: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    service_name: Mapped[str | None] = mapped_column(String, nullable=True)
    service_action: Mapped[str | None] = mapped_column(String, nullable=True)
    service_type: Mapped[str | None] = mapped_column(String, nullable=True)
    phase: Mapped[str | None] = mapped_column(String, nullable=True)
    env: Mapped[str | None] = mapped_column(String, nullable=True)
    rat: Mapped[str | None] = mapped_column(String, nullable=True)
    earfcn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0.41.0 — ECGI serving propagé par le populate_ecgi : dernier SIB1
    # de la capture avec même (pci, earfcn) en ordre (capture_id, seq).
    # Après HO sans SIB1 relu → NULL (jamais l'ancien).
    ecgi: Mapped[str | None] = mapped_column(String, nullable=True, index=True)


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
    # 0.41.0 — Enrichissement géo (upload opérateur). ``commune`` libellé
    # textuel, ``insee`` code INSEE 5 chiffres (jamais invent é — vient
    # de l'upload du référentiel).
    commune: Mapped[str | None] = mapped_column(String, nullable=True)
    insee: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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


class LlmSettingsRow(Base):
    """Config LLM persistée (singleton id=1).

    `api_key_cipher` est un blob Fernet (base64). NE JAMAIS lu en clair
    hors de `app/services/llm_crypto.decrypt_key`. NE JAMAIS loggé.
    Précédence côté `/assistant` : DB > env (`BC4_LLM_*`).
    """

    __tablename__ = "settings_llm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="")
    base_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    model: Mapped[str] = mapped_column(String, nullable=False, default="")
    api_key_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 0.27.0 — Maîtrise des coûts
    # Modèle utilisé par la boucle agent (tool-calling répétitif).
    # Si NULL, fallback sur `model`. Permet d'affecter un modèle cher
    # (model) au probe/qualité et un modèle pas cher (model_loop) à
    # la boucle outils où la précision de rédaction est secondaire.
    model_loop: Mapped[str | None] = mapped_column(String, nullable=True)
    # Plafond journalier USD. NULL = pas de cap. Le moteur refuse
    # d'appeler le LLM dès que SUM(llm_usage.cost) du jour >= cap.
    daily_cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class LlmUsage(Base):
    """Journal d'appels LLM — tokens entrée/sortie + coût estimé (0.27.0).

    Alimente le plafond journalier (`settings_llm.daily_cap_usd`) et
    permet d'auditer la dépense agrégée par modèle / jour. Pas
    d'identité abonné (log de méta-usage, pas de contenu utilisateur).
    """

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # 0.45.0 — Dictionnaire v2 : enrichissement calculé au populate.
    param_key:         Mapped[str | None]  = mapped_column(Text,    nullable=True)
    display_name:      Mapped[str | None]  = mapped_column(String,  nullable=True)
    choice_of:         Mapped[str | None]  = mapped_column(String,  nullable=True)
    discriminators:    Mapped[dict | None] = mapped_column(JSON,    nullable=True)
    origin:            Mapped[str | None]  = mapped_column(String,  nullable=True)
    is_identifier:     Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    functional_group:  Mapped[str | None]  = mapped_column(String,  nullable=True)


class Skill(Base):
    """Skill déclaratif (Markdown + frontmatter YAML) stocké en base
    (0.38.0 — Skills Center).

    Le skill ne contient JAMAIS de code exécutable. Il est validé par
    ``app.services.skills.validate_skill`` avant toute activation.
    Historique : ``(slug, version)`` unique ; les anciennes versions
    du même slug restent en base (status=``archived``), jamais
    écrasées silencieusement.
    """

    __tablename__ = "skill"
    __table_args__ = (
        UniqueConstraint("slug", "version", name="uq_skill_slug_version"),
        Index("ix_skill_slug", "slug"),
        Index("ix_skill_status", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    triggers: Mapped[list] = mapped_column(JSON, nullable=False)
    tools_allowed: Mapped[list] = mapped_column(JSON, nullable=False)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    render: Mapped[list | None] = mapped_column(JSON, nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    # draft | validated | active | archived
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    validated_by: Mapped[str | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
