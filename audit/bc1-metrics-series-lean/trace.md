# bc1/metrics-series-lean — preuve par le contenu

## Disque / base

Le lot ne crée aucune nouvelle base : il réutilise en lecture la base jetable
du hotfix pour G51 et le corpus Test_6 pour la mesure. Contrôle disque :

```bash
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
```

```text
free_bytes=48146595840 free_gib=44.84
threshold_bytes=21474836480 threshold_gib=20
G36 VERDICT=PASS
G36_EXIT=0
```

## Chemin de la preuve front précédente

La mesure KPI UX annoncée via l'IP de `bc4-api-1:5174` ne passait pas par
le front déployé. Elle visait le serveur Vite jetable
`bc1-kpi-ux-proof`, lancé avec `--network container:bc4-api-1` : le port
5174 était donc ouvert dans le namespace réseau partagé de l'API. Cette
comparaison avant/après est retirée.

Pour le présent lot, avant et après utilisent exactement :

```text
http://127.0.0.1:9081/projects/43e81a34a073/metrics/series?capture_id=a4b0c321c52e&codes=cell_rsrp%40lte-type-0
```

Le conteneur de preuve est recréé sur le même port entre les deux mesures ;
`task_result` est neutralisé dans ce runner de lecture pour ne pas modifier la
base utilisée comme corpus.

## Mesure HTTP avant / après

