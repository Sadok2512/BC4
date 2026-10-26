# HANDOFF — Catalog versioning déterministe (0.82.4, 2026-10-26)

## Pourquoi le sha changeait

Trois sha différents observés sur le même catalog "2.51.0" :

| Build | sha256 | Cause |
|---|---|---|
| 8dc4bcf8… | catalog_2.51.0.json (initial) | `generated_at` = timestamp build 1 |
| 5a3a75dd… | re-build après rebuild image | `generated_at` = timestamp build 2 |
| b1bed98b… | post uniqueids postprocessor | contenu réellement différent (uniqueids appliqués) |

**Non-déterminisme identifié** :
1. `generated_at` (ISO timestamp) — change à chaque build.
2. `source_csv`, `source_txt` — chemins absolus (`/specs/…` dans container
   vs `/tmp/nff250/…` sur l'host).
3. Lecture `corpus_cell_types(db)` — fonction D du pipeline. Dépend
   de l'état DB (quelles captures en 1.7.1, quelles cell_types observées
   dans `nmf_event_light_group`). Dans le JSON initial, les feuilles
   avec cell_type non-observé étaient `displayed=False`. Ça varie entre
   environnements.

## Fix — déterminisme garanti

1. **`generated_at`, `source_csv`, `source_txt`** → sortis du JSON
   versionné, écrits dans un fichier sidecar `<out>.meta.json` à côté
   (utile pour debug, non committé dans l'image).
2. **Lecture DB `corpus_cell_types()`** → SUPPRIMÉE du build. Toutes
   les 7 feuilles canoniques @cell_type sont `displayed=True` dans le
   JSON. Le filtre selectable/grisé est produit RUNTIME par
   `app/kpi/metrics_catalog_v4.py` depuis `nmf_event_light_group.cell_type`.
3. **Preuve** : 2 builds consécutifs du script, mêmes entrées, même
   sha : `baaddbbc00e96075e844891350631a81e0b37eec7ec842497f1f78408b3060ec`.

Entrées du build :
- `scripts/catalog/categories.yaml` (committé)
- `/specs/nmf_all_events_fields_2.50.csv` (spec externe stable)
- `/specs/nemo_file_format_2.50.txt` (spec externe stable)
- `app/nmf_decoder/schemas/*.yaml` (committés — source de `source_column`)

## catalog_release.sha256 contrat

- `app/kpi/catalog_release/catalog_<version>.json` committé dans
  bc4-back/.
- `Dockerfile` `COPY . /app` embarque dans l'image bc4-api:latest.
- `catalog_release.sha256` DB = `sha256(catalog_<version>.json)` disque.
- **Jamais régénéré au runtime**. Seul `scripts/catalog/build_catalog.py
  --commit` touche la ligne `catalog_release`.

## GC1 au démarrage via /health

`app/kpi/catalog_release/registry.py:gc1_check(db)` :

```python
status ∈ {"ok", "no_current", "missing", "sha_mismatch"}
```

- `ok` : fichier existe + sha disque == `catalog_release.sha256` DB.
- `no_current` : table `catalog_release` vide (bootstrap frais).
- `missing` : row `is_current` existe mais fichier absent disque
  (image corrompue, release non committé).
- `sha_mismatch` : fichier existe mais sha ne colle pas DB → le JSON
  a été altéré après commit DB (hot-fix non reproductible, image
  divergeante). FAIL closed.

`/health` renvoie :
```json
{
  "status": "ok" | "degraded",
  "env": "...",
  "version": "0.82.4",
  "decoder_version": "1.7.1",
  "catalog": {
    "status": "ok" | "no_current" | "missing" | "sha_mismatch",
    "catalog_version": "2.51.1",
    "disk_sha": "...",
    "db_sha": "...",
    "reason": null | "..."
  }
}
```

Un mismatch dégrade `/health` → monitoring côté infra (Grafana, alerting
HTTP) voit `status=degraded` et peut router l'intervention.

## Inventaire des autres artefacts générés dans le conteneur

| Artefact | Chemin container | Politique |
|---|---|---|
| **Catalog JSON** | `/app/app/kpi/catalog_release/catalog_<v>.json` | **COMMITÉ bc4-back/**. GC1 vérifie sha au démarrage. |
| **Catalog sidecar meta** | `/app/app/kpi/catalog_release/catalog_<v>.json.meta.json` | Non commité. Généré par `--commit` quand on bump. Debug uniquement. |
| **Decoder YAMLs** `schemas/*.yaml` | `/app/app/nmf_decoder/schemas/*.yaml` | **COMMITÉ bc4-back/**. Chaque suppression/ajout commité (ex 86 2.50 partiels supprimés dans lot nuit). |
| **Decoder YAMLs 2.50 overrides** `schemas-2.50/*.yaml` | `/app/app/nmf_decoder/schemas-2.50/*.yaml` | **COMMITÉ bc4-back/** (193 fichiers après nettoyage lot nuit). |
| **Decoder corpus events scope** `corpus_events_2_2a.txt` | `/app/app/nmf_decoder/corpus_events_2_2a.txt` | **COMMITÉ**. |
| **Specs externes** | `/specs/nmf_all_events_fields_2.50.csv`, `/specs/nemo_file_format_2.50.txt` | **NON COMMITÉ** — specs tierces, copiées à la main dans l'image lors des builds catalog. Scope lot ultérieur : les committer dans `bc4-back/specs/` et les charger via chemin relatif. |
| **Metrics catalog cache** (DB) | `metrics_catalog_cache` | RUNTIME. Reconstruit à la 1re requête `/metrics` après `TRUNCATE`. G18b valide la parité cache↔fresh. |
| **Range violations** (DB) | `range_violations` | RUNTIME. Alimenté par `redecode_corpus.py`. Sha non pertinent (données observationnelles). |
| **Alembic versions** | `/app/alembic/versions/*.py` | **COMMITÉ**. Linear history. |
| **Alembic version row** (DB) | `alembic_version.version_num` | RUNTIME. Mise à jour par `alembic upgrade head` au startup. |
| **catalog_release row** (DB) | `catalog_release` | Posé explicitement par `build_catalog.py --commit`. Jamais touché runtime hors GC1 report. |
| **nmf_event_light etc.** (DB) | Tables de données | RUNTIME. Alimentées par `redecode_corpus.py` ou ingestion. Pas d'invariant sha. |

Les artefacts GÉNÉRÉS runtime sans sha vérifié sont de la DATA
(observations décodées, caches dérivés), pas du CODE. Le CODE
(catalog JSON, YAMLs, scripts) est systématiquement committé.

## Preuves livrables

- `/health` post-rebuild (0.82.4) : `status="ok"`, `catalog.status="ok"`,
  `catalog_version="2.51.1"`, `disk_sha == db_sha ==
  baaddbbc00e96075e844891350631a81e0b37eec7ec842497f1f78408b3060ec`.
- GC1 forcé en mismatch (test manuel sed sur le JSON) :
  `catalog.status="sha_mismatch"`, `/health status="degraded"`.
  (test optionnel, non commité automatiquement).

— Agent BC3
