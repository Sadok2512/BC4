from typing import Literal

from pydantic import BaseModel

Role = Literal["admin", "editor", "viewer"]


class Actor(BaseModel):
    login: str
    role: Role


class User(BaseModel):
    id: str
    login: str
    display_name: str
    role: Role
    active: bool
    created_at: str
    last_login_at: str | None


class PasswordPolicy(BaseModel):
    min_length: int
    require_digit: bool
    require_upper: bool


class ApiPermissions(BaseModel):
    editor_can_edit_geo: bool
    editor_can_edit_kpi: bool


class UsersResponse(BaseModel):
    users: list[User]
    policy: PasswordPolicy
    permissions: ApiPermissions


class UserCreate(BaseModel):
    login: str
    display_name: str
    role: Role
    password: str
    password_confirm: str


class UserPatch(BaseModel):
    display_name: str | None = None
    role: Role | None = None
    active: bool | None = None


class GeoReference(BaseModel):
    id: str
    version: int
    filename: str
    imported_at: str
    author: str
    status: Literal["active", "archived"]
    rows: int


class GeoIssue(BaseModel):
    row: int | None
    level: Literal["error", "warning"]
    field: str | None
    message: str


class GeoImportPoint(BaseModel):
    site_id: str
    site: str
    lat: float
    lng: float


class GeoImportReport(BaseModel):
    total: int
    valid: int
    rejected: int
    warnings: int
    issues: list[GeoIssue]
    points: list[GeoImportPoint]
    committed: GeoReference | None


class GeoImportRequest(BaseModel):
    filename: str
    mapping: dict[str, str | None]
    rows: list[dict[str, str]]
    commit: bool


KpiStatus = Literal["draft", "validated", "published", "archived"]


class KpiHistoryEntry(BaseModel):
    version: int
    at: str
    author: str
    change: str


class Kpi(BaseModel):
    code: str
    name: str
    description: str
    family: str
    tech: str
    unit: str
    formula: str
    status: KpiStatus
    version: int
    source_events: list[str]
    history: list[KpiHistoryEntry]


class KpiCatalogResponse(BaseModel):
    items: list[Kpi]
    statuses: list[KpiStatus]
    formula_engine: None = None


class KpiInput(BaseModel):
    code: str
    name: str
    description: str
    family: str
    tech: str
    unit: str
    formula: str
    source_events: list[str]
    status: KpiStatus | None = None


class AiConnection(BaseModel):
    status: Literal["untested", "mock_ok", "mock_failed"]
    tested_at: str | None
    message: str | None
    simulated: Literal[True] = True


class AiConfig(BaseModel):
    enabled: bool
    endpoint_url: str
    model_code: str
    provider: str
    providers: list[str]
    auth_method: Literal["none", "api_key", "bearer"]
    has_secret: bool
    config_version: int
    saved_at: str | None
    connection: AiConnection


class AiConfigInput(BaseModel):
    enabled: bool
    endpoint_url: str
    model_code: str
    provider: str
    auth_method: Literal["none", "api_key", "bearer"]
    secret: str | None = None


class Appearance(BaseModel):
    org_primary_hex: str | None


class OrganizationLimits(BaseModel):
    name_max: int
    logo_max_bytes: int
    logo_types: list[str]


class Organization(BaseModel):
    name: str
    short_name: str
    description: str
    logo_data_url: str | None
    admin_contact: str
    domain: str
    show_in_header: bool
    show_in_exports: bool
    limits: OrganizationLimits


class OrganizationInput(BaseModel):
    name: str
    short_name: str
    description: str
    logo_data_url: str | None
    admin_contact: str
    domain: str
    show_in_header: bool
    show_in_exports: bool


class About(BaseModel):
    app_name: Literal["BC4"] = "BC4"
    version: str
    build_number: str | None
    build_date: str | None
    environment: Literal["mock", "development", "production"]
    api_contracts_version: str | None
    api_client_status: str
    organization: str | None
    license: str | None


class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    session: str
    profile: User
