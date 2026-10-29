# STOP — pas de voie de suppression par capture dans l'application

Opération : Test_5 (`d8d14aefa51f`) — réduire à 3 captures (`a4b0c321c52e`, `ecffb18dbd7f`, `daa2b1df250d`), supprimer les 21 autres.

Décision : **STOP**. Conformément à la règle du prompt BC3 (« S'il n'existe pas : STOP, et propose le service — pas de DELETE SQL à la main »), aucune suppression n'a été exécutée. Prérequis G36, witness-nmf 3/3 et services up ont été validés en amont (voir plus bas).

Agent : Claude Opus 4.7 (BC4 ops) · session 2026-10-29 · décideur BC3.

---

## Ce qui existe dans bc4-back (`a998fe7`)

| # | Chemin | Portée | Verdict |
|---|---|---|---|
| 1 | `app/routes/projects.py:259` — `DELETE /projects/{project_id}` → `delete_project()` | **Projet entier**, cascade FK DB | ❌ supprime tout, pas 21/24 |
| 2 | `app/scripts/reparse_capture.py` | Re-parse d'UNE capture, `decode_capture(force=True)` ; `nmf_capture` conservé | ❌ ne supprime pas la capture |
| 3 | `scripts/catalog/redecode_corpus.py:33` — `purge_capture(db, pid, cap)` | Purge replay-only : `nmf_cell_second`, `nmf_event_light`, `nmf_event_light_ext`, `nmf_event_group`, `nmf_event_deep` | ❌ laisse `nmf_capture`, `stg_event`, `stg_event_raw`, `param_occurrence`, `nmf_event_light_group`, `nmf_event_pair`, partitions `nmf_deep_<cap>` / `nmf_group_<cap>`, `nmf_metric_value`, `metric_sample`, `measurement_points`, `rrc_observations`, `signaling_procedure`, `task_run`, `range_violations`, `superstream_member` |
| 4 | `app/nmf_decoder/store.py` — DELETE par capture internes à `decode_capture` / `write_light` | Purge-avant-réinsertion uniquement pendant un décodage | ❌ pas un service |

**Aucune** route `DELETE /projects/{pid}/captures/{cap}`, **aucun** service `delete_capture()` dans `app/services/`, **aucun** script `app/scripts/*` à portée « supprimer la capture ». `grep -rn "@router\.delete" app/routes/` = 4 résultats, aucun sur une capture.

Tables scoppées par `capture_id` (inventaire DB) :

- `nmf_capture`
- `nmf_cell_second`, `nmf_event_light`, `nmf_event_light_ext`, `nmf_event_light_group`
- `nmf_event_deep`, `nmf_event_group`, `nmf_event_pair`
- partitions dédiées `nmf_deep_<capture_id>` et `nmf_group_<capture_id>` (créées par `nmf_decoder_partition(:cap)`)
- `stg_event`, `stg_event_raw`, `stg_measurement_raw`
- `measurement_points`, `metric_sample`, `nmf_metric_value`
- `range_violations`, `rrc_observations`, `signaling_procedure`
- `task_run`, `superstream_member`

Chaîne cascade indirecte :

- `param_occurrence.stg_event_id → stg_event.id ON DELETE CASCADE` (requête FK vérifiée)
- `nmf_file` reste orphelin si aucune autre capture ne le référence (`nmf_capture.nmf_file_id` est la seule FK retrouvée en lecture `/openapi.json` + schéma).

Agrégats de projet à **recalculer** après suppression (via `app/services/populate_chain.py:132` `run_populate_chain`, étapes A→F documentées lignes 35–129) :

- A `populate_measurements(purge=True)`
- B `populate_measurement_points`
- C `populate_ecgi_for_project`
- D `populate_tasks`
- E `populate_metric_samples`
- F UPDATE `projects.last_populate_at, n_points`
- + mise à jour `project.n_captures_ingest`, `project.status_ingest` (via `app/services/import_worker.py:279`)

---

## Service proposé (à implémenter par BC1 ou BC2, pas par ops ad hoc)

**Route** : `DELETE /projects/{project_id}/captures/{capture_id}` → 204, header-locked `DEPLOY_LOCK`.

**Service** : `app/services/capture_delete.py::delete_capture(db, project_id, capture_id, *, reason: str)`.

