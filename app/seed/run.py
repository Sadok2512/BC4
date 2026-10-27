"""Idempotent seed. Safe to run many times — upsert by natural key.

Usage:
    python -m app.seed.run

Shouts if DSN is missing (handled by config.py's required field).
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal, engine
from app.models import (
    AiConfigRow,
    ApiPermissionsRow,
    AppearanceRow,
    AppUser,
    ConversionRule,
    DictMessage,
    DictParam,
    ExecStepRow,
    GeoReference,
    KpiCatalogGroup,
    KpiCatalogItem,
    KpiRrcSummary,
    MeasurementPoint,
    OrganizationRow,
    PasswordPolicyRow,
    Project,
    RrcObservation,
    User,
)
from app.services.auth import hash_password
from app.seed.fixtures_data import (
    AI_CONFIG,
    ASSISTANT_EXEC_STEPS,
    DICT_MESSAGES,
    DICT_PARAMS,
    GEO_REFERENCES,
    KPI_GROUPS,
    KPI_ITEMS,
    KPI_RRC_SUMMARY,
    OP_BIAS,
    ORG_DEFAULT,
    PROJECTS,
    USERS,
)


def _project_seed(project_id: str) -> int:
    """Reproduce the TS seed = sum of char codes."""
    return sum(ord(c) for c in project_id)


def _generate_points(project: dict) -> list[dict]:
    """Mirror pointsFor() from fixtures.ts (same shape, same volume)."""
    if project["status"] == "processing":
        return []
    r = random.Random(_project_seed(project["id"]))
    n = min(900, project["captures"])
    start = datetime.fromisoformat(project["periodStart"]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(project["periodEnd"]).replace(tzinfo=timezone.utc)
    days = max(1, (end - start).days + 1)
    lte_bands = [b for b in project["bands"] if not b.startswith("n")]
    nr_bands = [b for b in project["bands"] if b.startswith("n")]
    points: list[dict] = []
    for i in range(n):
        operator = r.choice(project["operators"])
        tech = r.choice(project["technologies"])
        service = r.choice(project["services"])
        pool = lte_bands if tech == "LTE" else (nr_bands or lte_bands)
        band = r.choice(pool)
        dep = r.choice(project["departements"])
        dx = (r.random() - 0.5) * 0.28
        dy = (r.random() - 0.5) * 0.16
        weak = 0.45 if dx > 0.06 and dy > 0.03 else 1.0
        bias = OP_BIAS[operator] * weak
        tech_mul = 1.0 if tech == "LTE" else 3.2 if tech == "NR" else 2.4
        miss = r.random()
        day = int(r.random() * days)
        ts = (start.timestamp() + day * 86400 + r.random() * 86400)
        ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        points.append(
            {
                "id": f"{project['id']}-{i}",
                "project_id": project["id"],
                "lat": project["center"][1] + dy,
                "lng": project["center"][0] + dx,
                "operator": operator,
                "tech": tech,
                "service": service,
                "band": band,
                "dep": dep,
                "site": f"S{dep}-{int(r.random() * 40):03d}",
                "ts": ts_iso,
                "dl": None if miss < 0.04 else round(max(0.5, (20 + r.random() * 60) * tech_mul * bias), 1),
                "rsrp": None if miss > 0.97 else round(-118 + r.random() * 40 * min(1.0, bias), 1),
                "sinr": None if miss > 0.95 else round(-3 + r.random() * 26 * min(1.0, bias), 1),
                "latency": None if service == "SMS" else round(18 + (r.random() * 40) / bias),
                "capture_id": project["id"],
                "seq": i,
            }
        )
    return points


def _weighted_pick(r: random.Random, values: list[str], weights: list[int]) -> str:
    total = sum(weights)
    x = r.random() * total
    cumul = 0
    for v, w in zip(values, weights):
        cumul += w
        if x < cumul:
            return v
    return values[-1]


def _generate_observations(project: dict, params: list[dict]) -> list[dict]:
    """Per-project observations. Branch count = 0 for techs not in project."""
    r = random.Random(_project_seed(project["id"]) * 31 + 7)
    out: list[dict] = []
    for p in params:
        msg = next(m for m in DICT_MESSAGES if m["msg_id"] == p["msg_id"])
        if msg["techno"] == "NR" and "NR" not in project["technologies"]:
            continue
        if msg["techno"] == "LTE" and "LTE" not in project["technologies"]:
            continue
        samples = p["samples"]
        for seq in range(samples):
            operator = r.choice(project["operators"])
            if msg["techno"] == "LTE":
                pool = [b for b in project["bands"] if not b.startswith("n")]
            else:
                pool = [b for b in project["bands"] if b.startswith("n")] or project["bands"]
            band = r.choice(pool)
            service = r.choice(project["services"])
            dep = r.choice(project["departements"])
            lat: float | None = None
            lng: float | None = None
            if p["has_gps"] and r.random() > 0.04:
                lat = project["center"][1] + (r.random() - 0.5) * 0.16
                lng = project["center"][0] + (r.random() - 0.5) * 0.28
            raw_num: float | None = None
            raw_str: str | None = None
            if p["spec_kind"] == "numeric":
                center = p["spec"]["center"].get(operator, p["spec"]["center"]["Orange"])
                spread = p["spec"]["spread"]
                low, high = p["spec"]["range"]
                v = center + (r.random() - 0.5) * 2 * spread
                v = max(low, min(high, v))
                raw_num = round(v)
            else:
                weights = p["spec"]["weights"].get(operator, p["spec"]["weights"]["Orange"])
                raw_str = _weighted_pick(r, p["spec"]["values"], weights)
            out.append(
                {
                    "project_id": project["id"],
                    "param_id": p["param_id"],
                    "operator": operator,
                    "band": band,
                    "service": service,
                    "dep": dep,
                    "raw_num": raw_num,
                    "raw_str": raw_str,
                    "lat": lat,
                    "lng": lng,
                    "capture_id": project["id"],
                    "seq": seq,
                }
            )
    return out


def seed() -> None:
    # Ownership is mandatory from 0057 onward. Seed the configured admin first
    # so optional demo projects can reference a real owner. With demo enabled,
    # missing admin credentials are a hard error instead of creating ownerless
    # projects or silently skipping the ownership contract.
    _seed_admin_from_env()
    demo_owner_id: str | None = None
    if settings.seed_demo:
        admin_email = (settings.admin_email or "").strip().lower()
        if not admin_email:
            raise RuntimeError("BC4_SEED_DEMO=1 requires BC4_ADMIN_EMAIL and BC4_ADMIN_PASSWORD")
        with SessionLocal() as owner_db:
            demo_owner_id = owner_db.execute(
                select(AppUser.id).where(AppUser.email == admin_email)
            ).scalar_one_or_none()
        if demo_owner_id is None:
            raise RuntimeError("BC4_SEED_DEMO=1 requires a successfully seeded admin owner")

    with SessionLocal() as db:
        # ----- Settings singletons -----
        for Row, defaults in (
            (AppearanceRow, {"id": 1, "org_primary_hex": None}),
            (
                OrganizationRow,
                {
                    "id": 1,
                    "name": "",
                    "short_name": "",
                    "description": "",
                    "logo_data_url": None,
                    "admin_contact": "",
                    "domain": "",
                    "show_in_header": True,
                    "show_in_exports": True,
                    "name_max": ORG_DEFAULT["limits"]["name_max"],
                    "logo_max_bytes": ORG_DEFAULT["limits"]["logo_max_bytes"],
                    "logo_types": ORG_DEFAULT["limits"]["logo_types"],
                },
            ),
            (PasswordPolicyRow, {"id": 1, "min_length": 10, "require_digit": True, "require_upper": True}),
            (ApiPermissionsRow, {"id": 1, "editor_can_edit_geo": True, "editor_can_edit_kpi": False}),
            (AiConfigRow, {"id": 1, **AI_CONFIG}),
        ):
            stmt = pg_insert(Row).values(**defaults)
            stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
            db.execute(stmt)

        # ----- Users (dépréciée) : gatée derrière BC4_SEED_DEMO ------
        # 0.89.4 — la table `users` est dépréciée (vs `app_user`) mais garde
        # le seed historique de 85 lignes de fixtures démo. On ne pose plus
        # rien par défaut : jamais d'identité inventée dans la base.
        if settings.seed_demo:
            for u in USERS:
                row = {
                    **u,
                    "created_at": datetime.fromisoformat(u["created_at"].replace("Z", "+00:00")),
                    "last_login_at": (
                        datetime.fromisoformat(u["last_login_at"].replace("Z", "+00:00"))
                        if u["last_login_at"]
                        else None
                    ),
                }
                stmt = pg_insert(User).values(**row).on_conflict_do_update(
                    index_elements=["id"],
                    set_={k: row[k] for k in ("login", "display_name", "role", "active", "last_login_at")},
                )
                db.execute(stmt)

        # ----- Assistant exec steps -----
        for step in ASSISTANT_EXEC_STEPS:
            stmt = pg_insert(ExecStepRow).values(**step).on_conflict_do_update(
                index_elements=["id"],
                set_={k: step[k] for k in step if k != "id"},
            )
            db.execute(stmt)

        # ----- Geo references -----
        for g in GEO_REFERENCES:
            stmt = pg_insert(GeoReference).values(**g).on_conflict_do_nothing(index_elements=["id"])
            db.execute(stmt)

        # ----- KPI catalog -----
        for item in KPI_ITEMS:
            stmt = pg_insert(KpiCatalogItem).values(**item).on_conflict_do_update(
                index_elements=["code"],
                set_={k: item[k] for k in item if k != "code"},
            )
            db.execute(stmt)

        for pos, (group_name, items) in enumerate(KPI_GROUPS):
            stmt = pg_insert(KpiCatalogGroup).values(name=group_name, items=items, position=pos)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"], set_={"items": items, "position": pos}
            )
            db.execute(stmt)

        stmt = pg_insert(KpiRrcSummary).values(id=1, **KPI_RRC_SUMMARY).on_conflict_do_update(
            index_elements=["id"], set_={k: KPI_RRC_SUMMARY[k] for k in KPI_RRC_SUMMARY}
        )
        db.execute(stmt)

        # ----- Projects (démo) : gatée derrière BC4_SEED_DEMO ------
        # 0.89.4 — zéro projet démo par défaut. Codex67 crée ses projets
        # via l'UI (POST /projects) ou via upload NMF.
        if settings.seed_demo:
            for p in PROJECTS:
                row = {
                    "id": p["id"],
                    "owner_id": demo_owner_id,
                    "visibility": "public",
                    "name": p["name"],
                    "geography": p["geography"],
                    "center_lng": p["center"][0],
                    "center_lat": p["center"][1],
                    "operators": p["operators"],
                    "technologies": p["technologies"],
                    "services": p["services"],
                    "bands": p["bands"],
                    "departements": p["departements"],
                    "period_start": p["periodStart"],
                    "period_end": p["periodEnd"],
                    "captures": p["captures"],
                    "imported_at": p["importedAt"],
                    "status": p["status"],
                }
                stmt = pg_insert(Project).values(**row).on_conflict_do_update(
                    index_elements=["id"],
                    set_={k: row[k] for k in row if k != "id"},
                )
                db.execute(stmt)

        # ----- Dict messages / params / conversion_rule -----
        for m in DICT_MESSAGES:
            stmt = pg_insert(DictMessage).values(**m).on_conflict_do_update(
                index_elements=["msg_id"],
                set_={k: m[k] for k in m if k != "msg_id"},
            )
            db.execute(stmt)

        for p in DICT_PARAMS:
            row = {k: p[k] for k in ("param_id", "msg_id", "path", "leaf", "type", "has_gps", "simulate_error", "spec_kind", "spec")}
            stmt = pg_insert(DictParam).values(**row).on_conflict_do_update(
                index_elements=["param_id"],
                set_={k: row[k] for k in row if k != "param_id"},
            )
            db.execute(stmt)
            if p["conversion_rule"]:
                cr_row = {"param_id": p["param_id"], **p["conversion_rule"]}
                stmt = pg_insert(ConversionRule).values(**cr_row).on_conflict_do_update(
                    index_elements=["param_id"],
                    set_={k: cr_row[k] for k in cr_row if k != "param_id"},
                )
                db.execute(stmt)

        db.commit()

        # ----- Measurement points & RRC observations : démo gaté ------
        # 0.89.4 — données générées par fixtures ne sont posées que si
        # BC4_SEED_DEMO=1. Jamais inventées sinon : les vrais points
        # viennent des uploads NMF.
        if settings.seed_demo:
            for p in PROJECTS:
                db.execute(delete(MeasurementPoint).where(MeasurementPoint.project_id == p["id"]))
                pts = _generate_points(p)
                if pts:
                    db.execute(MeasurementPoint.__table__.insert(), pts)
            db.commit()

            for p in PROJECTS:
                db.execute(delete(RrcObservation).where(RrcObservation.project_id == p["id"]))
                obs = _generate_observations(p, DICT_PARAMS)
                if obs:
                    db.execute(RrcObservation.__table__.insert(), obs)
            db.commit()

    _seed_demo_from_env()

    print("[seed] done.")


def _seed_admin_from_env() -> None:
    """Admin B2 : idempotent sur `email`. Si BC4_ADMIN_EMAIL/PASSWORD manque,
    crie et saute — un garde silencieux ne garde rien. Mot de passe hashé
    argon2, jamais stocké en clair ni loggé."""
    email = (settings.admin_email or "").strip().lower()
    password = settings.admin_password or ""
    if not email or not password:
        print("[seed] BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquant — admin non seedé (écart déclaré)")
        return
    with SessionLocal() as db:
        existing = db.query(AppUser).filter(AppUser.email == email).one_or_none()
        if existing:
            print(f"[seed] admin {email} déjà présent (idempotent)")
            return
        user = AppUser(
            id=f"adm-{uuid.uuid4().hex[:12]}",
            email=email,
            password_hash=hash_password(password),
            role="admin",
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        print(f"[seed] admin {email} créé (role=admin)")


def _seed_demo_from_env() -> None:
    """Démo P1-1 : idempotent sur `email`. Si BC4_DEMO_EMAIL/PASSWORD
    manque, le seed démo est sauté (jamais demo/demo en dur).
    Rôle par défaut `ingenieur` ; override via BC4_DEMO_ROLE ∈
    {admin, ingenieur, lecteur}. Même règles que admin : argon2id,
    pas de clair en log."""
    email = (settings.demo_email or "").strip().lower()
    password = settings.demo_password or ""
    role = (settings.demo_role or "ingenieur").strip().lower()
    if not email or not password:
        print("[seed] BC4_DEMO_EMAIL/BC4_DEMO_PASSWORD manquant — démo non seedée (optionnel)")
        return
    if role not in {"admin", "ingenieur", "lecteur"}:
        print(f"[seed] BC4_DEMO_ROLE={role!r} invalide (admin|ingenieur|lecteur) — démo non seedée")
        return
    with SessionLocal() as db:
        existing = db.query(AppUser).filter(AppUser.email == email).one_or_none()
        if existing:
            print(f"[seed] démo {email} déjà présent (idempotent)")
            return
        user = AppUser(
            id=f"demo-{uuid.uuid4().hex[:12]}",
            email=email,
            password_hash=hash_password(password),
            role=role,
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        print(f"[seed] démo {email} créé (role={role})")


if __name__ == "__main__":
    seed()
