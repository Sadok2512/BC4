# bc4-back — CHANGELOG

Versions SemVer. Type de bump: `patch` / `minor` / `major`. Un écart se ferme ou se déclare ouvert, jamais expliqué par hypothèse.

## 0.14.0 — 2026-10-15 (minor) — Fix mirror captures + PLMN non catalogué visible + bc4-enrich 1.2.0

> Lot chaîné avec **bc4-enrich 1.2.0** (table PLMN étendue aux MVNO FR
> + `ctx["operator_by_plmn"]`). Garde G15 (G13/G14 sont pris par les
> lots périmètre et dictionnaire).

### Corrigé
- **Bug mirror captures** (`app/ingest/nmf.py`, ex-ligne 730) :
  `if project.n_captures_ingest is not None:` écrasait silencieusement
  `project.captures` par 0 au prochain `refresh_project_summary`
  sur un projet seedé B0 (`n_captures_ingest = 0`, pas None). Les 6
  projets seedés (Paris 2.4M, Lyon 850k, Marseille 1.2M, Rennes 410k,
  Benchmark 5.8M, Tests Indoor 320k) perdaient leurs captures seedés
  au premier refresh déclenché. **Garde** : `n_captures_ingest > 0`.
  Même garde appliquée à `scripts/mirror_ingest_to_b0.py`.
- **PLMN non catalogué invisible** (`app/ingest/nmf.py`,
  section post-enrich) : un PLMN SIB1 non catalogué remontait dans
  `operators_plmn` mais pas dans `project.operators` → disparition
  silencieuse en N/D côté front. Désormais, chaque PLMN non mappé
  émet une entrée explicite `"PLMN <id> (non catalogué)"` dans
  `project.operators`. Format partagé avec le front
  (`OperatorChip` 1.6.0 : couleur slate neutre pour toute étiquette
  hors des 4 MNO). Les MVNO FR reconnus en 1.2.0 (Lyca, Lebara, …)
  sortent avec leur marque, pas en « non catalogué ».

### Ajouté
- `scripts/re_refresh_after_plmn_extension.py` : one-shot idempotent
  qui itère sur TOUS les projets avec `status_ingest NOT NULL` et
  appelle `refresh_project_summary`. Rapporte les deltas
  `(captures_before, captures_after)` et `(operators_before,
  operators_after)` par projet. Captures seedés **inchangés** (grâce
  à la garde `> 0`).
- `scripts/g15_mirror_plmn.sh` + `tests/test_g15_mirror_plmn.py` :
  garde manuelle qui vérifie :
  (a) refresh d'un projet seedé B0 ne touche PAS `captures` ;
  (b) MVNO mappé (`20825` → « Lyca Mobile ») sort via
      `ctx["operator_by_plmn"]` ;
  (c) PLMN inconnu (`20899`) sort en `"PLMN 20899 (non catalogué)"`
      dans `project.operators` (plus en N/D silencieux) ;
  (d) TEST2 reste à 9 captures, operators
      `["Bouygues","Free","Orange"]`.

### Versions tierces chaînées
- `bc4-enrich` : **1.1.0 → 1.2.0** (table PLMN étendue + nouveau
  champ `operator_by_plmn`). Déployé à `/opt/nmf_decoder` via
  bind-mount read-only — rebuild `api` nécessaire pour que le
  module soit rechargé (sinon le binding Python conserve la 1.1.0
  en cache). Voir `/home/devmat/BC4/decoder/CHANGELOG.md`.

### Écarts ouverts
- **20888** (Bouygues) : hérité de la table 1.0.0. Pas d'audit ANFR
  frais fait dans ce lot — déclaration maintenue, pas vérifiée.
- **20831** (Oracle Communications / ex-Mundio Mobile) : attribution
  GSMA, pas trouvée dans la vue ANFR directe en 2024-2026. Si une
  SIB1 réelle remonte `20831`, confirmer avant d'y faire reposer
  une décision pilotage.
- **Sous-marques invisibles** : Sosh / RED by SFR / B&You partagent
  le PLMN parent — une capture Sosh sortira « Orange ». C'est
  conforme à la règle « 4 MNO propres » ; un besoin de distinction
  sous-marque demanderait une couche IE séparée (hors scope).

## 0.13.0 — 2026-10-15 (minor) — Dictionnaire complet RRC LTE+NR (`param_occurrence`)

> Lot « dictionnaire » prévu initialement à 0.12.0. **Collision de version**
> avec le lot `perimeter` + `bc4-enrich 1.1.0` d'un agent parallèle (déjà
> publié à `0.12.0`, migration `0007_project_perimeter`). Mon minor prend
> `0.13.0` (règle « jamais deux lots sur la même version »). La garde est
> numérotée **G14** pour la même raison (`G13` est pris par `g13_perimeter.sh`).
>
> Compatibilité : ma migration `0008_param_occurrence` chaîne depuis
> `0007_project_perimeter` sans interférer avec `project.perimeter`.
> Les deux lots partagent `bc4_enrich 1.1.0` (SIB1 → PLMN FR + cells).

### Ajouté
- Table **`param_occurrence`** (migration `0008_param_occurrence`) :
  stocke chaque occurrence d'un paramètre RRC décodé par pycrate à
  partir de `stg_event.payload_hex`. Colonnes : `project_id`,
  `stg_event_id` (FK CASCADE), `system` (LTE|NR), `channel`, `message`,
  `path`, `value`, `value_converted`, `unit_converted`, `operator`,
  `band`, `lat`, `lon`. Trois index composites
  (`(project_id, system, message, path)`, `(project_id, operator, band)`,
  `(project_id, path)`) + UNIQUE `(project_id, stg_event_id, path)` →
  **idempotence** du populate (`ON CONFLICT DO NOTHING`).
