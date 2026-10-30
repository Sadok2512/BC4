# BC1 — metrics-map-lean

## Verdict

PASS sur pile jetable, projet `43e81a34a073`, capture `a4b0c321c52e`.
SemVer back : PATCH ; numéro attribué par BC3.

La nouvelle route légère est :

```text
GET /projects/{project_id}/metrics/map?capture_id=...&codes=...
```

Elle renvoie uniquement `map_points`, leur total et l'enveloppe de version.
Le contrat des points reste celui de `MetricMapPoint` : position, valeur,
serving cell et liens radio prouvés.

## Avant

Commande à froid sur la pile jetable :

```bash
docker restart bc1-metrics-map-lean-db
URL='http://127.0.0.1:8000/projects/43e81a34a073/metrics/table?capture_id=a4b0c321c52e&codes=cell_rsrp%40lte-type-0&include_map=true'
curl --fail-with-body -sS -H "Authorization: Bearer $TOKEN" \
  -o /tmp/metrics-map-before.json \
  -w 'status=%{http_code} starttransfer=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' "$URL"
```

```text
status=200 starttransfer=44.819776s total=44.831606s bytes=4270988
map_points=4935 rows=1000 total_rows=4935
```

Profil Python reproductible :

```bash
PYTHONPATH=/app python audit/bc1-metrics-map-lean/profile_legacy.py
```

```text
dataset_init_s=23.858146
response_s=4.233523
pydantic_validate_s=0.257940
json_encode_s=0.084474
sql_execute_s=8.391612
```

Le profil `cProfile` associé compte 428 188 lignes SQL itérées. Le premier
poste Python est `Dataset.__init__`, qui reconstruit l'horloge et le contexte
complet alors que la carte n'en a pas besoin.

EXPLAIN exact :

```bash
docker exec -i bc1-metrics-map-lean-db psql -U bc1metrics \
  -d bc1_metrics_map -P pager=off \
  < audit/bc1-metrics-map-lean/explain_context.sql
```

Résultat utile : `Execution Time: 8374.330 ms`, 383 294 lignes produites,
13 495 blocs lus et tris externes temporaires. Le `context_sql()` contient le
scan/tri UNION de `stg_event_raw` et `stg_event`, l'agrégat
`measurement_points` et le join `param_occurrence` ; ce travail n'est pas
nécessaire aux points de carte.

## Après

Commande à froid :

```bash
docker restart bc1-metrics-map-lean-db
URL='http://127.0.0.1:8000/projects/43e81a34a073/metrics/map?capture_id=a4b0c321c52e&codes=cell_rsrp%40lte-type-0'
curl --fail-with-body -sS -D /tmp/metrics-map-after.headers \
  -H "Authorization: Bearer $TOKEN" -o /tmp/metrics-map-after.json \
  -w 'status=%{http_code} starttransfer=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' "$URL"
grep -i '^server-timing:' /tmp/metrics-map-after.headers
```

```text
status=200 starttransfer=0.906776s total=0.912767s bytes=2665709
server-timing: dataset;dur=9.450, metric;dur=363.078, gps;dur=0.251, links;dur=398.914
```

`gps` est le temps d'attente résiduel : sa requête capture-scopée s'exécute en
parallèle de la projection métrique. `links` inclut la cellule serving, les
voisines et l'ancre NR. Les références hors de la boîte conservative de 25 km
ne sont pas transférées ; le compte de candidats reste calculé sur l'ensemble
des correspondances radio.

## Identité du contenu

Commande appliquée aux réponses avant et après :

```bash
python -c 'import hashlib,json,sys;p=json.load(open(sys.argv[1]))["map_points"];print(len(p),hashlib.sha256(json.dumps(p,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest())' RESPONSE.json
```

```text
avant 4935 476865ace2e55f283b9365e92067f0f41061cf14e92fdb3e12807f43e08583a2
après 4935 476865ace2e55f283b9365e92067f0f41061cf14e92fdb3e12807f43e08583a2
```

## Gardes

```bash
df -BG --output=avail /home/devmat/BC4 | tail -1
# 160G — G36 PASS (seuil 20G)

python -m pytest -q tests/test_metrics_map_lean.py tests/test_map_cell_links.py tests/test_metrics_v3.py
# 9 passed

python -m compileall -q app/kpi/metrics_map.py app/kpi/map_cell_links.py \
  app/kpi/metrics_v3.py app/routes/metrics_v3.py
# exit 0

git diff --check
# exit 0
```

La tentative des gardes avec `python` directement sur l'hôte a rendu 127
(`python: command not found`) : VERDICT FAIL pour cette commande. Les mêmes
gardes ont ensuite été exécutés dans `bc1-metrics-map-lean-api`, environnement
Python de la pile, avec le verdict PASS ci-dessus ; aucun test n'a été sauté.

## Nettoyage

```bash
docker stop bc1-metrics-map-lean-api bc1-metrics-map-lean-db
docker rm bc1-metrics-map-lean-api bc1-metrics-map-lean-db
docker volume rm bc1-metrics-map-lean-dbdata
docker network rm bc1-metrics-map-lean-net
df -h /home/devmat/BC4
```

```text
/dev/sda1  388G  237G  151G  62% /
```
