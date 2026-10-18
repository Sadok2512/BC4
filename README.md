# bc4-back — Backend FastAPI (lot B0)

Backend qui sert, depuis PostgreSQL, exactement les contrats Zod lus dans
`franco-focus-forge/src/lib/api/*-schemas.ts`. Les volumes, projets de
démo, arbre RRC LTE+NR, règles de conversion 3GPP et catalogue KPI sont
peuplés par un seed idempotent.

Voir [CHANGELOG.md](./CHANGELOG.md) pour la liste des écarts ouverts.

## Démarrage rapide (docker-compose)

Depuis `/home/devmat/BC4` :

```bash
docker compose up --build
# puis, dans un autre terminal :
export BC4_API_BASE=http://localhost:8000
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
bc4-back/scripts/g1_boot.sh
```

- `db` : PostgreSQL + PostGIS sur `:5432`
- `api` : FastAPI sur `:8000` (migrations + seed au démarrage)
- `front` : `bun run dev` sur `:5173` (lit `VITE_API_BASE_URL`)

Le front doit afficher la même démo qu'avec le mock (parité de formes, pas
de valeurs numériques byte-identiques — voir CHANGELOG).

## Démarrage sans docker

```bash
# 1. Postgres local (image PostGIS si tu veux la préparer pour B1) :
docker run --name bc4-db -e POSTGRES_USER=bc4 -e POSTGRES_PASSWORD=bc4 \
  -e POSTGRES_DB=bc4 -p 5432:5432 -d postgis/postgis:16-3.4

# 2. Backend :
cd bc4-back
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
alembic upgrade head
python -m app.seed.run           # idempotent
uvicorn app.main:app --reload --port 8000
```

## Gardes (à lancer à la main)

Les gardes vérifient que le livrable tient. **Aucune CI** : chaque garde
crie si `BC4_DSN` ou `BC4_API_BASE` est absent.

```bash
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000

bc4-back/scripts/g1_boot.sh         # G1 : /health + migrations + boot
bc4-back/scripts/g2_parity.sh       # G2 : chaque endpoint = schéma Zod
bc4-back/scripts/g3_coverage.sh     # G3 : NR peuplé Paris / vide Rennes
bc4-back/scripts/g4_conversion.sh   # G4 : conversion_rule 3GPP conforme
bc4-back/scripts/g5_db_sourced.sh   # G5 : handlers sans littéraux + somme = DB
```

Lancer toutes les gardes d'un coup :

```bash
for g in bc4-back/scripts/g*_*.sh; do "$g" || exit 1; done
```

## Débrancher le mock du front

Le front lit `src/lib/api/*.ts` qui importent les fixtures. Pour taper
sur le back, exposez `VITE_API_BASE_URL=http://localhost:8000` et câblez
les adaptateurs `client.ts`/`dictionary.ts`/`assistant.ts`/`settings.ts`
sur `fetch(VITE_API_BASE_URL + path, …)`. Ce câblage côté front n'est
**pas** dans la portée de B0 (le lot B0 ne touche à aucun composant
front, voir le brief).

## Structure

```
bc4-back/
├── alembic/              # migrations (0001_initial)
├── app/
│   ├── config.py         # settings, DSN obligatoire (fail-fast)
│   ├── db.py             # engine SQLAlchemy
│   ├── deps.py           # extraction Actor via headers X-Actor-*
│   ├── main.py           # FastAPI app + CORS + /health
│   ├── models/           # SQLAlchemy 2 (users, projects, mp, dict_*, kpi_*, settings_*)
│   ├── routes/           # auth, projects, kpi, dictionary, assistant, settings
│   ├── schemas/          # Pydantic 1:1 avec Zod (common, dictionary, assistant, settings)
│   ├── services/         # overview, dict_service, filters
│   └── seed/             # fixtures_data.py + run.py idempotent
├── scripts/g*.sh         # gardes G1-G5 (shout si DSN manquant)
├── tests/test_g*.py      # pytest par garde
├── Dockerfile
├── alembic.ini
├── requirements.txt
└── CHANGELOG.md
```

## Ce que B0 **ne** fait **pas**

- Pas d'ingestion NMF (lot B1).
- Pas d'identité en base avec hashs/politique (lot B2).
- Pas de scénarios assistant complets.
- Pas de mutations admin lourdes (import géo, CRUD users, config IA).
- Ne touche à aucun composant du front.

### Imports NMF en arrière-plan

`POST /projects/{id}/nmf` sauvegarde les fichiers sur le volume `bc4_nmf_source`
et répond **202** avec un identifiant de lot. Il ne renvoie plus directement le
rapport final. Lire `GET /projects/{id}/imports/{job_id}` pour suivre les états
`queued`, `decoding`, `finalizing`, `done` ou `error`, les compteurs par fichier
et le rapport final. La liste des projets expose également `import_job`.

Démarrer le service `import-worker` avec l'API (`docker compose up -d --build
api import-worker`). Les lots et leur progression sont persistés en base. Après
un redémarrage, le worker reprend les lots interrompus ; les fichiers déjà
validés sont reconnus par leur SHA-256. Le worker sérialise les lots avec un
verrou PostgreSQL conservé pendant les commits. Un second import ou une
suppression du même projet est refusé tant que son lot est actif.

Le décodage ne recalcule plus les mesures après chaque fichier. Le dictionnaire
RRC et la chaîne de mesures sont calculés une seule fois à la fin du lot. Une
erreur de finalisation conserve les sources et marque le lot en échec ; elle
n'est pas présentée comme un succès. Les anciens imports synchrones interrompus
avant cette évolution doivent être renvoyés : les doublons déjà décodés sont
réutilisés.
