# bc1/dict-tree-cold — rapport de preuve

## Questions préalables

### `127.0.0.1:9081`

Commande d'état actuelle :

```bash
ss -ltnp '( sport = :9081 )'
for id in $(docker ps -aq); do
  docker inspect --format '{{.Name}} {{.Config.Image}} {{json .HostConfig.PortBindings}}' "$id"
done | rg 9081
```

Sortie : aucun socket ni conteneur actuel. La trace du lot précédent donne le
contenu historique :

```bash
rg -n '127\.0\.0\.1:9081|bc1-metrics-series-proof' \
  audit/bc1-metrics-series-lean/trace.md
```

`9081` exposait le conteneur jetable `bc1-metrics-series-proof`, recréé sur le
même port avant/après et relié au corpus Test_6. Il a été supprimé.

### Projet `1cb56dd9257f`

Commandes :

```bash
docker exec bc4-db-1 sh -lc 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT * FROM projects WHERE id=..."'
rg -n '1cb56dd9257f' audit/bc1-metrics-series-lean/trace.md
```

La base locale active renvoie zéro ligne. La trace l'identifie comme le projet
jetable de G51 dans la base du hotfix, avec la capture `daa2b1df250d`; ce n'est
pas Test_6.

### Hotfix 0.99.2

Commandes :

```bash
git diff --unified=80 8faca97^ 8faca97 -- \
  app/kpi/metrics_v3.py app/routes/metrics.py
sed -n '160,230p' audit/bc1-metrics-series-lean/trace.md
```

Le diff étend la branche `cell_scoped` aux événements hors CELLMEAS, protège
les `label`/`unit` nuls et extrait `catalog()['metrics']`. G51 enregistré :
`n_500=0`, `failures=0`, `G51 VERDICT=PASS`, `EXIT_CODE=0`. Verdict : **PASS**.

## Disque et corpus

```bash
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
df -h /home/devmat/BC4
```

Sortie avant base jetable : `free_gib=41.78`, seuil `20`, `verdict=PASS`.

La base `bc1-dict-tree-cold-db` est une restauration en lecture source de la
base active. Comptage par contenu :

```sql
SELECT count(*) FILTER (WHERE origin='network_config'),count(*)
FROM param_occurrence WHERE project_id='43e81a34a073';
```

Sortie : `129356|171766`. Le constat initial `60970` n'est donc plus celui du
contenu courant; écart déclaré ouvert. Toutes les preuves utilisent les
`171766` lignes actuelles.

## Contrat avant / après

Oracle avant, code `main` sur la même base jetable :

```bash
BC4_DSN='postgresql+psycopg://postgres@127.0.0.1:55471/bc4' \
BC4_JWT_SECRET='bc1-dict-tree-cold-test-secret' python3 - <<'PY'
import hashlib,json,time
from app.db import SessionLocal
from app.dict.service_v2 import build_dict_tree
with SessionLocal() as db:
 t=time.perf_counter();v=build_dict_tree(db,'43e81a34a073','catalog',None);dt=time.perf_counter()-t
b=json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
print(dt,len(b),hashlib.sha256(b).hexdigest(),v['total_rows'])
PY
```

Avant : `3.585226 s`, `954103` octets,
`c23d95a002957da368dc2aa362aa758aa02016735e774472c08eeaddbff68715`,
`171766` lignes.

Après migration et rattrapage, la même commande depuis la branche donne
`0.526207 s`, la même taille, la même empreinte et le même total.

Premier HTTP après redémarrage du runner (cache mémoire froid) :

```bash
curl -sS -H "Authorization: Bearer $BC1_TOKEN" \
  -H 'Accept-Encoding: identity' -o /tmp/bc1-dict-tree-final.json \
  -w 'http=%{http_code} starttransfer=%{time_starttransfer} total=%{time_total} size=%{size_download}\n' \
  'http://127.0.0.1:9081/projects/43e81a34a073/dict/v2/tree?view=catalog'
```

Sortie : `http=200 starttransfer=0.806852 total=0.809812 size=954103`.
L'empreinte canonique de la réponse reste celle de l'oracle. **VERDICT=PASS**.

## Migration, rattrapage et idempotence

```bash
python3 -m alembic downgrade 0070_signaling_materialized
python3 -m alembic upgrade head
python3 -m app.scripts.backfill_dict_network_catalog 43e81a34a073 \
  --reason 'BC1 dict-tree-cold disposable final proof'
```

Sortie : `FINAL_SETUP_EXIT=0`, `VERDICT=PASS`. La génération active contient
`843` lignes réseau et `213` lignes catalogue non réseau.

Deuxième exécution :

```bash
python3 -m app.scripts.backfill_dict_network_catalog 43e81a34a073 \
  --reason 'BC1 dict-tree-cold idempotency second pass'
```

Sortie : `IDEMPOTENCY_EXIT=0`, `VERDICT=PASS`. Contrôle :

```sql
SELECT s.source_occurrences,s.eligible_occurrences,s.summary_rows,s.catalog_rows,
 (SELECT count(*) FROM dict_network_catalog_entry e
  WHERE e.project_id=s.project_id AND e.generation=s.generation),
 (SELECT count(*) FROM dict_catalog_group_entry e
  WHERE e.project_id=s.project_id AND e.generation=s.generation),
 (SELECT count(*) FROM dict_network_catalog_entry e
  WHERE e.project_id=s.project_id AND e.generation<>s.generation)
FROM dict_network_catalog_state s WHERE s.project_id='43e81a34a073';
```

Sortie : `129356|103430|843|213|843|213|0`. Après invalidation de génération,
le HTTP froid donne `starttransfer=0.833562 s` et la même empreinte.

Sans raison :

```bash
python3 -m app.scripts.backfill_dict_network_catalog 43e81a34a073
```

Sortie : `VERDICT=FAIL reason=reason_too_short`, `NO_REASON_EXIT=2`.

## Plans des requêtes restantes

Commande : `EXPLAIN (ANALYZE, BUFFERS)` appliqué successivement à la lecture
PK de `dict_network_catalog_state`, aux deux tables de génération, à
`dict_category_map`, `dict_v22_backup`, `dict_category` et
`dict_subcategory`.

Temps d'exécution sortis par PostgreSQL : état `0.127 ms`, catalogue non réseau
`3.116 ms`, catalogue réseau `23.445 ms`, mapping `2.532 ms`, backup
`0.034 ms`, catégories `0.015 ms`, sous-catégories `0.039 ms`. Aucun tri disque.

## Tests

```bash
docker run --rm --name bc1-dict-tree-cold-tests \
  -v /home/devmat/BC4/worktrees/bc1-dict-tree-cold-back:/app:ro -w /app \
  -e BC4_DSN='postgresql+psycopg://postgres@172.17.0.2:5432/bc4' \
  -e BC4_JWT_SECRET='bc1-dict-tree-cold-test-secret' bc4-api:latest \
  python -m pytest -q tests/test_dict_network_catalog.py tests/test_api_lean.py \
  tests/test_dict_distribution_totals.py tests/test_dict_map_v2.py \
  tests/test_dict_geo_filters.py tests/test_dict_categories_v23.py
```

Sortie : `41 passed`, `PYTEST_EXIT=0`.

## SemVer

Type déclaré : **back patch**. Le contrat HTTP ne change pas; migration,
matérialisation et commande de rattrapage sont internes. Numéro attribué par
BC3 au merge.