Contrat :

1. Advisory lock worker (`SELECT pg_try_advisory_lock(LOCK_ID)` comme `reparse_capture.py`) ; refuse si worker actif.
2. Lock advisory session projet : `SELECT pg_advisory_xact_lock(hashtext('populate:'+pid))` (même clé que `decode_capture`).
3. Snapshot before : `SELECT * FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap` → journalisé.
4. Suppressions **dans cet ordre** (une transaction) :
   - `DELETE FROM task_run WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM superstream_member WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM signaling_procedure WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM rrc_observations WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM measurement_points WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM metric_sample WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_metric_value WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM range_violations WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_event_pair WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_event_light_group WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_event_light_ext WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_event_light WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_event_group WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_event_deep WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM nmf_cell_second WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM stg_event WHERE project_id=:p AND capture_id=:c` *(cascade param_occurrence via FK CASCADE)*
   - `DELETE FROM stg_event_raw WHERE project_id=:p AND capture_id=:c`
   - `DELETE FROM stg_measurement_raw WHERE project_id=:p AND capture_id=:c`
   - `DROP TABLE IF EXISTS nmf_deep_<cap>` ; `DROP TABLE IF EXISTS nmf_group_<cap>` *(partitions dédiées — à confirmer avec le propriétaire de `nmf_decoder_partition`)*
   - `nmf_file_id := (SELECT nmf_file_id FROM nmf_capture WHERE …)` ; `DELETE FROM nmf_capture WHERE project_id=:p AND capture_id=:c`
   - Si plus aucune `nmf_capture` ne référence ce `nmf_file_id` → `DELETE FROM nmf_file WHERE id=:fid` + unlink `source_path` sur disque *(sous le DEPLOY_LOCK)*.
5. Appel final `run_populate_chain(db, project)` (idempotent, purge=True pour A) pour recalculer agrégats, measurement_points, opérateurs, période.
6. `UPDATE projects SET n_captures_ingest = (SELECT count(*) FROM nmf_capture WHERE project_id=:pid), status_ingest='ready'`.
7. Journal JSON `audit/capture_delete/<ts>_<cap>.json` : before snapshot, counts par table (avant/après), reason obligatoire.
8. Guard d'intégrité post-op : `SELECT count(*) FROM {toutes les tables ci-dessus} WHERE project_id=:pid AND capture_id=:cap` = 0 pour tout; sinon rollback.

Pré-conditions imposées par la route :

- `DEPLOY_LOCK` posé par l'opérateur (lecture du fichier côté API, pas conditionné à un worker auto).
- Pas d'import en vol : `SELECT pg_try_advisory_lock(LOCK_ID)` doit réussir.
- `reason` ≥ 10 caractères.

CLI équivalente proposée : `python -m app.scripts.delete_capture <project_id> <capture_id> --reason "<justification>"`.

---

## Préalables validés (encore valides au moment du STOP)

```
G36 : verdict=PASS free=56.37 GiB (seuil 20) — 10:11:28Z
witness-nmf : 3/3 fichiers chmod 444 — sha256 matchant nmf_file :
  parcours_26Jun10_155941.8.nmf  a4b0c321c52e... 57 930 189 B  (a4b0c321c52e)
  ikea_26Jun10_172354.2.nmf      ecffb18dbd7f... 2 440 473 B   (ecffb18dbd7f)
  ikea_26Jun10_172354.6.nmf      daa2b1df250d... 2 044 640 B   (daa2b1df250d, ajouté)
services : bc4-db-1 healthy · bc4-api-1 healthy /health=0.94.0 catalog 2.55.0 decoder 1.7.2 · bc4-front-1 http 200 (localhost + 185.248.33.125)
DEPLOY_LOCK : non pris — opération refusée en amont.
```

---

## Prochain pas requis

1. BC1 ou BC2 implémente `delete_capture` + route + script CLI (SemVer `minor` bump sur `bc4-back`, CHANGELOG + rebuild + guard, conformément à CLAUDE.md règle 5).
2. Une fois mergé/déployé : rejoue l'opération Test_5 avec le DEPLOY_LOCK pris et les 21 appels via l'ORM (ou la route) dans un script tracé.
3. En attendant : **Test_5 reste à 24 captures**. Pas de SQL direct, pas de scanner, pas de workaround.
