# HANDOFF — Phase 2.51.0 1b (reprise mi-course)

Ouvert par BC3 le 2026-10-25 ~15:30Z. Mis à jour 2026-10-25 ~17:12Z.
Branche `feat/bc3-catalog-2.51`, 3 commits BC3 posés au-dessus de 3a8a0b2.
DEPLOY_LOCK **TOUJOURS PRIS** par BC3 — redécode en cours.

## État mi-course (17:12Z)

### Fait

- **Decoder 1.7.0** livré (commit `aa4c05b`) :
  - `schema_for(event, system)` : dispatch LTE/NR via `_variants[9]`
    posés depuis les YAMLs `*_NR` (CELLMEAS, MIMOMEAS, TAD, TXPC, PHRATE).
  - Decoder re-sélectionne la variante NR après résolution de `r.system`.
  - `txpc_cell_type()` RESTRICTE à LTE (system==7). NR via header
    `txpc.cell_type` dimension=true.
  - `Light.add` : neighbors agrégation CELLMEAS skippée pour NR.
  - `RANGE_VIOLATIONS` counter global + `reset_range_violations()`.
  - PHRATE_NR.yaml créé (4 fields NFF 2.50 §PHRATE Parameters for NR).

- **Alembic 0053** (`c7e5596` dépendance décaissée) + **Alembic 0054**
  (`c7e5596`) :
  - 0053 : +19 cols headers NR dans `nmf_event_light` + `nmf_event_deep`,
    +14 cols cells NR dans `nmf_event_light_group` + `nmf_event_group`.
  - 0054 : +14 cols cells NR aussi dans `nmf_event_light` (codes
    propagés par la boucle `for f in definition['fields']: add(...)`
    sans `aggregate_selection=first`).

- **Fix YAMLs NR start=INT** (`dfbf4bf`) :
  - CELLMEAS_NR : `start: 7` (int = col 1-indexed de n_cells).
  - MIMOMEAS_NR : `start: 6`.
  - Preuve avant fix : SELECT cell_type FROM nmf_event_light_group WHERE
    system=9 → valeurs -126, -117, -110 (= RSRP pris pour cell_type).
  - Preuve après fix : décoder test NR cell_type=199 → `groups[0]
    .values.cell_type == 199`.

- **cells.py SKIP NR CELLMEAS** (`dfbf4bf`) : évite UniqueViolation
  nmf_cell_second_pkey (clé ne distingue pas LTE PCell=0 de NR PCell=0).
  Series cells NR passent par `nmf_event_light_group.cell_type` dans ce
  lot. Migration pkey+system = lot ultérieur.

- **build_catalog.py** (`dfbf4bf`) : `corpus_cell_types()` lit aussi
  les cell_types depuis `nmf_event_light_group` (groupes `cells`,
  `measurements`). Les 7 feuilles cellule canoniques (PCell/SCell 1-4/
  PSCell/SCell NR 100+) sont générées avec `reason` sur non-observé.

- **CHANGELOG×3 draft** : CHANGELOG.md (0.81.0), CHANGELOG_DECODER.md
  (1.7.0), CHANGELOG_CATALOG.md (2.51.0).

- **Rebuild api** : `bc4-api:latest` built. `/health` renvoie
  `{"status":"ok","env":"development","version":"0.81.0","decoder_version":"1.7.0"}`.

- **Redécode UE** en cours (3e tentative) :
  - PID=4513 (python inside bc4-api-1).
  - Progress : `/app/exports/redecode_progress.txt`.
  - Main log : `/app/exports/redecode_20261025_171053.log`.
  - 83 captures UE (16 deep + 67 light). ETA ~2h30 restante.
  - Les 2 premières tentatives ont échoué (alembic 0053 colonnes
    manquantes dans nmf_event_light ; cells.py pkey violation NR). Les
    4 captures OK de la 2e tentative (134af70a06eb) ont des cell_type
    NR faux dans groupes → la 3e tentative les redécode via `force=True`.

### Scope restant (ordre impératif)

1. **Attendre fin redécode** : `docker exec bc4-api-1 cat /app/exports/
   redecode_progress.txt | tail -20` doit afficher `DONE total=83
   failed=0`. Si failed>0 : lister les captures + exceptions.

2. **G28 corpus post-redécode** :
   `docker exec bc4-api-1 python scripts/guards_2026_10/G28_ranges_corpus.py
    > /home/devmat/BC4/exports/G28_1_7_0.log 2>&1`
   FAIL (out_of_range>0) = STOP + rapport. Rajouter G28 ciblé sur
   `723547b196b3` et `44621571bccc` (CELLMEAS NR RSRP range, PHRATE
   PDSCH bitrate range).

3. **Dump sentinelles** : `docker exec bc4-api-1 python -c "from app.
   nmf_decoder.decoder import RANGE_VIOLATIONS; import json; print(json
   .dumps(dict(RANGE_VIOLATIONS), indent=2))"` → copier top-20 dans
   CHANGELOG_DECODER.md. Note : counter non-persistant, se perd au
   redémarrage container → script redecode doit dumper en fin de run
   (TODO scope ultérieur ou copier le JSON de MEMORY du container).

4. **Build catalog 2.51.0** :
   `docker exec -w /app bc4-api-1 python scripts/catalog/build_catalog.py \
     --csv /specs/nmf_all_events_fields_2.50.csv \
     --txt /specs/nemo_file_format_2.50.txt \
     --categories scripts/catalog/categories.yaml \
     --version 2.51.0 --decoder-min 1.7.0 \
     --out app/kpi/catalog_release/catalog_2.51.0.json --commit`

   Prérequis : copier les 2 specs dans `/specs/` du container.
   Vérifier `n_leaves_displayed`, `n_metrics`, cells NR dans leaves.