Commande commune (le jeton est créé localement et n'est jamais affiché) :

```bash
BC1_TOKEN=$(docker exec -i bc1-metrics-series-proof python - <<'PY'
from app.services.auth import create_token
print(create_token(user_id='adm-be45f070eba8', role='admin', ttl_min=15,
                   secret='bc1-metrics-series-proof-secret')[0])
PY
)
curl -sS -H "Authorization: Bearer $BC1_TOKEN" \
  -H 'Accept-Encoding: identity' -o /tmp/bc1_series_http.json \
  -w 'http=%{http_code} starttransfer=%{time_starttransfer} total=%{time_total} size=%{size_download}\n' \
  'http://127.0.0.1:9081/projects/43e81a34a073/metrics/series?capture_id=a4b0c321c52e&codes=cell_rsrp%40lte-type-0'
```

Sorties :

```text
avant: http=200 starttransfer=19.021283 total=19.023420 size=778958
après: http=200 starttransfer=0.840663 total=0.842888 size=778958
VERDICT=PASS
```

Empreinte de contenu (JSON canonique, seul `result_id` aléatoire est remplacé
par `normalized-result-id`) :

```bash
python3 - <<'PY'
import hashlib,json
d=json.load(open('/tmp/bc1_series_http.json'))
d['result_id']='normalized-result-id'
b=json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
print(len([p for s in d['series'] for p in s['points']]))
print(hashlib.sha256(b).hexdigest())
PY
```

Avant et après :

```text
points=4935
sha256=4f6e719c3912b45203d7e8f62c7db37fe43dcba7a5a416274d5c8b3037cf6710
VERDICT=PASS
```

## Diagnostic

Profil Python, code 0.99.2, corpus Test_6 :

```bash
docker exec -i bc4-api-1 python - <<'PY'
# cProfile autour de Dataset(...), parse_selection(...), ds.response(...)
PY
```

Sortie utile :

```text
dataset_init_s=24.896128
parse_selection_s=0.211294
response_s=1.211702
total_s=26.319123
Dataset.__init__ cumtime=24.896
clock cumtime=7.645
SQLAlchemy rows itérées=394471
VERDICT=PASS
```

Même instrumentation après, avec le code de branche monté en lecture seule
sur le même corpus :

```text
dataset_init_s=0.203807
parse_selection_s=0.076855
response_s=0.641266
total_s=0.921928
points=4935
VERDICT=PASS
```

`pg_stat_statements` a confirmé que la requête cellule elle-même n'était
pas la source des dizaines de secondes. L'`EXPLAIN (ANALYZE, BUFFERS)` après
suppression du join temporel redondant est lancé par :

```sql
EXPLAIN (ANALYZE, BUFFERS)
WITH ranked AS (
  SELECT g.seq,g.cell_pci,g.cell_ch,
         row_number() OVER (
           PARTITION BY g.project_id,g.capture_id,g.seq,g.cell_type
           ORDER BY g.identity)-1 occurrence
  FROM nmf_event_light_group g
  WHERE g.project_id='43e81a34a073'
    AND g.capture_id='a4b0c321c52e'
    AND g.group_name='cells' AND g.cell_type=0
), physical AS (
  SELECT s.seq_first seq,MAX(s.seq_last) seq_last,s.second,
         NULL::double precision exact_t_rel_s,
         r.cell_pci,r.cell_ch cell_arfcn,
         CASE WHEN SUM(s.weight) FILTER (WHERE s.weight>0)>0
           THEN SUM(s.value*s.weight) FILTER (WHERE s.weight>0)
                / SUM(s.weight) FILTER (WHERE s.weight>0)
           ELSE AVG(s.value) END value,
         COUNT(*)::int observation_count,
         MIN(s.cell_index)::int storage_order
  FROM nmf_cell_second s LEFT JOIN ranked r
    ON r.seq=s.seq_first AND r.occurrence=s.cell_index-1003
  WHERE s.project_id='43e81a34a073'
    AND s.capture_id='a4b0c321c52e'
    AND s.event_code='CELLMEAS' AND s.metric_code='cell_rsrp'
    AND s.cell_index BETWEEN 1003 AND 1083
  GROUP BY s.seq_first,s.second,r.cell_pci,r.cell_ch,
    CASE WHEN r.cell_pci IS NULL OR r.cell_ch IS NULL
         THEN s.cell_index ELSE NULL END
)
SELECT seq,seq_last,second,exact_t_rel_s,cell_pci,cell_arfcn,value,
       observation_count,COUNT(*) OVER()::int total_rows
FROM physical
ORDER BY seq,cell_arfcn NULLS LAST,cell_pci NULLS LAST,storage_order;
```

Plan de la requête applicative complète : index-only scan
`ix_nmf_cell_second_metric_cell_seq`, 466 buffers hit, aucun tri disque,
`Execution Time: 56.724 ms`, `VERDICT=PASS`.

## Sous-échantillonnage min/max

Commande :

```bash
curl -sS -H "Authorization: Bearer $BC1_TOKEN" \
  -H 'Accept-Encoding: identity' -o /tmp/bc1_series_http_sampled.json \
  -w 'http=%{http_code} starttransfer=%{time_starttransfer} total=%{time_total} size=%{size_download}\n' \
  'http://127.0.0.1:9081/projects/43e81a34a073/metrics/series?capture_id=a4b0c321c52e&codes=cell_rsrp%40lte-type-0&max_points=2000'
```

Sortie, comparée par Python au JSON complet :

```text
http=200 starttransfer=0.581385 total=0.582696 size=398412
full_points=4935 sampled_points=1980
full_min=-129.8 sampled_min=-129.8
full_max=-66.8 sampled_max=-66.8
VERDICT=PASS
```

## Session

Le lot retient une durée par défaut plus longue, toujours configurable :

```bash
BC4_DSN='postgresql+psycopg://unused:unused@127.0.0.1:1/unused' \
BC4_JWT_SECRET='bc1-test-only-secret' python -c \
  'from app.config import settings; print(settings.jwt_ttl_min)'
```

La sortie attendue sur la branche est `480`; l'environnement de déploiement
peut encore imposer `BC4_JWT_TTL_MIN`.

## Relecture hotfix et G51

Commande sur l'image reconstruite depuis `bc3/metrics-celltype-fix` 0.99.2,
base jetable du hotfix :

```bash
docker exec bc3-metrics-fix-runner-1 sh -lc '
  G51_TOKEN=$(python - <<"PY"
import os
from app.services.auth import create_token
print(create_token(user_id="adm-b8078db2ce32", role="admin", ttl_min=120,
                   secret=os.environ["BC4_JWT_SECRET"])[0])
PY
  ); export G51_TOKEN
  python scripts/guards_2026_10/G51_metrics_catalog_regression.py \
    --base-url http://127.0.0.1:8000 \
    --project 1cb56dd9257f --capture daa2b1df250d
'
```

Sortie finale :

```text
leaves_in_catalog=231
table: 200=174, 422=57, 500=0
series: 200=174, 422=57, 500=0
mixed: 200=3
n_200=351 n_422=114 n_500=0 failures=0
G51 VERDICT=PASS
EXIT_CODE=0
```

## SemVer

Type déclaré : **back patch**. Numérotation finale par BC3.