- Module **`app/dict/`** :
  - `decode.py` : adapté de `/home/devmat/BC4/decoder-archive/build_dict.py`.
    La regex **`DENY`** (identités d'abonné) et la fonction **`walk()`**
    sont **RÉUTILISÉES INCHANGÉES**. Table PDU : les 6 canaux LTE
    (BCCH-BCH/2, BCCH-SCH/2, CCCH/1, CCCH/2, DCCH/1, DCCH/2) + les 6
    équivalents NR + 3 IE capability NR (`UE-NR-Capability IE`,
    `UE-MRDC-Capability IE`, `FreqBandList IE`).
  - `conversions.py` : table 3GPP (TS 36.133 / TS 38.133). Convertit en
    valeur physique (dBm / dB) : **`rsrp-Result`** (idx-141 dBm),
    **`rsrq-Result`** (idx/2-20 dB), **`a3-Offset`** (×0.5 dB),
    **`q-RxLevMin`** (×2 dBm), **`threshold-RSRP`** / **`thresholdRSRP`**
    (idx-140 dBm), **`q-Hyst`** (×1 dB), **`s-Measure`** (idx-140 dBm),
    **`rsrp-ThresholdSSB`** (idx-140 dBm), **`rsrq-ThresholdSSB`**
    (idx/2-20 dB). Un paramètre inconnu laisse `value_converted = NULL`
    (jamais inventé).
  - `populate.py::populate_param_occurrence(db, project_id)` : itère
    `stg_event` du projet où `event_code='RRCSM' AND payload_hex IS NOT NULL`,
    ordre canonique `(capture_id, seq)`. Rattache `operator` via le
    DERNIER SIB1 vu dans la même capture avec `seq <= event.seq`
    (fallback global `(freq, pci)`), et `band` via le SIB1 ou
    `bc4_enrich.band_from_freq(freq, system)`. Insert par lots de 1000
    avec `ON CONFLICT DO NOTHING`. Purge+repop par projet pour un état
    déterministe.
- `app/ingest/nmf.py::refresh_project_summary` appelle **automatiquement**
  `populate_param_occurrence(..., purge=True)` après chaque upload NMF.
  Best-effort (log + continue si pycrate indisponible).
- Trois endpoints `/projects/{id}/dict/*` (dispatch par query-params —
  rétro-compat totale avec les routes B0 historiques) :
  - **`GET /dict/tree`** → arbre `{branches: [{system, count, messages:
    [{message, count, params: [{param, count}]}]}]}` depuis
    `param_occurrence`. Si `param_occurrence` est vide pour le projet
    (p.ex. projets seedés B0), fallback transparent sur l'arbre B0
    historique (G2/G3 vert).
  - **`GET /dict/params?system=LTE|NR&message=…&operator=…&band=…`** →
    `{params: [{system, message, path, count, unit_converted, buckets:
    [{operator, band, count, avg_converted}]}]}`. L'ancien
    `?msg_id=…` continue de fonctionner → logique B0 (G2 vert).
  - **`GET /dict/param/map?path=…&system=…&limit=10000`** →
    `{path, system, points: [{lat, lon, value_raw, value_converted,
    operator, band}]}`. Filtre sur lat/lon non null, borné `limit`
    (défaut 10 000, max 100 000, pilotable par
    `BC4_DICT_MAP_LIMIT_*`). L'ancien `?param_id=…` continue de
    fonctionner → logique B0 (G2 vert).
- Script **`scripts/populate_dict_for_all_projects.py`** : one-shot
  pour les projets déjà ingérés avant 0.13.0. Idempotent (purge+repop
  par projet). TEST2 (19 064 events RRC) est passé en un seul run.

### Deny-list identités (règle dure)
La regex `DENY` du fichier archive (`build_dict.py` ligne 14-16) est
**reprise INCHANGÉE** dans `app/dict/decode.py::DENY` — matche
`ue-Identity`, `s-TMSI`, `m-TMSI`, `mmec`, `imsi`, `randomValue`,
`newUE-Identity`, `c-RNTI`, `shortMAC`, `dedicatedInfoNAS`,
`registeredMME`, `gummei`, `nextHopChaining`, `ue-CapabilityRAT*`,
`lateNonCriticalExtension`, `nonCriticalExtension$`, `ng-5G-S-TMSI`,
`fullI-RNTI`, `shortI-RNTI`, `dedicatedNAS`, `registeredAMF`, `guami`.
Deux niveaux de filet :
  1. `walk()` filtre à chaque clé (dict + CHOICE) — jamais recursé.
  2. `path_matches_deny()` sur le path aplati complet, en sortie —
     ligne décomptée dans `stats["n_params_denied"]` du populate.

Vérifié : **0 ligne** dans `param_occurrence` match la deny-list pour
TEST2 (query `path ~ 'ue-Identity|s-TMSI|dedicatedNAS…'` → 0 rows).

### Garde `G14` (`scripts/g14_dict.sh` + `tests/test_g14_dict.py`, 6 assertions)
- `param_occurrence` peuplé pour TEST2 (count > 0).
- `/dict/tree` : branche **LTE non vide** ET **NR non vide**.
- `/dict/params?system=LTE&message=SystemInformationBlockType1`
  expose au moins un path `q-RxLevMin` avec `unit_converted='dBm'`
  (preuve que la table 3GPP s'applique).
- `/dict/param/map?path=…&system=LTE` sur un path PLMN de SIB1 →
  `len(points) > 0` + chaque point porte `operator`/`band` rattachés.
- Deny-list : 0 ligne match côté DB ET côté API.

### Chiffres réels TEST2 (après populate initial)
- `events_scanned = 19 064` RRCSM avec payload_hex (LTE+NR).
- `events_decoded_ok = 8 889` (46,6 %), `events_decoded_err = 10 175`
  (53,4 %, dont `no_params = 10 175` — essentiellement Paging LTE
  skippé, UECapabilityInformation hors table + NR messages sans canal).
- `n_params_written = 98 679`, dont **68 633 LTE** et **30 046 NR**.
- `n_params_denied = 0` (règle dure respectée au populate).
- 764 paths distincts.
- Conversions appliquées sur plusieurs milliers de lignes (RSRP, RSRQ,
  a3-Offset, q-RxLevMin, s-Measure, threshold-RSRP), unités
  `dBm`/`dB` honnêtes. Exemples :
  - `rsrpResult = 62 → "-79 dBm"` (idx-141).
  - `rsrqResult = 5 → "-17.5 dB"` (idx/2-20).
  - `q-RxLevMin = -62 → "-124 dBm"` (×2).
  - `a3-Offset = 2 → "1 dB"` (×0.5).

### Écarts ouverts
- **`events_decoded_err = 10 175`** : la majorité vient de Paging LTE
  (volontairement skippé — contient uniquement des identités d'abonné)
  et de messages NR dont le canal n'est pas rempli dans `stg_event`
  (`channel=''` pour 1 007 events NR). Ces messages ne sont PAS
  insérés en `param_occurrence` — déclaré, pas comblé par heuristique.
  Un lot ultérieur pourra enrichir la détection de canal NR
  (actuellement conditionnée par le décodeur canonique
  `bc4_decoder 1.0.0`).
- **UMTS (58 events `INTER_RAT_HANDOVER_INFO`)** : hors scope RRC
  LTE+NR — pas de PDU pycrate pour UMTS, 0 ligne en
  `param_occurrence`. Déclaré.
- **`avg_converted` dans les buckets de `/dict/params`** : calculé en
  PostgreSQL avec un `regexp_replace` qui nettoie `value_converted`
  pour un cast flottant. Fonctionne pour les paramètres purement
  numériques (rsrp, rsrq, q-RxLevMin…) ; renverra `NULL` si le
  `value_converted` contient des espaces ou unités (ce qui n'arrive
  pas aujourd'hui car `unit_converted` est stocké séparément).
  L'écart potentiel est pris en compte mais ne se matérialise pas sur
  les règles actuelles.
- **Rétro-populate** : les projets ingérés avant 0.13.0 n'ont pas de
  `param_occurrence` calculé jusqu'au lancement une fois du script
  `scripts/populate_dict_for_all_projects.py` (fait sur TEST2 à la
  release). Un ré-ingest (ou un futur `POST /projects/{id}/reindex`)
  les enrichira automatiquement.
- **Front** : la consommation des trois nouveaux endpoints est
  reportée au lot `1.7.0` du front (hors scope de ce lot back).

### Garde (manuel)
```
docker compose up -d --build api
curl http://localhost:8000/health   # version == "0.13.0"
docker exec bc4-api-1 python /app/scripts/populate_dict_for_all_projects.py
# Vérifier le count TEST2 :
docker exec bc4-db-1 psql -U bc4 -d bc4 -c \
  "SELECT count(*) FROM param_occurrence WHERE project_id = (SELECT id FROM projects WHERE name='TEST2');"
# Vérifier LTE + NR non vides :
docker exec bc4-db-1 psql -U bc4 -d bc4 -c \
  "SELECT po.system, count(*) FROM param_occurrence po
   JOIN stg_event se ON se.id=po.stg_event_id
   WHERE po.project_id = (SELECT id FROM projects WHERE name='TEST2')
   GROUP BY po.system;"
# Vérifier absence deny-list :
docker exec bc4-db-1 psql -U bc4 -d bc4 -c \
  "SELECT path FROM param_occurrence WHERE path ~ 'ue-Identity|s-TMSI|dedicatedNAS' LIMIT 5;"
# G14 complet :
export BC4_API_BASE=http://localhost:8000
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_ADMIN_EMAIL=admin@bc4.local
export BC4_ADMIN_PASSWORD=... # idem container
export BC4_NMF_DECODER_PATH=/home/devmat/BC4/decoder
bc4-back/scripts/g14_dict.sh
```

## 0.12.0 — 2026-10-15 (minor) — Périmètre géo (jointure cells Orange ↔ `cell_ref`) + bc4-enrich 1.1.0 (Agent BC1)

### Release couplée : `bc4_enrich` 1.1.0
Déposé dans `/opt/nmf_decoder` (bind-mount read-only commun). CHANGELOG
en tête du module.
- Nouvelle sortie `ctx["cells"] = [{rat, plmn, cell_id}]` : liste unique
  des cellules observées en SIB1. `cell_id` est la représentation
  **décimale** du `cellIdentity` (28 bits LTE, 36 bits NR), pour matcher
  la convention `cell_ref.eci` / `cell_ref.nci` de `ref_cell_4G5G.csv`.
- Rétro-compat 1.0.0 : `operators`, `bands`, `technos`, `plmns`,
  `plmns_unknown`, `freqs_unknown`, `n_sib1_lte`, `n_sib1_nr` restent
  inchangés. `_extract_plmns` conservé pour les appelants v1.0.0.
- Ajout G13 (unit) : encode un SIB1 Orange avec `cellIdentity=41000001`
  → vérifie `ctx["cells"] == [{"rat":"LTE","plmn":"20801","cell_id":"41000001"}]`.

### Ajouté (bc4-back)
- Migration **`0007_project_perimeter`** : colonne JSON nullable
  `projects.perimeter`. Pas d'index (lecture colonne entière à
  l'affichage). Vide tant qu'aucune cellule Orange n'a été jointe
  (déclaré, pas `0`).
- Modèle `Project.perimeter: Mapped[dict | None]`.
- `app/ingest/nmf.py::_compute_perimeter(db, cells)` — jointure côté
  back :
  - Pour chaque cellule plmn=20801 (Orange) :
    - LTE : `cell_id` matché contre `cell_ref.rat='4G' AND eci = ...`.
    - NR  : `cell_id` matché contre `cell_ref.rat='5G' AND nci = ...`.
  - Agrège DISTINCT `dor`, `dr`, `plaque`, `site_name`, `arcep_zone`,
    `coverage` depuis les lignes jointes.
  - Rapport :
    ```
    cells_total, cells_orange, cells_other,
    cells_joined, cells_orange_unjoined, join_rate_pct,
    dors, drs, plaques, sites, arcep_zones, coverage,
    label        # résumé lisible (ex: "DR Paris, DR Lyon")
    zone_source  # "cell_ref_exact" | "none"
    ```
  - `null` reste `null`. La UI affiche « N/D » quand `zone_source=none`.
- `refresh_project_summary` : après `detect_context`, appelle
  `_compute_perimeter(db, ctx["cells"])` et écrit `project.perimeter`.
- `ProjectIngestView.perimeter` (schéma Pydantic + sous-objet
  `PerimeterView`) : exposé sur `GET /projects/{id}/ingest`.
- Garde `G13` (`scripts/g13_perimeter.sh` + 4 assertions) :
  - `bc4_enrich 1.1.0` expose `ctx["cells"]` depuis un SIB1 encodé.
  - `_compute_perimeter([])` → `label="N/D"`, `zone_source="none"`.
  - Cellule non-Orange (plmn=20810 SFR) → `cells_other=1`,
    `cells_joined=0`, label `N/D` — **DÉCLARÉ, pas comblé par
    heuristique GPS** (règle P1).
  - Cellule Orange + ligne `cell_ref` injectée en base
    → `cells_joined=1`, `cells_orange_unjoined=1` (preuve que la
    jointure n'invente pas pour les cellules sans correspondance),
    `join_rate_pct=50.0`, `drs=["DR-G13"]`, `label="DR-G13"`,
    `zone_source="cell_ref_exact"`.

### Écarts ouverts
- **PLMN non-Orange (SFR, Bouygues, Free) : périmètre non attribuable
  par cellule.** `cell_ref` ne couvre QUE Orange. Les cellules
  non-Orange sont comptées dans `cells_other` et n'alimentent pas
  `dors`/`drs`/`plaques`. Propagation GPS (si event `lat/lon` →
  reverse-geocode) = lot mesures ultérieur. **Jamais deviné.**
- **cell_ref vide** : si l'admin n'a pas uploadé `ref_cell_4G5G.csv`,
  la jointure matche 0 ligne. `perimeter` sort avec
  `cells_joined=0` et `zone_source="none"`. Déclaré, pas une erreur.
- **Rétro-perimeter** : les projets ingérés avant 0.12.0 n'ont pas de
  `perimeter` calculé (colonne reste `NULL`). Un ré-ingest (ou un
  futur `POST /projects/{id}/reindex`) les enrichira.
- **NR cellIdentity** : `pycrate` RRCNR schema v16+ expose
  `cellIdentity` dans `plmn-IdentityInfoList[i]` (36 bits). Testé via
  l'ASN.1 schema, pas sur une capture 5G réelle — à confirmer sur
  témoin NR du décodeur.

### Garde (manuel)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_NMF_DECODER_PATH=/opt/nmf_decoder   # ou /home/devmat/BC4/decoder
bc4-back/scripts/g13_perimeter.sh

# E2E : après upload d'un NMF témoin dans un projet neuf
docker exec bc4-db-1 psql -U bc4 -d bc4 -c "
  SELECT id, perimeter->>'label' AS label,
         perimeter->>'cells_joined' AS joined,
         perimeter->>'cells_orange' AS orange,
         perimeter->>'join_rate_pct' AS rate_pct
  FROM projects WHERE perimeter IS NOT NULL;
"
```

## 0.11.1 — 2026-10-15 (patch) — Miroitage B1-ingest -> B0 (`captures`, `technologies`)

### Correctif
Les projets créés via `POST /projects` (flow B1-ingest) sortaient avec
les champs B0 (`captures`, `technologies`, `operators`, `geography`,
`departements`) vides par construction, alors que l'ingestion NMF
remplit les champs B1-ingest parallèles (`n_captures_ingest`,
`technos_seen`, …). Les deux conventions se complétaient au lieu de se
coordonner — TEST2 live sortait `captures=0` + `technologies=[]` alors
que `n_captures_ingest=9` et `technos_seen={LTE:15587, NR:3735, UMTS:58}`.

0.11.1 **miroite systématiquement** à la fin de
`refresh_project_summary` (après chaque upload NMF), conditionnel pour
ne pas écraser les projets seedés B0 :

- `project.captures = project.n_captures_ingest` si `n_captures_ingest is not None`.
- `project.technologies = sorted(technos_seen.keys(), key=lambda k: -technos_seen[k])`
  si `technos_seen` est un dict non-vide, **filtré sur le vocabulaire
  Zod `{LTE, NR, EN-DC}`** (règle 0.10.0). technos_seen peut contenir
  d'autres clés (p.ex. `"UMTS"` sur TEST2) qui restent visibles sur
  `GET /projects/{id}/ingest.technos_seen` pour trace, mais ne polluent
  pas la liste Zod `project.technologies` (sinon pydantic rejette au
  `GET /projects`, 500). Tri par comptage décroissant, zéro invention.
- **`project.operators`, `project.geography`, `project.departements`
  NON TOUCHÉS** (écarts ouverts, cf. ci-dessous). Paris 2026 Q1 et les
  autres projets seedés B0 conservent leurs `operators=["Orange","SFR",
  ...]` et leur géo.

### Rétro-miroitage des projets déjà ingérés
Pas de migration Alembic (c'est de la donnée, pas du schéma). Un
one-shot `scripts/mirror_ingest_to_b0.py` itère sur les projets avec
`status_ingest IS NOT NULL` et applique le miroitage. **Lancer une fois
après le déploiement 0.11.1** :

```
docker exec bc4-api-1 python /app/scripts/mirror_ingest_to_b0.py
```

Idempotent : rejouer ne change rien de plus.

### Écarts ouverts (déclarés)
- **PLMN -> opérateur** : `bc4_enrich` 1.0.0 décode les SIB1 LTE/NR
  présents, mais si le NMF ne porte pas de SIB1 (p.ex. 2G-only,
  décode partiel), `project.operators` reste `[]`. Hérité de 0.11.0,
  pas de régression.
- **`geography` et `departements` depuis l'ingestion** : nécessiterait
  un reverse-geocoding des `stg_event.lat/lon` (bbox / INSEE lookup).
  Hors scope de ce patch. Les projets seedés B0 ont déjà ces champs
  renseignés via `app/seed/fixtures_data.PROJECTS` ; les projets
  ingérés gardent leurs valeurs à la création (`geography=""`,
  `departements=[]`).

### Garde (manuel)
```
docker compose up -d --build api
curl http://localhost:8000/health   # version == "0.11.1"
docker exec bc4-api-1 python /app/scripts/mirror_ingest_to_b0.py
# Vérifier qu'un projet ingéré sort maintenant avec captures et
# technologies miroités depuis n_captures_ingest / technos_seen :
docker exec bc4-db-1 psql -U bc4 -d bc4 \
  -c "SELECT name, captures, n_captures_ingest, technologies, technos_seen
      FROM projects WHERE status_ingest IS NOT NULL;"
# Vérifier qu'un projet seedé B0 (Paris 2026 Q1) est INCHANGÉ :
docker exec bc4-db-1 psql -U bc4 -d bc4 \
  -c "SELECT name, operators FROM projects WHERE name='Paris 2026 Q1';"
```

## 0.11.0 — 2026-10-15 (minor) — Correctif 0.10.0 : enrichissement operators + bands via `bc4_enrich` (Agent BC1)

### Rectification de 0.10.0
Le CHANGELOG 0.10.0 déclarait `project.operators` et `project.bands`
« indisponibles » à l'ingestion. **C'était une erreur de qualification** :
le PLMN est extractible du SIB1 via ASN.1 (pycrate) et la bande est
dérivable de `EARFCN` / `ARFCN` via les tables 3GPP (TS 36.101
§5.7.3-1, TS 38.101-1 §5.4.2.3-1). Les deux sources étaient disponibles
dès 0.6.1 — manquait seulement l'intégration. 0.11.0 ferme l'écart.

### Ajouté
- Module **`bc4_enrich.py`** déposé à côté de `bc4_decoder.py` dans
  `/opt/nmf_decoder` (bind-mount read-only commun), export `__version__`
  `"bc4-enrich 1.0.0"`.
  - `PLMN_TO_OPERATOR` : table statique France (11 PLMN, 4 opérateurs).
    PLMN hors table → bucket `plmns_unknown` (jamais deviné).
  - `band_from_freq(freq, system)` : mappe EARFCN → bande LTE
    (20 bornes, FDD+TDD France+voisines) et ARFCN → bande NR
    (15 bornes, FR1+FR2 mmWave).
  - `detect_context(events) -> {operators, bands, technos, n_sib1_lte,
    n_sib1_nr, plmns, plmns_unknown, freqs_unknown}`.
  - PLMN décodé par **pycrate** sur `BCCH-DL-SCH-Message` (LTE) et
    `BCCH-DL-SCH-Message` NR + SIB1 nu (fallback). Toute exception
    au décode est **avalée au niveau d'un payload** — jamais au niveau
    du contexte global (un SIB1 corrompu n'empoisonne pas les autres).
- `pycrate==0.8.1` ajouté à `requirements.txt`.
- `app/ingest/nmf.py::_detect_enrich_context()` : relit les events
  (system, message, freq, payload_hex) **depuis `stg_event`** (pas de
  second décode du `.nmf`), passe à `bc4_enrich.detect_context()`,
  écrit `project.operators`, `project.bands`, `project.technologies`
  et met à jour `project.operators_plmn` (dict `{plmn: 1}` pour trace).
- `app/ingest/nmf.py::_import_enrich()` : résolution du module
  `bc4_enrich` avec les mêmes candidats que le décodeur
  (`BC4_NMF_DECODER_PATH` + fallbacks).

### Garde `G12` (`scripts/g12_enrich.sh` + 5 assertions unitaires)
- `band_from_freq` : LTE 3000→B7, 6300→B20, 9500→B28 ; NR 632628→n78,
  155000→n28 ; `None`/non-numérique/hors plage → `None`.
- `PLMN_TO_OPERATOR` couvre les 4 opérateurs FR
  (Orange, SFR, Bouygues, Free).
- `detect_context` sans SIB1 : `operators=[]` (déclaré par
  `n_sib1_lte`/`n_sib1_nr` = 0, PAS une erreur) ; `bands` et
  `technos` toujours remplis depuis `freq`/`system`.
- `detect_context` sur **SIB1 LTE encodés pour Orange/SFR/Bouygues/Free**
  → `operators = {Orange, SFR, Bouygues, Free}` + `plmns ⊇ {20801,
  20810, 20820, 20815}`.
- PLMN non répertorié (p.ex. `22299`) → `operators=[]` +
  `plmns_unknown=["22299"]`. **Jamais mappé par heuristique.**

### Écarts ouverts
- **Fichier NMF sans SIB1 (ex. 2G-only, décode partiel)** :
  `operators=[]`, `bands=[]` restent **vides** à l'issue de
  `refresh_project_summary`. `n_sib1_lte`/`n_sib1_nr` = 0 déclarent
  l'absence de source. Ce n'est pas une erreur de l'enrichissement —
  c'est l'honnêteté du rapport (règle « null → N/D, jamais 0 »).
- **Bandes NR mmWave (FR2)** : les plages n257/n258/n260/n261 sont
  présentes dans la table mais la détection effective dépendra des
  ARFCN rapportés par le décodeur sur du matériel 26/28/39 GHz —
  pas de garde E2E sur du mmWave dans ce lot (pas de témoin dispo).
- **Rétro-enrichissement** : les projets ingérés avant 0.11.0 ne
  sont pas recalculés automatiquement. Un ré-upload du même NMF
  (idempotent sur `project_id, sha256`) ne réimporte rien mais ne
  recalcule pas l'enrichissement non plus — un `POST /projects/{id}/
  reindex` est reporté à un lot ultérieur.

### Garde (manuel)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_NMF_DECODER_PATH=/opt/nmf_decoder    # ou /home/devmat/BC4/decoder hors container
bc4-back/scripts/g12_enrich.sh
# Pour la garde END-TO-END (import d'un NMF témoin, vérif en base) :
export BC4_API_BASE=http://localhost:8000
export BC4_ADMIN_EMAIL=admin@bc4.local
export BC4_ADMIN_PASSWORD=... # idem container
# Upload du NMF, puis :
docker exec bc4-db-1 psql -U bc4 -d bc4 \
  -c "SELECT id, operators, technologies, bands FROM projects WHERE id='<pid>';"
```

## 0.10.0 — 2026-10-15 (minor) — DELETE /projects/{id} + enrichissement `technologies` (Agent BC1)

### Ajouté
- **`DELETE /projects/{id}`** : supprime un projet et **tous** ses enfants
  en cascade via les FK `ondelete=CASCADE` déjà déclarées en migration
  (`nmf_file`, `stg_event`, `measurement_points`, `rrc_observations`).
  Portée strictement limitée à l'ID : aucune autre table n'est touchée.
  - admin + ingenieur peuvent supprimer (via mapping `admin|editor`).
  - **204** si supprimé.
  - **404** si l'ID n'existe pas (même pour admin — on ne laisse pas
    fuiter l'existence par le code HTTP).
  - **403** si le rôle est insuffisant (lecteur).
- Enrichissement `project.technologies` à l'ingestion :
  `refresh_project_summary()` écrit maintenant aussi `project.technologies`
  à partir des clés de `technos_seen`, filtrées sur le vocabulaire Zod
  (`LTE | NR | EN-DC`). Zéro invention : si le décodeur n'a pas vu la
  techno, elle n'apparaît pas. Un projet neuf **avant** le premier
  ingest sort toujours avec `technologies=[]` (déclaré).

### Tranche (point 3 — projets de seed)
- **Les projets de démo (`idf-t3-2026`, `national-2026`,
  `rennes-lte-2026`, `lyon-drive-2026`, `marseille-5g-2026`,
  `lille-indoor-2026`) ont déjà `operators`, `technologies` et `bands`
  renseignés en base** par `app/seed/fixtures_data.PROJECTS` + le
  seed `_seed_projects()` qui les écrit tels quels. Aucune action
  dans ce lot. L'assertion est garantie par `G11.test_seed_projects_
  have_operators_technos_bands`. L'audit initial (« ils sortent N/D »)
  ne reflète pas l'état actuel après `app/seed/run.seed()`.

### Écarts ouverts
- **`project.operators` et `project.bands` à l'ingestion** : non peuplés
  — les sources manquent :
  - `operators` : `bc4_decoder 1.0.0` n'expose pas la clé `plmn` (déclaré
    déjà au CHANGELOG 0.6.1). Sans mapping PLMN → opérateur, pas
    d'enrichissement honnête possible.
  - `bands` : `stg_event` ne porte pas de colonne `band`. Un futur lot
    pourra déduire la bande d'`freq` (EARFCN/UARFCN) via une table de
    mapping — pas dans ce lot.
  Un projet créé puis ingéré sort donc avec `operators=[]`, `bands=[]`,
  `technologies=[techs_vraiment_vues]`. Front doit afficher **N/D**
  pour operators/bands tant que la source n'est pas câblée.
- Projets créés **avant** cette version restent avec leurs listes
  d'origine (`[]` pour les créations post-0.3.0, listes seedées pour
  les démos B0). Pas de rétro-enrichissement rétroactif (serait une
  migration de données, hors périmètre).

### Garde `G11` (`scripts/g11_delete_enrich.sh` + 7 assertions)
- `DELETE` par admin → 204 + absent du listing + 404 au second DELETE.
- `DELETE` par ingenieur → 204 (mapping `editor` → autorisé).
- `DELETE` par lecteur → 403.
- `DELETE` sur ID inconnu → 404.
- Projets de seed : `operators`, `technologies`, `bands` non vides en base.
- Projet fraîchement créé **sans** ingest : `operators`/`technologies`/
  `bands` vides (déclaré).
- Après injection d'events `system='LTE'` + appel direct de
  `refresh_project_summary()` : `project.technologies` contient `"LTE"`.
  `operators` et `bands` restent intentionnellement vides (écart).

### Garde (manuel)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
export BC4_JWT_SECRET=... # idem container
export BC4_ADMIN_EMAIL=admin@bc4.local
export BC4_ADMIN_PASSWORD=... # idem container
export BC4_DEMO_EMAIL=demo@bc4.local
export BC4_DEMO_PASSWORD=... # idem container
export BC4_DEMO_ROLE=ingenieur
bc4-back/scripts/g11_delete_enrich.sh
```

## 0.9.0 — 2026-10-15 (minor) — POST /settings/users + policy serveur + mapping 3-rôles (P1-2, Agent BC1)

### Ajouté
- `POST /settings/users` **implémenté** (plus de 501) :
  - **Admin requis** (`require_role(actor, "admin")`). Un ingenieur
    reçoit 403, un lecteur reçoit 403.
  - **Password policy appliquée côté serveur**, lue depuis
    `settings_password_policy` en base (`min_length`, `require_digit`,
    `require_upper`). Mdp non conforme → **422 `WEAK_PASSWORD`** avec
    la liste détaillée des règles violées + copie de la policy pour
    l'affichage client. Mismatch `password_confirm` → 422 `VALIDATION`.
  - Création **atomique** d'une ligne `app_user` (source d'auth JWT,
    rôle DB en FR via `ROLE_API_TO_DB`) **et** d'une ligne `users`
    (vue d'affichage settings). Email dérivé de `login`
    (`login@bc4.local` si pas d'arobase), uniq checké sur les deux tables.
  - Mdp hashé argon2id puis **oublié** — jamais stocké en clair, jamais
    loggé, jamais renvoyé (vérifié par G10).
  - Après création, le nouveau compte peut se loger immédiatement
    (`POST /auth/login` renvoie 200 + token).

### Vérifié / documenté
- **Mapping 3-rôles correct** sans correctif de code : la table
  `ROLE_DB_TO_API` (`admin→admin`, `ingenieur→editor`, `lecteur→viewer`)
  est appliquée dans `deps.get_actor`. `require_role(actor, "admin",
  "editor")` laisse donc passer **admin + ingenieur** mais pas lecteur,
  tel qu'attendu. L'audit mentionnait un risque de verrouillage à
  admin seul — **non confirmé** : G10 démontre
  `{admin: 201, ingenieur: 201, lecteur: 403}` sur un POST protégé.
  Aucun rôle fantôme « editor » absent du CHECK base ne verrouille
  l'écriture — le mapping résout proprement.
- `POST /settings/users` est explicitement **admin-only**
  (plus strict que les autres mutations `admin+editor`) — reflète
  que créer un compte est un acte d'administration.
- Les routes d'écriture restantes
  (`POST /projects`, `POST /projects/{id}/nmf`, `POST /reference/cell/upload`)
  conservent `admin+editor` → `admin+ingenieur` effectif via mapping.

### Garde `G10` (`scripts/g10_users_policy_roles.sh` + 6 assertions)
- 3 logins {admin, ingenieur, lecteur} valides → tokens différents.
- Mêmes 3 rôles → `POST /projects` renvoie `{201, 201, 403}` dans l'ordre.
- Mdp faible (`"abc"`) → 422 + chaque règle violée nommée.
- Mdp conforme → 201 + login du nouveau compte réussit.
- Ingenieur essaie `POST /settings/users` → 403.
- Audit logs : aucun mot de passe en clair ni hash argon2 ne sort
  dans `docker logs bc4-api-1` (vérifié manuellement, non automatisé).

### Écarts ouverts
- **PATCH / DELETE /settings/users** restent 501 (modification d'un
  compte existant, désactivation, changement de rôle). Lot ultérieur.
- **Mécanisme de reset mdp** : toujours absent. Un admin recrée le
  compte si nécessaire. Déclaré depuis 0.7.0.
- **GET /settings/users** reste accessible à `admin+editor`. On n'a
  pas durci sa portée dans ce lot ; la lecture reste étendue à
  l'équipe édito.

### Garde (manuel)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
export BC4_JWT_SECRET=... # idem container
export BC4_ADMIN_EMAIL=admin@bc4.local
export BC4_ADMIN_PASSWORD=... # idem container
export BC4_DEMO_EMAIL=demo@bc4.local
export BC4_DEMO_PASSWORD=... # idem container
export BC4_DEMO_ROLE=ingenieur
bc4-back/scripts/g10_users_policy_roles.sh
```

## 0.8.0 — 2026-10-15 (minor) — CORS front + seed démo env-driven (P1-1, Agent BC1)

### Ajouté
- CORS durci : méthodes explicites (`GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD`),
  en-têtes explicites (`Authorization`, `Content-Type`, `Accept`, `Origin`),
  `expose_headers=[Content-Length, Content-Type]`, `max_age=600`. Le
  préflight OPTIONS est explicitement accepté pour les uploads multipart
  (cell_ref 128 Mo, NMF).
- Origines pilotées **uniquement par env** `BC4_CORS_ORIGINS` (CSV). La
  valeur par défaut en dev couvre `localhost:{5173,5174,8080}` **et**
  `127.0.0.1:{5173,5174,8080}`. `docker-compose.yml` surcharge via
  variable d'env host.
- Seed démo idempotent dans `app/seed/run._seed_demo_from_env` : crée
  le compte à partir de `BC4_DEMO_EMAIL` + `BC4_DEMO_PASSWORD`, rôle
  par défaut `ingenieur` (override via `BC4_DEMO_ROLE`). **Jamais
  demo/demo en dur**. Si l'une des deux env manque, le seed démo est
  sauté (optionnel). Mot de passe hashé argon2id, jamais stocké ni
  loggé en clair.
- Garde `G9` (`scripts/g9_cors_demo.sh` + `tests/test_g9_cors_demo.py`,
  4 assertions) :
  - OPTIONS depuis `BC4_FRONT_ORIGIN` → 200 + `Allow-Origin` cohérent,
    `Allow-Methods` ⊇ {GET, POST, PUT, PATCH, DELETE, OPTIONS},
    `Allow-Headers` ⊇ {Authorization, Content-Type}.
  - OPTIONS depuis une origine inconnue → pas d'`Allow-Origin` (aucune
    fuite permissive).
  - POST `/projects` authentifié avec `Origin: BC4_FRONT_ORIGIN` → 201
    + `Allow-Origin` renvoyé sur la vraie requête.
  - Seed démo : après suppression du compte et appel de
    `_seed_demo_from_env()`, le compte revient ; re-run idempotent.

### Écarts ouverts
- **Aucun pour P1-1.** Les origines sont pilotées par env ; les rôles
  et le mapping (admin/ingenieur/lecteur → admin/editor/viewer) restent
  inchangés depuis 0.7.0 — P1-2 traitera l'enforcement de la password
  policy serveur et la création d'utilisateur.

### Garde (manuel)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
export BC4_JWT_SECRET=... # idem container
export BC4_ADMIN_EMAIL=admin@bc4.local
export BC4_ADMIN_PASSWORD=... # idem container
# optionnel : seed démo
export BC4_DEMO_EMAIL=demo@bc4.local
export BC4_DEMO_PASSWORD=... # idem container
export BC4_DEMO_ROLE=ingenieur
# optionnel : surcharge de l'origine front testée (défaut http://localhost:5174)
# export BC4_FRONT_ORIGIN=http://localhost:5174
bc4-back/scripts/g9_cors_demo.sh
```

## 0.7.1 — 2026-10-15 (patch) — Dimension `arcep_zone` sur `cell_ref` (B1-réf amendement)

Ajouté : dimension `arcep_zone` sur `cell_ref` (migration `0006_cell_ref_arcep_zone`, colonne `TEXT NULL` + index btree), exposée via `arcep_breakdown` sur `/reference/cell/summary` et dans `ImportReport` ; mapping LITTÉRAL depuis `cat_arcep_code` (11 catégories réelles, `01/` à `12/` avec gap `09/` déclaré ouvert dans les données), `"(null)"`/`""` → NULL base ; bucket NULL = clé `"__null"` dans le rapport d'import (NULL non-sérialisable) et `"N/D"` dans le summary (via `_bucket()`, cohérent avec `by_dor`/`by_dr`). Dimension **orthogonale** à la géo — pas dans `/geo/tree`. Zod `ImportReport`/`CellSummary` étendus 1:1. Garde G6 étendue : vérifie `sum(arcep_breakdown) == rows_loaded` sur témoin ; si `BC4_CELL_REF_CSV` est fourni, exige les 11 catégories + bucket N/D en base après rechargement.

## 0.7.0 — 2026-10-15 (minor) — Authentification comptes locaux (B2, Agent BC1)

> Lot « auth » prévu initialement à 0.4.0. Collision de version avec les
> patches 0.4.1 / 0.5.1 / 0.6.1 d'un agent parallèle (BC2) → mon minor
> prend `0.7.0` pour éviter deux entrées sur la même version
> (règle « pas de version muette, pas deux lots sur la même version »).

### Ajouté
- Table `app_user` (migration `0005_app_user`) : `id`, `email` (uniq +
  index `lower(email)`), `password_hash`, `role` ∈ {`admin`, `ingenieur`,
  `lecteur`} (CHECK en base), `active`, `created_at`.
- Service `app/services/auth.py` :
  - `hash_password` / `verify_password` via **argon2id** (`argon2-cffi`).
  - `create_token` / `decode_token` **JWT HS256**, secret
    `BC4_JWT_SECRET` fermé (app refuse de démarrer sans), TTL fermé par
    `BC4_JWT_TTL_MIN` (60 min par défaut).
  - **Temps constant** : si l'email est inconnu, un hash « dummy »
    pré-calculé reçoit la vérif argon2 — pas de timing attack qui
    distinguerait email inconnu / mauvais mdp.
- Endpoints auth :
  - `POST /auth/login` (body `{email, password}`) →
    `{token, token_type:"Bearer", expires_at, user}`. **401 franc** avec
    `code: INVALID_CREDENTIALS`, **même message** pour email inconnu
    ou mdp invalide.
  - `POST /auth/logout` (Bearer requis) → 204. JWT stateless.
  - `GET /auth/me` (Bearer requis) → `PublicUser`.
- Dépendance d'auth au niveau **routeur** sur `/projects`, `/reference`,
  `/projects/*/dict*`, `/projects/*/assistant` : 401 sans Bearer valide.
  Les écritures/uploads conservent `require_role(actor,"admin","editor")`
  → effet « lecteur min lecture, ingenieur min écriture ».
- Seed admin idempotent (`_seed_admin_from_env`) : lit `BC4_ADMIN_EMAIL`
  et `BC4_ADMIN_PASSWORD`. Si l'un manque, le seed crie et saute (écart
  déclaré). Mdp passé argon2id, **jamais stocké en clair, jamais loggé**.
- Garde `G8` (`scripts/g8_auth.sh` + `tests/test_g8_auth.py`,
  8 assertions) : login OK, email inconnu & mauvais mdp → même 401, route
  protégée sans Bearer → 401, avec Bearer → 200, `/auth/me` OK, hash
  stocké préfixé `$argon2`, mdp absent de la DB.

### Modifié
- `tests/conftest.py` : nouvelle fixture `client_noauth` (sans header)
  pour G8 (tests négatifs) et `client` par défaut signé Bearer admin via
  `/auth/login` réel. Tous les gardes G1–G6 passent avec Bearer sans
  autre modification.
- `app/deps.py::get_actor` : lit maintenant **le JWT**
  (via `get_current_user`) au lieu des `X-Actor-*`. Mapping role
  FR → EN (admin/ingenieur/lecteur → admin/editor/viewer) explicite.
  **Les headers `X-Actor-*` ne sont plus honorés.**

### Audité, pas touché
- `response_model_exclude_none=True` sur `/dict/param/map` et
  `/assistant` : audit champ par champ, chaque field susceptible d'être
  `None` dans les handlers actuels est bien `.optional()` côté Zod
  (`MapLegend.{stops,classes}`, `AssistantResponse.error`,
  `AssistantFilters.{op,tech,svc,band,dep}`, `Claim.source_id`,
  `TableColumn.{unit,numeric}`, `BlockTable.formula`). Les champs
  `.nullable()` susceptibles d'être `None` (p. ex. `SummaryItem.value`,
  `MeasurementPoint.{dl,rsrp,sinr,latency}`) ne sont **jamais** émis
  à `None` par le code actuel (toujours un nombre réel) — pas de
  stripping silencieux. Si un handler futur produit `None` sur un
  champ `.nullable()`, la règle « exclusion ciblée champ par champ »
  s'appliquera (patch séparé). Réserve levée.

### Écarts ouverts
- **Pas de revocation list** côté serveur : JWT stateless. Un token
  reste valide jusqu'à `exp` même après `/auth/logout`. Purge
  entièrement côté client. Révocation immédiate = lot ultérieur
  (table `token_blacklist` + check dans `get_current_user`).
- **Pas de reset mdp** : admin créé via seed env, autres comptes
  reportés.
- **Vocabulaire Zod double** : DB en FR, routes B0/B1 en EN. Mapping
  dans `deps.ROLE_DB_TO_API`. Harmonisation complète = lot `major`.

### Garde (manuel)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
export BC4_JWT_SECRET=... # idem container
export BC4_ADMIN_EMAIL=admin@bc4.local
export BC4_ADMIN_PASSWORD=... # idem container
bc4-back/scripts/g8_auth.sh
```

## 0.6.1 — 2026-10-15 (patch) — Câblage au décodeur canonique `bc4_decoder 1.0.0`

### Ajouté
- Câblage à `bc4_decoder 1.0.0` (API dicts plats via
  `decode_nmf_file(path) -> Iterator[dict]`) ; `decoder_version` est
  désormais persistée **depuis le module importé** (`DECODER_VERSION =
  "bc4-decoder 1.0.0"`), plus aucune string hardcodée côté back.
- Migration `0004_stg_event_decoder_fields` : trois colonnes nullable
  ajoutées à `stg_event` — `ts` (horodatage ISO, ATTRIBUT seulement :
  l'ordre canonique reste `(capture_id, seq)` STRICT, jamais `ts`),
  `freq` (EARFCN/UARFCN/ARFCN), `pci` (PCI/PSC). Ces trois attributs
  sortent gratuitement du décodeur ; l'index canonique reste inchangé.
- Bind-mount Docker read-only `./decoder:/opt/nmf_decoder:ro` et
  variable `BC4_NMF_DECODER_PATH=/opt/nmf_decoder` dans `docker-compose.yml`.
  Le décodeur est un artefact SÉPARÉ : pas copié dans l'image, un bump du
  décodeur ne force pas un rebuild de `bc4-api`. Healthcheck préservé.
- Garde G7 (`scripts/g7_nmf_ingest.sh`) étendue : si `BC4_NMF_WITNESS`
  est fourni, lance maintenant la comparaison « compte `n_events` renvoyé
  par `GET /projects/{id}/import` ↔ comptage direct du décodeur en CLI
  (`python3 /opt/nmf_decoder/bc4_decoder.py <témoin.nmf>`) » et exige
  `status=done`. Sans témoin, reste gracieuse et vérifie l'import honnête
  du module (version lue depuis `DECODER_VERSION`).

### Modifié
- Signature de `resolve_decoder()` : charge le module unique
  `bc4_decoder` (plus `nmf_export` + `build_dict`). `DecoderHandle` expose
  désormais `decoder` (module) au lieu de `nmf_export`/`build_dict`.
- `decode_nmf_file()` (consumer interne) itère DIRECTEMENT sur
  `bc4_decoder.decode_nmf_file(path)` — flux de **dicts plats**. Plus de
  parcours à deux niveaux `Capture.events[]`. `capture_id` est agrégé par
  comptage de l'ensemble des `capture_id` vus (le décodeur en garantit
  l'unicité par fichier : `sha256[:12]` du fichier).
- Insert `stg_event` étendu avec `ts`, `freq`, `pci` (bind params
  explicites, pas d'étoile SQL).
- `_strip_identity` défensif conservé mais ne tente **plus** de masquer
  `payload_hex` : le décodeur garantit son intégrité pour l'analyse ASN.1
  aval ; un masquage textuel y corromprait les octets.

### Écarts ouverts
- **PLMN non exposé par `bc4_decoder 1.0.0`** : la clé `plmn` n'est pas
  dans le contrat de dict plat. `operators_seen` (et `project.operators_plmn`)
  restent **vides** tant qu'une source PLMN n'existe pas. Jamais inventé.
  La branche de code qui agrège `operators` existe toujours pour quand
  cette source sera câblée (lot ultérieur).
- Le mapping PLMN → libellé opérateur (Orange/SFR/…) reste reporté comme
  en 0.3.0.

### Garde (à lancer à la main)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
# optionnel : chemin vers un NMF témoin (active la comparaison stricte CLI/API)
# export BC4_NMF_WITNESS=/chemin/vers/temoin.nmf
# optionnel : surcharge du chemin décodeur (par défaut /opt/nmf_decoder puis candidats)
# export BC4_NMF_DECODER_PATH=/home/devmat/BC4/decoder
bc4-back/scripts/g7_nmf_ingest.sh
```

## 0.3.2 — 2026-10-15 (patch) — Mapping 3GPP étendu (bandes réelles ref_cell_4G5G)

### Ajouté
Cinq entrées explicitement ajoutées à la table de mapping
`BAND_MAP` dans `app/services/cell_ref_ingest.py`, suite à l'écart
ouvert remonté par le rapport d'upload utilisateur (186 lignes au total,
3 bandes NR + 2 bandes LTE/NR mixtes) :

| Libellé source | 3GPP | Fréquences | Référence |
|---|---|---|---|
| `LTE900`         | `B8`   | 880–915 / 925–960 MHz FDD | TS 36.101 §5.5 |
| `NR_1400`        | `n75`  | 1432–1517 MHz SDL          | TS 38.101-1 §5.2 |
| `NR_1800`        | `n3`   | 1710–1880 MHz FDD          | TS 38.101-1 §5.2 |
| `NR_2600`        | `n7`   | 2500–2690 MHz FDD          | TS 38.101-1 §5.2 (homologue direct de `LTE2600→B7`, mêmes bornes) |
| `NR_26_GHZ_000`  | `n258` | 24.25–27.5 GHz TDD (FR2)   | TS 38.101-2 §5.2 |

Aucune nouvelle entrée n'est heuristique : chaque libellé source est
cité tel qu'il apparaît dans `ref_cell_4G5G.csv`, et chaque identifiant
3GPP est renvoyé à la section correspondante de la norme (en commentaire
dans le code).

### Comportement
Pas de changement de contrat : `ImportReport.bands_unmapped` reste la
sortie officielle d'un éventuel écart. Les 186 lignes précédemment
chargées avec `band_3gpp = NULL` seront **réalignées à la prochaine
réimportation** du même CSV (upsert idempotent sur `id`).

### Garde
G6 étendu : un test assert `BAND_MAP` contient exactement les
13 entrées attendues (régression impossible silencieusement en cas
d'édition ultérieure).

## 0.3.1 — 2026-10-15 (patch) — Perf cell_ref ingest (COPY STDIN)

### Correctif
- `POST /reference/cell/upload` : la couche d'écriture DB passe de
  `executemany` (lots de 1 000) à **`COPY STDIN` → table TEMP
  `cell_ref_stg` → `INSERT … ON CONFLICT (id) DO UPDATE`** dans une
  transaction unique. Les motifs de rejet, les comptes et la forme
  de `ImportReport` sont rigoureusement inchangés (G6 vert, test
  témoin et test 422 inclus).
  - Avant : 1 m 57 s pour 459 547 lignes.
  - Après : 1 m 14 s pour 459 547 lignes (≈ −36 %).
- Fenêtre d'ingestion plus courte → moins vulnérable à un rebuild
  concurrent du container API. L'idempotence sur `id` n'est pas
  affectée : rejouer le même CSV ne duplique rien.
- Aucun changement de contrat Zod ↔ Pydantic. Aucun changement de
  migration. `BATCH_SIZE` conservé mais inutilisé par cette route
  (laissé exporté pour éviter de casser un éventuel import externe).

## 0.3.0 — 2026-10-15 (minor) — B1-ingest (projet + import/décodage NMF)

### Ajouté
- Trois tables (migration `0003_nmf_ingest`) :
  - `nmf_file` (métadonnées upload : `sha256`, `size_bytes`,
    `decoder_version`, `status` ∈ {pending, decoding, done, error},
    `error_msg`, comptes réels `n_captures / n_events / n_gps`).
    **Contrainte unique `(project_id, sha256)`** → re-upload du même
    fichier dans le même projet est idempotent, pas de ré-décodage,
    pas de doublon `stg_event`.
  - `stg_event` (staging aplatie du décodeur : `project_id`,
    `nmf_file_id`, `capture_id`, `seq`, `event_code`, `system`,
    `channel`, `direction`, `message`, `payload_hex`, `lat`, `lon`).
    Index `(project_id, capture_id, seq)` — **ordre canonique
    `(capture_id, seq)` STRICT, JAMAIS `ts`.**
  - Huit colonnes de résumé ajoutées à `projects` (nullable, les
    projets seedés B0 restent intacts) : `created_at`, `actor`,
    `status_ingest` ∈ {draft, importing, ready, error},
    `operators_plmn` (JSON, PLMN→n events), `technos_seen` (JSON,
    LTE/NR→n events), `n_captures_ingest`, `n_events_ingest`,
    `gps_coverage_pct`. Toutes remplies à l'ingestion depuis des
    **comptages SQL réels**, jamais calculées à l'avance.
- Endpoints FastAPI (`app/routes/projects.py`) :
  - `POST /projects` (body `{name}`) → crée un projet draft, actor
    renseigné depuis `X-Actor-Login`. Les colonnes Zod existantes
    (`operators`, `technologies`, etc.) sont initialisées à `[]`/`0`
    pour rester 1:1 avec le schéma Zod du front, et seront
    recalculées à mesure que les NMF arrivent.
  - `POST /projects/{id}/nmf` : upload multi-fichiers streamé
    (chaque fichier passe par un `NamedTemporaryFile` disque et un
    hash SHA256 à la volée — jamais tout en RAM). Limite 2 GiB par
    fichier, bascule disque au-delà de 32 MiB. Idempotent sur
    `(project_id, sha256)`.
  - `GET /projects/{id}/import` → `NmfImportReport` reconstruit à
    partir des rangs `nmf_file` et de requêtes `COUNT(*)` sur
    `stg_event`. `gps_coverage_pct` est `None` quand `n_events == 0`
    (jamais remplacé par 0).
  - `GET /projects/{id}/ingest` → `ProjectIngestView` (vue
    draft/importing/ready/error, sans toucher au contrat Zod existant
    de `GET /projects/{id}`).
- Deny-list d'identité d'abonné appliquée AU NIVEAU DU PERSISTAGE
  dans `app/ingest/nmf.py::_strip_identity` : les clés `imsi`,
  `msisdn`, `imei`, `imeisv`, `tmsi`, `s_tmsi`, `guti`, `m_tmsi`,
  `ptmsi`, `subscriber_id` sont retirées de l'event aplatis AVANT
  insertion `stg_event`. `payload_hex` reste brut (champs non-identité
  jamais masqués, cf. règle).
- Schémas Pydantic (`app/schemas/ingest.py`) 1:1 avec le contrat
  décrit en mission : `NmfImportReport` (`files_received`,
  `files_done`, `files_error`, `by_file[]`, `n_captures`, `n_events`,
  `gps_coverage_pct` nullable, `operators_seen`, `technos_seen`).
- Résolution honnête du décodeur externe
  (`app/ingest/nmf.py::resolve_decoder`) : cherche `nmf_export.py` et
  `build_dict.py` dans `BC4_NMF_DECODER_PATH`, `/opt/nmf_decoder`,
  `/home/devmat/nmf_decoder`, `/home/devmat/BC4/decoder`. Si trouvé,
  lit `DECODER_VERSION` ou `__version__` et l'inscrit dans
  `nmf_file.decoder_version`. Si absent : fichier marqué
  `status=error`, `error_msg="decoder_unavailable: …"`, zéro event
  injecté — l'écart est **déclaré**, pas comblé par heuristique.
- Garde G7 (`scripts/g7_nmf_ingest.sh` + `tests/test_g7_nmf_ingest.py`) :
  crée un projet via l'API, uploade un NMF témoin (ou un placeholder
  si `BC4_NMF_WITNESS` n'est pas fourni), vérifie l'idempotence sur
  sha256, le comptage réel renvoyé par `/import`, et que l'absence
  de décodeur produit un `status=error` propre (jamais masqué par
  des zéros silencieux).

### Écarts ouverts
- **Décodeur NMF non livré dans bc4-back** : les symboles
  `nmf_export` / `build_dict` ne sont pas présents dans ce dépôt ni
  dans les arborescences `/home/devmat/*` connues (seuls des
  décodeurs **`.lcbin` Nokia** sont disponibles — format différent).
  Le module `app/ingest/nmf.py` est câblé pour les charger dès
  qu'ils seront déposés (via `BC4_NMF_DECODER_PATH` ou l'un des
  chemins listés). Tant qu'ils ne sont pas disponibles, un upload
  NMF est accepté, streamé, hashé, enregistré en `nmf_file` avec
  `status=error` + `error_msg=decoder_unavailable` + comptes = 0 ;
  aucun event n'est produit. Le CHANGELOG déclare l'écart au lieu
  de le masquer. **Aucun bump de release côté décodeur** : rien n'a
  bougé puisqu'il n'y en a pas à bumper dans ce lot.
- **Mapping PLMN → libellé opérateur** (Orange/SFR/…) non livré :
  `operators_plmn` stocke `{PLMN: n_events}` tel que vu par le
  décodeur. Le libellé opérateur est reporté à un lot ultérieur
  (nécessite une table de référence PLMN) ; la vue
  `ProjectIngestView.operators` expose donc le comptage par PLMN,
  pas le libellé. Jamais deviné.
- **Mapping status ingest → status Zod** : le front voit toujours
  les trois valeurs Zod existantes (`ready` / `processing` /
  `failed`). Le détail interne (`draft` / `importing` / `ready` /
  `error`) est exposé via `GET /projects/{id}/ingest`.

### Garde (à lancer à la main)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
# optionnel : chemin vers un NMF témoin + emplacement du décodeur
# export BC4_NMF_WITNESS=/chemin/vers/temoin.nmf
# export BC4_NMF_DECODER_PATH=/chemin/vers/decoder
bc4-back/scripts/g7_nmf_ingest.sh
```

## 0.2.0 — 2026-10-15 (minor) — Référence cellulaire (B1-réf)

### Ajouté
- Tables `cell_ref` (PostGIS `geometry(Point, 4326)`, index GIST) et
  `reference_import` (JSONB du rapport, provenance de chaque upload).
- `POST /reference/cell/upload` — multipart `UploadFile`, limite 256 Mo
  dur, buffer disque au-delà de 16 Mo. Le CSV est streamé (jamais
  chargé en mémoire), l'en-tête est validé avant l'ingestion (422 si
  colonne attendue manquante — rien d'inséré), les lignes sont
  insérées par lots de 1000 via `INSERT … ON CONFLICT (id) DO UPDATE`
  (idempotent).
- Mapping bande fixé par **table** (`LTE800→B20`, `LTE700→B28`,
  `LTE1800→B3`, `LTE2100→B1`, `LTE2600→B7`, `NR_700→n28`, `NR_2100→n1`,
  `NR_3500→n78`). Toute autre valeur est **comptée dans
  `bands_unmapped`** et jamais devinée — écart ouvert déclaré au
  rapport.
- Rejets motivés : `bad_rat`, `missing_id`, `missing_eci` (4G),
  `missing_nci` (5G), `bad_position` (lat/lng hors bbox France
  métropolitaine [40, 52] × [−6, 11]). On ne filtre pas sur `etat` :
  la colonne reste présente et comptée dans `etat_breakdown`.
- `GET /reference/cell/imports` — historique des uploads
  (plus récent d'abord), avec l'`ImportReport` complet par entrée.
- `GET /reference/cell/summary` — total + buckets `by_rat`,
  `by_band_3gpp`, `by_dor`, `by_dr` ; les lignes sans valeur sont
  déclarées `N/D`, jamais remplacées par 0.
- `ImportReport` Pydantic exposé 1:1 côté Zod (champ pour champ).
- Garde `G6` : upload d'un lot témoin (lignes conformes + rejets
  variés), vérifie les comptes réels, l'idempotence, le motif
  `bands_unmapped` sur une bande hors table, le 422 d'en-tête invalide
  et que `/summary` et `/imports` reflètent la base.

### Écarts ouverts
- Bbox France métropolitaine seulement — DOM-TOM pas pris en compte
  en B1-réf (une mesure Guyane/Réunion sera rejetée en `bad_position`).
  À élargir quand la stack couvre ces territoires.
- `bands_unmapped` reste visible dans le rapport ; aucune nouvelle
  bande n'est ajoutée automatiquement à la table de mapping — il faut
  passer par une migration explicite.

### Garde (à lancer à la main)
```
export BC4_DSN=postgresql+psycopg://bc4:bc4@localhost:5432/bc4
export BC4_API_BASE=http://localhost:8000
bc4-back/scripts/g6_cell_ref.sh
```

## 0.1.1 — 2026-10-15 (patch) — Parité sérialisation Zod

### Correctif
- `GET /projects/{id}/dict/param/map` et `POST /projects/{id}/assistant`
  utilisent désormais `response_model_exclude_none=True` : les champs
  Zod déclarés `.optional()` (comme `MapLegend.classes`,
  `AssistantResponse.error`, `AssistantFilters.op/tech/svc/band/dep`)
  n'apparaissent plus comme `null` dans la réponse, ce qui rejetait
  le `.optional()` côté Zod côté front. Détecté lors du smoke de bc4-front
  (G2). Pas de changement de contrat — alignement sur le Zod existant.

## 0.1.0 — 2026-10-15 (minor, initial release)

Lot B0 : parité des contrats + seed. But final atteint : débrancher le mock
du front `franco-focus-forge` et lancer **front + back** de bout en bout.

### Ajouté
- FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL (image PostGIS, extension
  activée dès la migration initiale pour préparer B1).
- Modèles Pydantic v2 écrits **1:1** contre les schémas Zod lus dans
  `franco-focus-forge/src/lib/api/*-schemas.ts` (champ pour champ, type
  pour type, nullabilité pour nullabilité).
- Endpoints HTTP alignés sur les fonctions des adaptateurs mock :
  - `POST /auth/login`, `GET /auth/me`
  - `GET /projects`, `GET /projects/{id}`, `GET /projects/{id}/overview`
  - `GET /kpi/catalog`
  - `GET /projects/{id}/dict`, `/dict/tree`, `/dict/params`, `/dict/param`, `/dict/param/map`
  - `POST /projects/{id}/assistant`, `GET /projects/{id}/conversations`
  - `GET /settings/appearance`, `/organization`, `/about`
  - `GET /settings/users`, `/geo`, `/kpi`, `/ai`, `/ai/enabled`
- Script seed **idempotent** (`python -m app.seed.run`) :
  - 6 projets (dont « Paris 2026 Q1 » LTE+NR et « Rennes LTE (sans NR) »)
  - 7 messages RRC (4 LTE + 3 NR), 12 paramètres (8 LTE + 4 NR), règles
    de conversion 3GPP (TS 36.331 §6.3.4, 36.133 §9.1.4/9.1.7, 38.133
    §10.1.6/10.1.16)
  - jusqu'à 900 points de mesure par projet, observations RRC par
    projet × param (branche NR vide pour Rennes)
  - Catalogue KPI (3 KPI + 7 groupes + synthèse `RRC_SR`)
  - 4 comptes de démo (`demo.ingenieur` admin, `m.martin` editor,
    `p.leroy` viewer, `s.bernard` viewer inactif)
  - Singletons settings (appearance, organization, password_policy,
    api_permissions, ai_config), référentiel géo
- `docker-compose` à la racine du dépôt BC4 : `db` (postgis/postgis:16-3.4)
  + `api` (bc4-back) + `front` (bun run dev sur `franco-focus-forge`).
- Table `assistant_exec_steps` : les étapes d'exécution renvoyées par
  `POST /projects/{id}/assistant` sont lues depuis le seed, pas inscrites
  en dur dans le handler (G5).
- Gardes G1–G5 avec scripts `scripts/g*.sh`. **Aucune CI** : chaque
  garde se lance à la main. Chaque garde crie si DSN/BC4_API_BASE est
  absent.
- Un ordre canonique `(capture_id, seq)` est présent dans
  `measurement_points` et `rrc_observations`, prêt pour B1.

### Écarts ouverts (déclarés, pas comblés)
- **Fixtures byte-identiques** : les volumes et distributions
  correspondent au mock, mais les valeurs numériques exactes
  diffèrent (PRNG Python ≠ `mulberry32` TS). Impact : nombres
  d'échantillons par bin légèrement différents entre démo front
  (mock) et démo back (seed). Le front doit afficher la **même
  démo** en terme de forme et de volumétrie, pas des valeurs
  identiques.
- **Identité en base (B2)** : `POST /auth/login` accepte un mot de
  passe non vide pour un compte seedé actif ; aucun hash n'est
  stocké. Les headers `X-Actor-Login` / `X-Actor-Role` portent la
  session côté front.
- **Mutations admin lourdes** : `POST /settings/users`,
  `POST /settings/geo/import`, `POST /settings/kpi`, `PUT /settings/ai`
  renvoient `501 NOT_IMPLEMENTED`. Les GET exposent le seed en
  lecture seule.
- **Historique conversations assistant** :
  `GET /projects/{id}/conversations` renvoie `[]`. Les endpoints
  `createConversation`/`rename`/`delete`/`appendMessages` sont
  MOCK-ONLY côté front (commentaire explicite dans
  `assistant-schemas.ts`) et ne sont pas servis par B0.
- **Scénarios assistant** : `POST /projects/{id}/assistant`
  renvoie un `scenario=b0_sample_count` neutre (comptage de
  l'échantillon filtré) ; la logique scénario (rrc_success, nr_bands,
  endc, etc.) est reportée au lot B2.
- **GeoJSON `type: "Feature"`** : le schéma Zod rend `type` optionnel
  (`type: z.literal("Feature").optional()`), notre réponse le fournit
  toujours — plus strict que le schéma, pas de régression.

### Notes de garde
- Les gardes sont lancées **à la main** (pas de CI dans le dépôt).
- `BC4_DSN` et `BC4_API_BASE` sont obligatoires ; sans ces variables,
  les scripts échouent avec un message explicite (voir `scripts/_lib.sh`).