5. **Gardes stricts** :
   - G25 : `docker exec bc4-api-1 python scripts/guards_2026_10/G25_catalogue.py`
   - G18b : `docker exec bc4-api-1 python scripts/guards_2026_10/G18b_parity.py`
   - G24 : `docker exec bc4-api-1 python scripts/guards_2026_10/G24_leaves.py --pid 134af70a06eb`
     puis `--pid 723547b196b3` si projet NR séparé.
   - G29 : `docker exec bc4-api-1 python scripts/guards_2026_10/G29_file_vs_db.py`

6. **PNG #2 PHRATE PDSCH bitrate 0 · PCell** sur `44621571bccc` :
   - métrique = `phrate_pdsch_bitrate_0` (col 6 LTE PDSCH, when c4=2)
   - filtre : `cell_type=0 AND phrate_ph_ch_type=2`
   - adapter `scripts/shot_metrics_sidebar.ts` du front OU curl direct
     `/projects/<pid>/metrics/timeseries?...` + matplotlib.

7. **PNG #3 CELLMEAS NR RSRP meas_type=1 · cell_type=199** sur
   `723547b196b3` :
   - métrique = `cell_rsrp` depuis `nmf_event_light_group`
   - filtre : `cell_type=199 AND cell_meas_type=1 AND group_name='cells'`
   - directe `SELECT second, cell_rsrp FROM nmf_event_light_group ...`
     + matplotlib.

8. **Vérifier arbre NR non vide** : interroger `/projects/<pid>/metrics`
   et vérifier que les nodes tech=NR ont des leaves selectable=true.
   Front check avec `shot_metrics_sidebar.ts` facultatif.

9. **Merge back + front** sous DEPLOY_LOCK :
   - Branche `feat/bc3-catalog-2.51` → main (fast-forward si possible,
     sinon merge --no-ff).
   - Rebuild api si nouveau commit après dfbf4bf.
   - `/health` collé : `0.81.0 / 1.7.0`.
   - CHANGELOG×3 (main, catalog, decoder) déjà prêts, à publier.
   - Front : `1.108.3` (BC1 ok), pas de nouveau tag si rien à toucher.
   - **Libérer DEPLOY_LOCK**.

## Détails techniques

### Convention de dispatch LTE/NR
`schema.py` loader détecte le suffixe `_NR` et pose le YAML sous
`result[event]['_variants'][9]`. `schema_for(event, system)` dispatch :
- `TXPC` + `system=7` → TXPC.yaml (LTE)
- `TXPC` + `system=9` → TXPC_NR.yaml (NR)
- Dedans `decoder.decode()`, après avoir résolu `r.system`, bascule
  `schema = schema_for(code, r.system)` AVANT la boucle header.

### Convention start.header_col vs start=INT dans YAMLs groups
- `start.header_col=K` : lit `size = tokens[K-1]` (TAILLE préfixe
  variable), puis `idx = K-1 + 1 + size` = col count. Utilisé si le
  préfixe entre `header_col` et count a une taille déclarée par un
  token (ex: LTE CELLMEAS hdr_n=0 → size=0 → idx=K).
- `start=K` (int) : `idx = K-1` directement. Utilisé si count est à
  col K sans préfixe variable (NR CELLMEAS/MIMOMEAS).

**Pattern à retenir** : si YAML fields headers n'ont pas de token
"size prefix" avant count, utiliser `start=INT` (col 1-indexed de
count).

### Dette NR cell_rows()
cells.py skippe tous les buckets NR CELLMEAS pour éviter la pkey
violation. Les séries cells NR ne sont donc pas servies par
`nmf_cell_second`. Le lot ultérieur devra :
- Migration alembic : ajouter `system int` à `nmf_cell_second.pkey`.
- cells.py : étendre `_cell_index_for()` pour system=9 avec les
  cell_type bruts NR (sans collision avec LTE).
- /metrics v3 : propager system dans les series requests.

### Reset decoder_version 1.7.0 → 1.6.0 pour forcer redécode
Pas nécessaire — `redecode_corpus.py` utilise `force=True` donc redécode
même les captures déjà en 1.7.0.

## Repro reprise session

```bash
cd /home/devmat/BC4/bc4-back

# 1) Vérifier état
cat /home/devmat/BC4/DEPLOY_LOCK            # BC3 holder
git log --oneline -5                        # dfbf4bf au top
curl -s http://localhost:8000/health         # 0.81.0 / 1.7.0

# 2) Progress redécode
docker exec bc4-api-1 cat /app/exports/redecode_progress.txt | tail -20
docker exec bc4-db-1 psql -U bc4 -d bc4 -tAc \
  "SELECT decoder_version, COUNT(*) FROM nmf_capture WHERE kind='ue' GROUP BY 1"

# 3) Si redécode DONE, exécuter étapes 2-9 ci-dessus.
```

## Blockers / dettes connus

1. **cell_type en groupes = brut**. CELLMEAS LTE expose 0, 10-13.
   CELLMEAS NR expose 0, 199, 100-131 (spec), observé 101/108/117/199
   (audit 1a). Le catalog 2.51.0 agrège en "SCell NR 100+" (bucket).
2. **nmf_cell_second absent pour NR** (dette ci-dessus).
3. **Tests back** : 13 fails baseline (dette Phase 2.2a — YAMLs 2.50
   écrasent partiellement les 1.5.1 pour PHRATE/MACRATE/CI/TXPC/CQI).
   Pas d'augmentation suite lot 1b. Fix dette séparé.
4. **RANGE_VIOLATIONS non persisté** : counter in-process. Dumper en
   fin de redécode via patch script (TODO lot ultérieur).

— Agent BC3
