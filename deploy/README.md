# bc4-back/deploy — docker-compose + fichiers d'infra

Ce dossier versionne l'orchestration locale BC4 (db + api + import-worker +
proxy front production). Le fichier `docker-compose.yml` est symliné depuis
`/home/devmat/BC4/docker-compose.yml` pour conserver le chemin
historique de `docker compose`.

## Services

| Service | Image | Bind host |
|---|---|---|
| `db` | `postgis/postgis:16-3.4` | `127.0.0.1:5432` |
| `api` | `bc4-api:latest` (build `./bc4-back`) | `127.0.0.1:8000` |
| `import-worker` | `bc4-api:latest` | — (interne) |
| `front` | `bc4-front-v2:<version>` (build `./franco-focus-forge/Dockerfile.v2`) | `0.0.0.0:5174` |

Depuis le durcissement 2026-10-27 : **db et api ne sont PLUS exposés sur
l'IP publique**. Le navigateur atteint le back via le proxy same-origin
`http://<host>:5174/api/*` qui est forwardé par Nitro vers
`http://api:8000` sur le réseau Docker interne.

## Variables `.env` requises (chmod 600, hors git)

Le compose exige explicitement ces variables (défaut forcé à `?required`
pour fail-fast au démarrage) :

| Variable | Rôle |
|---|---|
| `POSTGRES_PASSWORD` | Mot de passe PG du rôle `bc4` (généré via `secrets.token_urlsafe(32)`). |
| `BC4_PGPW` | Même valeur que `POSTGRES_PASSWORD`, utilisée dans la construction de `BC4_DSN`. |
| `BC4_JWT_SECRET` | Secret JWT (généré via `secrets.token_urlsafe(64)`). |

Variables optionnelles (défauts fournis) :

| Variable | Défaut compose |
|---|---|
| `BC4_CORS_ORIGINS` | liste des origins autorisés (localhost + lovable) |
| `BC4_JWT_TTL_MIN` | 60 min |
| `BC4_ADMIN_EMAIL` / `BC4_ADMIN_PASSWORD` | admin seedé au premier `app.seed.run` |
| `BC4_DEMO_EMAIL` / `BC4_DEMO_PASSWORD` / `BC4_DEMO_ROLE` | compte démo (vide par défaut) |
| `BC4_LLM_SECRET_KEY` | clé Fernet pour chiffrer `settings_llm.api_key_cipher` |
| `BC4_SEED_DEMO` | 0 par défaut (0.89.4+) ; mettre `1` pour seed démo complet |

Voir `deploy/.env.example` pour un modèle (valeurs factices).

## Rotation des secrets

### Rotation `POSTGRES_PASSWORD` + `BC4_PGPW`

```bash
# Génère sans jamais afficher la valeur en clair
NEW_PGPW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
# ALTER ROLE via psql -v (interpolation sûre)
printf '%s\n' "ALTER ROLE bc4 WITH PASSWORD :'pw';" | \
  docker exec -i bc4-db-1 psql -v ON_ERROR_STOP=1 -U bc4 -d postgres -v pw="$NEW_PGPW"
# Écrire dans .env (chmod 600)
umask 077
grep -v "^POSTGRES_PASSWORD=\|^BC4_PGPW=" /home/devmat/BC4/.env > /tmp/.env.new
echo "POSTGRES_PASSWORD=$NEW_PGPW" >> /tmp/.env.new
echo "BC4_PGPW=$NEW_PGPW" >> /tmp/.env.new
mv /tmp/.env.new /home/devmat/BC4/.env
chmod 600 /home/devmat/BC4/.env
unset NEW_PGPW
# docker compose up -d api import-worker  # recharge BC4_DSN
```

### Rotation `BC4_JWT_SECRET`

Rotater le JWT invalide toutes les sessions utilisateur en cours — à
communiquer avant.

```bash
NEW_JWT="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
umask 077
grep -v "^BC4_JWT_SECRET=" /home/devmat/BC4/.env > /tmp/.env.new
echo "BC4_JWT_SECRET=$NEW_JWT" >> /tmp/.env.new
mv /tmp/.env.new /home/devmat/BC4/.env
chmod 600 /home/devmat/BC4/.env
unset NEW_JWT
docker compose up -d api import-worker
```

## Rebuild + redémarrage

```bash
# Back
docker compose build api
docker tag bc4-api:latest bc4-api:<version>
docker compose up -d api import-worker

# Front (image production Nitro)
cd /home/devmat/BC4/franco-focus-forge
docker build -f Dockerfile.v2 -t bc4-front-v2:<version> -t bc4-front-v2:latest \
  --build-arg VCS_REF=$(git rev-parse main) --build-arg APP_VERSION=<version> .
cd /home/devmat/BC4
docker compose up -d front
```

## Debug db / api depuis l'hôte

Les ports sont bindés localhost — pour debug depuis l'extérieur, utiliser
un tunnel SSH :

```bash
# depuis le PC distant
ssh -L 5432:127.0.0.1:5432 devmat@<host>   # psql
ssh -L 8000:127.0.0.1:8000 devmat@<host>   # curl API direct
```
