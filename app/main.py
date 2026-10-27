import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.routes import (
    assistant,
    auth,
    dict_identity,
    dictionary,
    kpi,
    measurements,
    project_dict_v2,
    project_kpi,
    projects,
    reference,
    settings as settings_routes,
    settings_cell_ref,
    settings_skills,
)

# 0.34.1 — Logger `app.*` au niveau INFO par défaut. Nécessaire pour que
# `intent_llm` publie son `path=llm | fallback-*` dans `docker logs`
# (sans ça, le niveau effectif racine reste WARNING et on perd la
# preuve du chemin pris par l'extracteur d'intention).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logging.getLogger("app").setLevel(logging.INFO)

app = FastAPI(title="bc4-back", version="0.89.0")

# CORS (B2 / P1-1) : origines PILOTÉES par `BC4_CORS_ORIGINS` (jamais en
# dur), méthodes/en-têtes explicites pour les uploads multipart
# (cell_ref 128 Mo, NMF). `allow_credentials=True` est nécessaire pour
# que le navigateur envoie `Authorization: Bearer` sur les requêtes
# cross-origin ; avec Starlette, l'étoile `allow_methods=["*"]` est
# correctement traduite en liste explicite dans la réponse preflight.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=600,
)


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    from app.nmf_decoder import DECODER_VERSION
    # 2.52.0 — GC1 au démarrage : fichier catalog_<v>.json présent ET
    # sha256 disque == catalog_release.sha256 en DB. Un mismatch dégrade
    # /health avec reason explicite. Jamais de régénération silencieuse.
    from app.db import SessionLocal
    from app.kpi.catalog_release.registry import gc1_check
    db = SessionLocal()
    try:
        gc1 = gc1_check(db)
    finally:
        db.close()
    status = "ok" if gc1["status"] == "ok" else "degraded"
    return {
        "status": status,
        "env": settings.env,
        "version": "0.89.0",
        "decoder_version": DECODER_VERSION,
        "catalog": gc1,
    }


# 0.74.3 (C) — Warm /kpi/catalog cache au démarrage. Au lieu de laisser le
# premier user payer 60s cold, on pré-chauffe en background pour chaque
# projet connu. Non bloquant : si la query échoue, log + skip.
def _warm_kpi_catalog():
    import threading
    from app.db import SessionLocal
    from app.kpi.catalog_cache import catalog_cache
    from app.kpi.service_v2 import build_catalog_v2_response

    def worker():
        try:
            with SessionLocal() as db:
                projects = db.execute(text("SELECT id FROM projects")).scalars().all()
            for pid in projects:
                try:
                    with SessionLocal() as db:
                        catalog_cache.get((pid, ()), lambda: build_catalog_v2_response(db, pid, services=()))
                        logging.getLogger("app.warmup").info("warm /kpi/catalog pid=%s OK", pid)
                except Exception as e:
                    logging.getLogger("app.warmup").warning("warm pid=%s failed: %s", pid, e)
        except Exception as e:
            logging.getLogger("app.warmup").warning("warm skipped: %s", e)

    threading.Thread(target=worker, name="kpi-catalog-warm", daemon=True).start()


@app.on_event("startup")
def _startup_warm():
    _warm_kpi_catalog()


app.include_router(auth.router)
app.include_router(projects.router)
from app.routes import tasks, metrics, metrics_v3, capture_sheet, file_summary
app.include_router(tasks.router)
app.include_router(file_summary.router)
app.include_router(metrics.router)
app.include_router(metrics_v3.router)
app.include_router(capture_sheet.router)
app.include_router(project_kpi.router)
app.include_router(kpi.router)
app.include_router(dictionary.router)
app.include_router(dict_identity.router)
app.include_router(project_dict_v2.router)
app.include_router(assistant.router)
app.include_router(settings_routes.router)
app.include_router(settings_skills.router)
app.include_router(settings_cell_ref.router)
app.include_router(reference.router)
app.include_router(measurements.router)

from app.routes import settings_dict_templates
app.include_router(settings_dict_templates.router)

from app.routes import kpi_timeseries
app.include_router(kpi_timeseries.router)



from app.routes import nmf_decode
app.include_router(nmf_decode.router)

from app.routes import signaling
app.include_router(signaling.router)

# 0.78.2 — Site layer map (SA1) : /sites?bbox=... lazy par bbox.
from app.routes import sites as sites_route
app.include_router(sites_route.router)
