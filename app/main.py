import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.routes import (
    assistant,
    auth,
    dictionary,
    kpi,
    measurements,
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

app = FastAPI(title="bc4-back", version="0.42.0")

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
def health() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "env": settings.env, "version": "0.42.0"}


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(project_kpi.router)
app.include_router(kpi.router)
app.include_router(dictionary.router)
app.include_router(assistant.router)
app.include_router(settings_routes.router)
app.include_router(settings_skills.router)
app.include_router(settings_cell_ref.router)
app.include_router(reference.router)
app.include_router(measurements.router)
