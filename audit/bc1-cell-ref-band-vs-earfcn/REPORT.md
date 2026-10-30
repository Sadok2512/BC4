# BC1 — cell_ref : bande MHz vs canal exact

## Verdict

PASS sur clone jetable complet de la base. Aucune écriture en production.

SemVer back : **MINOR**, car le lot ajoute deux colonnes et remplace l'index
radio par deux index `CONCURRENTLY`. Numéro attribué par BC3.

## Audit du contenu source

Commande :

```sh
python3 - <<'PY'
# csv.DictReader ; Counter sur earfcn, dl_earfcn, nr_arfcn et rat
PY
```

Résultat sur `/home/devmat/ref_cell_4G5G.csv` :

```text
earfcn    non_null=459499 distinct=8  values=700/800/900/1400/1800/2100/2600/3500
dl_earfcn non_null=19642  distinct=8  values=524/547/1300/3000/6275/6400/9310/9335
nr_arfcn  non_null=0      distinct=0
```

Avant migration, la commande SQL suivante sur le clone montrait les domaines
fusionnés :

```sql
BEGIN READ ONLY;
SELECT count(*),count(earfcn),count(DISTINCT earfcn) FROM cell_ref;
SELECT earfcn,count(*) FROM cell_ref GROUP BY earfcn ORDER BY earfcn NULLS LAST;
COMMIT;
```

Résultat : `459901` lignes, `459853` valeurs, `20` valeurs distinctes : les
huit bandes, les huit EARFCN LTE et quatre NR-ARFCN cohabitaient dans
`cell_ref.earfcn`.

## Correctif

- Migration `0077_cell_ref_band_channels` :
  `band_mhz`, `earfcn` LTE exact, `nr_arfcn` NR exact. Une valeur historique
  égale à la bande de sa ligne est ambiguë et n'est pas conservée comme canal.
  Les NR-ARFCN hors domaine MHz sont préservés, y compris sur les lignes
  legacy portant encore un libellé LTE.
- `/reference/cell/upload` et `/settings/cell-ref/upload` lisent séparément
  `earfcn`, `dl_earfcn` et `nr_arfcn` ; aucun fallback inter-colonnes.
- Map-cell-links joint directement `earfcn=cell_arfcn` pour LTE et
  `nr_arfcn=cell_arfcn` pour NR. La bande n'apparaît dans aucune jointure.
- `/sites` expose `band_mhz`, `earfcn`, `nr_arfcn` et l'alias d'affichage
  `arfcn`, toujours tiré d'un canal exact.
- Rattrapage `python -m app.scripts.reimport_cell_reference SOURCE --reason …` :
  lock BC3 obligatoire, verrou advisory, checksum et JSON avant/après,
  idempotent par `cell_ref.id`, sans re-décodage.

## Migration et réimport réels

Migration :

```sh
docker run --rm --network bc1-cell-ref-band-net \
  -e BC4_DSN=<dsn-jetable> -v <worktree>:/app bc4-api:latest \
  alembic upgrade head
```

Résultat : upgrade `0076_map_cell_links -> 0077_cell_ref_band_channels`, exit 0.

Refus sans lock :

```sh
BC4_DEPLOY_LOCK_PATH=/tmp/missing-lock python -m \
  app.scripts.reimport_cell_reference /witness/ref_cell_4G5G.csv \
  --reason 'guard refusal proof'
```

Résultat : exit 1,
`VERDICT=FAIL reason=deploy_lock_required`. Aucune écriture.

Réimport avec lock jetable `holder: BC3` :

```sh
python -m app.scripts.reimport_cell_reference \
  /witness/ref_cell_4G5G.csv \
  --reason 'separate MHz bands from exact LTE and NR channels'
```

Résultat : `VERDICT=PASS`, historique `completed`, `459547` lignes lues,
`457845` chargées et `1702` rejetées par les contrôles métier. Journal exact :
`audit/cell-ref-channel-reimport/20261030T231338Z-7ab9a545.json`.

Comptage final :

```sql
BEGIN READ ONLY;
SELECT count(*),count(band_mhz),count(DISTINCT band_mhz),
       count(earfcn),count(DISTINCT earfcn),
       count(nr_arfcn),count(DISTINCT nr_arfcn)
FROM cell_ref;
SELECT count(*) FROM cell_ref
WHERE earfcn=band_mhz OR nr_arfcn=band_mhz;
COMMIT;
```

```text
total=459901
band_mhz=459487 / 8 valeurs
earfcn=19642 / 8 valeurs
nr_arfcn=366 / 4 valeurs
égalité canal/bande ambiguë=0
```

La migration finale a également été rejouée après downgrade sur quatre lignes
de contenu : LTE ambigu `1800`, LTE exact `1300`, NR exact legacy `643392` et
bande NR `3500`. Sortie :

```text
ambiguous-lte|1800||
band-nr|3500||
exact-lte|1800|1300|
legacy-nr|||643392
```

## Preuve ecffb18dbd7f

Commande avant avec l'image 0.115.1, puis après avec les sources de branche :

```sh
python - <<'PY'
# appel direct metric_map(project=43e81a34a073,
# capture=ecffb18dbd7f, codes=cell_rsrp@lte-type-0), puis comptage du JSON
PY
```

```text
BEFORE_TOTAL_POINTS=199
BEFORE_SERVING_LINKS=199
AFTER_TOTAL_POINTS=199
AFTER_SERVING_LINKS=199
```

VERDICT : liens serving conservés **199/199**. Les liens voisins et ancres NR
restent à zéro avant et après ; aucun lien n'est inventé sans canal exact et
géométrie prouvée.

Contrôle `/sites` sur une cellule réelle :

```text
{'id': '466735016', 'band_mhz': 1800, 'earfcn': 1300,
 'nr_arfcn': None, 'arfcn': 1300, 'pci': 500}
```

## Tests et écarts d'exécution

```sh
python -m pytest tests/test_g6_cell_ref.py -q
# 3 passed
python -m pytest tests/test_cell_ref_channels.py tests/test_map_cell_links.py \
  tests/test_metrics_map_lean.py tests/test_operational_write_guards.py \
  tests/test_deploy_guard.py -q
# 12 passed
python -m compileall -q app alembic/versions/0077_cell_ref_band_channels.py
# exit 0
```

- Un premier clone a été interrompu par le redémarrage final de l'entrypoint
  PostgreSQL après que son serveur temporaire eut répondu au healthcheck :
  exit non nul, VERDICT FAIL. La base jetable a été recréée et le clone complet
  suivant a terminé avec exit 0. Écart fermé.
- Un premier pytest groupé sans `BC4_API_BASE` a produit deux erreurs explicites
  de fixture, donc exit non nul. L'API jetable a été démarrée et G6 a été
  relancé : `3 passed`. Écart fermé.
- `ruff` est absent de l'image (`python -m ruff` : exit 1). Écart déclaré ;
  `compileall`, imports de schéma et tests ciblés passent.
- Le premier `chown` local du journal a échoué (fichier créé par le conteneur,
  exit 1). Le propriétaire a été corrigé depuis un conteneur avec l'UID/GID
  mesuré par `id -u devmat; id -g devmat`, puis confirmé par `ls -l`.
  Écart fermé.

Nettoyage : conteneur, volume et réseau `bc1-cell-ref-band-*` supprimés.
`df -h /home/devmat/BC4` : `148G` disponibles, au-dessus du seuil G36.
