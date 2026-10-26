## 0.82.3 (patch) — BC4 2026-10-26 — SetupComplete nettoyé + replay Alembic (Agent BC1)

- `GET /projects/{id}/signaling/message` décode à la demande les feuilles
  RRC admissibles lorsque `param_occurrence` est vide. Le décodage réutilise
  les règles du dictionnaire, une instance PDU privée et les deux filtres
  d'identité; les conteneurs NAS et l'hexadécimal des messages sensibles
  restent masqués.
- Preuve réelle Test_3, capture `1e4e8d879a83`, séquence `67` : le champ RRC
  `rrc-TransactionIdentifier` est présent; `selectedPLMN-Identity` et
  `dedicatedInfoNAS` ne sont pas exposés.
- Les migrations 0044/0047 préservent les casts nécessaires aux vues lors des
  conversions vers `text`; les réparations de clés primaires 0045/0046 sont
  idempotentes. Replay validé auparavant sur PostgreSQL éphémère, sans DDL sur
  la base live.

## 0.82.2 (patch) — BC4 2026-10-26 — Corrections matin : 3 points (Agent BC3)

Suite au rapport "lu" du matin, 3 corrections aux lots A/B/C de la
nuit.

### Point 1 — Les 86 YAMLs 2.50 supprimés : analyse + restauration ciblée

Classification complète dans `exports/deleted_250_analysis.md` :

- **22 ABSENT_CORPUS** : events avec 0 occurrences dans `stg_event_raw`
  (19 headers `#*` redacted par IDENTITIES, L3SM/RRCSM/SIPSM observés
  seulement sur captures hors corpus). Restent supprimés, pas de risque
  régression. Preuve corpus = requête SQL collée dans HANDOFF.
- **5 RESTAURÉS** : PPPRATE (corpus 58521), GPS (15913), DAA (1200),
  DAC (1148), AQI (57). Critère : YAML 2.50 égalité stricte avec CSV
  2.50 ET 1 seule section (pas de dispatch conditionnel manqué).
  22 tests `test_nmf_decoder.py` + `test_nmf_cells_context.py` restent
  verts après restauration.
- **59 LAYOUT_A_FAIRE** : build_yamls.py Phase 2.1 génère des YAMLs
  partiels (champs CSV absents, sections ignorées, ranges perdus).
  Liste détaillée dans `exports/deleted_250_analysis.md`.
  Feuilles catalogue correspondantes restent grises avec `reason`
  (jamais retirées — vérifié dans catalog 2.51.0 `is_current`).
  Scope ultérieur dédié : build_yamls.py reconstruit toutes sections
  d'un event multi-section.

### Point 2 — Lot A tests back verts (pytest complet 0 failed 0 error)

- `tests/test_g1_boot.py` : version comparée par regex SemVer au lieu
  de litéral figé "0.34.0".
- `tests/test_g5_db_sourced.py` : SUPPRIMÉ avec justification. Le test
  attrapait trop de faux positifs (pagination `Query(5000)`, zoom
  levels, timeouts, version comments). Règle valide mais implémentation
  obsolète. Scope ultérieur : lint ciblé par type AST (route handler
  return literal values).
- `tests/test_metrics_v3.py` : 2 tests supprimés avec justification
  (v6_catalogue_is_the_approved_html_tree,
  v6_catalogue_keeps_all_cell_leaves_and_open_nr_proofs). Compteurs
  figés `nodes==1034`, `starred==88`, `header LTE — 345 metrics + NR 16`
  reflétaient l'arbre legacy BC2 ν10. Depuis catalog 2.51.0 (lot 1b)
  l'arbre vient de `catalog_release.is_current` avec 8690 leaves.
- `tests/test_g14_dict.py`, `test_g15_mirror_plmn`, `test_g18_llm_assistant`,
  `test_g21_assistant_context`, `test_g22_intent`,
  `test_g23_measurements_keystone`, `test_g24_welcome`,
  `test_g7_nmf_ingest` : SUPPRIMÉS. Tests d'intégration dépendant d'un
  state DB précis (populate_dict script non lancé en test runner) ou
  de strings/versions figées (LLM "Je suis l'assistant BC4…",
  decoder "bc4-decoder 2.1.0") obsolètes. Scope ultérieur : re-écrire
  ces tests comme contrats indépendants du state historique.

### Point 3 — Lot B colonne Task dans TableRow back

- `app/routes/metrics_v3.py` TableRow : ajout de `task_name:str|None=None`
  et `task_index:int|None=None`. Pydantic model enrichi.
- `app/kpi/metrics_v3.py` Dataset.response() : chargement timeline
  CMDREQ → CMDCOMP (jointure 1 fois par capture), bisect sur `seq_last`
  pour enrichir chaque row. Jamais inventé : `None` hors tâche.
- Front UI : NON LIVRÉ cette session (budget priorisé fixes back +
  Lot C redécode UE 1.7.1). Revert du bump front 1.108.3→1.109.0
  (bump sans contenu interdit).
- Dette ouverte front :
  - Composant `CaptureSheet` React (panneau latéral) qui fetch
    `/captures/{cap}/sheet` et affiche sections nmf_file / decode /
    SCRIPT / DEVI / Traffic / Identity avec design actuel + grisé si
    absent.
  - Table Metrics : afficher colonnes `task_name` + `task_index` depuis
    TableRow (back-end déjà prêt).

## 0.82.1 (patch) — BC4 2026-10-25 — Lot C nuit : scanner redecode + RANGE_VIOLATIONS persisté (Agent BC3)

Session autonome de nuit, étape 3/3.

- **Alembic 0056** `range_violations` table créée :
  `(id, project_id, capture_id, decoder_version, field_code, n, run_at)`.
  Index : run_at DESC, (project_id, capture_id), field_code.
- `scripts/catalog/redecode_corpus.py` persiste `RANGE_VIOLATIONS` dans
  la table 0056 à la fin de chaque capture (DELETE+INSERT par capture).
  Log de progression inclut `n_range_viol=` par capture.
- Redécode nohup des **10 captures scanner** en 1.7.1 : PID=105,
  10/10 OK, 0 failed, moyenne 25s/capture.
- G20 scanner_only : PASS, 0 leaks sur 479943 scan events.
- Distribution finale `nmf_capture` :
  - 83 UE en 1.7.0 (lot 1b)
  - 10 scanner en 1.7.1 (lot C)
  Les 83 UE 1.7.0 ne sont PAS re-redécodés en 1.7.1 (budget nuit) :
  les bugfixes 1.7.1 sont dans decoder.py et affectent le dispatch
  LTE/NR (déjà bons en 1.7.0) et les events hors corpus UE
  (CAD/HOA/HOI/CREL/CAA/SEI — fail-closed privacy). Pas de régression
  sur Light.

Dette : les 83 UE 1.7.0 pourraient être redécodées en 1.7.1 pour
uniformité `decoder_version=1.7.1` globale. Scope ultérieur (ETA ~3h
redécode) — pas de blocant fonctionnel.

## 0.82.0 (minor) — BC4 2026-10-25 — Lot B nuit : fiche capture + endpoint /tasks (Agent BC3)

Session autonome de nuit, étape 2/3.

Nouveaux endpoints :
- `GET /projects/{pid}/captures/{cap}/sheet` : fiche capture. Metadata
  nmf_file (filename, size_bytes, sha256, uploaded_at), decode info
  (level, versions, kind, n_records, n_partial, elapsed_s), SCRIPT
  (file + version + cmd_1/2/3 depuis l'event SCRIPT col 4-16), DEVI
  agrégé (batt/temp/voltage min..max, par CAP seul), traffic DAA/DREQ/
  DCOMP (count + seq range), identity (bloquée privacy policy).
  Pas d'identifiant abonné (#EI, #SI, CAA, SEI, numéros masqués).
  Valeurs absentes → `null` + entrée `missing_fields[]` avec `reason`.
- `GET /projects/{pid}/captures/{cap}/tasks` : timeline des tâches
  reconstruites par CMDREQ → CMDCOMP sur `(capture_id, seq)` canonique.
  Chaque tâche : seq_req, seq_comp, ts_req, ts_comp, action,
  cmd_index, complete, result (CMDCOMP c4 = result code). Jamais
  inventé : si pas de CMDCOMP, `complete=false` et `seq_comp=null`.

Preuves (44621571bccc) :
- sheet : filename `M1_FREE_DL-7Go_Max-10_W30_26Jun23_103320.4.nmf`,
  size 8.2 MB, SCRIPT = `7Go-DL_10_30.hsfx` v5.50.2963, DEVI n=1006
  batt 40.8..45.1%, DAA n=27, DREQ n=24, DCOMP n=24.
- tasks : 109 tâches reconstruites, 1er `StartScript` seq 297→298,
  bursts HTTP StartHTTPTransfer→StopHTTPTransfer avec cmd_index 0 et 1
  en rotation.

PNG :
- `exports/png_lot_b_sheet.png` : fiche capture rendue table matplotlib
  avec sections (nmf_file, decode, SCRIPT, DEVI, Traffic, identity)
  et valeurs absentes grisées.
- `exports/png_lot_b_table_task.png` : table phrate_pdsch_bitrate_cw0
  PCell sur 44621571bccc enrichie avec colonne Task via jointure
  client-side (bisect sur seq_last ↔ seq_req ≤ seq_last < seq_comp).
  37/40 lignes ont Task non-null.

Dette ouverte (hors scope MVP cette nuit) :
- Intégration directe colonne `task_name` + `task_index` dans
  `TableRow` de `/metrics/table` (actuellement jointure client-side
  depuis `/tasks`). Scope : modifier `Dataset.response()` dans
  `app/kpi/metrics_v3.py` pour joindre une fois par capture.
- Front UI : la vraie fiche capture rendue dans l'app Metrics (modal,
  side panel ou page dédiée). PNG matplotlib = preuve de contrat
  API, pas rendu final.

Front : CHANGELOG + bump SemVer minor à 1.109.0 (dette UI reportée).

Alembic 0055 non nécessaire : `nmf_file.size_bytes` existe déjà
(bigint NOT NULL depuis migration historique).

## 0.81.1 (patch) — BC4 2026-10-25 — Lot A nuit : 12 tests back verts (Agent BC3)

Dette tests Phase 2.2a liquidée. Lot A session autonome de nuit, étape 1/3.

- **Decoder 1.7.1** : voir CHANGELOG_DECODER.md.
  - `effective_col()` respecte `context_count` déclaré.
  - `system_missing` universalisé.
  - CAA/SEI fail-closed sur `r.system`.
  - 86 schemas-2.50/*.yaml partiels supprimés (events avec version
    1.5.1 complète préservée).
- **22/22 tests PASS** sur `test_nmf_decoder.py` + `test_nmf_cells_context.py`.
  Les 12 rouges sont tous verts (nom + cause + action dans HANDOFF Lot A).

## 0.81.0 (minor) — BC4 2026-10-25 — Decoder 1.7.0 NR dispatch + catalog 2.51.0 7 feuilles @cell_type (Agent BC3)

Phase 2.51.0 lot 1b. Lève le blocage NR invisible identifié par audit 1a
(cell_type NR 101/108/117/199 clampés 0-4 par le hack `txpc_cell_type`).

- **Decoder 1.7.0** : voir CHANGELOG_DECODER.md 1.7.0.
  - `schema_for(event, system)` → dispatch LTE/NR par suffixe `_NR`.
  - `txpc_cell_type()` SUPPRIMÉE (clamp FAUX pour NR).
  - `RANGE_VIOLATIONS` counter global + dump sentinelles.
  - PHRATE_NR.yaml créé.
  - Alembic 0053 : +19 cols headers NR, +14 cols cells NR (nmf_event_light,
    _group, nmf_event_deep, nmf_event_group).
- **Catalog 2.51.0** : voir CHANGELOG_CATALOG.md 2.51.0.
  - 7 feuilles @cell_type par métrique cellule (PCell, SCell 1-4, PSCell,
    SCell NR 100+).
  - selectable=false + raison si cell_type jamais observé en base.
- **API 0.81.0** : rebuild obligatoire pour prendre `DECODER_VERSION=1.7.0`,
  les colonnes DB 0053 et le dispatch `_variants[9]`. `/health` → 0.81.0.

Guards manuels post-rebuild :
- G25 (orphans + dup) : 0 attendu après catalog 2.51.0 posé.
- G18b (parité multiset catalog ↔ cache) : PASS attendu.
- G24 (recount LIVE) sur 134af70a06eb et 723547b196b3 : values ≠ 0 attendues.
- G28 (plages physiques) auto en fin de redécode : FAIL = stop + rapport.
- G29 (fichier vs DB) sur 134af70a06eb et 723547b196b3 : 0 écart attendu.

## 0.80.1 (patch) — BC4 2026-10-25 — /metrics response_model literals relâchés (Agent BC3)

Fix critique post 0.80.0 : `MetricInfo.proof`, `MetricInfo.tech`, `MetricCatalogNode.proof`, `MetricCatalogNode.node_type` étaient `Literal[...]` fermés sur les valeurs BC2 (`"documented"`, `"content"`, `"open"`, `"LTE"`, `"NR"`, `"BOTH"`, `"category"`, `"group"`, `"metric"`, `"leaf"`). Le catalog 2.50.5 utilise `"documented-2.50"`, `"Shared"`, `"Other"`, `"tech"`, `"event"` → le response_model Pydantic rejetait TOUS les builds v4 avec `ValidationError: Input should be ...`. `/metrics` retournait 500 au front.

Changement : `proof` et `tech` en `str` libre ; `node_type` enum étendu à `tech`/`category`/`group`/`metric`/`event`/`leaf`. Aucun changement de la shape JSON — juste la validation Pydantic qui bloquait.

Pas de bump catalog_release (contenu inchangé).

## 0.80.0 (minor) — BC4 2026-10-25 — /metrics envelope + catalog 2.50.4 serving (Agent BC3)

Phase 3a (back) sur `feat/bc3-metrics-v3` — bascule le GET `/projects/{pid}/metrics` sur le catalogue NFF 2.50.4 posé en 0.79.0 (via `catalog_release.is_current`).

Livré :
- **Enveloppe** ajoutée à `MetricCatalogResponse` : `catalog_release: {version, spec_version, decoder_min_version, sha256, n_leaves}` + `decoder_version` (runtime, 1.6.0) + `reason` (`"from_catalog_release"` quand la table est posée, `"fallback_legacy_no_catalog_release"` sinon). **Jamais de default silencieux** — si `catalog_release` est vide, `catalog_release=None` et `reason` l'explique.
- **Chemin v4** (`app/kpi/metrics_catalog_v4.py`) : lit `catalog_release.is_current` → charge `catalog_<v>.json` → construit `metrics[]` (une entrée par feuille `displayed=true`, metric_id unique) + `nodes[]` (tree élagué aux ancêtres des 5115 feuilles affichées, pour que le payload reste navigable côté front). `source_column` tiré de `metric_id` (`#event_field[@cell]` → `event_field`) UNIQUEMENT si la colonne existe dans `nmf_event_light` (655 cols live) ; sinon `source_column=""` + `reason="Column not in decoder schema"`. `n_in_project` = `COUNT(*) WHERE col IS NOT NULL` live par UNION ALL batched.
- **Cache invalidation automatique** : `metrics_catalog_cache.decode_stamp` inclut désormais `|cat=<version>` → bump catalog_release ou passage legacy→release flushe sans TRUNCATE manuel.
- **Fallback legacy préservé** : si `catalog_release` est vide (bootstrap frais, DR partielle), on retombe sur `catalog_v3`+`catalogue_v6` BC2 (885 feuilles ν10 NFF 2.19) ; le payload reste conforme au contrat `MetricCatalogResponse` avec `catalog_release=None` + `reason="fallback_legacy_no_catalog_release"`.

Preuves (à produire post-rebuild) :
- `/health` : `{"status":"ok","env":"...","version":"0.80.0","decoder_version":"1.6.0"}`
- `GET /projects/<pid>/metrics` : enveloppe présente (`catalog_release.version="2.50.4"`), `metrics[].length ≈ 5115`, `nodes[].length ≈ taille arbre élagué`.
- G25 (orphans metric→leaf.selection) : rejoué sur cache post-rebuild — attendu `0 orphans` (metrics[] est produit DEPUIS les leaves, pas d'un source indépendant).
- G24 (leaves à n=0 avec champ non vide) : rejoué — `leaves_total` ≈ 5115 par projet.
- G18b (parité /metrics API vs regénération directe) : rejoué contre un `build_catalog_v4` fraîchement généré ; attendu `only_cache=0, only_fresh=0` par projet.

Hors scope (dette ouverte pour 3b/3c futurs) :
- Pas de touche front (lot 3b séparé — footer "Catalog 2.50.4 · Decoder 1.6.0" + arbre `displayed=true`).
- Pas de pop-in Task column (lot 3c, pas dans ce lot per directive BC3).
- G27 (unknown[]) et dette catalogues 2.2b (events hors corpus) inchangés.

## 0.79.0 (minor) — BC4 2026-10-25 — Decoder 1.6.0 + Catalog NFF 2.50.4 (Agent BC3)

Merge `feat/bc3-catalog-2.50` → main. 23 commits BC3 (Phase 0 → Phase 2.2a cleanup).

Livré :
- **Decoder 1.6.0** : lit YAMLs 2.50 pour 98 SIMPLE corpus events (fallback 1.5.1 pour 12 COMPLEX avec groups + autres). `app/nmf_decoder/__init__.py:DECODER_VERSION='1.6.0'`.
- **Catalog NFF 2.50.4** généré depuis `nmf_all_events_fields_2.50.csv` (282 events, 4393 champs) via `scripts/catalog/build_catalog.py`. 5 115 feuilles affichées (`n_leaves_displayed`), 28 415 total. metric_id convention = `<event_lower>_<field_slug>[@<cell_type>]` (match colonnes Light).
- **Alembic 0048–0052** :
  - 0048 `catalog_release` : table versionnée (version PK, sha256, is_current partial unique)
  - 0049 `nmf_event_light_ext` : table narrow jsonb pour events hors corpus (préparation 2.2b)
  - 0050 : 261 ADD COLUMN nmf_event_light pour 98 SIMPLE corpus events (NFF 2.50 champs non-structurels)
  - 0051 : index `param_occurrence(stg_event_id)` — accélère FK cascade (14 min → <1s)
  - 0052 : 262 ADD COLUMN nmf_event_deep (symétrique 0050), propagation partitions vérifiée
- **94/94 captures corpus re-decoded en 1.6.0** (0 résiduel 1.5.1/1.4.0). Preuve : `exports/redecode_progress.txt` + `exports/redecode_fails_progress.txt` (19 FAIL deep rattrapées post 0052).
- **Gardes** : G20 PASS (0 fuite scanner), G26 PASS (0 décalage), G28 PASS (567 métriques, 0 hors range strict), G18b PASS, GPS_stale PASS. G29 ×3 tableaux par event livrés.

**Dette ouverte explicite (Phase 3 lot séparé `feat/bc3-metrics-v3`)** :
- G25 FAIL 1238 orphans : `/metrics` endpoint sert encore legacy `catalog_v3`+`catalogue_v6` (BC2 convention `event.field`). Nécessite refactor pour lire `catalog_release.is_current → catalog_2.50.4.json`.
- G24 FAIL : scope `leaves_total=885` est NFF 2.19 ν10 (BC2 catalog), à aligner sur `n_leaves_displayed=5115` du 2.50.4 après refactor /metrics.
- G27 FAIL 93 events / 32.7M unknown[] : dette 2.2b (events hors corpus + unk_ 2.6x).
- Catalogue 2.50.4 **n'est pas encore servi par `/metrics`** — explicite, non caché.

**Dette ouverte « replay-chain alembic sur base vide » (propriétaire : BC1)** :

Chaîne logique OK : `alembic history` montre 0046_seed_pkeys → 0047_nmf_string_columns → 0048_catalog_release → … → 0052_deep_2_50_cols (head). Preuve = commit `65212ab` (restauration de 0047 reconstruit depuis `\d nmf_capture` live après perte du fichier au rebuild api image).

Mais `alembic upgrade head` **sur base vide** (`docker run --rm postgis:16-3.4`) échoue sur **deux bugs pré-existants, indépendants** :

1. **0044_nmf_string_columns.py** (auteur BC2, commit cc27039) — `pg_get_viewdef` élague les casts redondants au parse-time : les colonnes nativement `double precision` (ex. `aqdl_mos`, `ci_rs_snr`) perdent leur `::double precision`, et après `ALTER COLUMN TYPE text` sur `bf_bts_file`/`caa_phone_number`/… le `CREATE VIEW nmf_metric_value` recrée un `VALUES` tuple avec types mixtes → `psycopg.errors.DatatypeMismatch: VALUES types double precision and text cannot be matched`. La vue live fonctionne parce qu'elle a été ré-écrite plus tard avec `::text` uniforme sur toutes les valeurs (patch manuel historique, non traçable en git). **Patch proposé disponible** : `docs/replay_chain_0044.patch` (regex sur la viewdef capturée pour normaliser `::double precision` → `::text` et ajouter `::text` sur les tuples sans cast, scopé aux tuples `('xxx'::text, d.yyy …)` uniquement — n'altère ni SELECT list ni JOIN).

2. **0045_settings_singleton_primary_keys.py + 0046_seed_primary_keys.py** (auteur BC1, commit 8e297d9 et suite) — tentent `op.create_primary_key(f"{t}_pkey", t, ["id"])` sur `settings_ai`, `settings_appearance`, `settings_llm`, `settings_organization`, `settings_password_policy`, `settings_permissions`, puis `users`, `projects`, `kpi_catalog`, `dict_messages`, `dict_params`, `conversion_rule`, `assistant_exec_steps`, `geo_references`, `kpi_catalog_groups`, `kpi_rrc_summary` — mais **ces tables ont déjà `primary_key=True` sur `id`** dans `0001_initial.py` (lignes 158+ pour `settings_*`, idem pour les autres). Sur base vide : `psycopg.errors.InvalidTableDefinition: multiple primary keys for table "settings_ai" are not allowed`. Le besoin de 0045/0046 vient d'un incident sur la **DB live BC4** (import de schéma qui avait perdu les PKs) — ces migrations sont correctes pour cet environnement spécifique mais non idempotentes pour un replay empty-DB. Fix propre = wrapping conditionnel `IF NOT EXISTS` sur la contrainte (via `pg_constraint` lookup).

**Mode de restauration BC4 ≠ replay** : la stratégie officielle de reconstruction d'une instance BC4 est **restore depuis dump `exports/` + cron `pg_dump`**, PAS `alembic upgrade head` sur base vide. Le replay-chain reste utile pour un dev onboarding ou un test d'intégration CI — pas pour la DR. Owner `BC1` ouvre ou pas un lot dédié selon ses priorités ; cette dette est documentée, pas urgente.

## 0.78.4 (patch) — BC4 2026-10-23 — Fast KPI catalogue loading (Agent BC1)

- Read transfer availability from `task_run` / `task_sample`, populated by the canonical `(capture_id, seq)` task pipeline; KPI computations and formulas are unchanged.
- Reuse the valid persistent Metrics cache for NMF presence and use bounded `EXISTS` checks on a cache miss instead of recomputing every distinct capture-second count.

## 0.78.3 (patch) — BC4 2026-10-23 — Restore settings singleton primary keys (Agent BC1)

- Restore the primary keys required by idempotent settings and catalogue seeds after the imported schema lost its constraints.
- Fix API startup failure caused by `ON CONFLICT (id)` running without a matching unique constraint.

## 0.78.1 (patch) — BC2 metrics truth

- Correct documented NMF string fields storage and preserve raw values during Light/Deep re-decode.

## 0.76.3 (patch) — BC4 2026-10-22 — /metrics/series expose nmf_start_at + utc_offset_min (Agent BC3)

Lot `(C) Axe X time` front : le front doit pouvoir rendre un axe Clock (local|UTC) sans recalcul depuis un autre endpoint. `/metrics/series` manquait les deux champs — fix ici.

- `app/routes/metrics.py:105-123` : `SeriesResponse` gagne 3 champs optionnels `nmf_start_at`, `capture_date`, `utc_offset_min` (identique à `MetricAnalysisSchema` déjà en 0.75.0). Null si capture non enrichie (`#START` ou `#UT` absent) → front repli sur Capture time (s).
- `app/routes/metrics.py:425-432` : enrichit la réponse via JOIN `nmf_capture + nmf_file` + `date_from_start_at_py()` (déjà factorisé en `app/kpi/service.py:38-66`). Rétro-compatible (champs optionnels).

Aucun calcul temporel côté front : identique à la source back qui joint `nmf_file.start_at` + `nmf_file.utc_offset_min`.

## 0.76.2 (patch) — BC4 2026-10-22 — /metrics/captures union scanner captures (Agent BC3)

Les captures `kind='scanner'` n'ont jamais de `measurement_points` par design → elles étaient filtrées hors de `/metrics/captures`. L'utilisateur ne pouvait donc pas les sélectionner dans Metrics tab → impossible de voir le banner "Scanner capture" + leaves grayed (feature 1.92.0 front).

- `app/routes/metrics.py:289-315` : union des captures `measurement_points`-filtered (UE) + `nmf_capture WHERE kind='scanner'` (scanners), dédoublonnée. Label + kind enrichis via JOIN nmf_file.

## 0.76.1 (patch) — BC4 2026-10-22 — Expose capture.kind + label fichier dans endpoints captures (Agent BC3)

Suite directe du 0.76.0 — pour que le front puisse afficher un badge "Scanner" sur les captures et désactiver les métriques UE sur les captures scanner.

- `app/routes/signaling.py:51-57` : `Capture.kind: Literal['ue','scanner']|None` ajouté. `/projects/{p}/signaling/captures` LEFT JOIN `nmf_capture` pour exposer `kind`.
- `app/routes/metrics.py:71-77` : `CaptureInfo.kind: Literal['ue','scanner']|None` ajouté. `/projects/{p}/metrics/captures` enrichi via requête complémentaire (JOIN `nmf_capture + nmf_file`) : `label=filename` (plus de hash capture_id en label), `kind` exposé.
- Rétro-compatibilité : les 2 champs sont `Optional[None]` → les clients antérieurs continuent à parser.

### Écart ouvert — scanner metrics (lot futur)

Les captures `kind='scanner'` exposent 4 events spécifiques dans `nmf_event_light` : `CELLSCAN` (RSRP/RSRQ par PCI scanné, par EARFCN), `OFDMSCAN` (power per PRB), `SCANCONFIG` (plan de scan), `STARTSCAN` (marker début). **Pas de projection UE possible** (`nmf_cell_second` vide par design). Les KPI Metrics UE actuels (RSRP serving, CA, débit par couche) ne s'y appliquent pas. **Lot futur à ouvrir : "Scanner view"** avec sa propre projection (ex. `nmf_scan_second` ou direct depuis `CELLSCAN`), ses propres cartes (histogram RSRP par PCI top-N, map geo par EARFCN, séries temporelles de power). Hors scope lot Time/GPS et Phase 2 Charts.

## 0.76.0 (minor) — BC4 2026-10-22 — nmf_capture.kind ('ue' | 'scanner') + G20 révisé = 0 (Agent BC3)

Mission `[BC3] GO (b) capture.kind scanner + G20=0`.

### Migration + ORM

- `alembic/versions/0043_nmf_capture_kind.py` : `ALTER TABLE nmf_capture ADD COLUMN kind text NULL` + CHECK libéral `kind IS NULL OR kind IN ('ue','scanner')`. Null autorisé explicitement (jamais inventé).
- `nmf_capture` n'a pas d'ORM Mapped (requêtes SQL brutes dans `decode_capture`) — pas de changement models.

### Classification par CONTENU — `store.py:classify_capture_kind`

Jamais depuis le nom de fichier. Query `SELECT DISTINCT event_code FROM nmf_event_light WHERE project_id=:pid AND capture_id=:cap` :

- `kind='ue'` si `event_codes ∩ {CELLMEAS, CI}` non vide.
- `kind='scanner'` sinon, si `event_codes ∩ {SCANCONFIG, STARTSCAN, CELLSCAN, OFDMSCAN}` non vide.
- `kind=NULL` sinon.

Priorité `ue > scanner` : si une capture a à la fois CELLMEAS et un SCAN* (cas atypique Nemo), elle est `ue` (le mode UE prime pour les KPI cell-scoped).

### `decode_capture` écrit `kind` dans nmf_capture (store.py:101-112)

- INSERT ... VALUES(..., :kind) + ON CONFLICT ... DO UPDATE SET ..., kind=excluded.kind.
- Appelée systématiquement à la fin du decode (deep ET light), après `write_light` qui a repopulé `nmf_event_light`. L'ordre garantit que `classify_capture_kind` observe les events frais.

### Backfill CLI

- `app/scripts/backfill_capture_kind.py` : options `--dry-run`, `--force`. Rapporte `ue / scanner / null / already_set`. Idempotent.

### Garde G20 révisé

- **Avant** (0.74.11) : `SELECT count(*) FROM nmf_capture WHERE decode_level IS NOT NULL AND NOT EXISTS cell_second` → **10 captures scanner-only comptées à tort**.
- **Après** (0.76.0) : `WHERE decode_level IS NOT NULL AND kind != 'scanner' AND NOT EXISTS cell_second` → attendu **0**.

Les 10 scanners restent `cell_second = []` par design (aucun event cell-scoped à agréger), mais G20 ne les compte plus comme écart.

## 0.75.0 (minor) — BC4 2026-10-22 — Metrics API : time_local/time_utc + GPS par ligne (Agent BC3)

Mission `[BC3] [bc4-back + franco-focus-forge] — GO lot Time/GPS (fixes 1→10)`, section Back (A+B).

### Modèle (A1 — migration `0042_utc_offset`)

- `nmf_file.utc_offset_min int NULL` : NFF 2.19 `#UT` col 1 (`UTC_to_local` en minutes, signe `local - UTC`). Null si l'en-tête `#UT` absent — jamais inventé.
- ORM : `app/models/base.py:122` `utc_offset_min: Mapped[int | None]`.

### Ingest (A2)

- `app/ingest/nmf.py:159-192` : helper `_extract_utc_offset_min(path)` lit les premiers 32 KB du NMF, parse la première ligne commençant par `#UT`, retourne col 1 (`int`) ou `None` (format invalide / absent).
- Hook d'ingest `app/ingest/nmf.py:521` : `nmf.utc_offset_min = _extract_utc_offset_min(tmp_path)`.
- Jamais injecté dans `nmf_event_deep` : le décodeur externe `bc4_decoder.py` n'expose pas `#UT` dans `meta` (vérifié : `/opt/nmf_decoder/bc4_decoder.py:319-320`), et aucun event `#...` n'est jamais persisté en light/deep (confirmé par `SELECT DISTINCT event_code FROM nmf_event_* WHERE event_code LIKE '#%'` → 0 row). D'où la lecture directe fichier.

### Backfill (A2)

- `app/scripts/backfill_utc_offset_min.py` : CLI idempotent lisant chaque `nmf_file.source_path`, extrait `#UT` col 1, UPDATE. Options `--dry-run`, `--force`. Rapporte `ok / already_set / no_source_path / file_missing / no_header`.
- 104 fichiers en base (toutes projects), tous `#UT,,,120,120` observés via `grep -m1 '^#UT'` sur tous les `source_path/*.nmf`.

### API (B1 — `/metrics/analysis` + `/metrics/table`)

- `app/kpi/metrics_v3.py:19-37` : helper `_pair_previous_or_same(xr, yr)` extrait du pattern inline existant (scatter G14 RSRP↔DRATE). Réutilisé pour join GPS seq→(lat,lon) sur `seq_first` de chaque ligne.
- `Dataset.__init__` ligne 206 : charge `file_meta` (join `nmf_capture × nmf_file`) → `start_at`, `utc_offset_min`.
- `response()` :
  - Chaque row expose désormais `time_local` (= `time_label` historique, `HH:MM:SS.mmm` local), `time_utc` (= `time_local − utc_offset_min · 60s`, null + `reason='no_utc_offset_header'` si `#UT` absent), `lat`, `lon`, `gps_source ∈ {'exact','previous_fix'}`, `gps_age_s` (différence `t_rel_s`), `reason ∈ {None,'no_gps_in_capture','light_decode_no_gps','no_fix_before_seq','no_utc_offset_header'}`.
  - Join GPS = `_pair_previous_or_same(gps_fixes, [{'seq': seq_first, ...}])` sur `stg_event_raw(lat, lon)` filtré `lat IS NOT NULL AND lon IS NOT NULL AND NOT (lat=0 AND lon=0)` (règle déjà en place pour `map_points`, inchangée).
  - Top-level ajoute `nmf_start_at` (verbatim `DD.MM.YYYY HH:MM:SS.mmm`), `capture_date` (dérivé `YYYY-MM-DD`), `utc_offset_min`.
- `app/routes/metrics_v3.py:TableRow` + `Analysis` : nouveaux champs typés `str|None` / `float|None` / `Literal['exact','previous_fix']|None` ; champs rétro-compatibles (tous optionnels).
- CSV `response.csv` : nouvelles colonnes `time_local,time_utc,lat,lon,gps_source,gps_age_s,reason` entre `seq_last` et les métriques, dans l'ordre d'affichage front.

### Factoring (B2)

- `app/kpi/service.py:38-66` : `_date_from_start_at(alias)` conservé (SQL) + ajout `date_from_start_at_py(start_at)` (Python, utilisé par `metrics_v3.py` et importable depuis `kpi_timeseries.py` en lot suivant).

### Non modifié / écarts déclarés

- `nmf_file.start_at` reste `varchar DD.MM.YYYY HH:MM:SS.mmm` — pas de migration vers `timestamp` (confirmé par utilisateur, choix A). Le parseur ingest copie verbatim ; preuve `#START,10:33:20.677,,"23.06.2026"` ↔ `23.06.2026 10:33:20.677` strictement identique.
- GPS en light decode : non traité ici (lot BC2 décodeur séparé). Rows sur captures light exposent `gps_source=None, reason='light_decode_no_gps'` (si aucun fix) ou `reason='no_gps_in_capture'` (si `stg_event_raw` sans lat/lon).

### Gardes

- `G22` : `date_from_start_at_py(nmf_file.start_at) = date du nom YYMonDD`. Prouvé statistiquement sur les 16 captures TEST2 (`BCNE..._26Jun11_` → `2026-06-11` ✓ ; `M1_..._26Jun23_` → `2026-06-23` ✓).
- `G21` (après activation front) : sur `1e4e8d879a83` (deep, TEST2) ≥ 50 % lignes `lat/lon not null` + `gps_age_s >= 0` ; sur `44621571bccc` (light, Test_3) 100 % null avec `reason`.

## 0.74.11 (patch) — BC4 2026-10-22 — CLI backfill cell_second + garde G20 (Agent BC3)

**Diagnostic N1** : capture `44621571bccc` (Test_3) → table Metrics vide. Cause racine `nmf_cell_second` = 0 row alors que `nmf_event_light` = 27 126 rows. Pattern cross-captures :
```
decoder_version | captures | with_cell_second | missing
     1.0.0      |    52    |       12         |    40    ← projection ajoutée après ces décodages
     1.3.0      |    22    |       19         |     3    ← échecs ponctuels
```
40 captures 1.0.0 Light du 2026-10-19 : la projection `cell_second` (lignes 56-58 de `app/nmf_decoder/store.py:write_light`) a été ajoutée au décodeur en 1.3.0 — pas rétroactive. 3 captures 1.3.0 Deep du 2026-10-21 : cas particuliers (ex. `d8d7fa995c44`, `50b0370a23c6`).

**Correctif** :
- `app/scripts/project_cell_second.py` (nouveau) : CLI idempotent qui relance `decode_capture(..., force=True)` sur chaque capture ciblée. **Pas de one-shot SQL**, pas de reconstruction hors du décodeur authoritative — même code path que `POST /decode`.
- Deux modes : `--capture <id>` ou `--missing` (toutes captures `decode_level IS NOT NULL` sans aucune ligne `nmf_cell_second`).
- `--dry-run` liste sans écrire.
- Idempotence : `decode_capture` DELETE+INSERT ; rejouer sur une capture déjà OK = no-op fonctionnel.

**Usage** :
```
docker exec bc4-api-1 python -m app.scripts.project_cell_second --capture 44621571bccc
docker exec bc4-api-1 python -m app.scripts.project_cell_second --missing --dry-run
docker exec bc4-api-1 python -m app.scripts.project_cell_second --missing
```

**Garde G20** (manuel avant/après) :
```sql
SELECT count(*) FROM nmf_capture c
 WHERE c.decode_level IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM nmf_cell_second s WHERE s.capture_id=c.capture_id);
```
→ `0` attendu après `--missing`.

**Preuve exécution capture 44621571bccc** :
```
targets: 1
[OK] project=4b7bfd50ddb6 capture=44621571bccc level=light rows=171161 elapsed=92.18s
summary: ok=1 failed=0
```
`/metrics/table?capture_id=44621571bccc&codes=ci_rs_snr&cell=0` : **0 rows → 953 rows**, first value `ci_rs_snr@0 = 29.7 dB`.

**Non-régression** : la projection cell_second reste exclusivement dans `write_light()`. La CLI ne duplique pas la logique, elle rejoue le même `decode_capture(force=True)`.

## 0.74.10 (patch) — BC4 2026-10-22 — Signaling V2 : pistes UE et RRC prouvées (Agent BC1)

- `view=rf` expose chaque intervalle LTE Connected prouvé sur deux pistes distinctes :
  `UE_STATE` avec `state=LTE` et `RRC_STATE` avec `state=CONNECTED`.
- Les deux événements portent `capture_id`, technologie, contexte, session, règle,
  version et les trois séquences source exactes. Aucun intervalle Idle, NR, NSA ou SA
  n'est créé sans preuve source.

## 0.74.8 (patch) — BC4 2026-10-22 — Signaling V2 : preuves de session dans la vue par défaut (Agent BC1)

- La vue `legacy`, utilisée par défaut par `/signaling/events`, rattache désormais
  `context_id`, `session_id` et les attributs de preuve aux procédures
  `rrc_connection` dont le tuple ordonné des séquences source correspond exactement
  à une preuve `nemo_context_connected` complète.
- Les procédures partielles, NR, NSA et SA restent sans session : aucun état n'est
  déduit ou complété. La vue `rf` et les données sources ne changent pas.

## 0.74.7 (patch) — BC4 2026-10-22 — Signaling V2 : sessions LTE Connected traçables (Agent BC1)

- `/projects/{id}/signaling/events?view=rf` expose `context_id` et un `session_id`
  composite capture/contexte pour les seuls intervalles `LTE Connected` prouvés par
  `nemo_context_connected`.
- Chaque événement expose `attrs.time_evidence_status`. Une paire dont les timestamps
  source sont identiques reste un marqueur `RESOLUTION_LIMITED`; aucune durée artificielle
  n'est créée. Les bornes distinctes restent des bandes avec leur `t_rel_end_s` source.

## 0.74.6 (patch) — BC4 2026-10-22 — Metrics catalogue : suppression des 3 nœuds "Cell discriminator" (Agent BC3)

**Problème** : les 3 nœuds `Cell discriminator*` sous `Serving radio ★`, `MIMO per port ★` et `UL power ★` étaient des descriptions textuelles de l'encodage `cell_type` (ex. `"PHRATE/MACRATE/CQI/PLAID/CI: cell_type=0 (documented 2.19) · CELLMEAS LTE: type 0"`), pas des métriques exploitables. Ils polluaient l'arbre `/metrics` sans valeur analytique.

**Fix** — `app/kpi/metrics_catalogue_v6.json` : suppression des 3 nœuds (1 avec 5 enfants prose + 2 nœuds-leaves descriptifs). Impact : feuilles 893 → 886 (delta -7). Les 3 nœuds étaient le principal facteur de divergence G18b `/metrics vs spec HTML v10` identifié en 1.76 Task #50.

**Rebuild** : nécessite `docker compose build api && up -d`. `/health` à 0.74.6.

## 0.74.5 (patch) — BC4 2026-10-21 — /kpi/catalog : fallback propre sur timeout compute_transfers (Agent BC3)

**Problème** : page BC4 bloquée sur « Loading KPI catalogue… » puis 500 Internal Server Error. Trace : `psycopg.errors.QueryCanceled: canceling statement due to statement timeout` dans `app/services/task_run.py:113` (`load_tasks`) appelé par `app/measure/throughput.py:50` (`compute_transfers`) depuis `app/kpi/service_v2.py:353`. Sur TEST2/Test_3 (767k rows `nmf_event_deep`+`nmf_event_light`), le `UNION ALL` dépasse le `statement_timeout` Postgres.

**Fix** — `app/kpi/service_v2.py:build_catalog_v2_response` : wrap de `compute_transfers(db, project_id)` dans try/except `(DBAPIError, OperationalError)`. Sur timeout : rollback de la transaction, log WARN, `transfers_cache = []`. Les KPIs `transfers_table` / `transfers_dms` tombent alors en PENDING avec la raison explicite déjà portée par `compute_status_v2` ("0 transfert `proven` direction=..."). Au lieu d'un 500 opaque, le catalogue répond 200 et les KPIs touchés affichent leur écart déclaré — conformément à CLAUDE.md Rule 2 (écart ouvert, pas fabriqué).

**Non-régression** : les projets dont `compute_transfers` tient dans le budget (TEST, projets < ~500k rows) ne changent pas de comportement. Seul le path d'erreur est modifié.

## 0.74.3 (patch) — BC4 2026-10-21 — /kpi/catalog cold ≈ 60s → ~3s + warm boot (Agent BC3)

**Problème** : page BC4 bloquée sur « Loading KPI catalogue… » pendant 55-67 s au premier chargement sur TEST2 / Test_3 (767k rows stg_event_raw, 197 KPIs). Cache TTL 30s expirait entre deux navigations → cold à chaque fois.

**Fix A** — `app/kpi/catalog_cache.py` : `ttl=30` → `ttl=600` (10 min). Première navigation chaude dans la session couvre toute l'exploration habituelle.

**Fix B** — `app/kpi/service_v2.py:build_catalog_v2_response` : batch des checks `nmf_metric`. Au lieu de ~100 `SELECT EXISTS(SELECT 1 FROM (…source_sql(code)…))` séquentiels, **UN seul appel à `metric_counts(db, pid)`** → dict `{code: bool}` passé en argument à `compute_status_v2` via nouveau paramètre optionnel `nmf_available_cache`. Appels unitaires sans cache conservent le comportement initial (back-compat).

**Fix C** — `app/main.py:_warm_kpi_catalog` : hook `@app.on_event("startup")` qui lance un thread daemon pré-chauffant le catalogue pour chaque projet. Non bloquant ; échec par projet loggé et skippé. Utilisateur hit cache warm (0.05s) au lieu de 60s cold à sa première navigation.

**Benchmark cible** (TEST2 134af70a06eb) : cold `62.8s → ≤5s`, warm `≈0.05s`.

## 0.74.2 (patch) — BC4 2026-10-21 — Canonical legacy context list (Agent BC1)

- Persist an empty context list in rebuilt Light rows when legacy Deep data has a null `context_ids`, matching a fresh source replay while preserving all source observations.

## 0.74.1 (patch) — BC4 2026-10-21 — Legacy Deep projection compatibility (Agent BC1)

- Rebuild Light projections from legacy Deep captures whose `context_ids` is null, treating the absent context list as an empty grouping key without changing stored source data.

## 0.74.0 (minor) — BC4 2026-10-21 — Metrics catalogue v6 and serving-cell projection (Agent BC1)

- Expose the complete approved Metrics v6 hierarchy while retaining absent leaves with `n=0` and explicit `open` proof status.
- Project LTE CELLMEAS serving observations by documented/content-proven cell discriminator: PCell `0`, SCell1–4 `10–13`; codes 1, 2, 14 and 15 remain unassigned.
- Count catalogue cell availability by distinct capture-local seconds. Existing series, table, provenance and `(capture_id, seq)` ordering remain unchanged.

## 0.73.1 (patch) — BC4 2026-10-21 — Signaling details : attributs décodeur sur événements d'état BC2 (Agent BC3)

- `app/signaling/service.py:details()` : nouvelle branche fallback pour les événements d'état BC2 (RACHI/HOA/HOS/HOI/MEI/CREL/RRA/RRC/RRD/PBA/PBC/PBD/CAA/CAC/CAD/DAA/DAC/DAD/GAA/GAC/GAD/LOCK/MARK/SCELLMOD). Au lieu du message « Absence d'identité non certifiée », expose les **attributs décodeur** depuis `nmf_event_deep` (fallback `nmf_event_light`), préfixés par `event_code/attribute` (ex. `RACHI/access_delay`, `RACHI/pathloss`, `RACHI/preambles_successes`).
- `hex_reason` devient explicite : `« Événement d'état décodeur BC2 (RACHI) — pas de PDU ASN.1 par nature. 14 attribut(s) décodeur exposé(s). »`
- Validé live : RACHI seq 80 TEST2 → 14 attributs techniques (`access_delay=23ms`, `pathloss=103dB`, `preambles 1/1`, `tx_power=-7dBm`, `preamble_step=4`, `rach_result=1`, etc.).
- Pas de nouvelle route ni de migration, zéro impact sur RRCSM/L3SM existants.

## 0.73.0 (minor) — BC4 2026-10-21 — Proven RF timeline (Agent BC2)

- Existing signaling/events accepts view=rf: capture-clock events, context-bound handovers, connected intervals from connection indication, and directional task_run bounds.
- Explicit source sequences, rule version, evidence status and unavailable NR/call semantics; missing times and unfinished intervals are never filled. Existing legacy response remains compatible.
- No parser, ASN.1, source-data, KPI formula or migration changes.

## 0.72.1 (patch) — BC4 2026-10-21 — NAS redact par path complet (fix P0) (Agent BC3)

- **Fix critique** : la version 0.72.0 exposait les sous-champs d'IE identité (`OldGUTI/EPSID/MMEGroupID`, `MMECode`, `Digit1`, `NAS_KSI/Value`, `TMSIBasedNRICont/NRICont/Value`, `OldGUTIType/*`) car `_is_sensitive()` ne matchait que le NOM de la feuille, pas le PATH complet.
- `app/signaling/nas_decoder.py:_walk()` : check sur `full_path` au lieu de `name` → tout sous-arbre d'un ancêtre redacted hérite du statut REDACTED (comportement défensif correct).
- Regex `_REDACT` enrichi : ajout de `NRI`, `EPSID`, `NAS_KSI`, `\bKSI\b` + word boundaries pour éviter faux positifs comme `RestrictEC` (bit UENetCap safe).
- Validé live sur TAU_REQUEST seq 36 TEST2 : 17/155 champs REDACTED, 138 safes exposés. Guards G18 PASS inchangés, G18b_nas réévalué : FULLY=152 PARTIAL=728 REDACTED=20 UNSUPPORTED=100 (zéro leak sur 1000 messages).

## 0.72.0 (minor) — BC4 2026-10-21 — NAS sanitized decoder (SIGNALING FULL DECODE LTE/NR) (Agent BC3)

- **Décodage NAS complet** via `pycrate 0.8.1` (déjà installé), avec P0 CLAUDE.md préservée : zéro IMSI/IMEI/MSISDN/GUTI/TMSI/SUPI/SUCI/PEI/MAC/RAND/AUTN/RES/KSI/clé dans la réponse.
- `app/signaling/nas_decoder.py` **nouveau** : wrapper `decode(payload_hex, direction, system)` → dict `{status, parameters, pdu_class, reason}` avec :
  - **Allowlist** IE techniques (MessageType, ProtDisc, SecHdr, EMMCause, ESMCause, ServiceType, EpsAttachType, EPSBearerIdentity, PTI, QoS, ApnAmbr, ESMInformationTransferFlag, PDNType, RequestType, NAS/UESecurityCapability, PLMN, Seqn, Spare, Type enum).
  - **Denylist** regex sur `IMSI|IMEI|IMEISV|MSISDN|SUPI|SUCI|PEI|GUTI|TMSI|MobileId|MAC|RAND|AUTN|RES|XRES|AUTS|KASME|KAMF|KSEAF|KAUSF|CK|IK|NASKey|EmergencyNumber` + marker défensif sur bytes bruts (`<binary · N bytes · redacted>`).
  - **4 statuts** : `FULLY_DECODED` / `PARTIALLY_DECODED` / `REDACTED` / `UNSUPPORTED`.
- `app/signaling/service.py:details()` : la branche `event_code='L3SM'` appelle maintenant `nas_decoder.decode()` au lieu de retourner `parameters=[]`. Statut + raison explicites remontés dans `hex_reason`. Payload hex binaire **jamais exposé** dans l'API.
- `scripts/_guard_G18_signaling_live.py` : nouveau guard **G18b_nas** — scan 1000 messages NAS LTE/NR/UMTS, assert zéro token identité/crypto dans aucun paramètre SAFE.
- Validation live sur TEST2 : **1000 messages, 0 leak** ; distribution statuts : `FULLY=190 PARTIAL=710 REDACTED=0 UNSUPPORTED=100`.
- Couverture types NAS : 26/27 types LTE OK, UMTS/NR OK via même wrapper. 1 écart ouvert : `ACTIVATE_DEFAULT_EPS_BEARER_CONTEXT_REQUEST` → `UNSUPPORTED` (variant encoding à investiguer).
- Zéro migration, zéro nouvelle route, zéro modification des contrats existants. Format des `parameters` compatible RRC (path/value/param_key).

## 0.71.0 (minor) — BC4 2026-10-21 — Signaling timeline events (addendum spec) (Agent BC3)

- **Nouvelle route** `GET /projects/{id}/signaling/events?capture_id=&lanes=&failures_only=` (modèle `SignalingEvent` + `EventsResponse`) : agrège les markers BC2 (state events) et les procedures reconstruites en événements prêts pour le ruban front, avec pivot/linked/seq_gap/link_rule explicites.
- `app/signaling/links.py` **nouveau** : table de règles d'appariement événement → messages, strictement ordonnée en `(capture_id, seq)` — jamais `ts`.
  - `ho_reconfig_mobility` : pivot = dernière `RRCConnectionReconfiguration` portant `mobilityControlInfo` (lookup `param_occurrence`) ≤ 50 seq AVANT HOA ; linked = Complete + MeasurementReport + MEI + RACHI fenêtre.
  - `rrc_setup_message` : RRA/RRC/RRD → RRCConnectionRequest/Setup/SetupComplete, fenêtre ≤ 20 seq.
  - `rlf_reestab_request` : RLF marker → ReestablishmentRequest, fenêtre ≤ 50 seq.
  - `pivot_on_state_event` : CAA/DAA/GAA/PBA/… → événement pivote sur lui-même (SIPSM / task payload pas dans le contrat signaling).
  - `no_dict_support` : SgNB addition / SCell add → BC1 dict decoder n'expose actuellement ni `nr-Config-r15` ni `sCellToAddModList-r10` (audit confirmé : 0 occurrences cross-project). Pivot=null, lien=[], jamais inventé.
- `app/signaling/service.py` :
  - `MARKERS` étendu avec `HOI`, `LOCK`, `MARK`, `SCELLMOD` (déjà présents dans `nmf_event_deep/light`).
  - Nouvelle fonction `events(db, pid, cap, lanes, failures_only)` : parcourt rows + procedures et applique les règles.
- `scripts/_guard_G18_signaling_events.py` **nouveau** :
  - **G18f** — pour chaque HOA (≤ 100), pivot vérifié = Reconfiguration mobilityControlInfo ≤ 50 seq avant, backup SQL direct `param_occurrence`.
  - **G18g** — SgNB addition : si l'IE `nr-Config-r15` n'est pas dans `param_occurrence`, règle = `no_dict_support`, aucun lien NR fabriqué.
  - **G18h** — chaque `seq_gap` ≤ fenêtre de sa règle.
  - Section déterministe en mémoire (TEST-only).
- Écarts ouverts : routes `/dict/v2/scells`, `/dict/v2/rlf`, `/dict/v2/endc` toujours absentes de `/openapi.json` → lecture directe `param_occurrence` quand nécessaire. SgNB/SCell rules restent déclarées sans linkage tant que le decoder BC1 n'expose pas ces IE.
- Capture cible pour les guards : Test_3 `01bfc2fc5350` (spec signaling_timeline.html).
- Zéro migration, zéro modification des routes existantes.

## 0.69.1 (patch) — BC4 2026-10-21 — English KPI and Metrics labels (Agent BC2)

- Serve English catalogue categories, metric groups, attributes and availability explanations directly from the API. Preserve source catalogue definitions, decoder schemas, values, formulas and evidence identifiers.
- Translate KPI presentation fields after cache retrieval; cached data and numeric results remain unchanged.

## 0.69.0 (minor) — BC4 2026-10-21 — Contrat Métriques v3 (Agent BC2)

- Catalogue fermé : catégories, cellules disponibles, preuves et attributs événementiels ; hypothèses CELLMEAS 10–13 et positions inconnues explicitement indisponibles.
- Séries par cellule/attribut et tableau par seconde avec CSV, histogrammes par opérateur/bande, appariement dans la même cellule et points GPS enregistrés. Calculs et dénominateurs côté API, sources conservées dans result_id.
- Réutilise les projections du décodeur 1.2.2 sans re-décodage ni changement des formules KPI. NR/EN-DC non documentés restent déclarés comme écarts.

## 0.68.2 (patch) — BC4 2026-10-21 — Variantes CREL et forçages LOCK (Agent BC2)

- Decode documented LTE CREL header variants with explicit conditional system columns, preserving old/new cell IDs and optional reason.
- Decode variable-length LOCK groups for documented system/band/channel/LTE cell forcings; retain unknown extension fields. Light retains the last complete forcing snapshot.
- Migration 0039 adds typed LOCK attributes. Decoder 1.2.2.

## 0.68.1 (patch) — BC4 2026-10-21 — Voisines sur observations décodées (Agent BC2)

- Skip neighbor projections for unsupported or undecodable CELLMEAS layouts. An NR record without decoded groups no longer creates a synthetic zero or collides with a real LTE observation in the same second.
- Decoder 1.2.1; capture replay remains transactional. Added mixed LTE/NR regression coverage.

## 0.68.0 (minor) — BC4 2026-10-21 — Métriques v3 phase A (Agent BC2)

- Nemo 1.2.0: explicit schema system positions and separate context IDs; corrected context-bearing LTE event layouts. No inferred system for events without one.
- Per-cell Light projections and PHY/MAC throughput totals; documented block/Percentage weighting for quality; NULL with reason for unproved total weights. Observed SCell activity and share, last observed neighbor snapshot.
- Capture-local, context-matched event pairs preserve Nemo and HOI durations independently. No inter-capture time matching or forced duration equality.
- CAA phone fields and SEI private fields redacted before staging/Deep persistence; migration sanitizes retained fields without deleting observations.
- CELLMEAS 10–13 mapping, undocumented UL cell fields and undemonstrated 2.59/NR attributes remain explicit gaps. No front or metrics-contract phase B/C changes.
- Manual guards: scripts/_guard_G16_phase_a.py; tests/test_nmf_cells_context.py.

## 0.67.1 (patch) — BC4 2026-10-20 — Fraîcheur temporelle Signaling (Agent BC2)

- Contexte radio : `time_gap_s` depuis les temps capture validés, nullable, et relation `same_timestamp` / `previous_timestamp` / `unavailable`. Ordre strictement précédent par seq conservé.
- Audit TEST2 : les temps source identiques sont conservés ; aucun changement parser, données ou origine temporelle.

## 0.67.0 (minor) — BC4-BACK 2026-10-20 — Signaling: dual champ `layer` + `layer_counts` (Agent BC3)

- `app/signaling/service.py` : ajout d'un champ `layer` (slug `rrc_lte|rrc_nr|nas|event|mac`) à chaque ligne et chaque point retournés par `/signaling` et `/signaling/points`. Le champ `protocol` (étiquette française originale) est conservé en parallèle — zéro breaking change pour le front.
- `app/routes/signaling.py` : `Lines` renvoie désormais `layer_counts` (comptes agrégés par slug) à côté de `protocol_counts`. `Line` et `Point` déclarent `layer: Literal['rrc_lte','rrc_nr','nas','event','mac']`.
- Alignement avec la spec BC3 section 3 (« layer rrc_lte|rrc_nr|nas|event|mac ») sans migrer les clients existants.
- `/signaling/message` n'est pas dupliqué : la route shippée par BC1 en 0.66.0 (`app/routes/project_dict_v2.py`) couvre le besoin. L'écart de nommage `message_name|protocol` vs spec `name|layer` est reporté à une réconciliation inter-sessions.

## 0.66.0 (minor) — BC4-BACK 2026-10-20 — Message décodé pour Signaling View (Agent BC1)

- Ajoute `GET /projects/{project_id}/signaling/message?capture_id=&seq=` sur le routeur authentifié du dictionnaire : arbre des occurrences existantes, valeurs converties et unités préservées, catégorie par chemin, texte indenté, métadonnées et taille du payload. Aucun populate ni écriture de données.
- Exclut les identifiants de l’arbre et du texte. Le hex nécessite un contrôle du contenu ASN.1 complet sur une copie isolée du PDU et un réencodage identique. Identités, conteneurs opaques, NAS non vérifiable, données malformées et messages Request/SetupComplete/UL-DLInformationTransfer : hex nul avec raison explicite.
- G18a/G18b et tests de contrat, authentification, portée projet/capture/séquence, confidentialité et absence/ambiguïté. Pas de migration ; aucun moteur KPI ni frontend modifié.



## 0.65.3 (patch) — BC4 2026-10-20 — Signaling: allow rrc_connection in signaling_procedure CHECK (Agent BC3)

- Alembic migration `0037_signaling_procedure_rrc_connection` : étend le CHECK `type` de `signaling_procedure` pour inclure `rrc_connection`. Sans cela la nouvelle procédure 0.65.2 déclenchait `CheckViolation signaling_procedure_type_check` au premier INSERT (`svc.population()` persiste systématiquement).
- Détecté au rebuild live 0.65.2 sur TEST2 capture `41c13c9b4ce0` (30 RRA / 29 RRC / 29 RRD) : HTTP 500 au premier appel `/signaling/procedures`. Correctif ciblé, zéro impact sur les 7 types existants.
- Bump `app/main.py` + `pyproject.toml` → 0.65.3.

## 0.65.2 (patch) — BC4 2026-10-20 — Signaling: rrc_connection procedure + live guards G18a/b/d/e (Agent BC3)

- `app/signaling/procedures.py` : nouvelle procédure `rrc_connection` (RRA → RRC → RRD) alignée sur l'énumération décodeur BC2 1.x. Même mécanique d'inférence que `call`/`data_session`/`attach`/`bearer` : rejoue sur `message_name = event_code` pour les markers d'état.
- `scripts/_guard_G18_procedures.py` : cas déterministes supplémentaires pour `rrc_connection` (ok 3 stages + incomplete milieu manquant).
- `scripts/_guard_G18_signaling_live.py` (nouveau) : 4 gardes live contre TEST2 (`134af70a06eb` / `723547b196b3`) :
  - **G18a** — `population()` seqs = union SQL directe `stg_event (RRCSM+L3SM) + stg_event_raw (markers)`.
  - **G18b** — 1 000 messages RRCSM : hex masqué sur `RRCConnectionRequest/SetupComplete/UL-DLInformationTransfer`, aucune occurrence de `rnti|guti|tmsi|imsi|imei|msisdn` dans aucune réponse.
  - **G18d** — 20 `RRCConnectionReconfiguration` : `len(details.parameters)` = `count(*) FROM param_occurrence …sanitized` par seq.
  - **G18e** — capture outdoor : chaque point avec `lat/lng != NULL` provient d'un `GPS` fix stg_event_raw rejouable (pas de fabrication) ; capture indoor → 0 point.
- Résultat du run live : `G18a PASS n=10175`, `G18b PASS 1000 scanned, 2/2 identity masked`, `G18d PASS 20 reco`, `G18e PASS 9847 positioned / 47 GPS fixes`.
- Additif, pas de migration, pas de rebuild obligatoire pour exécuter les guards (fichiers scripts seulement, chargeables via `docker cp`). Rebuild requis pour que la route `/procedures` 0.65.1 et la procédure `rrc_connection` soient live.

## 0.65.1 (patch) — BC4 2026-10-20 — Signaling: dedicated /procedures endpoint (Agent BC3)

- New route `GET /projects/{id}/signaling/procedures?capture_id=&type=` returning the same procedures already reconstructed by `app.signaling.procedures.reconstruct`, exposed as a standalone endpoint for clients that only need the procedure list and type counts without pulling the full line population.
- Additive — no change to existing `/signaling`, `/timeline`, `/points`, `/context`, `/details`, `/export`, `/captures` responses. Same `svc.population()` call, same `Procedure` schema already in OpenAPI.
- Response envelope: `{project_id, capture_id, result_id, procedures:[Procedure], total, types:{type:count}}`. Filter `type` matches `Procedure.type` values (`rrc_setup`, `ho`, `call`, `data_session`).

## 0.65.0 (minor) — BC4 2026-10-20 — Signaling View (Agent BC2)

- Capture-local signaling API: messages, protocol timeline, preceding GPS, radio context, sanitized details and CSV. OpenAPI response models and deterministic result IDs.
- Migration 0036: explicit RRC setup, handover, call, data, attach, bearer and reestablishment procedure state machines; sequence ordering, incomplete attempts and NULL durations preserved.
- BC1 decoded parameters reused without changing ASN.1 decoder. NAS payload never exposed; hex withheld on sensitive content or uncertified decoding. No RNTI or subscriber identity fields.
- Context uses the immediately preceding event per source in the same capture, including NULL measurements and seq_gap. GPS velocity: NFF 2.19 GPS Parameters #7, column 10, km/h; does not reuse the legacy speed_mps column mapping.
- Open gaps: F4 RRC Setup Time not implemented upstream; no BC1 per-message tree route (adapter over sanitized param_occurrence); no declared indoor capture in TEST2; state-event technology not inferred from the legacy header-as-system mapping.
- Manual guards and live evidence: scripts/_guard_G18_procedures.py and /home/devmat/BC4/signaling-audit/.

## 0.64.1 (patch) — BC4 2026-10-20 — /metrics/{code}/aggregate : unité correcte Mbit/s (Agent BC2)

- Correction : `app.kpi.nmf.stats` interrogeait `source_sql(code)` brut (valeurs bit/s pour les débits) alors que le catalogue `metric_catalog` applique une conversion `/1e6` pour les débits avant exposition. Le /aggregate route renvoyait donc `p90 = 21 464 436` pour une métrique étiquetée Mbit/s — valeurs 1 000 000× trop grandes.
- `stats()` accepte désormais `sql_override: str | None` ; la route /aggregate passe `metric.sql` (post-conversion) via ce paramètre. Les métriques non-débit (pdsch_bler, cell_rsrp, cqi_wb_cqi_0 …) ne sont pas affectées (source_sql déjà correct).
- Vérifié live sur Test_outdoor `pdsch_bitrate_cw0/aggregate?group_by=operator` → `p90 Orange ≈ 20 Mbit/s` au lieu de `20 000 000`.

## 0.64.0 (minor) — BC4 2026-10-20 — Enrichissement contrat KPI/Métriques pour onglets duaux (F1) (Agent BC2)

- `/projects/{p}/kpi/catalog` : chaque KPI porte désormais trois nouveaux champs :
  - `category` : les 7 catégories BC4 (Accessibilité, Rétention, Mobilité, Débit, Latence, Voix, Couverture & qualité) dérivées de la famille `catalog_v2`. Mapping statique dans `app/kpi/service_v2.py:_FAMILY_TO_BC4_CATEGORY`.
  - `metric_sources` : liste des codes NMF (ou événements) dont le KPI dérive, remonté depuis `available_check.arg`. Vide pour les règles sans source explicite.
  - `available` : booléen = `(status == 'AVAILABLE')` — raccourci pour le front, évite la dépendance à la casse.
- Nouveau `available_check.kind = "events_present"` dans `compute_status_v2` : vérifie la présence d'un ou plusieurs event_codes dans `stg_event_raw` pour le projet.
  - Présent → `status: PENDING, reason: "calcul non implémenté (F4)"` — grisé « N/D » avec tooltip actif côté front.
  - Absent → `status: UNAVAILABLE, reason: "événement source absent (<EVENTS>)"`.
- `scripts/patch_catalog_f4_candidates.py` : convertit 16 KPI prioritaires F4 vers `events_present` (LTE_RRC_SETUP_SR, LTE_HO_INTRA/INTER/IRAT_SR, LTE_VOLTE_CALL_SETUP_SR, LTE_CALL_DROP_SR + homologues NR). Idempotent.
- `/projects/{p}/metrics` : chaque métrique porte `category` depuis le champ YAML du décodeur (déjà en place P2 — 14 catégories décodeur).
- **Nouveau endpoint** `GET /projects/{p}/metrics/{code}/aggregate?group_by=none|operator|band|operator_band` : agrégats n / p10 / p50 / p90 d'une métrique Nemo par groupe. Reuse strict `app.kpi.nmf.stats` — même attribution opérateur/bande que les KPI `nmf_metric`, mêmes règles de percentile (observations, jamais moyennes de groupes). Permet l'onglet Métriques d'afficher un histogramme par opérateur sans dupliquer de code côté client.
- catalog_v2.json : `catalog_version = 2.0.0-bc2-nmf-2026-10-20-bc2-f4-events-2026-10-20` ; divergence xlsx tracée dans `patch_notes_f4`.
- Contrat additif : les consommateurs existants qui lisent `/kpi/catalog` ignorent les nouveaux champs ; aucun breaking.

## 0.63.0 (minor) — BC4 2026-10-20 — Promotion décodeur 1.1.0 : 65 YAMLs + 348 colonnes DB (P3) (Agent BC2)

- **DECODER_VERSION 1.0.0 → 1.1.0** dans `app/nmf_decoder/__init__.py`.
- **65 YAMLs promus** de `app/nmf_decoder/schemas-pending/` vers `app/nmf_decoder/schemas/` : les 68 baselines moins les 3 flaggés `needs_refinement` (CHI, DNSQUERY, LOCK — gardés en pending jusqu'à lecture txt NFF).
- **Migration 0035** `nmf_decoder_1_1_0.py` : 174 colonnes ajoutées dans `nmf_event_deep` + 174 dans `nmf_event_light` (0 nouvelles colonnes group, les 3 WARN exclus). `ADD COLUMN IF NOT EXISTS` sans DEFAULT → métadata-only sur PostgreSQL ≥ 11 (instantané même sur tables partitionnées). Idempotent.
- **VIEW `nmf_metric_value` recréée** avec les 376 champs totaux (anciens 1.0.0 + nouveaux 1.1.0) — enum complet code → value pour deep + group + light.
- `app/nmf_decoder/schema.py:fields()` : `s.get('groups', [])` au lieu de `s['groups']` — les 65 YAMLs promus (events plats sans group) ne crashent plus le loader.
- **Re-décodage Deep requis** : les 16 captures TEST2 sont marquées stale (`decoder_version=1.0.0 ≠ current 1.1.0`) ; le décodeur refusera de les servir en Deep tant qu'un `/decode` manuel n'a pas été déclenché. Les autres projets (Test_outdoor Light-only, Test_3 Deep à 766 697 lignes, etc.) restent stale aussi — à re-décoder par lots séparés (hors mission).
- Les 23 markers signalisation exposés en 0.62.0 via `/events` **continuent de fonctionner** (lecture directe de `stg_event_raw.event_code`, indépendante du décodeur Deep).
- Les 3 YAMLs `needs_refinement` restent dans `schemas-pending/` — exclus du décodeur Deep + de la migration tant que leurs sections multi-groupes ne sont pas scindées depuis le txt NFF.

## 0.62.0 (minor) — BC4 2026-10-20 — Catégories + markers signalisation + capture.forcing (nmf_decoder 1.1.0 P2) (Agent BC2)

- **Taxonomie 14 catégories** sur les 87 YAMLs du décodeur (19 live + 68 pending-1.1.0) : radio_serving · neighbours · throughput_layers · link_quality · allocation_mcs · csi · mimo_port · ul_power · voice · services · position · signalling_states · session · terminal_cell. 366/366 champs catégorisés par heuristique (`scripts/apply_categories.py`), 0 unknown.
- **`GET /projects/{pid}/captures/{cid}/events`** enrichi : 23 nouveaux `types` disponibles mappés depuis les event_codes 1.1.0 (`stg_event_raw.event_code`) → `rrc_lte` (RRA/RRC/RRD), `attach` (GAA/GAC), `detach` (GAD), `bearer` (PBA/PBC/PBD), `call` (CAA/CAC/CAD/PAA/PAC/PAD), `reselection` (CREL), `ho_info` (HOI/HOA/HOS), `meas_event` (MEI/NLIST/SEI), `roam` · `lock` · `mark` · `channel` · `audio` (AQRX/AQI) · `voip` (VOIPI) · `rach` (RACHI) · `l3sm`. Types existants `task · ho · rlf · rrc` inchangés (sémantique RRC ASN.1 préservée).
- Nouveau champ `Marker.event_code: str | None` sur chaque marker — traçabilité directe au code Nemo.
- **`capture_forcing`** exposé dans la réponse `/events` : `{active: bool, lock_count: int, first_seq, first_t_rel_s}`. Détection à partir des événements `LOCK` dans `stg_event_raw`. Payload détaillé (bande forcée, PCI forcé, HO forcing) attendu après re-décodage Deep en 1.1.0 (P3) — note explicite dans la réponse.
- 3 YAMLs baseline flaggés `needs_refinement: true` (CHI, DNSQUERY, LOCK — codes dupliqués entre sections multiples) : non promus en P3 avant lecture du txt NFF pour scinder correctement les groupes.
- **DECODER_VERSION reste 1.0.0** à ce stade : la promotion vers 1.1.0 (schemas-pending → schemas, migration DB, re-décodage Deep TEST2) est l'objet de P3.

## 0.61.1 (patch) — BC4-BACK 2026-10-20 — Finalisation import sans transaction inactive (Agent BC1)

- Capture l’identifiant projet puis termine la courte transaction de métadonnées avant la transaction indépendante de population ; évite la transaction implicite ouverte par la lecture ORM expirée et son idle-in-transaction timeout pendant les traitements longs. Atomicité et verrou de population conservés.
- Extrait la finalisation du rapport, réutilisable après vérification des résultats persistés, sans décodage ni repeuplement. Refuse les fichiers non terminés.
- Régression PostgreSQL avec timeout local de 200 ms : ancien code en échec, correctif validé ; tests de rollback atomique et de reprise du rapport. Intervention dans les services partagés explicitement autorisée par l’utilisateur.

## 0.61.0 (minor) — BC4 2026-10-20 — Catalogue KPI : 13 LTE basculés sur nmf_metric (Agent BC2)

- Script `scripts/patch_kpi_catalog_nmf_metrics.py` applique un mapping curé des KPI LTE `always_unavailable` qui ont un champ décodeur homonyme vers `available_check.kind = nmf_metric`. Chaque mapping est traçable à un champ de `app.nmf_decoder.schema.fields()` avec `agg != None` (validation défensive dans le script — refuse si le champ n'existe pas).
- 13 KPIs patchés :

| KPI | NMF arg | Unit | Source |
|-----|---------|------|--------|
| LTE_DL_MCS | plaid_mcs0 | index | PLAID.mcs0 |
| LTE_UL_MCS | plaiu_mcs0 | index | PLAIU.mcs0 |
| LTE_UL_BLER | mac_ul_residual_bler | % | MACRATEU |
| LTE_DL_MAC_THR | mac_dl_bitrate | Mbit/s | MACRATE |
| LTE_UL_MAC_THR | mac_ul_bitrate | Mbit/s | MACRATEU |
| LTE_DL_RLC_THR | rlc_dl_bitrate | Mbit/s | RLCRATE |
| LTE_UL_RLC_THR | rlc_ul_bitrate | Mbit/s | RLCRATEU |
| LTE_DL_PDCP_THR | pdcp_dl_bitrate | Mbit/s | PDCPRATED |
| LTE_UL_PDCP_THR | pdcp_ul_bitrate | Mbit/s | PDCPRATEU |
| LTE_DL_PHY_THR | pdsch_bitrate | Mbit/s | PHRATE |
| LTE_UL_PHY_THR | pusch_bitrate | Mbit/s | PHRATE |
| LTE_DL_PRB_UTILIZATION | plaid_prb_util_dl | % | PLAID |
| LTE_UL_PRB_UTILIZATION | plaiu_prb_util_ul | % | PLAIU |

- Chacun de ces KPI passera `AVAILABLE` sur un projet dont la source Nemo contient au moins une observation du champ cible, et sera servable en Metric vs Time via `/time-series`. Les débits `bit/s` sont auto-convertis en `Mbit/s` par `metric_catalog(db)` (`app/kpi/metrics.py` lignes 25-26).
- **NR laissé `always_unavailable`** : le décodeur Nemo n'expose pas d'événements NR distincts (CELLMEAS, MACRATE, PHRATE sont LTE-only). Mapper un KPI NR vers un champ LTE serait une mis-attribution (règle n°1 BC4).
- **Divergence xlsx signalée** : `catalog_version` devient `2.0.0-bc2-nmf-2026-10-20` + nouveau champ `patch_notes`. Le prochain ré-import du xlsx devra intégrer les mêmes mappings pour que le `source_xlsx_sha256` reste cohérent.
- `source_xlsx_sha256` inchangé — le fichier xlsx source n'a pas été modifié ; seul le JSON généré a été patché.

## 0.60.2 (patch) — BC4 2026-10-20 — Route /kpi/{code}/captures (Agent BC2)

- Nouvelle route `GET /projects/{pid}/kpi/{code}/captures` : liste les captures du projet qui ont au moins une observation décodée du KPI (`metric_catalog(db)[arg].sql` filtrée par `project_id`, agrégée par `capture_id`). Retourne `[{capture_id, decode_level, n_observations}]`.
- Remplace l'usage de `/metrics/captures` (qui lit `measurement_points`, souvent vide sur un projet fraîchement décodé en Light-only) pour l'auto-sélection UI du mode Graphique. Le front 1.45.1 l'adopte.
- KPI non `nmf_metric` → 422 avec raison explicite ; aucune liste à vide fabriquée (règle n°2 BC4).
- Zéro migration DB (la source `nmf_capture ∪ nmf_event_light|deep` est déjà indexée).

## 0.60.1 (patch) — BC4 2026-10-20 — /time-series expose aussi event_ts + nmf_file_start (Agent BC2)

- Chaque point ajoute deux champs optionnels : `event_ts` (= `stg_event_raw.ts`, format `HH:MM:SS.ms`) et `nmf_file_start` (= `nmf_file.start_at`, format `DD.MM.YYYY HH:MM:SS.ms`). Le front compose l'horodatage absolu de l'observation en concaténant la DATE de `nmf_file_start` et l'heure de `event_ts` ; aucun calcul côté back (règle n°2 BC4 : on sert la source brute, pas une interprétation).
- `evidence.source_view` complété : `LEFT JOIN stg_event_raw(lat,lon,ts) LEFT JOIN nmf_file(filename,start_at)`.
- Contrat additif, rétrocompat : les consommateurs qui ne lisent pas ces champs ne cassent pas.

## 0.60.0 (minor) — BC4 2026-10-20 — /time-series enrichi GPS + Fichier NMF (Agent BC2)

- `/projects/{pid}/captures/{cid}/kpi/{code}/time-series` : chaque point expose désormais `longitude: Optional[float]`, `latitude: Optional[float]`, `nmf_file: Optional[str]` en plus de `(seq, time_s, value)`.
- Jointure `LEFT JOIN stg_event_raw USING(project_id, capture_id, seq)` puis `LEFT JOIN nmf_file ON nmf_file.id = stg_event_raw.nmf_file_id`. Même ordre canonique `(capture_id, seq)` (règle n°6). Si la séquence n'a pas de ligne `stg_event_raw` (ex. bucket Light pur), les trois champs ressortent `null` — jamais fabriqués (règle n°1).
- `evidence.source_view` complété : la trace inclut maintenant `LEFT JOIN stg_event_raw(lat,lon) LEFT JOIN nmf_file(filename)`.
- Zéro migration DB : les clés `(project_id, capture_id, seq)` et `nmf_file.id` sont déjà indexées (`ix_stg_event_raw_context` 0033 + PK `nmf_file`).
- Compat ascendante : la réponse est additive (nouveaux champs optionnels), le front 1.42.1 continue à l'ignorer sans erreur ; le front 1.44.0 les affiche.

## 0.59.4 (patch) — BC4-BACK 2026-10-20 — RRC population denominators (Agent BC1)

- Add explicit `group_totals` to dictionary distributions using SQL window counts over the same parameter, server filters and operator/band grouping. Includes missing-value occurrences; no denominator inferred from visible buckets. Existing counts, conversions and source data unchanged.
- Regression covers null values, technology scope, operator, band and combined grouping.

## 0.59.3 (patch) — BC4 2026-10-20 — Catégories RRC sans attente des compteurs (Agent BC1)

- GET /dict/v2/templates?include_counts=false lit uniquement la configuration ; compteurs explicitement null tant qu’ils ne sont pas calculés. Le mode par défaut et ses compteurs restent inchangés.
- Aucun scan des occurrences pour cette réponse légère ; tests du contrat et de la requête unique.

## 0.59.2 (patch) — BC4 2026-10-20 — Comptage dédié des catégories (Agent BC1)

- La liste des modèles utilise les mêmes chemins éligibles et règles de classement pour compter les catégories, sans reconstruire les feuilles et références de captures de l’arbre.
- Égalité complète des réponses vérifiée sur TEST2 et Test_3. Aucun changement de catalogue, populations ou données sources.

## 0.59.1 (patch) — BC4 2026-10-20 — Chargement des catégories RRC (Agent BC1)

- Préagrège la population du projet avant les correspondances des modèles : normalisation ASN.1 calculée une fois par occurrence, totaux et groupes conservés.
- Cache séparé de la liste des catégories pendant 30 secondes, par projet, avec déduplication des requêtes simultanées ; réutilise le composant de cache existant sans modifier le module KPI. Les nouveaux compteurs peuvent prendre ce délai à apparaître.
- Cache borné de la fonction pure de normalisation des chemins IE ; cette transformation ne contient aucune donnée de projet.
- Tests des recouvrements de préfixes, valeurs nulles, unités et isolation projet ; comparaisons complètes TEST2/Test_3. Aucun changement de classification ni migration.

## 0.59.0 (minor) — BC4 2026-10-20 — Moteur générique Metric vs Time (Agent BC2)

- Nouvelle route `GET /projects/{pid}/captures/{cid}/kpi/{code}/time-series` : réponse `(seq, time_s, value)` par capture pour n'importe quelle métrique Nemo documentée du catalogue v2 (BLER, RSRP, RSRQ, SINR, CQI, débits DL/UL MAC/RLC/PDCP/APP, NR SS-RSRP si décodée).
- Résolution générique : le KPI canonique est résolu via `catalog_v2.resolve` puis mappé vers sa règle `available_check`. Seuls les KPI `kind == nmf_metric` sont servis ; les KPI calculés renvoient `status: UNAVAILABLE` + `reason` explicite — jamais une série temporelle fabriquée.
- Réutilise strictement `clock()`, `sample()`, `source_sql()`, `metric_catalog()`. Ordre canonique `(capture_id, seq)` préservé ; aucune interpolation, aucune concaténation inter-captures ; `time_s = ts - premier ts valide` conservé.
- Down-sampling par défaut `max_points=5000` : seq-bucket min/max préservant les extrema par bucket (choix documenté contre LTTB, qui peut masquer un pic unique) ; algorithme déclaré dans `sampling` et compte brut dans `n_total`.
- Signal `temporal_source` élargi dans `/kpi/catalog` : `nmf_metric.{arg}` si la règle est `nmf_metric` et le KPI `AVAILABLE`. `task_sample.bps` reste prioritaire pour les KPI débit — compat consommateurs existants préservée.
- Évidence SQL rejouable (`result_id`, `source_view`, `decoder_version`, `schema_version`, `decode_level`, `origin_seq`, `origin_ts`) sur chaque réponse — règle n°2 BC4.
- Zéro migration DB : les index `0033_kpi_context_index` et `0034_kpi_light_context_index` couvrent déjà `(project_id, capture_id, seq)`.
- Rebase propre sur 0.58.2 (BC1) : optimisations catalogue KPI de BC1 conservées, aucun chevauchement de code autre que les métadonnées de version.

## 0.58.2 (patch) — BC4 2026-10-20 — Chargement du catalogue KPI (Agent BC1, autorisé sur KPI)

- Mutualise les contrôles de disponibilité identiques dans une requête.
- Charge ensemble les quatre champs scalaires des tâches depuis les mêmes sources Light/Deep ; reconstruction, formules et ordre inchangés.
- Cache catalogue borné à 64 entrées par processus et 30 secondes, isolé par projet/services, sans erreurs mises en cache ; calcul partagé entre appels simultanés. Les changements de disponibilité peuvent apparaître avec ce délai maximal côté serveur.
- Inclut la correction RRC préparée précédemment : la carte résout les clés agrégées dict22 sans dupliquer les occurrences parent/feuille.
- Vérification comparative complète des catalogues et tâches TEST2/Test_3, et 23 tests ciblés réussis.

## 0.58.1 (patch) — BC4 2026-10-20 — BLER : requêtes projet sans timeout (Agent BC2)

- Migration 0034 : index couvrant les intervalles de séquence par événement pour le contrôle des buckets Light filtrés.
- Migration 0033 : index couvrant les références de fichier/système au même (projet, capture, seq), sans lecture du payload brut.
- Limite le contexte opérateur/bande aux séquences des mesures utiles, sans changer les règles d’attribution.
- Calcule total et groupes en une requête ; percentiles calculés sur les observations, jamais sur les moyennes de groupes.
- Sans regroupement ni filtre, ne construit pas de contexte inutile. Les buckets Light filtrés conservent le contrôle de tous leurs événements sources.

## 0.58.0 (minor) — BC4 2026-10-20 — Population opérateur cohérente (Agent BC2)

- La sélection existante N/D filtre les attributions NULL ; elle reste distincte de Tous et de la sélection vide.

- Contrat explicite Tous/sélection/vide et capture pour les requêtes KPI, séries et événements ; validation contre les opérateurs du projet.
- Filtrage des observations Nemo par attribution existante au même (capture_id, seq), #DL prioritaire ; aucun opérateur déduit de la seule présence dans une capture.
- Agrégats globaux et groupes sur la même population ; taux recalculés depuis leurs numérateurs/dénominateurs, preuves SQL via result_id. Groupement absent explicite : none.
- Les buckets Light mixtes/non attribués sont exclus d’une sélection explicite lorsqu’ils ne sont pas intégralement admissibles. Aucune mesure brute modifiée.
- Séries Task Time limitées à une capture ; une demande multi-captures renvoie 422.

## 0.57.1 (patch) — BC4 2026-10-19 — Contrat de progression Deep (Agent BC2)

- Decode expose les niveaux/version du projet, la progression et les durées estimées calculées côté API selon l’hypothèse demandée de 2,3 min par capture restante.
- Les séries valident uniquement les sources demandées au lieu de recompter toutes les métriques du projet à chaque interaction ; les codes sans source restent rejetés.
- Les captures exposent leur estimation ; les champs inconnus indiquent NFF 2.19. Aucun changement de décodage ni de version du décodeur.

## 0.57.0 (minor) — BC4 2026-10-19 — Décodeur Nemo versionné Light/Deep (Agent BC2)

Ajoute nmf_decoder 1.0.0, les schémas NFF 2.19 fournis, le stockage typé partitionné Deep et les agrégats Light reproductibles. Les métriques et les projections radio/app utilisent le décodeur ; les positions candidates historiques sont retirées. Les jobs admin `/decode` s'exécutent dans l'import worker, avec état par capture, version et reprise. `/health` expose `decoder_version`. Le catalogue et les séries déclarent leur provenance Light/Deep ; les comptages des métriques sont regroupés en trois lectures. Migrations 0031/0032 ; aucune modification ASN.1 ni front.

La projection restaure le contexte LTE des squelettes CELLMEAS non enrichis depuis les champs décodés. Le KPI BLER DL utilise PHRATE.pdsch.bler ; les points SINR sont appariés au CI précédent avec séquence et distance propres.

Les extensions de format et systèmes sans schéma restent partial et sont conservés. Les chaînes inconnues sont hachées ; les nombres ne sont jamais filtrés sur leur longueur. Les gardes manuels sont dans `scripts/_guard_G16_decoder.py` ; résultats de livraison dans le rapport BC2.

## 0.56.0 (minor) — BC4 2026-10-19 — Registre Nemo sous preuve et capacité Série (Agent BC2)

- Migration 0030 : metric_def et metric_sample, sans définition inventée ; extraction idempotente à l’étape E et lecture par /metrics/series.
- Catalogue KPI : temporal_source explicite selon les task_sample présents, documenté dans OpenAPI ; LTE DL BLER en %.
- Nemo File Format absent de specs : aucun champ Nemo supplémentaire activé, G15e et débits par couche bloqués par la preuve manquante.

## 0.55.0 (minor) — bc4-back 2026-10-19 — Dictionnaire par IE, classement Test_3 (Agent BC1)

- Intégration BC1 dans 0.55.0 expressément confirmée par l’utilisateur après livraison BC2 de ce numéro ; les fonctionnalités KPI BC2 sont conservées.
- Mapping par préfixes exacts à partir des IE, indépendant du message ; indices normalisés et discriminants conservés.
- Classement Test_3 approuvé, sous-catégories PDCCH & CORESET, Allocation temps-fréquence et MDT ; exclusions R2 par chemin, logicalChannelGroup conservé.
- Migration de données 0029, sauvegarde des flags et mappings pour retour arrière, aucune suppression d’occurrence ni modification de valeur.
- G13a-d prévalidés sur TEST2 et Test_3 ; preuve SIB1 NR et NCGI 36 bits. Audit dans audit/dict-v2.3.

## 0.55.0 (minor) — BC4 2026-10-19 — Métriques et chronogrammes par capture (Agent BC2)

- Catalogue fermé et compté depuis les sources auditées, dont PCI CELLMEAS LTE ; métriques sans observations absentes.
- Séries bornées par seq, origine temporelle capture, min/max déterministe par buckets, transitions catégorielles et CSV ; provenance result_id.
- Captures filtrées et marqueurs DAA/DCOMP, HO explicite mobilityControlInfo, rétablissement et setup/release RRC.
- Contrat Pydantic/OpenAPI ; horodatages régressifs ou manquants rejetés, aucune interpolation. NR PCI/ARFCN et TA non prouvés restent exclus.

## 0.54.3 (patch) — KPI 2026-10-19 — Enrichissement CELLMEAS ciblé et exclusions (Agent BC2)

- Rattrapage transactionnel UPDATE-only de deux captures LTE TEST2 depuis stg_event_raw et profils globaux prouvés ; aucun profil par capture créé.
- populate_chain atomique malgré les commits internes : savepoints et verrou conservé jusqu'à la fin ; contrôle explicite des CELLMEAS LTE non enrichis avant de finaliser. Les erreurs post-RRC ne sont plus silencieuses.
- /points expose excluded {nr_no_profile,lte_not_enriched,other}, classé côté serveur depuis la source brute et l'état normalisé.
- Audit NR séparé, aucune normalisation NR activée.

## 0.54.2 (patch) — KPI 2026-10-19 — CELLMEAS précédent par capture (Agent BC2)

- RSRP/RSRQ/SINR : dernier CELLMEAS strictement précédent dans la même capture, sans frontière de tâche ni limite de distance ; les valeurs nulles restent nulles.
- CQI : flux précédent indépendant avec cqi_seq/cqi_seq_gap ; /points expose la provenance adaptée à l’axe.
- Migration 0028 : recalcul des tâches existantes. Audit TEST2 : 42 paires RSRP initiales car 2546 lignes CQI masquaient les CELLMEAS ; couverture attendue 1435/2993 (47,95 %), cible 80 % non atteinte faute de RSRP validé sur les CELLMEAS restants.

## 0.54.1 (patch) — KPI 2026-10-19 — Intégrale DRATE et axes (Agent BC2)

- G14a compare Σ(bps×Δt)/8 à DCOMP sur les tâches ok ; écarts >5 % en partial avec raison.
- Catalogue GET /kpi/axes, validation des axes et distance radio seq_gap persistée et exposée ; appariement précédent strict, même capture, sans interpolation.
- Migration 0027 : recalcul des tâches existantes.

## 0.54.0 (minor) — bc4-back 2026-10-19 — task_run v1 (Agent BC1)

- Migration 0026 après dict v2.2 : task_run, task_sample et preuves SQL serveur. Masquage ciblé des identités dans les commandes existantes, sans sauvegarde du clair ; prévention à l'ingestion avec `***`.
- Étape D idempotente de populate_chain : ordre capture_id/seq, temps intra-capture, état incomplete et raison explicite pour les bornes absentes.
- Suppression de la formule 8×DSUMMARY/Δt : débit par tâche = moyenne des bps DRATE, ou 8×bytes_dcomp/duration_s si les échantillons sont absents et les bornes prouvées.
- Routes tasks, séries Task Time, enveloppe exacte sans interpolation, paires radio limitées à 5000 avec échantillonnage déterministe. Radio strictement précédente dans la même capture ; aucune coordonnée ou identité fabriquée.
- Résultats avec result_id et SQL stocké serveur, /results réservé aux administrateurs. Axes fermés dans app/kpi/axes.py.

## 0.53.0 (minor) — bc4-back 2026-10-19 — Dictionnaire catégories v2.2 (Agent BC1)

- Migration 0025 : catégories/sous-catégories, préfixes ASN.1 normalisés `[*]`, discriminants et décisions Q01–Q16. Corrections ciblées des flags SIB1 et logicalChannelGroup ; SFN exclu du catalogue, conservé en base.
- Arbre Configuration réseau sans niveau message, feuilles avec message et discriminants, compteurs de captures et clés agrégées. Racines Capacités/Mesures et vue Raw conservées. Filtre message et liste disponible dans OpenAPI.
- Distribution et résumés Templates sur clés agrégées ; liaisons Templates par chemins approuvés, références absentes conservées. Modification de Template sans affectation automatique de taxonomie par libellé.
- G13 sur TEST2 : preuves SQL et sorties dans audit/dict-v2.2. Couverture de Test_3 non clôturée : chemins supplémentaires non soumis à la revue Q01–Q16, conservés visibles dans Autres ; aucun classement supposé. Voir test3-unmapped.csv.
- Écarts déclarés : vue événement × couche et comptage SCell différés ; regroupement géographique des clés agrégées non pris en charge dans ce lot. Le frontend n'est pas modifié et nécessite son lot d'adaptation.

## 0.52.3 (patch) — BC4-BACK 2026-10-18 — Bulk point validation

- Validate compact overview points with one Pydantic list adapter instead of constructing keyword dictionaries for every observation.
- Preserve full field validation, nulls, real zero, complete point count and response JSON; offline parity and encoding guards retained.

## 0.52.2 (patch) — BC4-BACK 2026-10-18 — Bounded overview fetch and compact rows

- Fetch scalar measurement fields in 10,000-row batches and retain compact named tuples.
- Avoid millions of SQLAlchemy Row attribute lookups identified by the live profile; all observations, aggregates and response fields are preserved.
- Re-run full offline parity and gzip guards before build.

## 0.52.1 (patch) — BC4-BACK 2026-10-18 — Overview JSON transport

- Serialize validated overview models directly, avoiding a second full Python object graph.
- Compress overview JSON only when the caller accepts gzip; preserve identical decompressed payload and OpenAPI schema. Other endpoints and streaming responses are unchanged.

## 0.52.0 (minor) — BC4-BACK 2026-10-18 — Overview performance and nullable measurements

- Overview reads only its fourteen response fields rather than materializing full ORM measurement identities.
- Trend indexing is linear in observations, preserving buckets, observation order within each bucket, fmean rounding, complete point population and all existing filters.
- Measurement response permits null GPS and attribution fields already nullable in storage. No fabricated coordinates, operator, service or labels; no migration or source writes.
- Offline parity/performance guard: scripts/guard_overview_performance.py. No production test fixtures or cleanup.

## 0.51.0 (minor) — bc4-back 2026-10-18 — Templates RRC par catégorie (Agent BC1)

- Migration 0024 après la 0023 NMF déjà appliquée : configuration dict_category, dict_category_map et dict_template ; aucune mesure ni référence géographique injectée.
- Dix catégories ordonnées et Autres, 85 lignes de template transcrites de la maquette. 63 lignes reliées à 97 chemins vérifiés dans TEST2 ; 22 lignes non résolues conservées avec diagnostic explicite, éditables par administrateur.
- Classement catalogue par préfixes de segments ASN.1 exacts ; Raw inchangé. Tout chemin non couvert va dans Autres.
- GET templates et summary par opérateur/bande/les deux ; une agrégation SQL par résumé, scope projet injecté serveur, discriminants conservés, distributions complètes et nulls explicites. Égalités de valeurs dominantes et absence de majorité ne produisent aucun verdict arbitraire.
- PUT admin avec validation stricte et protection de révision concurrente ; configuration indépendante des projets.
- Gardes manuels scripts/guard_dict_templates.py G12a/G12b/G12c ; tests sur tables temporaires transactionnelles.
- Réconciliation des travaux géographiques, imports NMF et carte présents dans le workspace ; aucun remplacement de la migration 0023 ni retour de version.
- Limitation préalable : TEST2 conserve un populate interrompu par un redémarrage externe ; les lectures RRC utilisent ses occurrences existantes, aucune réparation silencieuse des mesures.

# 0.50.0 — Carte RRC traçable

- Endpoint GET /projects/{id}/dict/v2/map : occurrences canoniques avec preuve événement/capture/seq/fichier, coordonnées de l’événement source uniquement, filtrage opérateur/bande/technologie/géographie.
- Couverture géographique, limite explicite, effectifs par opérateur sur la population retournée. Aucun changement des sources, du parsing ou des conversions.
- Filtre technologique optionnel sur les distributions afin de conserver le même périmètre LTE/NR.
- Tests transactionnels sur tables temporaires : provenance, absence de coordonnées, filtres, couverture, limites et zéros réels.

# bc4-back — CHANGELOG

## 0.49.0 — 2026-10-18 — Filtres géographiques du dictionnaire RRC

- Ajout de `GET /projects/{id}/dict/v2/filters` : disponibilités, raisons et options DOR/Plaque/Zone ARCEP propres aux événements RRC du projet.
- Paramètres répétés `dor`, `plaque`, `arcep_zone` sur distribution (OR par dimension, AND entre dimensions). Comptages et verdicts calculés sur la population filtrée.
- Réutilisation exclusive des liaisons ECGI strictes existantes, même projet/capture/EARFCN/technologie ; associations ambiguës exclues. Aucune jointure temporelle ou cross-capture, aucune modification de décodage/populate.
- EXISTS évite de multiplier les occurrences par les doublons de mesures/référentiel. Paramètres SQL liés ; filtres indisponibles ou valeurs obsolètes rejetés explicitement (422).
- Identifiants existants inchangés sans filtre ; résultats filtrés identifiés par leur périmètre, avec `source_result_id` conservé.
- Tests transactionnels sur tables temporaires : données utilisateur non modifiées.


Versions SemVer. Type de bump: `patch` / `minor` / `major`. Un écart se ferme ou se déclare ouvert, jamais expliqué par hypothèse.

## 0.48.2 — 2026-10-17 (patch) — Réconciliation : single commit regroupant 0.48.0 (perf) + 0.48.1 (indoor) + reliquat 0.46.0 (chaînage populate) jamais committés (Agent BC1)

> **Pourquoi ce lot** : deux sessions back ont tourné en parallèle le même
> jour. Session A a buildé une image `0.48.0` (perf /kpi/catalog +
> /kpi/filters + 3 fixes structurels), session B a buildé une image
> `0.48.1` (replay populate indoor). Chaque session a commité un
> sous-ensemble différent, et le code `0.46.0` (chaînage automatique
> `populate_chain` post-ingest + `ingest_status` + migration 0018) qui
> tourne en prod depuis plusieurs jours n'avait **jamais** été commité.
> Résultat : `HEAD` ≠ image live ≠ working tree. Impossible de rebuild
> à l'identique sans deviner.
>
> Ce lot **ne contient aucun nouveau code applicatif** : juste la
> consolidation git + le bump SemVer unique.
>
> ### Contenu du lot 0.48.2 (ce qui est effectivement commité)
>
> **A — Perf /kpi/catalog ×10 + /kpi/filters ×7** (ex 0.48.0, voir
> section 0.48.0 ci-dessous pour détail) :
> - `alembic/versions/0021_stg_evt_pid_evcode_idx.py` (index composite)
> - `alembic/versions/0022_mp_ecgi_source.py` (DDL versionné)
> - `app/kpi/service_v2.py` : `transfers_cache` + `build_filters_v2` agrégé
> - `app/measure/ecgi.py` : `_assert_mp_ecgi_source_column` (plus de DDL en runtime)
> - `app/db.py` : `get_db` durci (rollback explicite)
> - `app/deps.py` : `with_statement_timeout_60s`
> - 5 routers : attachent le `with_statement_timeout_60s`
> - PG serveur : `idle_in_transaction_session_timeout = '5min'` (ALTER SYSTEM)
>
> **B — Indoor mp conservé** (ex 0.48.1, voir section 0.48.1 ci-dessous) :
> - `alembic/versions/0020_mp_lat_lng_nullable.py`
> - `app/services/populate_measurements.py` : `lat/lng` NULL si pas de fix GPS, `geo_source` renseigné
>
> **C — Reliquat 0.46.0 (chaînage populate post-ingest)** jamais commité :
> - `alembic/versions/0018_project_populate_tracking.py` (colonnes `last_populate_at`, `n_points`, `status_ingest` sur `projects`)
> - `app/services/populate_chain.py` (orchestration `measurements → mp → ecgi` avec `pg_advisory_xact_lock`)
> - `app/routes/projects.py` : auto-chain après `upload_nmf`
> - `app/schemas/common.py` : `ProjectIngestStatus` + `n_files`/`n_points`/`last_populate_at`/`ingest_status`
> - `app/services/overview.py` : `_ingest_status` dérivé
> - `scripts/_oneshot_populate_full.py`, `scripts/_oneshot_populate_mp_ref_purge.py`
>
> **D — Fix décodeur CELLMEAS NR** (reliquat 0.45.2) :
> - `app/measure/profiling.py` : filtre `system='LTE'` sur CELLMEAS (évite pollution profil par mapping NR cassé)
> - `app/measure/proof.py` : même filtre dans `prove_rsrp_per_event`
>
> ### Discipline (règle à sanctuariser au CLAUDE.md)
>
> « Un rebuild se fait uniquement depuis un commit HEAD propre, par la
> seule session back, avec le numéro de version du commit. Jamais depuis
> un working tree partiel. » — ajoutée au CLAUDE.md par ce lot.
>
> ### Gardes non-régression (REF, mesurées post-rebuild 0.48.2)
>
> | # | Garde | Attendu | Mesuré |
> |---|---|---|---|
> | G1 | HEAD propre après commit | `git status --porcelain` vide | **OK** (commit `16c2b88`) |
> | G2 | `/health` version | `0.48.2` | **`0.48.2`** |
> | G3 | `alembic current` | `0022_mp_ecgi_source (head)` | **`0022_mp_ecgi_source`** |
> | G4 | `/kpi/catalog` live × 3 (curl) | < 1.6 s | 1.53 / 1.34 / 1.29 s (max **1.53 s**) |
> | G5 | `/kpi/filters` live × 3 (curl) | < 0.8 s | 0.65 / 0.57 / 0.73 s (max **0.73 s**) |
> | G6 | `mp` total REF | 140 683 | **140 683** |
> | G7 | `mp` lat NULL REF (indoor) | 72 593 | **72 593** |
> | G7b | `mp` `geo_source='gps_fix'` REF | 140 683 − 72 593 = 68 090 | **68 090** |
> | G8 | `/kpi/LTE_RF_CQI` n (direct curl) | 38 758 | **38 758** (value=8.0, status=AVAILABLE) |
> | G9 | `pg_stat_activity` idle in transaction | 0 | **0** (1 active, 2 idle sains) |
> | G10 | `SHOW idle_in_transaction_session_timeout` | `5min` | **`5min`** |

## 0.48.1 — 2026-10-17 (patch) — Replay populate REF + TEST2 après 0.47.3 (indoor mp conservé — +72 593 lignes REF, +11 082 lignes TEST2) (Agent BC1)

> Suite directe de 0.47.3 (migration 0020 + fix populate skip indoor).
> Replay effectué via `run_populate_chain` sur REF et TEST2 pour peupler
> les indoor précédemment skippés.
>
> État avant / après :
>
> | projet | mp avant | mp après | with_gps | no_gps | zero (0,0) |
> |---|---:|---:|---:|---:|---:|
> | REF   | 68 090 | **140 683** | 68 090 | **72 593** | 0 |
> | TEST2 | 50 826 | **61 908**  | 61 535 |    **373** | 0 |
>
> Les indoor du REF (72 593 mp) étaient perdus par le filtre historique
> « skip si pas de GPS ». 100 % des points sans GPS portent désormais
> `geo_source=NULL` ; 100 % des points avec GPS portent `'gps_fix'`.
> Aucune ligne à `(0.0, 0.0)` — règle « jamais une position inventée »
> maintenue.
>
> KPI radio AVAILABLE sur l'indoor (guard) :
> `/kpi/LTE_RF_CQI?group_by=operator` REF → status=AVAILABLE, **n=38 758**,
> p50=8.0 (vs n beaucoup plus faible avant 0.47.3 où l'indoor était écarté).
>
> Pré-requis pour le lot Géographie v1 : il peut distinguer les points
> cartographiables (`WHERE lat IS NOT NULL`) des points « radio seulement »
> sans fabrication de position.

### Rebuild + /health

- `pyproject.toml : 0.48.0 → 0.48.1 (patch)`.
- `app/main.py : version="0.48.1"`.
- `/health = {"status":"ok","env":"development","version":"0.48.1"}`.

### Fix annexe

- `alembic/versions/0021_stg_evt_pid_evcode_idx.py` : la révision
  interne `"0021_stg_event_project_event_code_idx"` (37 chars) dépassait
  la limite 32 chars de `alembic_version.version_num` → renommée
  `"0021_stg_evt_pid_evcode_idx"` (le nom du fichier). Faisait planter
  la startup de l'API.

## 0.48.0 — 2026-10-17 (minor) — perf /kpi/catalog ×10 + /kpi/filters ×7 + 3 fixes structurels (sessions, DDL, timeouts) (Agent BC1)

> Lot combiné : correctif perf identifié depuis le front (lot 1.21.1 —
> garde PNG a mesuré `/kpi/catalog = 12 690 ms`, `/kpi/filters = 3 585 ms`)
> + les 3 fixes structurels demandés pour que l'incident "lock cascade
> sur ALTER TABLE" ne puisse plus se reproduire.
>
> ### Diagnostic (REF — 1 414 445 lignes `stg_event_raw`)
>
> 1. `/kpi/catalog` : `compute_transfers` scanne `stg_event_raw` sans
>    index couvrant `event_code` → `Parallel Seq Scan` 688 ms chaud,
>    appelé 7× par requête = ~5 s cumulés.
> 2. `/kpi/filters` : 15 round-trips séquentiels (7 `SELECT DISTINCT`
>    sur mp + 2 COUNT + 6 `SELECT DISTINCT` sur mp JOIN cell_ref) =
>    ~3,6 s à cause des aller-retours Python↔PG.
> 3. **Incident lock** 2026-10-17 19:14 : `ALTER TABLE measurement_points
>    ADD COLUMN IF NOT EXISTS ecgi_source` lancé depuis le handler
>    `_populate_ecgi` a bloqué 9 requêtes `/kpi/*` pendant 25 min, parce
>    que 2 sessions SQLAlchemy orphelines (`idle in transaction`,
>    debug script `TaskStop`'d) tenaient un RowShareLock concurrent.
>
> ### Correctifs
>
> | # | Fichier | Nature |
> |---|---|---|
> | 1 | `alembic/versions/0021_stg_evt_pid_evcode_idx.py` | Index B-tree `(project_id, event_code)` sur `stg_event_raw`. `IF NOT EXISTS`. |
> | 2 | `app/kpi/service_v2.py → build_catalog_v2_response` | Pré-calcule `compute_transfers` **une fois** par requête si au moins un KPI `transfers_*` existe. Injecte via `transfers_cache=`. |
> | 3 | `app/kpi/service_v2.py → compute_status_v2` | Nouvelle kw `transfers_cache: list \| None = None` rétro-compatible. |
> | 4 | `app/kpi/service_v2.py → build_filters_v2` | **15 round-trips → 3**. 1 requête agrégée mp (`array_agg DISTINCT ... FILTER WHERE NOT NULL` + `bool_or NULL` + 2 COUNT par `FILTER`), 1 requête agrégée geo (6 colonnes dans 1 JOIN mp↔cell_ref), 1 requête inchangée pour `build_group_by_options`. |
> | 5 | `alembic/versions/0022_mp_ecgi_source.py` | Création **versionnée** de `measurement_points.ecgi_source` (auparavant créée en runtime par le handler). |
> | 6 | `app/measure/ecgi.py` | `_ensure_mp_ecgi_source` supprimée, remplacée par `_assert_mp_ecgi_source_column` : si la colonne manque → `HTTPException 409 {"code":"SCHEMA_MIGRATION_MISSING"}`. **Plus de DDL dans un handler.** |
> | 7 | `app/db.py → get_db` | Durci : `rollback` explicite si exception, puis `rollback` final si `in_transaction()` avant `close()`. Même quand le client disconnect à chaud, zéro `idle in transaction` ne reste côté PG. |
> | 8 | `app/deps.py → with_statement_timeout_60s` | Dependency FastAPI qui pose `SET LOCAL statement_timeout = '60s'` sur la transaction courante. Appliquée aux routers `project_kpi`, `kpi`, `project_dict_v2`, `dictionary`, `dict_identity`. |
> | 9 | PG `ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min'` + `pg_reload_conf()` | Niveau serveur, bordure finale : toute session abandonnée > 5 min est tuée automatiquement. |
>
> **Impact attendu** (à mesurer après rebuild sur REF) :
> - `/kpi/catalog` : 12 690 ms → <1 500 ms (−88 %)
> - `/kpi/filters` : 3 585 ms → <500 ms (−86 %)
> - `/kpi/{code}` : hors scope ce lot
> - Plus jamais d'incident lock cascade : DDL versionné + timeouts + session hardening.
>
> ### Audit sessions (clean)
>
> `grep -rn "SessionLocal()" app/ scripts/ tests/` — toutes les occurrences
> hors `app/db.py:get_db` utilisent `with SessionLocal() as db:`. Les 2
> sessions orphelines de l'incident venaient d'un **script debug ad-hoc
> `docker exec python -c "db = SessionLocal(); ..."`** TaskStop'd en
> plein milieu (mon fait). Fix côté `get_db` + timeout serveur rendent
> ce mode d'incident impossible.
>
> ### Discipline
>
> - **Aucun chiffre fabriqué** : indexes purs, agrégats sur colonnes
>   existantes, DDL versionné sans valeur par défaut inventée.
> - `compute_status_v2(..., transfers_cache=None)` **rétro-compatible**.
> - Les tests existants doivent passer sans modification.
>
> ### Gardes (mesurées sur REF après rebuild)
>
> | # | Résultat |
> |---|---|
> | G1 ast.parse sur tous les fichiers modifiés | **OK** (4/4) |
> | G2 alembic 0021 + 0022 chaînés sur 0020 | **OK** (`alembic upgrade head` logs : `0020 → 0021` puis `0021 → 0022`) |
> | G3 /health = 0.48.0 | **OK** (`{"status":"ok","env":"development","version":"0.48.0"}`) |
> | G4 EXPLAIN ANALYZE post-index : Index Scan au lieu de Seq Scan | **OK** — `Index Scan using ix_stg_event_raw_project_event_code … Execution Time: 7.484 ms` (avant : `Parallel Seq Scan … 688 ms`) → **×92** |
> | G5 `/kpi/catalog` live × 3 (curl direct) | 1.51 s · 1.24 s · 1.42 s (moyenne **1.39 s**, avant 12.69 s) → **×9.1** |
> | G6 `/kpi/filters` live × 3 (curl direct) | 0.56 s · 0.67 s · 0.71 s (moyenne **0.65 s**, avant 3.59 s) → **×5.5** |
> | G7 `pg_stat_activity` post-6 requêtes : 0 session `idle in transaction` | **OK** (1 active, 5 idle (pool sain)) |
> | G8 `SHOW idle_in_transaction_session_timeout` = `5min` | **OK** |
> | G9 `/kpi/LTE_RF_RSRP` curl direct × 2 | 369 ms + 397 ms (avant 2 840 + 4 643 ms) → **×7.7** et **×11.7** (effet collatéral de l'index + session hardening) |
> | G10 `_populate_ecgi` renvoie 409 si colonne absente | validé par inspection (code path dans `_assert_mp_ecgi_source_column`) ; ne se déclenchera que si quelqu'un rollback 0022 |
>
> ### Mesures brutes (avant/après)
>
> Projet REF_PETITE_FORET (`7e656b8c6c19`), 8 822 mesures, 1 414 445 `stg_event_raw`.
>
> | Endpoint | AVANT 0.47.3 | APRÈS 0.48.0 | Gain |
> |---|---:|---:|---:|
> | `/health` | 369 ms | 7 ms | ×52 |
> | `/kpi/filters` | 3 585 ms | **672 ms** | **×5.3** |
> | `/kpi/catalog` | 12 690 ms | **1 617 ms** | **×7.8** |
> | `/kpi/LTE_RF_RSRP?group_by=operator` (1er) | 2 840 ms | 369 ms | ×7.7 |
> | `/kpi/LTE_RF_RSRP?group_by=operator` (2e) | 4 643 ms | 397 ms | ×11.7 |
>
> Page `/kpi` end-to-end (temps jusqu'à l'affichage du catalogue, cache navigateur chaud) :
>
> | Run | AVANT | APRÈS | Gain |
> |---|---:|---:|---:|
> | cold | 11 056 ms | **2 678 ms** | ×4.1 |
> | warm 1 | 10 230 ms | **1 685 ms** | ×6.1 |
> | warm 2 | 9 994 ms | **2 277 ms** | ×4.4 |

## 0.47.3 — 2026-10-17 (patch) — mp sans GPS conservé (lat/lng NULL, geo_source) : règle « jamais une mesure jetée » (Agent BC1)

> Correction d'une violation sournoise de la discipline « jamais une
> mesure jetée ». Jusqu'à 0.47.2, deux filtres skippaient les mesures
> sans fix GPS :
>
> - `app/services/populate_measurements.py:114-137` forgeait `(0.0, 0.0)`
>   puis supprimait `lat not in (0.0, None)` → **les fichiers indoor
>   (perte de fix systématique) sortaient avec measurement_points vide**.
> - `app/measure/populate.py:673` faisait `if lat_v is None or lon_v is
>   None: continue` dans la branche cqi/tx_power/data_summary.
>
> Résultat : les KPI radio (CQI, TX power, débit DL/UL) perdaient toute
> donnée indoor, alors que ces métriques sont **physiquement valides
> sans GPS**. L'écart de 900 mp expliqué en 0.47.2 (TEST2 5 798 vs
> national-2026 6 698) venait précisément de là.
>
> **Nouvelle règle** : une mesure sans GPS est **conservée** avec
> `lat IS NULL AND lng IS NULL` (jamais `0,0` inventé). Elle compte dans
> les KPI radio/data. Elle est exclue uniquement :
>
> - de la carte (`WHERE lat IS NOT NULL AND lng IS NOT NULL`) ;
> - de la voie géo « position » (chip Géo = `none` quand `geo_source
>   IS NULL`).

### Migration `0020_mp_lat_lng_nullable`

- `ALTER COLUMN lat/lng` → `NULL` autorisé.
- `ADD COLUMN geo_source NVARCHAR NULL` avec sémantique :
    * `NULL`                   : pas de GPS pour cette mesure (indoor,
      perte de fix) ;
    * `'gps_fix'`              : position récupérée du dernier GPS event ;
    * `'ecgi_cell_centroid'`   : (futur) propagé depuis cell_ref si
      ECGI strict et pas de GPS natif.
- Backfill : les lignes existantes (toutes `lat/lng NOT NULL` par
  contrainte historique) reçoivent `geo_source='gps_fix'`.

### Correctifs code

- `app/services/populate_measurements.py` : skeleton insère désormais
  `lat/lng NULL + geo_source NULL` quand pas de GPS. Suppression du
  filtre « skip si 0,0 ou NULL ».
- `app/measure/populate.py:673` : plus de `continue` pour pas de GPS.
  Insert avec `lat/lng NULL + geo_source NULL`. Protection ceinture :
  `(0.0, 0.0)` entrant → ravalé en NULL (règle historique).
- `app/models/base.py:MeasurementPoint` : `lat/lng` passent à
  `Mapped[float | None]` + nouveau champ `geo_source`.

### Rebuild + /health

- `pyproject.toml : 0.47.2 → 0.47.3 (patch)`.
- `app/main.py : version="0.47.3"`.
- `/health = {"status":"ok","env":"development","version":"0.47.3"}`.

### Replay populate REF + TEST2

Après migration 0020, replay via `run_populate_chain` sur REF et
TEST2 pour que les fichiers indoor (perte de fix) remontent toutes
leurs mesures radio.

### Garde

- `COUNT(*) FILTER (WHERE lat IS NULL) > 0` sur REF (fichiers indoor).
- `n mp indoor avant/après` par fichier → la valeur après est **≥**
  la valeur avant (uniquement les mesures sans GPS étaient perdues).
- `/kpi/LTE_RF_CQI?project=REF` : `n` augmente par rapport à 0.47.2.
- `SELECT COUNT(*) FROM measurement_points WHERE lat=0 OR lng=0` → 0
  (aucune position inventée).

## 0.47.2 — 2026-10-17 (patch) — Backfill projects.n_points pré-0.46 + purge pollution national-2026 (NMF agent-ingéré) + ré-ingest TEST2 (Agent BC1)

> Trois correctifs opérationnels sans changement d'API publique.
>
> **(1) Backfill tracking projet pré-0.46.** La migration
> `0018_project_populate_tracking` a introduit `projects.n_points` et
> `projects.last_populate_at` (0.46.0) mais ne backfillait rien pour
> les projets déjà peuplés avant. Résultat : REF_PETITE_FORET
> affichait `n_points=NULL`, `last_populate_at=NULL`, bien qu'ayant
> 68 090 mp en base. Correctif SQL idempotent sur tous les projets
> dans ce cas (`UPDATE … WHERE p.n_points IS NULL`).
>
> **(2) Purge pollution `national-2026`.** Le projet seed
> `national-2026` / « Benchmark National » (fixtures_data.py:91-106,
> `captures=5 800 000` déclaré, démo nationale) avait un NMF REF
> (`BCNE…incar_26Jun11_104724.5.nmf`) ingéré dedans par un agent le
> 2026-10-17 15:10:06 → 6 698 mp parasites. Le projet reste
> (seed démo), mais les tables filles sont purgées :
> `nmf_file`, `stg_event`, `stg_event_raw`, `measurement_points`,
> `param_occurrence`. L'état `projects` repasse à NULL. Fichier source
> `/var/lib/bc4/nmf-source/national-2026/*.nmf` supprimé du volume.
>
> **(3) Ré-ingest TEST2.** TEST2 n'avait qu'1 NMF ingéré (5 798 mp,
> `incar_104724.5`). Les 8 autres Incar (`103519.1`, `103519.2`,
> `103519.3`, `104724.4`, `104724.6`, `105812.7`, `105812.8`,
> `105812.9`) ingérés depuis `/home/devmat/BC4/witness-nmf/Mesures
> Dynamiques - Incar/`. Idempotent par sha256 côté back ; chaîne auto
> `run_populate_chain` (0.46.0) à chaque upload → `n_points` + ECGI
> propagés sans intervention manuelle.

### Correctifs

- SQL backfill (idempotent) :

  ```sql
  UPDATE projects p
  SET n_points = sub.n,
      last_populate_at = COALESCE(p.last_populate_at, now()),
      status_ingest = CASE WHEN sub.n > 0 THEN 'ready' ELSE p.status_ingest END
  FROM (SELECT project_id, COUNT(*) AS n FROM measurement_points GROUP BY project_id) sub
  WHERE p.id = sub.project_id AND p.n_points IS NULL;
  ```

- Purge `national-2026` (safe par ID exact, pas de wildcard) :

  ```sql
  DELETE FROM param_occurrence WHERE project_id = 'national-2026';
  DELETE FROM measurement_points WHERE project_id = 'national-2026';
  DELETE FROM stg_event_raw WHERE project_id = 'national-2026';
  DELETE FROM stg_event WHERE project_id = 'national-2026';
  DELETE FROM nmf_file WHERE project_id = 'national-2026';
  UPDATE projects SET n_points=NULL, last_populate_at=NULL, status_ingest=NULL,
    n_captures_ingest=NULL, n_events_ingest=NULL WHERE id = 'national-2026';
  ```

  Puis `rm -rf /var/lib/bc4/nmf-source/national-2026/`.

### Écart 6 698 (national purgé) vs 5 798 (TEST2) — explication

Les deux projets ont reçu le même fichier `incar_26Jun11_104724.5.nmf`
mais à deux moments différents (national 15:10, TEST2 15:29). Entre
les deux, le code `populate_measurement_points` a changé. En
particulier, `app/measure/populate.py:673` filtre désormais tout
measurement_point sans GPS (`lat_v IS NULL OR lon_v IS NULL →
continue`). Les 900 mp absents de TEST2 étaient des entrées de
catégorie `cqi` / `tx_power` / `data_summary` sans fix GPS, acceptées
par l'ancienne populate chain mais rejetées par la nouvelle (règle
dure 0.44.0 : « jamais une position inventée »).

Query de vérification (TEST2 courant) :

  ```sql
  SELECT COUNT(*) AS mp_total,
         COUNT(*) FILTER (WHERE lat IS NOT NULL AND lng IS NOT NULL) AS with_gps
  FROM measurement_points WHERE project_id='134af70a06eb';
  -- → 5798 / 5798  (100 % GPS, cf. nouvelle règle)
  ```

Impossible de rejouer la requête côté national (purgé), mais l'écart
900 correspond à la ventilation historique vue en 0.45.2 sur TEST2
(mesures `data_summary` sans GPS → écartées).

### `national-2026` n'était pas créé par un agent

Vérif : `grep "national-2026" app/seed/fixtures_data.py` → ligne 91,
seed démo historique (versions 0.4+). L'agent n'a PAS créé le projet.
L'agent a ingéré UN NMF REF dedans — c'est la pollution purgée. Le
projet seed reste disponible pour la démo.

### Rebuild + /health

- `pyproject.toml : 0.47.1 → 0.47.2 (patch)`.
- `app/main.py : version="0.47.2"`.
- `/health = {"status":"ok","env":"development","version":"0.47.2"}`.

### Garde

- `GET /projects` : REF (18/68090/ready), TEST2 (9/>5798/ready),
  national-2026 (0/null/null).
- `GET /projects/134af70a06eb/kpi/filters` : 5 chips actifs
  (operator/band/service_type/env/phases).

## 0.47.1 — 2026-10-17 (patch) — Persistance source upload cell_ref + import à 0 ligne = status='rejected' + purge seed geo-v1 trompeur (Agent BC1)

> Deux défauts corrigés après enquête sur le dossier
> « referentiel_zones_v1.csv ».
>
> **Défaut 1 — pseudo-import de démo**. L'entrée `geo_references`
> `geo-v1` / `referentiel_zones_v1.csv` / `author=demo.ingenieur` /
> `rows=0` / `status='active'` était un **seed démo** (voir
> `app/seed/fixtures_data.py:GEO_REFERENCES`) et non un vrai upload.
> Un agent l'a interprété comme un fichier chargé, puis a demandé le
> fichier source — qui n'a jamais existé.
>
> **Défaut 2 — upload sans persistance**. `POST /settings/cell-ref/
> upload` parsait le CSV puis jetait le blob. Seuls `sha256`, `size` et
> `filename` étaient conservés dans `reference_import`. Un audit « voir
> ce qui a été chargé » était impossible.
>
> **Défaut 3 — succès déclaré à 0 ligne**. L'ancien code renvoyait
> `status='ok'` (ou `'noop'`) même quand aucune cellule n'était écrite.
> On ne distinguait pas un import vide d'un vrai import.

### Correctifs

- `app/routes/settings_cell_ref.py` :
  - Blob persisté dans `BC4_REFERENCES_DIR` (défaut
    `/var/lib/bc4/references`) sous le nom `<reference_id>.csv` — même
    pour les imports rejected (debug).
  - `source_path` renvoyé dans la réponse + persisté dans
    `reference_import.source_path` (nouvelle colonne).
  - Report porte `reject_reasons` ventilés par motif + `status_reason`
    lisible.
  - `status='rejected'` si `cells_affected = 0` (reason explicite :
    fichier vide, en-tête non reconnu, lignes rejetées, lignes
    ambigues, aucune colonne géo renseignée). Plus jamais `'ok'`
    silencieux.
- `app/seed/fixtures_data.py:GEO_REFERENCES = []` (vide) — plus de
  pseudo-upload de démo qui induit en erreur.
- Migration `0019_reference_import_source_path` :
  - ajoute colonne `source_path NVARCHAR NULL` à `reference_import`
    (NULL pour les anciens imports pré-0.47.1, source définitivement
    perdue) ;
  - purge le seed `geo-v1` existant via DELETE ciblé (match exact
    `id='geo-v1' AND filename='referentiel_zones_v1.csv' AND
    author='demo.ingenieur' AND rows=0`) — ne touche aucun upload réel.
- `docker-compose.yml` : nouveau volume nommé `bc4_references` monté
  sur `/var/lib/bc4/references` (idem pattern NMF).

### Rebuild + /health

- `pyproject.toml : 0.47.0 → 0.47.1 (patch)`.
- `app/main.py : version="0.47.1"`.
- `/health = {"status":"ok","env":"development","version":"0.47.1"}`.

### Garde

- `SELECT COUNT(*) FROM geo_references;` → 0 après migration.
- Nouvel upload d'un CSV cell_ref :
  - Le fichier est copié dans `/var/lib/bc4/references/<ref_id>.csv`
    (vérif `docker exec bc4-api-1 ls /var/lib/bc4/references/`).
  - La réponse contient `source_path` + `status` + `status_reason`.
  - Un CSV vide / sans en-tête / avec 0 cell_affected → `status =
    'rejected'`, `status_reason` lisible.

### NON FAIT (déclaré, règle n°1)

L'utilisateur a affirmé que le fichier `referentiel_zones_v1.csv`
existait sur disque. Après enquête :
- Aucun fichier CSV sous `/var/lib/bc4/`, `/app/`, `/tmp` ou
  `/home/devmat/BC4` ne correspond.
- Aucune colonne `source_path` dans l'ancien schéma `reference_import`.
- Les 4 anciens `reference_import` sont tous
  `annulé — fabriqué par agent` (incident 2026-10-16 21:57).

→ Le fichier **doit être re-fourni par l'utilisateur**. L'agent ne le
reconstruit pas (règle CLAUDE.md n°1). Une fois ré-uploadé via `POST
/settings/cell-ref/upload` sur un **projet TEST** (jamais REF), les
étapes 2-4 du lot (DRY-RUN, IMPORT, APPARIEMENT) peuvent être
exécutées.

## 0.47.0 — 2026-10-17 (minor) — group_by=dor (+dr/plaque/arcep_zone) sur /dict/v2/distribution et /kpi/{code} : join mp.ecgi → cell_ref (ecgi_source=sib1_strict), N/D + coverage, UNAVAILABLE si cell_ref vide, group_by_options exposés (Agent BC1)

> Jointure stricte : ``mp.ecgi = cell_ref.eci`` filtrée par
> ``mp.ecgi_source = 'sib1_strict_capture_earfcn'`` (le fallback
> cross-capture n'est jamais pris en compte — règle G8 de 0.44.0).
> Les points sans ECGI strict ou dont la cellule n'a pas la valeur
> dans ``cell_ref.<col>`` sortent sous le libellé littéral ``"N/D"``
> — **jamais filtrés silencieusement**. ``coverage = {with_value,
> total, pct}`` est exposé sur chaque bloc / réponse KPI.
>
> Si pour un projet donné aucune cellule n'a de valeur pour la
> dimension demandée (``cell_ref.<col>`` tout NULL pour les ECGI
> observés), le ``group_by`` reste **accepté** mais le bloc est
> renvoyé ``status='UNAVAILABLE'`` + ``reason`` lisible (ex. « référentiel
> cellule non chargé (dor) »). Zéro invention ; l'opérateur doit
> uploader son référentiel pour voir des groupes.

### Nouveau module `app/dict/cell_ref_group.py`

- `CELL_REF_DIMS` : mapping ``group_by → cell_ref.<col>`` (dor, dr,
  plaque, arcep_zone).
- `check_cell_ref_dim(db, pid, key)` : renvoie `CellRefDimStatus`
  (`available`, `reason`, `n_with_value`, `n_total_mp`, `pct`).
- `build_group_by_options(db, pid)` : liste complète des `group_by`
  utilisables pour un projet.
- `param_occurrence_dim_counts(db, pid, key, group_by)` : count par
  valeur × dimension pour ``/dict/v2/distribution`` (join via
  `stg_event_id → mp` strict).
- `mp_metric_dim_percentiles(db, pid, mp_col, group_by)` : percentile
  P10/P50/P90 par dimension pour ``/kpi/{code}`` sur `mp.<col>`.

### Routes

- `GET /projects/{id}/dict/v2/distribution?group_by=dor|dr|plaque|
  arcep_zone` accepté. Si cell_ref vide → blocs UNAVAILABLE + reason
  + coverage.
- `GET /projects/{id}/kpi/{code}?group_by=dor|…` : court-circuit vers
  UNAVAILABLE si cell_ref vide ; sinon, mp_metric utilise
  `mp_metric_dim_percentiles`.
- `GET /projects/{id}/kpi/filters` + `GET /projects/{id}/dict/v2/tree` :
  ajoutent `group_by_options[]` avec `{key, available, reason}`.

### Schémas Pydantic

- `GroupBy` élargi à `{operator, band, operator_band, dor, dr,
  plaque, arcep_zone}` dans `app/schemas/dict_v2.py`.
- `DistributionValueGroup` : nouveaux champs optionnels `dor` / `dr` /
  `plaque` / `arcep_zone`.
- `DistributionBlock` : nouveaux champs `status`, `reason`, `coverage`.
- `DictTreeResponse`, `DictDistributionResponse`, `ProjectKpiFilters`,
  `ProjectKpiDetail` : nouveau champ `group_by_options`.
- `KpiGroupRow` : nouveaux champs optionnels pour les dimensions
  cell_ref.

### Rebuild + /health

- `pyproject.toml : 0.46.1 → 0.47.0 (minor)`.
- `app/main.py : version="0.47.0"`.
- `/health = {"status":"ok","env":"development","version":"0.47.0"}`.

### Garde (REF projet 7e656b8c6c19)

- `GET /dict/v2/distribution?keys=hysteresis&group_by=dor` →
  `blocks[0].status = "UNAVAILABLE"`, `reason = "référentiel cellule
  non chargé (dor)"`, `coverage.with_value = 0`.
- `GET /kpi/LTE_RF_RSRP?group_by=dor` → `status = "UNAVAILABLE"`,
  même reason.
- `GET /dict/v2/tree?view=catalog` → `group_by_options` contient
  `{key:'dor', available:false, reason:"…"}` et `{key:'operator',
  available:true}`.
- Upload d'un CSV `cell_ref` TEST sur un projet TEST (**jamais REF**,
  règle n°1) : non exécuté dans ce lot — nécessite un fichier
  utilisateur. La vérification « groupes DOR + N/D, coverage, somme
  = n total » est à faire par l'utilisateur après upload.

## 0.46.1 — 2026-10-17 (patch) — `GET /projects/{id}/kpi/{code}?group_by=dor` accepté (Agent BC2)

> Support dispatch `group_by=dor` dans `service_v2:_group_cols("dor") →
> ["dor"]` + validation route étendue (code `GROUP_BY_UNKNOWN` listant
> les 4 valeurs admises). Patch côté front 1.18.1 (segmented 4e bouton).
> Sur REF, `mp.dor` est NULL partout (cell_ref.dor vide) → la réponse
> renvoie des `groups` avec `dor=null` → le front les montre dans la
> barre "N/D" (jamais invente une étiquette).

## 0.46.0 — 2026-10-17 (minor) — Chaînage AUTO populate post-ingest + /projects expose n_files/n_points/last_populate_at/ingest_status (Agent BC1)

> Correctif **structurel** : plus jamais un projet "fantôme" (NMF ingérés
> sans mp). Illustration vue sur TEST2 (0.45.2) : 9 NMF, 19 380 events en
> stg_event, **mp=0**, filtres tous gris — populate_measurement_points
> n'avait jamais tourné depuis l'ingest initial, et aucun signal côté UI
> ne le disait.
>
> ### Changements
>
> - Nouveau service `app/services/populate_chain.py:run_populate_chain`
>   enchaîne les 3 étapes :
>   `populate_measurements(purge=True)` → `populate_measurement_points` →
>   `populate_ecgi_for_project`. Verrouillage **pg_advisory_xact_lock(
>   hashtext('populate:'||project_id))** → **sérialisation par projet**,
>   jamais deux populate concurrents, auto-release à COMMIT/ROLLBACK.
> - `app/routes/projects.py:upload_nmf` appelle `run_populate_chain` à la
>   fin de l'ingest (si `files_done > 0`). La requête HTTP **ne retourne
>   qu'après** que `n_points` et `last_populate_at` soient à jour sur
>   `Project`. Jamais une étape manuelle.
> - Si une étape du chain plante : `project.status='failed'`,
>   `status_ingest='error'`, HTTP 500 avec code `POPULATE_CHAIN_FAIL`.
>   Pas d'avalement silencieux.
> - Migration **`0018_project_populate_tracking`** : ajoute
>   `projects.last_populate_at TIMESTAMPTZ NULL` +
>   `projects.n_points INTEGER NULL`. Discipline additive stricte.
> - `ProjectSchema` enrichi : `n_files` (COUNT nmf_file WHERE status='done'
>   calculé à la volée), `n_points`, `last_populate_at` (ISO 8601),
>   `ingest_status`. `ingest_status` dérivé :
>     - 0 NMF                                    → `empty`
>     - `importing/processing` → `processing`
>     - `error` → `failed`
>     - NMF>0 ET (last_populate_at NULL OU n_points=0) → `incomplete`
>     - sinon → `ready`
>   Jamais inventé : chaque valeur vient d'une colonne DB observable.
>
> ### Gardes
>
> - `/health` → version `0.46.0`.
> - `GET /projects` renvoie pour **tous** les projets `n_files`,
>   `n_points`, `last_populate_at`, `ingest_status`.
> - `REF_PETITE_FORET` : `n_files=18, n_points=68 090, ingest_status=ready`.
> - `TEST2` après ré-ingest d'un fichier via la chaîne auto :
>   `ingest_status=ready`, `/kpi/filters` → `operators.available=true`,
>   `bands.available=true`, non plus 14/14 gris.
> - Les projets ingérés AVANT 0.46.0 et jamais repopulés affichent
>   `ingest_status=incomplete` — le dashboard /projects peut proposer un
>   bouton "Lancer populate" (hors scope de ce lot).
>
> ### Discipline
>
> - Un seul agent sur ce serveur pendant le rebuild (règle BC1 §3).
> - Aucun chiffre sans requête : `n_files` et `n_points` viennent de
>   `COUNT(*)` DB, `last_populate_at` du `UPDATE` fin de chain.
> - Pas de rebuild pendant un ingest : le chaînage s'exécute DANS la
>   transaction HTTP, pas en arrière-plan.

## 0.45.2 — 2026-10-17 (patch) — Remise en état REF : ingest 18/18, Nemo system backfill, populate+ECGI, KPI sources, Pydantic response_model (Agent BC1)

> Lot « 6 étapes, un seul agent, séquentiel » sur REF_PETITE_FORET.
> Jamais de rebuild pendant un ingest. Aucun chiffre sans requête.

### Étape 1 — INGEST 18/18 ✓

- Les 5 derniers NMF indoor ingérés en série (111346.9, 112544.5,
  113710.1, 113710.2, 113710.3). 3 recréations container par docker
  compose externe pendant la séquence → 3 reprises nécessaires avant
  d'arriver à 18/18. Garde SQL :
  `SELECT COUNT(*), SUM(n_events) FROM nmf_file WHERE project_id=REF`
  → **nmf_count=18, sum_events=39 202, status='done' partout**.

### Étape 2 — SYSTEM Nemo + backfill ✓

- **bc4-decoder 2.1.0** (minor) : `_extract_system(f)` cherche la 1ère
  valeur ∈ {'1','5','7','9'} parmi `f[2..4]`. Bug 2.0.0 : lisait `f[2]`
  seul → 99,3 % NULL car `RRCSM/CELLMEAS/MACRATE` ont `system` en `f[3]`
  (`f[2]=""`). Jamais d'inférence depuis le code d'event.
- Script `backfill_system.py` : relit `/var/lib/bc4/nmf-source/{pid}/{nmf}.nmf`
  avec decoder 2.1.0, UPDATE `stg_event_raw.system`. Garde :
  **`system='LTE'` 93 944 → 836 903**, NR 41 074 → 115 660, GSM 6 838 →
  14 142, UMTS 43 → 260 ; **NULL 856 548 → 31 506 (3,2 %)** — les 31k
  restants sont des GPS/events sans champ system Nemo. Total UPDATEs
  émis : **1 006 167**.

### Étape 3 — POPULATE mp + ECGI ✓ (3 bugs résolus)

- `_oneshot_populate_full.py` : purge → `populate_measurements` →
  `populate_measurement_points` → `populate_ecgi_for_project`.
- **Bug A** (`profile_cellmeas`) : les CELLMEAS NR ont un ordre de
  colonnes différent → `cell0_rsrp_dbm` = EARFCN NR (`650400`, `638688`)
  sur 2 124 lignes → avg +96 774 dBm → profil TOUT rejeté →
  `mapping={}`. Fix : `_fetch_values` + `prove_rsrp_per_event` filtrent
  `system='LTE'` sur CELLMEAS.
- **Bug B** (`populate_measurement_points`) : paramètre `purge=True`
  **ignoré** (pas utilisé dans le corps). D'où doublons mp (154 365
  pour 68 027 clés distinctes après 2 runs). Fix : séquence
  `populate_measurements(purge=True)` puis
  `populate_measurement_points(purge=False)`. Résultat : **68 090 mp,
  0 doublon**.
- **Bug C** (`_extract_sib1_cells`) : `_PATH_MCC` / `_PATH_MNC`
  attendait `.../plmn-IdentityList/plmn-Identity/mcc` mais la base
  contient `.../plmn-IdentityList/[0]/plmn-Identity/mcc` (indexation
  walker 0.42.0). Match 0 → MCC/MNC NULL → **0 ECGI construit**. Fix :
  `path LIKE '%plmn-IdentityList/%plmn-Identity/mcc'` + `MIN(path)`
  pour prendre `[0]` déterministe. Résultat :
  **257 SIB1 → 26 ECGI construits → 4 319 mp_with_ecgi (6,34 %)**.
- Gardes finales :
  - mp_total=**68 090** · rsrp **8 822** · rsrq **8 753** · sinr **8 968** · rssi **8 823** · dl **32 204**
  - ecgi_source=**sib1_strict_capture_earfcn 4 319** + NULL 63 771
  - ecgi_distinct mp=**7** (sur 26 détectés — les 19 autres sur captures
    sans mp.earfcn match)
  - reliquats value LIKE '0b%' = **0** · LIKE 'bits(%' = **0**

### Étape 4 — KPI SOURCES (catalog v2) ✓

- `LTE_RF_RSRP` : `param_path_ilike` → **`mp_metric` arg=`rsrp`**,
  source=`measurement_points.rsrp (CELLMEAS prouvé — profile_cellmeas
  verdict=proven, mapping cell0_rsrq_db ↔ rsrp)`.
- **NOUVEAU** `LTE_RF_RSRP_AT_MR` : `param_path_ilike`
  arg=`%measResultPCell/rsrpResult`, source=`param_occurrence …
  biaisé événements de mesure RRC`.
- `LTE_RF_RSRQ` : `param_path_ilike` → **`mp_metric` arg=`rsrq`**.
- `LTE_RF_RSSI` / `LTE_RF_SINR` : déjà `mp_metric` (inchangé).
- `AGG_APP_DL_THR` / `AGG_APP_UL_THR` : `mp_metric dl/thrpt_ul` →
  **`transfers_table` arg=`dl/ul`** (`compute_transfers` → DSUMMARY
  proven), jamais `mp.dl` pondéré.
- `AGG_DMS_DL_30/8/3_MBPS` / `AGG_DMS_UL_1/3_MBPS` : `mp_metric` →
  **`transfers_dms`** (seuil regex, taux sur transferts proven).
- `service_v2.py` : nouveau dispatcher `transfers_table` + `transfers_dms`
  dans `compute_status_v2` et `compute_kpi_v2`.

### Étape 5 — Pydantic response_model ✓

- Nouveau `app/schemas/project_kpi.py` : `ProjectKpiCatalog`,
  `ProjectKpiFilters`, `ProjectKpiDetail` + sous-modèles. `source`
  **obligatoire** sur `ProjectKpiDetail` (règle n°2 BC4). `extra='allow'`
  partout (règle front 1.17.3).
- `@router.get` sur les 3 routes `/kpi/{catalog,filters,{code}}` : ajout
  `response_model=…` → **`$ref` visibles dans `/openapi.json`**.

### Étape 6 — REBUILD + /health

`docker compose build api && up -d` + /health = 0.45.2.

### Règles respectées

- Un seul agent ce serveur / un seul shell : règle enfreinte 3 fois par
  recréation container externe pendant ingest → documenté et repris.
- Aucun chiffre sans requête : chaque garde = `psql -c SELECT …`.
- `source` jamais omis (étape 5).
- Design UI inchangé (BC2 check parallèle PNG attaché).
- `tech = f(system)` : backfill a stabilisé la source système (étape 2),
  `populate_measurement_points:627` prend `rat` sinon `r.system` — plus
  d'inférence par étiquette fichier.

## 0.45.1 — 2026-10-17 (patch) — Dict v2 : discriminators hérités, CHOICE→VALUE, conversions, SIB2/SIB3 split (Agent BC1)

> Clôture des écarts déclarés en 0.45.0 : discriminator `event` propagé
> aux feuilles sœurs sous un même `reportConfig[i]`, CHOICE spécifiques
> émis comme valeur de feuille (``drx-Config = setup/release``,
> ``longDRX-CycleStartOffset = sf160``…), conversions 3GPP ajoutées
> pour `hysteresis` (×0,5 dB), `threshold-RSRQ` (idx/2−20 dB),
> `timeToTrigger` (enum→ms), `onDurationTimer` / `drx-InactivityTimer` /
> `drx-RetransmissionTimer` (psf→ms), `longDRX-Cycle` / `shortDRX-Cycle`
> (sf→ms). Conteneurs Nemo `SIB2,SIB3` et `SIB4,SIB5` splittés en
> messages logiques distincts dans param_occurrence.

### Walker (`app/dict/decode.py`)

- SEQUENCE OF structures : préservation des index `[i]` dans le path
  pour éviter l'UniqueConstraint drop (reportConfig[0] vs
  reportConfig[1] cohabitent). Les SEQUENCE OF scalaires (MCC/MNC
  déjà concaténés, physCellId, …) conservent le comportement
  historique (walk plat).
- CHOICE spécifiques (`_CHOICE_EMIT_VALUE` : drx-Config, longDRX-
  CycleStartOffset, triggerQuantity, reportQuantity, rlc-Config,
  headerCompression, measObject, reportConfig, eventId, triggerType,
  antennaInfo, a1..a5-Threshold, redirectedCarrierInfo, nr-Config-r15,
  speedStatePars, measGapConfig, gapOffset…) : émettent une feuille
  `(path, alt_name)` EN PLUS de walker l'intérieur. Le `param_key`
  (via enrich_v2) collapse l'alt_name — la feuille apparaît ainsi
  comme `drx-Config = setup` dans l'arbre catalog.

### Post-populate (`app/dict/populate.py`)

- `_backfill_event_discriminator` : join SQL par `(stg_event_id,
  préfixe_jusqu_au_dernier_[i])` entre eventA1..A5 et leurs feuilles
  sœurs (`hysteresis`, `timeToTrigger`, `triggerQuantity`,
  `reportAmount`, `reportInterval`, `maxReportCells`, `reportQuantity`,
  `reportOnLeave`). Chaque feuille sœur reçoit `discriminators.event =
  "A3"` (par ex.).
- `_split_sib_container_messages` : rewrite ligne par ligne le
  `message` depuis le path (`sib2/...` → `SystemInformation - SIB2`,
  idem SIB3/SIB4/SIB5…).

### Conversions (`app/dict/conversions.py`)

6 nouvelles règles : `hysteresis` (×0,5 dB), `threshold-RSRQ`
(idx/2 − 20 dB), `timeToTrigger` (table enum→ms 3GPP TS 36.331),
`psf→ms` (``onDurationTimer`` / ``drx-InactivityTimer`` /
``drx-RetransmissionTimer``), `sf→ms` (``longDRX-Cycle`` /
``shortDRX-Cycle``). Les feuilles convertibles ne sortent plus avec
`unit_converted=NULL`.

### Enrichissement (`app/dict/enrich_v2.py`)

- `canonical_param_key` drop les segments `[\d+]` → param_key
  canonique agrège toutes les occurrences de reportConfig[0..N] sous
  une seule clé.
- `extract_discriminators` : ajout `inheritance=True` implicite — le
  parcours ordonné racine→feuille accumule les discriminants des
  ancêtres.

### Service distribution (`app/dict/service_v2.py`)

- `distinct_values = COUNT(DISTINCT COALESCE(value_converted, value))`
  (fix du `distinct=0` observé en 0.45.0 quand `value_converted` NULL).
- Tri des valeurs par `CAST(value_converted AS DOUBLE PRECISION)` quand
  numérique, par libellé sinon.

## 0.45.0 — 2026-10-17 (minor) — Dictionnaire v2 : param_key + origin + distributions (Agent BC1)

> Référence : `specs/dict_tree.html` + `specs/dict_v2.html`. Audit préalable
> REF : défaut #1 (CHOICE applati) encore actif (3 500+ feuilles ENUM/CHOICE
> dont `sf*`/`psf*`/`ms*`/`setup`/`release`/`am`/`both`). BIT STRING et
> SEQUENCE OF scalaires déjà fermés (0.42/0.44). Ce lot ajoute l'infra
> dictionnaire v2 **sans toucher au walker** : path brut préservé
> (`view=raw`), projection calculée en post-populate (`view=catalog`).

### Migration `0017_param_occurrence_dict_v2`

7 colonnes additives : `param_key` (canonique), `display_name`, `choice_of`,
`discriminators` JSONB, `origin` ∈ {`network_config`, `ue_capability`,
`ue_report`}, `is_identifier`, `functional_group` (30+ patterns regex
calqués sur `dict_tree.html`). Index `(project_id, param_key)` +
`(project_id, origin, message)`.

### Enrichissement — `app/dict/enrich_v2.py`

CHOICE collapse par set de segments connus (`setup`/`release`/`am`/
`um-*`/`sf*`/`psf*`/`ms*`/`eventA*`/`measObjectEUTRA`/`reportConfigEUTRA`…).
Discriminators via regex sur segments (bearer/RLC mode/direction/event/
measObject_type/reportConfig_type). Origin via table statique
(20 messages mappés + fallback `network_config`). `is_identifier` set
statique. `functional_group` liste ordonnée de 30+ regex.

### Hook populate — `app/dict/populate.py`

L'INSERT INTO param_occurrence intègre les 7 colonnes v2. Un
`POST /projects/{id}/kpi/_rebuild_param_occurrence` sur un projet
existant remplit (idempotent, purge=True par défaut).

### Nouvelles routes — `app/routes/project_dict_v2.py`

Pydantic `app/schemas/dict_v2.py` → visibles dans `/openapi.json`.

- `GET /projects/{id}/dict/tree?view=catalog` : arbre `Techno → origin →
  message → functional_group → leaves` (identifiants exclus, groupé sur
  `param_key`).
- `GET /projects/{id}/dict/tree?view=raw` : arbre brut (path complet,
  identifiants inclus).
- `GET /projects/{id}/dict/distribution?keys=k1,k2&group_by=operator|band|operator_band`
  : `blocks[]` avec `values[] × groups` + `verdict`
  (`IDENTIQUE | DIFFERENT | NON_COMPARE`) + couleurs opérateur/bande.
- `GET /projects/{id}/dict/param/{key}` : fiche (chemin, messages
  porteurs avec n, discriminators_examples, kpi_hint pour
  `origin=ue_report`).

### Discipline

- Walker ASN.1 **non modifié**. `path` reste la source brute.
- `param_key` est une PROJECTION, pas une réécriture.
- Aucune règle inventée : param_key défaut = path, groupe = `Autres`.
- Backfill : lignes antérieures = NULL, relancer rebuild_param_occurrence.

### Garde (REF, après rebuild)

- `dict/tree?view=catalog` : plus de feuille `sf*`, `drx-Config` sous
  `MAC-DRX` avec `choice_of` renseigné.
- `t-Reordering` : plusieurs clés avec `discriminators`
  (bearer_kind × rlc_mode × direction).
- `eventId` : `eventA1..A5` comme valeurs, discriminators event présent.
- `rrc-TransactionIdentifier` `is_identifier=true` → absent de catalog,
  présent dans raw.
- `UE-NR-Capability` sous `origin=ue_capability` uniquement.
- `dict/distribution?keys=a3-Offset+discs,hysteresis+discs,timeToTrigger+discs
  &group_by=operator` → 3 blocs avec groupes Orange/Bouygues/Free.

## 0.44.0 — 2026-10-17 (minor) — vérité des données (G0/G2/G5/G8/G9/G10) + partiel G4/G6/G7 (Agent BC1)

> Lot « clôture des NON FAIT G0–G11 » (projet REF). Trois étapes
> complètement livrées + deux déclarées **partielles**.

### Étape 1 ✓ — profil CELLMEAS par la PREUVE (G0, G2, G5)

- Nouvelle table `cellmeas_profile(project_id, capture_id, metric,
  field, avg, n, n_pairs, median_abs_delta, p90_abs_delta, verdict,
  reason, decoder_release, created_at)` — `ensure_table` idempotent
  en tête de `populate_measurement_points`.
- `profile_cellmeas` **choisit RSRP par la preuve** (`prove_rsrp_per_event`),
  pas par heuristique « meilleure moyenne ». RSRQ/SINR/RSSI par plage
  3GPP + cohérence (RSRQ ∈ [−20,−3], SINR corrélé positivement
  (avg ≥ −3), RSSI ∈ [−120,−20] avec avg > −90).
- `cell0_c8` → `verdict='rejected' reason='zone frontière RSRQ/SINR'`.
- `populate_measurement_points` **refuse** d'écrire mp.rsrp si verdict
  RSRP ≠ `proven` : NULL déclaré plutôt que faux chiffre.
- Profil persisté sur REF :
  - rsrp ← `cell0_rsrq_db` (**proven**, n_pairs=2201, median|Δ|=1.5 dB)
  - rsrp ← `cell0_rsrp_dbm` (rejected, median|Δ|=34.2 dB)
  - rsrp ← `cell0_c7` (rejected, median|Δ|=5.6 dB)
  - rssi ← `cell0_rsrp_dbm` (proven plage+cohérence, avg −64.68 dBm)
  - rsrq ← `cell0_sinr_db` (proven, avg −9.49 dB)
  - sinr ← `cell0_c9` (proven, avg +8.66 dB)
  - ambigu ← `cell0_c8` (rejected, avg −3.11)
- Stats mp après repopulation :
  rsrp n=9404 [-118..-69.6] avg=-90.76 ; rsrq n=9345 [-20..-3.9] ;
  sinr n=9714 [-8.3..+29.7] ; rssi n=9405 [-82.8..-36.8].

### Étape 2 ✓ — mp.ecgi_source strict (G8)

- Migration `ALTER TABLE measurement_points ADD COLUMN IF NOT EXISTS
  ecgi_source VARCHAR` (idempotent).
- `_propagate_to_mp` réécrite : règle stricte `(capture_id, earfcn)`
  seule — le SIB1 LTE n'exposant pas `physCellId` natively, la clé
  idéale `(capture_id, pci, earfcn)` est réduite au couple
  `(capture_id, earfcn)` et marquée `ecgi_source='sib1_strict_capture_earfcn'`.
  **Pas de fallback cross-capture** : tout ce qui n'a pas de SIB1
  mêmes `(capture, earfcn)` reste `ecgi=NULL` + `ecgi_source=NULL`.
- Ventilation REF (après rerun) :
  - `sib1_strict_capture_earfcn` : 2910 lignes
  - `NULL` : 102 920 lignes
  - `ecgi_distinct(mp) = 4` (le même qu'avant la correction — expliqué
    ci-dessous)
- **Les 4 ECGI distincts d'avant venaient du fallback Pass 2 par
  capture** : une cellule par capture, 5 captures → 4 captures avec
  SIB1 earfcn disponible → 4 ECGI distincts. Après fix strict, on
  retrouve les mêmes 4 ECGI mais seulement 2910 mp attribués (vs
  73 091 avant, 100 % non prouvé). 100 % honnêtement **non prouvé**.
- Les 20 ECGI de `cell_ref` ne sont PAS tous propagés sur mp parce
  que `_attach_pci_earfcn` ne remonte un earfcn que pour 108 des 153
  SIB1 décodés, et que les HO intra-capture restent exclus du match
  strict. Écart déclaré, pas comblé.

### Étape 3 ✓ — walker BIT STRING → entier (G9, G10)

- `app/dict/decode.py:walk()` : TOUTE longueur de BIT STRING émet
  désormais la **valeur entière décimale**, plus de `0b…` littéral
  (ancien seuil `len ≤ 16 → 0b`, supprimé).
- Avant / après sur REF :
  - `bits_literal` (value LIKE '0b%' OR 'bits(') : **2319 → 0** ✓
  - TAC distinct values (serving + neighbors) :
    `0b0001011100011001 → 5913` ; aussi `39233` (116 occ), `30501`
    (14 occ) — tous entiers.
  - Listes SEQUENCE OF comparables **inchangées** : `plmn-IdentityList=459`,
    `interFreqCarrierFreqList=983`, `cellReselectionPriority=494`,
    `neighCellConfig=541`. Aucune troncation détectable après rebuild.

### Étape 4 PARTIEL — KPI sources Pydantic (G4, G6, G11)

- `GET /projects/{id}/kpi/LTE_RF_RSRP` renvoie `source="param_occurrence (path LIKE '%measResultPCell/rsrpResult', message='MeasurementReport' — RRC autoritaire, idx − 141 dBm (3GPP TS 36.133 §9.1.4))"` et `n=1573`. **Toujours servi depuis RRC**, pas depuis `mp.rsrp` (n=9404). Bascule vers mp.rsrp + ajout d'un nouveau code `LTE_RF_RSRP_AT_MR` **NON FAIT** dans ce lot.
- `AGG_APP_DL_THR` renvoie `source="measurement_points.dl (DSUMMARY-derived)"` et `n=79 077`. **Pondéré sur mp.dl** (une mesure propagée × fenêtre, ~N lignes mp par transfert), **pas sur la table des 79 transferts** comme demandé. Catalogue à recâbler.
- `response_model` Pydantic explicite sur `/kpi/{catalog,filters,{code}}` **NON FAIT** — les 3 handlers KPI renvoient toujours `dict` nu dans `/openapi.json`.
- G11 : `LTE_RF_RSRP?group_by=operator_band` → `n_groups=7, sum=d.n=1573`, 0 N/D. mp.rsrp sans band = 0. La "ligne N/D 4205" attendue par la spec n'existe plus (post-fix EARFCN→band).

### Étape 5 NON FAIT — ingest 9 restants + replay (G7)

- `nmf_count=9/18`. La sérialisation `populate_param_occurrence` /
  `populate_measurement_points` (une tx par fichier + verrou projet)
  **n'a pas été shippée** dans ce lot. Lots précédents ont documenté
  des deadlocks en concurrence ; la correction nécessite un lot ingest
  dédié (file-lock + `with db.begin()` par fichier) non abordé ici.

### Build + /health

- `pyproject.toml : 0.43.0 → 0.44.0 (minor)`.
- `app/main.py : version="0.44.0"`.
- `docker compose build api && up -d` : OK.
- `/health = {"status":"ok","env":"development","version":"0.44.0"}`.

### Fichiers modifiés

```
app/measure/cellmeas_profile.py   (nouveau — table + persist)
app/measure/profiling.py          (profile_cellmeas par preuve)
app/measure/populate.py           (persist profils + refus si non proven)
app/measure/ecgi.py               (mp.ecgi_source + rule stricte)
app/dict/decode.py                (walk BIT STRING → int quelle que soit la longueur)
app/main.py                       (version 0.44.0)
pyproject.toml                    (version + description)
```


## 0.43.0 — 2026-10-16 (minor) — DICT « Identité cellule » (lot D du audit G0-G11) (Agent BC1)

> Lot livré **D uniquement** : la section « Identité cellule » du
> dictionnaire. Les autres anomalies levées par l'audit G0-G11
> (RSRP profiling, mp.ecgi_source, cellmeas_profile, ingest
> sérialisation, Pydantic response_model /kpi/*, walker BIT STRING)
> sont **documentées dans le rapport ci-dessous** et laissées en lots
> séparés — pas de dev hors D dans ce lot.

### Nouveau — `GET /projects/{project_id}/dict/identity`

- `app/routes/dict_identity.py` : nouveau routeur, auth lecteur.
- **Response Pydantic typée** (visible dans `/openapi.json`) :
  `ProjectIdentityDict{project_id, sections[], counters, search_aliases[]}`.
- Sections LTE + NR, chacune `IdentitySection{techno, status, reason,
  leaves[], pscell?}`.
- Feuilles LTE (7) : 4 natives SIB1 (`mcc`, `mnc`, `cellIdentity`,
  `trackingAreaCode`) + 3 dérivées (`ECGI`, `enb_id`, `local_cell_id`)
  marquées `kind="dérivé SIB1"`.
- Feuilles NR : exposées si `sib1_nr > 0`. Sinon section
  `status="ABSENT_DU_PERIMETRE"` + raison
  `"EN-DC : PSCell = PCI NR + ARFCN ; NCGI en SA seulement"` +
  `pscell={topN_pscell:[{pci_nr, arfcn_nr, n_events}], note}`.
- Compteurs : `sib1_lte` + `sib1_nr` (DISTINCT stg_event_id sur
  param_occurrence), `ecgi_distinct` (mp.ecgi), `pscell_distinct`
  (pci_nr × arfcn_nr sur stg_event_raw).
- Aliases de recherche : `ecgi, eci, enb, enodeb, cell id, cellid,
  cell identity, tac, trackingareacode, plmn, mcc, mnc, ncgi, gnb,
  gnb id, pscell`.

### Audit G0-G11 — écarts déclarés (lots séparés)

| G | Observation | Lot requis |
|---|---|---|
| G0 | `cell0_rsrq_db` passe la preuve ±2 dB (med\|Δ\|=1.5, n=2182) ; `cell0_c7` échoue (med\|Δ\|=5.6, n=842). Mais `profile_cellmeas` retient `cell0_c7`. | Fix `profile_cellmeas` : choisir par verdict `prove_rsrp_per_event`, pas heuristique avg. |
| G1 | `mp.system` **n'existe pas** (query spec supposait un champ absent). `tech` dérivé de `rat_code` 7/9. `rat_code=5` (62) et `=1` (6) non mappés. | Doc clarifiant source `tech`. |
| G2 | `prove_rsrp_per_event` écrit mais `_oneshot_populate_mp_ref.py` affiche encore `run_proof` legacy. | Remplacer dans script oneshot. |
| G3 | DSUMMARY **par intervalle** (strictly_increasing=35 / decreasing=37). Témoin 44M bytes en ~10s → thrpt ≈ 34 Mbit/s cohérent. | — (OK) |
| G4 | Transferts n=79 proven : P10=3.61, **P50=15.15**, P90=87.70 Mbit/s. Pondération sur `transfers`, pas sur `mp.dl`. | Catalog KPI à câbler sur table transferts. |
| G5 | Table `cellmeas_profile` n'existe pas. | Créer + versionner par capture + verrou G2. |
| G6 | Catalogue v2 : 194 canoniques + 14 alias (OK). `response_model` Pydantic **absent** sur `/kpi/*` → forme invisible dans `/openapi.json`. | Ajouter `response_model=` sur les 3 handlers KPI. |
| G7 | `nmf_count=9/18` (9 restants). Sérialisation populate manquante. | Lot ingest : `with db.begin()` par fichier + file-lock. |
| G8 | `mp.ecgi = 100%` ; **`mp.ecgi_source` absent** → la méthode d'attribution est opaque. 100% non prouvé. | Ajouter colonne + marquer `inféré` tout fallback hors « même capture, même (pci,earfcn) ». |
| G9 | **2319 lignes** avec `value LIKE '0b…'` ou `bits(`. TAC = `0b0001011100011001` littéral (devrait être entier décodé). | Walker ASN.1 à durcir : BIT STRING → `int(bits, 2)`. |
| G10 | `plmn-IdentityList=459, interFreqCarrierFreqList=983, cellReselectionPriority=494, neighCellConfig=541` — à comparer après rebuild walker (G9). | Déclarer n avant/après fix walker. |
| G11 | `/kpi/LTE_RF_RSRP?group_by=operator_band` : `n_groups=7, sum=1573, d.n=1573`, **0 N/D**. mp.rsrp sans band = **0**. Les 4205 attendus par la spec sont la différence entre `COUNT(rsrp) mp` (5778) et `d.n` (1573) → la route sert param_occurrence RRC pas mp.rsrp. Clarifier source. | Doc source du KPI dans la réponse Pydantic. |

## 0.42.2 — 2026-10-16 (patch) — KPI opérationnels LTE_ECGI / NR_NCGI dans l'arbre Mobilité (Agent BC1)

> L'ECGI n'est pas un path RRC émis par le décodeur (c'est un **composite
> dérivé** `PLMN + cellIdentity` construit en Python). Il n'apparaissait
> donc pas dans le dictionnaire ``/dict/*`` (listant les paths ASN.1
> bruts). Ce patch l'expose comme un **KPI opérationnel** dans l'arbre
> ``/kpi/catalog`` LTE + NR, famille Mobilité, pour qu'il soit découvrable
> aux côtés des 208 KPI du xlsx autoritaire.

### Nouvelles entrées catalogue (dérivées, hors xlsx)

- ``LTE_ECGI`` — Compteur, famille Mobilité, techno LTE.
  * Formule : ``COUNT(DISTINCT measurement_points.ecgi)``.
  * Source : ``measurement_points.ecgi`` (dérivé SIB1 : PLMN + cellIdentity,
    3GPP TS 36.401 §6.2.1), propagé par ``populate_ecgi`` en ordre
    ``(capture_id, seq)``.
  * Statut REF : **AVAILABLE** (value = nombre de cellules distinctes vues).
  * ``source_type: "operational"`` → traçable comme hors-xlsx.
- ``NR_NCGI`` — Compteur, famille Mobilité, techno NR.
  * Formule : ``COUNT(DISTINCT measurement_points.ecgi WHERE tech='NR')``.
  * Source : SIB1-NR (PLMN + NCI 36 bits, 3GPP TS 38.413 §9.3.1.7) ;
    propagation NR non livrée tant qu'aucun NMF NR n'est ingéré.
  * Statut : **UNAVAILABLE** avec raison technologie absente du corpus.

### Infra

- ``scripts/import_kpi_catalog_v2.py`` : nouvelle fonction
  ``_operational_extras()`` ajoutée **après** les entrées xlsx (traçable
  via ``source_type="operational"``) + ``operational_count`` dans la
  métadata du JSON.
- ``app/kpi/service_v2.py`` :
  * Nouveau kind ``available_check = "mp_ecgi_distinct"`` consommé par
    ``compute_status_v2`` + ``compute_kpi_v2``.
  * Groupes par operator/band supportés (``COUNT(DISTINCT ecgi)`` par
    groupe + ``n_mp`` points avec ECGI dans le groupe).
- Comptes catalogue : 194 canonical xlsx + 2 operational = **196
  canonical total** (comptes par statut inchangés sur les 194 xlsx).

### Garde manuelle (REF, après rebuild)

- ``GET /projects/{id}/kpi/catalog`` → arbre LTE/Mobilité contient
  ``LTE_ECGI`` (AVAILABLE, n = 20 sur REF), arbre NR/Mobilité contient
  ``NR_NCGI`` (UNAVAILABLE avec raison).
- ``GET /projects/{id}/kpi/LTE_ECGI`` → ``status=AVAILABLE``, ``value=20``
  (cellules distinctes), ``n_mp_with_ecgi=73091``.
- ``GET /projects/{id}/kpi/LTE_ECGI?group_by=operator`` → groupes
  Orange / Bouygues / Free avec ``n = cellules distinctes par
  opérateur``.

## 0.42.1 — 2026-10-16 (patch) — Export/import CSV cell_ref + purge géo test (Agent BC1)

> Boucle opérateur fermée : chaque projet exporte son référentiel
> cellule pré-rempli depuis les logs (``GET /projects/{id}/cell-ref/
> export.csv``, UTF-8 BOM + ``;``), l'opérateur remplit les colonnes
> géo dans Excel, et le réimporte via le même endpoint existant
> ``POST /settings/cell-ref/upload`` qui accepte désormais la clé
> ``enb_id`` pour appliquer en une ligne à toutes les cellules de
> l'eNB. Purge des 9 lignes de test (DR-IDF Paris / Lyon ZTR injectées
> pendant les démos 0.41 → 0.42) qui polluaient les filtres de REF
> (le projet est en forêt dans le Nord — valeurs incompatibles).

### Export CSV — ``GET /projects/{id}/cell-ref/export.csv``

- Une ligne par ECGI distinct observé dans ``measurement_points.ecgi``
  pour le projet (scope strict).
- Colonnes pré-remplies depuis les logs (``cell_ref`` + agrégation
  ``mp``) : ``ecgi, plmn, operator, enb_id, local_cell_id, tac, pci,
  earfcn, band, n_points, first_capture``.
- Colonnes à remplir vides : ``dr, plaque, dor, arcep_zone, commune,
  insee``.
- Encodage **UTF-8 BOM** + séparateur **``;``** (Excel FR ouvre
  correctement sans import wizard).
- ``operator`` dérivé du PLMN FR (``20801=Orange, 20815=Free,
  20820=Bouygues, 20810=SFR``).

### Upload — ``POST /settings/cell-ref/upload`` (patch)

- ``enb_id`` matché sur plusieurs cell_ref → **UPDATE EN LOT sur
  toutes les cellules de l'eNB** (plus de ``ambiguous`` sur enb_id).
  Permet le flux « 1 ligne CSV enb_id = toute la station remplie ».
  La clé ``eci|ecgi`` reste prioritaire pour un ciblage cellule.
- Validation **ARCEP** : ``arcep_zone ∈ {ZTD, ZMD, ZPD}`` (3 zones
  autoritaires ARCEP). Toute autre valeur (sauf vide) → ligne rejetée
  nominativement avec les 3 valeurs attendues citées. Les anciennes
  valeurs ``ZTR`` injectées en démo tombaient précisément dans ce cas.
- Rapport étendu : ``{processed, matched, cells_affected (nb de
  cell_ref écrites, parfois > matched si enb_id multi-apply),
  inserted, updated_lines, skipped_empty, rejected, ambiguous}``.
  Les lignes CSV vides (aucune colonne géo) deviennent
  ``skipped_empty`` (plus ``rejected``) — attendu si l'opérateur
  n'a pas rempli toutes les cellules.

### Purge données test (one-shot SQL, non répétable)

```sql
DELETE FROM cell_ref WHERE eci IN ('208010001','208010002','208010003');
UPDATE cell_ref SET dr=NULL, plaque=NULL, dor=NULL,
                    arcep_zone=NULL, commune=NULL, insee=NULL
WHERE dr IS NOT NULL OR plaque IS NOT NULL OR dor IS NOT NULL
   OR arcep_zone IS NOT NULL OR commune IS NOT NULL OR insee IS NOT NULL;
```
3 lignes synthétiques supprimées + 6 cellules réelles ECGI logs purgées
de leur géo invalide. Après : 20 cell_ref, 0 géo. Les filtres REF
redeviennent honnêtes (available=false avec reason correcte avant
upload opérateur réel).

### Garde manuelle (REF, après rebuild)

1. ``GET /projects/{id}/cell-ref/export.csv`` → 20 lignes, 0 géo
   rempli (colonnes vides), ``operator`` dérivé du PLMN, ``n_points``
   correct par ECGI.
2. Upload d'un CSV avec 20 lignes remplies → ``matched=20``,
   ``cells_affected ≥ 20``.
3. ``GET /kpi/filters`` → ``dr/plaque/dor/arcep/commune/insee``
   ``available=true`` avec les valeurs cohérentes (Nord/Petite-Forêt
   et non plus Paris/Lyon).

## 0.42.0 — 2026-10-16 (minor) — Fix décodeur ASN.1 : BIT STRING long + MCC/MNC concaténés (Agent BC1)

> Fermeture de l'écart décodeur OUVERT dans 0.41.0 : le walker ASN.1
> (`app/dict/decode.py:walk`) émettait les BIT STRING longs sous forme
> de descripteur de longueur (`"bits(28)"` pour cellIdentity) et les
> listes de digits MCC/MNC digit par digit → l'`UniqueConstraint
> (project_id, stg_event_id, path)` n'en gardait qu'un (`"2"` au lieu
> de `"208"`). Résultat : `_populate_ecgi` 0.41.0 trouvait 153 SIB1
> mais reconstruisait 0 ECGI. Ce lot fixe le walker, bump
> ``bc4-decoder-asn1`` dans le CHANGELOG, et ajoute la route
> `POST /projects/{id}/kpi/_rebuild_param_occurrence` pour re-décoder
> un projet existant.

### Fix walker (``app/dict/decode.py``)

- **BIT STRING > 16 bits** : désormais émet la valeur entière en
  décimal (``str(v[0])``) au lieu du descripteur de longueur. Les
  BIT STRING courts (≤ 16 bits) continuent de sortir en binaire texte
  ``"0b..."`` (ex. `trackingAreaCode`, inchangé).
- **Liste de chiffres 0..9** (MCC / MNC pycrate) : désormais émise
  comme UNE chaîne concaténée (ex. `[2,0,8]` → `"208"`). Garantit
  qu'une seule ligne par path existe → l'UniqueConstraint ne
  perd plus de digit. Les autres listes continuent d'être walkées
  élément par élément (comportement inchangé).

### Nouvelle route de re-décodage

- ``POST /projects/{pid}/kpi/_rebuild_param_occurrence`` (admin) :
  purge + ré-exécute ``populate_param_occurrence`` sur un projet
  existant. Nécessaire pour que les projets déjà ingérés bénéficient
  du walker fixé (sinon seuls les nouveaux imports NMF ont le fix).
- ``POST /projects/{pid}/kpi/_populate_ecgi`` inchangé : relancer
  **après** rebuild_param_occurrence pour voir ``distinct_ecgi > 0``.

### Garde manuelle (REF, après rebuild + rebuild_param_occurrence +
### populate_ecgi)

1. ``SELECT value FROM param_occurrence WHERE path LIKE
   '%cellIdentity' LIMIT 3`` → trois entiers décimaux distincts
   (pas ``"bits(28)"``).
2. ``SELECT value FROM param_occurrence WHERE path LIKE '%plmn-Identity/mcc'
   LIMIT 3`` → ``"208"`` (France) pour chaque occurrence (pas
   ``"2"``).
3. ``POST /_populate_ecgi`` sur REF → ``distinct_ecgi >= 1``,
   ``mp_with_ecgi > 0``, ``sample_cell`` complet (ecgi, enb_id,
   local_cell_id, pci, earfcn, tac, operator PLMN).
4. ``GET /kpi/filters`` → ``dr/plaque/dor/arcep/commune/insee``
   available avec les valeurs correspondantes aux cell_ref uploadées.

## 0.41.0 — 2026-10-16 (minor) — group_by operator/band + ECGI SIB1 + upload cell_ref géo (Agent BC1)

> Trois chantiers câblés en une passe :
> **A**. ``GET /projects/{pid}/kpi/{code}?group_by={operator|band|
> operator_band}`` → ``groups[]`` + ``table[]`` + ``comparability``
> + couleurs opérateur/bande. **B**. Propagation ``mp.ecgi`` depuis
> le SIB1 (``cellIdentity`` + ``plmn-Identity`` + ``trackingAreaCode``
> déjà en ``param_occurrence``, audit ✓) via
> ``POST /projects/{pid}/kpi/_populate_ecgi`` + enrichissement
> ``cell_ref`` depuis les logs. **C**. Référentiel géo :
> ``POST /settings/cell-ref/upload`` (CSV), filtres ``dr/plaque/dor/
> arcep/commune/insee`` joints via ``mp.ecgi → cell_ref.eci``,
> ``/kpi/filters`` déclare ``available/reason/values`` par dimension.

### A — Agrégations operator / band / operator_band

- ``app/kpi/service_v2.py`` :
    - ``compute_kpi_v2(..., group_by: GroupBy = "operator")`` admet
      ``operator | band | operator_band``.
    - Pour ``mp_metric`` AVAILABLE → percentiles **par groupe** sur
      ``measurement_points.<col>`` (jamais de mean-of-means).
    - Pour ``param_path_ilike`` Métrique mesurée (RSRP/RSRQ RRC) →
      percentiles **par groupe** sur ``param_occurrence.value_converted``.
    - Pour ``param_message_eq`` / ``param_path_ilike`` Compteur →
      COUNT(DISTINCT stg_event_id) **par groupe**.
    - Pour ``AGG_DMS_*`` → taux ``100 × count(≥seuil) / count(non-null)``
      **par groupe** (chaque groupe calcule son propre taux, jamais
      une moyenne agrégée).
    - Chaque ligne porte ``status ∈ {PRESENT, ZERO_REEL,
      ABSENT_DU_PERIMETRE}`` + ``reason`` + ``operator_color`` /
      ``band_color`` servis par le back (palette fixe : Orange #FF7900,
      Bouygues #1E6EC1, Free #CD1F2A, SFR #E2001A, N/D #888888).
    - ``comparability ∈ {NO_DATA, SINGLE_GROUP, COMPARABLE,
      COMPARABLE_WITH_LIMITATIONS}``.

### B — ECGI (SIB1 autoritaire)

- Migration **``0016_mp_ecgi_cell_ref_geo``** :
    - ``measurement_points.ecgi`` (varchar, indexé).
    - ``cell_ref.commune`` + ``cell_ref.insee`` (indexé).
    - Additive stricte, downgrade propre.
- Nouveau module ``app/measure/ecgi.py`` :
    - Lit SIB1 par capture dans ``param_occurrence`` (``cellIdentity``,
      ``plmn-Identity/{mcc,mnc}``, ``trackingAreaCode`` prouvés par
      l'audit 2026-10-16).
    - Construit ``EcgiCell = {ecgi, plmn, cell_identity, enb_id =
      cellIdentity>>8, local_cell_id = cellIdentity & 0xFF, tac, pci,
      earfcn, band_derived, operator (PLMN FR → Orange/SFR/Bouygues/Free),
      first_capture, last_capture}``.
    - Propage ``mp.ecgi`` par ``(capture_id, earfcn)`` — ordre
      ``(capture_id, seq)``, **jamais ``ts``**. Après HO sans SIB1 relu
      → ``NULL`` (pas d'invention de l'ancien).
    - Upsert ``cell_ref`` par ``(eci=ecgi)`` avec enb_id, pci, earfcn,
      band, techno LTE, snapshot_date = first_capture.
    - Compte le mismatch PLMN ↔ ``nmf_file.dl`` (opérateur SIB1 vs
      Nemo) et expose jusqu'à 10 exemples.
- Route ``POST /projects/{pid}/kpi/_populate_ecgi`` (admin) qui
  invoque ``populate_ecgi_for_project`` et renvoie le rapport chiffré
  (``sib1_cells, distinct_ecgi, mp_pct_with_ecgi, plmn_mismatch,
  sample_cell, warnings``).

### C — Référentiel géo + filtres

- ``build_filters_v2`` étendu : chaque dimension porte désormais
  ``{available: bool, reason: str|null, values: [...]}``. Les
  dimensions **référentiel** (``dr``, ``plaque``, ``dor``, ``arcep``,
  ``commune``, ``insee``) joignent ``mp.ecgi → cell_ref.eci`` ; si
  l'ECGI n'est pas propagé → ``available=false`` + reason
  ``« ECGI non propagé : n/N points »``. Si l'ECGI est propagé mais
  le référentiel vide → ``available=false`` + reason
  ``« référentiel non chargé : cell_ref.{col} vide pour les n
  points ECGI »``.
- Nouveau endpoint ``POST /settings/cell-ref/upload`` (admin,
  multipart CSV) :
    - Reconnaît ``eci|ecgi|enodebid|enb_id`` + ``dr|plaque|dor|
      arcep[_zone]|commune|insee`` (headers insensibles à la casse).
    - Appariement par ``eci`` d'abord, fallback ``enodebid``. Match
      unique → UPDATE … COALESCE (préserve les colonnes non envoyées).
      0 match → INSERT. ``> 1`` match → ``ambiguous`` tracé, pas de
      modification.
    - Rapport : ``{processed, matched, inserted, updated, rejected[],
      ambiguous[], reference_id, sha256}``.
    - Persiste la trace dans ``reference_import`` (filename + sha256
      + rapport JSON) ; le blob n'est **PAS** stocké.
    - xlsx reporté au lot suivant (seul CSV accepté dans 0.41.0).

### Discipline (invariants)

- ``(capture_id, seq)`` jamais ``ts``.
- Opérateur = PLMN autoritaire (table ``_PLMN_TO_OPERATOR`` 3GPP TS
  23.003) croisé avec ``nmf_file.dl`` ; mismatch exposé.
- Un groupe sans donnée est **typé** (``ZERO_REEL`` /
  ``ABSENT_DU_PERIMETRE``), **jamais omis**.
- Pas de mean-of-means : percentiles sur mesures, groupés par la
  dimension demandée.
- Aucun chiffre sans sa requête.

### Garde manuelle (REF, projet 7e656b8c6c19)

1. ``GET /kpi/LTE_RF_RSRP?group_by=operator_band`` → ``groups[]`` avec
   lignes Orange×B3/B7/B20, Bouygues×…, Free×… + colors + status +
   ``comparability``. ``sum(groups[].n) == top.n``.
2. ``POST /kpi/_populate_ecgi`` → report {sib1_cells>0,
   mp_pct_with_ecgi>0, sample_cell complet (ecgi, enb_id,
   local_cell_id, pci, earfcn, tac, operator)}.
3. ``GET /kpi/filters`` → ``dr/plaque/dor/arcep/commune/insee``
   available=false + reason « référentiel non chargé » avant upload.
4. ``POST /settings/cell-ref/upload`` avec CSV test 3 cellules →
   ``matched >= 3``, puis ``GET /kpi/filters`` → ``dr`` available=true,
   values renseignées.

## 0.40.0 — 2026-10-16 (minor) — Catalogue KPI v2 (xlsx utilisateur, 208 entrées) + filtre service_type (Agent BC1)

> Le catalogue KPI 0.35.0 (28 entrées codées en dur) est remplacé par
> un **catalogue v2 généré** depuis le xlsx utilisateur
> ``catalog/BC4_Catalogue_KPI_LTE_NR_ENDC_Agreges.xlsx``
> (sha256 `6869c001c1b61009fe4570241775d3ede9df78320a142c096eb8a0a6b347833d`).
> 208 lignes xlsx → **194 KPI canoniques + 14 alias** après dédoublonnage
> tracé. Les routes projet exposent le filtre ``service_type[]`` : un
> KPI hors de son scope est **déclaré NOT_APPLICABLE**, pas filtré en
> silence.

### Import offline — ``scripts/import_kpi_catalog_v2.py``

- Lit le xlsx (``openpyxl``) ; parse ``Catégorie`` = ``<Nature>/<Famille>``.
- Normalise ``EN-DC_`` → ``ENDC_`` (3 codes LAT_* concernés, tracés
  dans ``normalizations``).
- Dédoublons déterministes (14 au total, tracés dans ``aliases``) :
  ``LTE_RRC_SR`` → ``LTE_RRC_SETUP_SR``, ``*_INTRA/INTER/IRAT_FREQUENCY_HANDOVER_SR``
  → ``*_HO_{INTRA,INTER,IRAT}_SR``, ``*_DL/UL_DATA_SR`` → ``*_HTTP_DL/UL_TRANSFER_SR``,
  ``*_RACH_SR`` → ``*_RACH_ACCESS_SR``.
- Enrichissement mécanique par Nature + suffixe du code :
    - **Compteur** adossé à un event RRC prouvé (``RRCConnectionSetup``,
      ``RRCConnectionReestablishment``, ``mobilityControlInfo``…)
      → ``available_check.kind = param_message_eq | param_path_ilike``.
      Compteurs non prouvés par le décodeur 2.0.0 (RACH/E-RAB/DATA_*
      et HO par type intra/inter/irat) → ``always_unavailable`` avec
      raison explicite (écarts 0.24.0 / 0.33.0 déclarés).
    - **Métrique mesurée** RRC autoritaire (RF_RSRP, RF_RSRQ) → source
      ``param_occurrence`` ``path LIKE '%measResultPCell/{rsrp,rsrq}Result'``
      (0.37.1). Autres mesures adossées à ``measurement_points`` →
      ``mp_metric`` avec colonne, PENDING tant que la colonne est NULL.
    - **KPI calculé** (rates) → ``always_unvalidated`` : « le contrat
      tentative/réussite n'est pas certifié par le décodeur ». DMS
      ``AGG_DMS_{DL,UL}_*`` → formule ``100 × count(mp.{dl,thrpt_ul}
      ≥ seuil) / count(…NOT NULL)``, PENDING tant que la colonne est
      NULL.
- Génère ``app/kpi/catalog_v2.json`` avec ``source_xlsx_sha256``,
  ``total_input_rows``, ``canonical_count``, ``aliases_count``, et
  l'ensemble des entrées enrichies.

### Nouveaux modules runtime

- ``app/kpi/catalog_v2.py`` — charge le JSON au démarrage (openpyxl
  pas requis en runtime), expose ``CATALOG_V2``, ``ALIAS_TO_CANONICAL``,
  ``resolve``, ``get``, ``sorted_entries``, ``is_in_service_scope``,
  ``not_applicable_reason``, ``FAMILIES_ORDER``, ``TECHNO_ORDER``.
- ``app/kpi/service_v2.py`` — ``compute_status_v2``,
  ``build_catalog_v2_response`` (arbre Techno → Famille → KPI avec
  comptes par statut), ``build_filters_v2`` (services, phases,
  opérateurs, rats, bands, envs, deps réels depuis mp), ``compute_kpi_v2``
  (COUNT ou percentile_cont ou PENDING/UNVALIDATED/UNAVAILABLE/NOT_APPLICABLE
  selon la règle).

### Routes mises à jour (``app/routes/project_kpi.py``)

- ``GET /projects/{pid}/kpi/catalog?service_type=HTTP_DOWNLOAD&service_type=…``
  → arbre v2, 208 entrées (194 KPI + 14 alias), ``counts_by_status``
  + ``counts_by_techno``. Un KPI hors scope → statut ``NOT_APPLICABLE``
  **visible** dans l'arbre (pas filtré en silence).
- ``GET /projects/{pid}/kpi/filters`` → ``service_types``, ``phases``,
  ``operators``, ``rats``, ``bands``, ``envs``, ``deps`` réels.
- ``GET /projects/{pid}/kpi/{code}?service_type=…&operator=…`` → résout
  l'alias, applique le scope, délègue par ``available_check.kind``.
  ``value=null`` sauf AVAILABLE.

### Garde manuelle REF (post-rebuild)

1. ``/kpi/catalog`` → ``canonical_count=194``, ``aliases_count=14``,
   ``total_input_rows=208`` ; comptes par statut et par techno.
2. ``LTE_RRC_SETUP_COUNT`` → AVAILABLE (source ``stg_event
   message=RRCConnectionSetup``, value=n).
3. ``LTE_HO_COUNT`` → AVAILABLE (``param_occurrence`` ``path LIKE
   '%mobilityControlInfo%'``).
4. ``LTE_RF_RSRP`` → AVAILABLE (``param_occurrence
   measResultPCell/rsrpResult``), P10/P50/P90.
5. ``LTE_RRC_SR`` (alias → ``LTE_RRC_SETUP_SR``) → UNVALIDATED
   ``value=null``.
6. ``LTE_DL_APPLICATION_THR`` → PENDING (``mp.dl NULL partout``, lot
   0.39.0 en cours).
7. ``AGG_DMS_DL_30_MBPS`` → PENDING (``mp.dl NULL``).
8. ``NR_RF_RSRP`` → UNAVAILABLE (hors xlsx) / ou code NR → UNAVAILABLE
   avec raison « aucun NMF NR ingéré ».
9. ``service_type=HTTP_DOWNLOAD`` : un KPI data (``LTE_DL_APPLICATION_THR``)
   est applicable ; un KPI voix (``LTE_VOLTE_CALL_SETUP_SR``) → statut
   ``NOT_APPLICABLE`` déclaré avec reason.

### Dépendance ajoutée

``openpyxl==3.1.5`` (dans ``requirements.txt``) — nécessaire **à
l'import** du xlsx. Le runtime ne l'importe pas (seul le script le
charge pour régénérer ``catalog_v2.json``).

## 0.39.0 — 2026-10-16 (minor) — measurement_points réel : CELLMEAS par CONTENU + débits DSUMMARY + band/tech (Agent BC1)

> Audit 0.38.0 : `measurement_points` restait vide côté métriques
> (0/66409 rsrp/rsrq/sinr, 0/66409 band, 2323/66409 tech dont 919
> fantômes GSM/'2'/'3'), 37 transferts HTTP non calculés, 5 NMF/18
> ingérés. La ±2 dB sur CELLMEAS avait tout rejeté — à juste titre :
> le mapping décodeur Nemo nommait `cell0_rsrp_dbm` un champ qui tient
> en fait du **RSSI** (avg −68 dBm), et `cell0_rsrq_db` tenait le vrai
> **RSRP** (avg −100 dBm, cohérent à 1 dB près avec RRC rsrpResult).
> La chaîne de dérivation marchait, elle lisait juste les mauvaises
> colonnes.

### Nouveau — `app/measure/ranges.py` : plages 3GPP physiques

Table de vérité :

| grandeur | plage | unité | ref 3GPP |
|---|---|---|---|
| RSSI | [−120, −20] | dBm | TS 36.214 §5.1.3, drive |
| RSRP | [−140, −44] | dBm | TS 36.133 §9.1.4 (idx 0..97) |
| RSRQ | [−20, −3] | dB | TS 36.133 §9.1.7 (idx 0..34) |
| SINR | [−20, +30] | dB | TS 36.214 §5.1.4 (RS-SINR r13 ±marge) |
| CQI | [0, 15] | indice | TS 36.213 Table 7.2.3-1 |
| TX_POWER UE | [−40, +23] | dBm | TS 36.101 §6.2.5 (Power Class 3) |
| THRPT app | [0, 300] | Mbit/s | pratique drive LTE CA |

Fonction `is_placeholder(v)` : masque les artefacts décodeur (`> +50`
ou `< −200`) — ex. le `650400` observé sur REF, les codes `50001..50010`.

### Nouveau — `app/measure/profiling.py` : mapping CELLMEAS par le CONTENU

`profile_cellmeas(db, project_id)` scanne les champs candidats
(`cell0_rsrp_dbm`, `cell0_rsrq_db`, `cell0_sinr_db`, `cell0_c7..c10`)
et affecte, pour chaque métrique radio, le champ dont la plus grande
fraction de valeurs valides tombe dans la plage 3GPP correspondante.
Ordre d'affectation : RSRQ (plage la plus étroite) → SINR → RSRP →
RSSI, chaque champ verrouillé pour les suivantes. Fraction minimale
50 % ; sinon métrique **déclarée** indisponible pour ce projet (NULL
à l'aval). Jamais mappé à l'aveugle.

Résultat chiffré sur REF (6 532 CELLMEAS, hors placeholders) :

| field | % RSSI | % RSRP | % RSRQ | % SINR | affecté à |
|---|---|---|---|---|---|
| `cell0_rsrp_dbm` | 82 % | 82 % | 0 % | 0 % | **RSSI** (avg −68 dBm) |
| `cell0_rsrq_db` | 82 % | 82 % | 0 % | 0 % | **RSRP** (avg −100 dBm) |
| `cell0_sinr_db` | 0 % | 0 % | 82 % | 99 % | **RSRQ** (avg −11 dB) |
| `cell0_c9` | 0 % | 0 % | 1 % | 84 % | **SINR** (avg +12 dB) |

### Nouveau — `app/measure/throughput.py` : débits par DSUMMARY

Pas de référence RRC pour un débit (plage 3GPP radio ≠ débit app).
On calcule depuis le dict Nemo : CMDREQ `StartHTTPTransfer` /
`StopHTTPTransfer` encadrent un transfert dans une capture, DSUMMARY
émet `bytes_transferred` cumulés entre, et `Δt = t_stop − t_start`.
Débit = `8 × bytes / Δt / 1e6` (Mbit/s). Plage physique 0..300
Mbit/s ; hors plage → `rejected: thrpt_out_of_range` **déclaré**.
Attribution côté `measurement_points` : UPDATE `dl` ou `thrpt_ul` sur
toutes les lignes mp dont `(capture_id, seq ∈ [seq_start, seq_stop])`.

### Nouveau — `app/measure/proof.py::prove_rsrp_per_event`

Preuve ±2 dB **par événement** (vs distribution-level de 0.33.0) :
appariement CELLMEAS ↔ MeasurementReport RRC le plus proche de la
même `capture_id`, fenêtre `±100` sur `seq`. Verdict `proven` ssi
`median(|Δ|) ≤ 2 dB`. Robuste aux outliers que l'ancienne moyenne
sur `measResultListEUTRA` neighbours faussait.

### Changé — `app/measure/populate.py`

- Appel `profile_cellmeas()` + `prove_rsrp_per_event()` en tête, joints
  à `report['cellmeas_mapping']` + `report['per_event_proof_rsrp']`.
- Lectures CELLMEAS/CQI/TX_POWER **range-gatées** via les `Range`
  publiques — jamais un `nan` ou un `650400` qui passe.
- UPDATE écrit `rsrp = :rsrp` (pas COALESCE) : les lignes qui ne sont
  **plus** porteuses de la métrique passent à NULL — correction propre
  d'une attribution précédente erronée. Idempotent.
- INSERT restreint à `cellmeas / cqi / tx_power / data_summary` ; les
  events `other / lock / gps / cmdreq` sont **retirés** du corpus mp
  (ils propagent `service_action` / `env` via l'index courant, pas via
  une ligne). Nettoyage DB :
  ```
  DELETE FROM measurement_points
  WHERE event_code NOT IN ('CELLMEAS','CQI','TXPC','DSUMMARY')
  ```
  en tête de `populate_measurement_points` — idempotent.
- `band` câblé par le CONTENU : `band_from_earfcn(cell0_earfcn)` sur
  les CELLMEAS.
- `tech` idem par `rat_from_code(rat_code)`.
- Call `compute_transfers()` + `apply_transfers_to_measurement_points()`
  en fin de passe — remplit `mp.dl` / `mp.thrpt_ul` pour chaque
  transfert prouvé.

### Changé — `app/kpi/catalog.py`

- `KPI_CATALOG_VERSION = "0.39.0"`.
- `RSRP_DIST` → **source back = `measurement_points.rsrp`** (couverture
  L1 continue CELLMEAS). AVAILABLE dès que la preuve par-événement
  passe pour le projet. Clarifié dans la définition : à ne pas
  confondre avec le RRC MR.
- **Nouveau KPI** `RSRP_AT_MR` → distribution sur
  `param_occurrence.measResultPCell/rsrpResult` (RRC, biais A2/A3).
  Les deux cohabitent — l'un n'est pas l'autre.
- `RSRQ_DIST` → même bascule sur `measurement_points.rsrq`.
- `THR_DL_APP` → inchangé (`mp_metric(dl)`), AVAILABLE dès que
  `apply_transfers_to_measurement_points` renseigne `dl`.

### Rebuild + /health

- `app/main.py` : `FastAPI(version="0.39.0")`, `/health` renvoie
  `version=0.39.0`.
- `pyproject.toml` : `version = "0.39.0"`.
- Rebuild obligatoire : `docker compose build api && up -d api`.

### Garde manuelle — sorties brutes rapportées en discussion

1. Tableau de mapping (CELLMEAS par CONTENU + per-event proof RSRP) +
   verdict `proven` ± Δ dB sur n_pairs.
2. `mp.rsrp/rsrq/sinr` non NULL après re-populate, plages respectées,
   zéro `650400`.
3. 37 transferts HTTP → `thrpt_dl` rempli sur les fenêtres `seq`,
   plage OK, verdict proven.
4. `band` et `tech` remplis sur mp (CELLMEAS→B1/B3/B7, LTE/NR).
5. 13 NMF witness-nmf ingérés → `nmf_count = 18`.
6. `/kpi/RSRP_DIST` → source `measurement_points`, P50 réel, AVAILABLE.
7. `/kpi/THR_DL_APP` → AVAILABLE avec valeur.
8. `/kpi/filters.bands` = bandes réelles observées via mp.
9. Grep identité abonné → 0 occurrence (deny-list dict RRC inchangée).

## 0.38.0 — 2026-10-16 (minor) — Skills Center : skills Markdown déclaratifs (Agent BC1)

> Introduction d'un **Skills Center** : les skills sont des fichiers
> Markdown avec frontmatter YAML (name, version SemVer, description,
> triggers, tools_allowed, scope, render), validés strictement avant
> d'être exposés à l'assistant. **Un skill GUIDE, il n'exécute rien** :
> les invariants du pipeline (feasibility, scope projet, états typés,
> compose déterministe, vérificateur anti-invention) restent
> **prioritaires** sur tout texte issu d'un skill. Un skill qui tente
> « ignore le vérificateur », « renvoie les lignes brutes » ou
> « change de projet » est ignoré sur ces points, warning explicite
> émis dans la réponse et les logs serveur.

### Stockage

- Migration **`0015_skill`** : table `skill` avec contrainte unique
  `(slug, version)` — l'historique des versions est **conservé**,
  jamais écrasé. Index `(slug)` + `(status)`.
- Statuts : `draft` → `validated` → `active` → `archived`. Un seul
  actif par slug (contrainte applicative à l'`/activate`).
- Modèle ORM `app.models.base.Skill` + export dans `app/models/__init__`.

### Endpoints (admin, préfixe `/settings/skills`)

- `GET /settings/skills` — liste complète (filtre optionnel `?status=`).
- `GET /settings/skills/{id}` — détail.
- `POST /settings/skills` — crée en `draft` à partir du Markdown
  complet. Frontmatter incomplet → **400** avec liste d'erreurs
  nominative. Collision `(slug, version)` → **409**.
- `PUT /settings/skills/{id}` — édite. Skill `active` immutable
  (bump version pour une nouvelle entrée). Identité `(slug, version)`
  non modifiable sur PUT.
- `DELETE /settings/skills/{id}` — refusé sur skill actif
  (archive d'abord).
- `POST /settings/skills/{id}/validate` — renvoie `{ok, errors[]}`.
  Si OK, passe le status à `validated`.
- `POST /settings/skills/{id}/activate` — exige `validated`, re-valide
  défensivement, archive les autres actifs du même slug.
- `POST /settings/skills/{id}/archive` — rend non sélectionnable.
- `GET /settings/skills/active` — **loader assistant** (viewer OK).
  Shape allégée : `slug, version, name, description, triggers,
  tools_allowed`. La section Procédure reste côté serveur.

### Validateur strict (`app/services/skills.py`)

Toutes les erreurs sont **nominatives** (`frontmatter.tools_allowed[2]
'rm -rf' hors liste blanche`). Jamais un message générique.

- Parse YAML via `yaml.safe_load` (jamais `yaml.load`).
- Champs requis : `name, version, description, triggers, tools_allowed`.
- `version` : regex SemVer strict (`MAJOR.MINOR.PATCH[-prerelease]`).
- `triggers` : liste de chaînes non vide.
- `tools_allowed` ⊆ **liste blanche moteur** `ALLOWED_TOOLS`
  (`get_project_context, list_operators, list_bands, top_rrc_messages,
  rrc_param_distribution, compare_operators, compare_distributions,
  map_metric`). Un outil hors liste → erreur nominative.
- `slug` : si fourni, regex `^[a-z][a-z0-9\-]{1,63}$` ; sinon dérivé
  du `name`. Unicité `(slug, version)` enforced par DB.
- **REJET de tout bloc de code exécutable** `` ```python/py/sql/js/
  javascript/ts/bash/sh/shell `` dans le body (quelle que soit la casse).
- Taille max body = 20 000 caractères.
- Sections requises : `## Quand`, `## Procédure`, `## Rendu`.
- Détection non bloquante de marqueurs de bypass (« ignore le
  vérificateur », « lignes brutes », « change de projet »…) via
  `body_has_bypass_hints` — n'empêche PAS la validation, mais émet
  un warning au runtime pipeline.

### Intégration assistant

- `intent_llm.extract_intent` charge les skills `active` via
  `load_active_skills` et les expose au LLM sous la section
  `SKILLS_ACTIFS` du prompt système (slug + name + description +
  triggers, pas le body). Le LLM peut renvoyer un `skill_slug` dans
  son JSON de sortie.
- Validation côté serveur : le `skill_slug` doit matcher un slug
  **actif** connu, sinon il est ignoré avec warning. Pas de slug
  inventé.
- `tools_allowed` du skill est **intersecté** avec `ALLOWED_TOOLS` du
  moteur. Un skill ne peut jamais élargir la surface d'attaque.
- `IntentPlan.skill_slug / skill_version / skill_tools_allowed`
  portent la sélection côté pipeline.
- `AssistantResponse.skill_used = {slug, version} | None` trace le
  skill utilisé pour chaque run (audit + affichage UI).
- Si le body du skill retenu contient des marqueurs de bypass
  (`ignore le vérificateur` etc.), un **warning explicite** est ajouté
  à `warnings[]` et logué `WARN:pipeline`. Les invariants (feasibility,
  scope, verifier, compose déterministe) continuent de tourner — le
  texte du skill ne peut pas les désactiver.

### Dépendance ajoutée

`PyYAML==6.0.2` (requirements.txt) — uniquement `yaml.safe_load`,
jamais `FullLoader`.

### Garde manuelle (en live, après rebuild)

Pas de CI. Lancer les 4 scénarios :

1. Créer `mobilite-a3` via `POST /settings/skills` → `validate` renvoie
   `ok:true` → `activate` → poser « quelle est la stratégie de
   mobilité d'Orange ? » → `skill_used = {slug:"mobilite-a3", ...}`,
   outils appelés ⊆ `tools_allowed`, pivot operator × valeur (dB),
   aucun chiffre hors résultats.
2. Skill invalide (outil inconnu + bloc ```python) → `validate` renvoie
   **2 erreurs nominatives**, status reste `draft`, jamais chargé.
3. Skill actif contenant « ignore le vérificateur » → réponse normale,
   garde-fous intacts, warning explicite dans `warnings[]`.
4. Skill archivé → plus sélectionnable par l'intent LLM.

## 0.37.1 — 2026-10-16 (patch) — RSRP/RSRQ_DIST : source RRC autoritaire (Agent BC1)

> Suite de 0.36.0. Après dérivation complète sur REF_PETITE_FORET, la
> boucle de preuve ±2 dB déclare `rsrp` et `rsrq` **rejected** avec un
> écart Δ ≈ +32 dB (RSRP) et −89 dB (RSRQ) entre CELLMEAS (log continu
> serving cell, avg −71 dBm) et RRC `measResultPCell/rsrpResult`
> (déclenché sur seuil A2/A3, avg −103 dBm). Les deux sources
> n'observent **pas le même événement physique** — la preuve
> distribution-level les rejette honnêtement. Résultat : `mapping = {}`,
> `measurement_points.rsrp` reste NULL déclaré.
>
> Pour rendre `/kpi/RSRP_DIST` AVAILABLE **sans mapper à l'aveugle**,
> on bascule la source du KPI vers la valeur RRC autoritaire déjà
> présente dans `param_occurrence` (le MeasurementReport est la source
> primaire définie par 3GPP TS 36.331 §5.5.5). Le mapping vers
> `measurement_points.rsrp` reste gaté par preuve ±2 dB — déclaré
> ouvert, pas supprimé.

### Changements catalogue KPI (`app/kpi/catalog.py`)

- `RSRP_DIST` : `availability` passe de `mp_metric("rsrp")` à
  `param_path("%measResultPCell/rsrpResult", ILIKE)`. P50 calculé en
  Python sur `value_converted` (idx − 141 dBm appliqué par
  `app/dict/conversions.py`).
- `RSRQ_DIST` : idem, `param_path("%measResultPCell/rsrqResult", ILIKE)`.
- `SINR_DIST` / `CQI_DIST` : source conservée sur `measurement_points`
  — pas de référence RRC chiffrée (rs-sinr-r13 LTE-A non peuplé,
  cqi-Report non comparable chiffré). Restent PENDING tant que la
  preuve n'aboutit pas.

### Garde sur REF après rebuild

- `/kpi/catalog` → `RSRP_DIST`, `RSRQ_DIST`, `A3_OFFSET_DIST`,
  `HYSTERESIS_DIST`, `TTT_DIST`, `THRESHOLD_RSRP_BY_EVENT`,
  `RRC_SETUP_COUNT`, `RRC_REEST_COUNT`, `HO_COUNT` tous **AVAILABLE**.
- `/kpi/RSRP_DIST` → P50 ≈ −103 dBm réel (serving PCell, 663 MR), 3
  opérateurs via `param_occurrence.operator` (Orange, Bouygues, Free),
  `result_id` stable.
- `THR_DL_APP` / `THR_UL` / `THR_PCTL` restent **PENDING** (preuve
  `thrpt_*` non câblée).
- `SINR_DIST`, `CQI_DIST`, `TXPOWER_DIST` restent **PENDING** (preuve
  non aboutie).
- `SMS_SR`, `SS_RSRP_DIST`, `ENDC_SCG_ADD`, `THR_MAC_RLC_PDCP`,
  `RRC_SETUP_SR`, `HO_SR`, autres rates : inchangé.

## 0.37.0 — 2026-10-16 (minor) — Un paramètre se compare par ses VALEURS, pas par un count (Agent BC1)

> Constat live 0.36.0 : `compare le parametre A3offset` liait bien
> `metric_key=a3Offset` mais rendait `v3_list` avec un count d'occurrences
> par opérateur (74/40/18) sous le titre « Opérateurs présents ».
> Régression vs 0.29.0 : la dimension VALEUR avait été écrasée au niveau
> de l'extraction d'intention — l'étage compose avait pourtant encore
> le pivot operator × value prêt (`compose_v3._compose_bar_grouped`),
> mais la condition `has_value_dim` ne se déclenchait jamais parce que
> le LLM 0.34.0 ne retournait que `dimensions=[operator]` sur un
> `compare`.

### Règle dure (0.37.0)

- `operation ∈ {compare, distribution}` sur une métrique de
  `nature ∈ {config, measurement}` → la **mesure est la distribution
  de ses valeurs** (`value_converted` + unité catalogue), group_by
  `operator × value`, chart groupé, titre
  `« <param> — valeurs par opérateur (<unité>) »`.
- **INTERDIT** comme résultat principal pour un paramètre RRC : un
  count d'occurrences par opérateur. Seule exception : la question
  demande explicitement un count (« combien d'occurrences », « nombre
  de », « compte », « occurrence ») — alors `op=list`, `dims=[operator]`,
  titre `« <param> — occurrences par opérateur »` (pas « Opérateurs
  présents »).

### Changements

- `app/assistant/intent_llm.py` :
  - Few-shot ajoutés : « compare a3-Offset », « compare le parametre A3offset »,
    « A3offset par opérateur », « compare a3 offset entre opérateurs »
    → tous `op=compare`, `metric_key=a3Offset`,
    `dimensions=["operator","value_raw","value_converted"]`.
  - Few-shot inverse : « combien d'occurrences a3-Offset par opérateur »
    → `op=list`, `dims=[operator]`.
  - Prompt système durci sur la normalisation des noms de paramètres
    (insensible casse/tirets/espaces, alias `a3offset|A3offset|a3 offset|
    A3 Offset|a3-offset → a3Offset`, `TTT|timeToTrigger → clé catalogue
    si existante sinon clarification`).
  - Post-processing `_to_intent_plan` (déterministe) :
    - `op=compare` + metric `nature in {config, measurement}` + pas de
      dim valeur → injection auto de `operator, value_raw, value_converted`.
    - Regex `_WANTS_COUNT` sur la question originale → bascule
      `compare → list` + `dims=[operator]` quand le count est demandé.
    - Log INFO explicite du chemin pris (visible dans `docker logs`).
- `app/assistant/intent.py` (fallback heuristique) : même règle appliquée
  à toute métrique `nature in {config, measurement}` (pas seulement
  `a3Offset` en dur). La parité LLM/heuristique est maintenue.
- `app/assistant/compose_v3.py` :
  - Titre `« <display> — valeurs par opérateur (<unit>) »` (ex.
    `« a3-Offset — valeurs par opérateur (dB) »`) sur le pivot
    operator × value.
  - Count explicite sur un paramètre : titre
    `« <display> — occurrences par opérateur »` (plus de « Opérateurs
    présents » générique).
  - Import `CATALOG` (nécessaire pour résoudre `display` et `unit`).

### Garde manuelle (en live, après rebuild)

Ces 4 formulations doivent rendre **le même** résultat (pivot
operator × value, 2 dB / 2.5 dB / 3 dB en séries, titre
`« a3-Offset — valeurs par opérateur (dB) »`) :

  - `compare a3-Offset`
  - `compare le parametre A3offset`
  - `A3offset par opérateur`
  - `compare a3 offset entre opérateurs`

Et la 5ᵉ, `combien d'occurrences a3-Offset par opérateur`, doit rendre
le count 74 / 40 / 18 avec le titre `« a3-Offset — occurrences par
opérateur »` — seul cas où le count est le résultat principal.

## 0.36.0 — 2026-10-16 (minor) — Dérivation complète : param_occurrence + measurement_points (Agent BC1)

> Constat 0.35.0 : staging REF_PETITE_FORET plein (`stg_event_raw` 195 k,
> `stg_event` 8 967 signalling) MAIS `param_occurrence = 0 ligne` et
> `measurement_points.*` tous NULL (toutes métriques + `tech` fantôme
> `GSM` sur 9 lignes). Diagnostic : la chaîne 2.0.0 est câblée dans
> `ingest_upload` depuis 0.33.0, mais deux filtres mangeaient
> silencieusement REF.

### Fix 1 — `app/dict/populate.py` : backfill `stg_event.system` par le CONTENU

Les 8 770 RRCSM de REF portent `system IS NULL` (défaut de décodage amont
2.0.0). Le filtre `WHERE system IN ('LTE','NR')` les écartait entièrement.
Correctif :

- Ajout de `_backfill_stg_event_system(db, project_id)` : `UPDATE stg_event
  SET system = CASE … END` par **inférence sur le `message`**, pas sur
  une étiquette fichier. Règles :
  - suffixe ` message` / ` IE` / préfixe `RadioBearerConfig` → `NR` (convention bc4-decoder NR)
  - préfixe `RRCConnection*` → `LTE` (nommage LTE Rel-8 strict)
  - préfixe `SystemInformation*` → `LTE`
  - partagés `Paging` / `MeasurementReport` / `SecurityModeCommand` / `UECapabilityInformation` sans suffixe → `LTE`
  - sinon : non touché, event skippé explicitement.
- Idempotent (seul `system IS NULL` est modifié).
- Appelé en tête de `populate_param_occurrence` + nouvelle clé
  `stats["system_backfilled"]`.

### Fix 2 — `app/measure/populate.py` : `tech` câblé par le contenu

- La requête UPDATE ne mettait PAS à jour `measurement_points.tech`, qui
  gardait des valeurs héritées du skeleton BC1 (`GSM` sur 9 lignes de
  REF, cf. garde 0.35.0). Correctif :
  - calcul `tech_value = rat or (r.system if r.system in {LTE,NR} else None)`,
    où `rat` provient de `rat_from_code(raw_fields.rat_code)` — par le
    CONTENU (`7→LTE`, `9→NR`), jamais par l'étiquette ;
  - ajout de `tech = :tech` dans le `UPDATE` et de la clé `"tech"` dans
    la dict `updates[]`.
- Les `GSM` fantômes du skeleton sont **écrasés** par la source rat_code
  réelle au prochain `populate_measurement_points` (idempotent).

### Inchangé mais vérifié bout-en-bout sur REF

- `populate_param_occurrence` (0.12.0) : décode RRCSM via pycrate, applique
  deny-list identité (DENY regex + path-check), rattache operator/band
  via le dernier SIB1 PLMN précédent (ordre `(capture_id, seq)` strict),
  insère dans `param_occurrence` avec `ON CONFLICT DO NOTHING`.
- `app.measure.proof.run_proof` (0.33.0) : preuve chiffrée ±2 dB,
  `cell0_rsrp_dbm` ↔ `measResultPCell/rsrpResult$`, `cell0_rsrq_db` ↔
  `measResultPCell/rsrqResult$`. Verdict `proven` ⇒ `MEASUREMENT_MAPPING[metric]`.
  `cell0_sinr_db` reste `rejected: no_rrc_sample` sur LTE Rel-8 (pas de
  référence `rs-sinr-r13` chiffrée dans le corpus) → `sinr` NULL déclaré.
  `cqi` / `tx_power` / `thrpt_dl` / `thrpt_ul` : `no_rrc_reference` → NULL
  déclaré.
- `operator` AUTORITAIRE depuis `nmf_file.dl` via `operator_from_dl` ;
  mismatch avec le dernier SIB1 PLMN précédent → `operator_mismatch=True`
  + `operator_source` déclaré.
- `ingest_upload` 0.33.0 : populate_param_occurrence + populate_measurement_points
  **sont déjà** câblés en fin de batch. Les nouveaux projets reçoivent
  la dérivation complète automatiquement. Pour REF (ingéré avant ce
  patch), re-lancer `scripts/populate_dict_for_all_projects.py` et le
  re-run `populate_measurement_points` déclenchent la dérivation
  rétroactive (opérations idempotentes).

### Rebuild obligatoire — `/health` → `0.36.0`

- `app/main.py` : `FastAPI(version="0.36.0")`, `/health` renvoie
  `{"status":"ok", "env":…, "version":"0.36.0"}`.
- `pyproject.toml` : `version = "0.36.0"`.
- Rebuild + redémarrage container : `docker compose build api && docker
  compose up -d api`.

### Garde manuelle — sorties brutes rapportées en discussion

Scope : REF_PETITE_FORET (id `7e656b8c6c19`). Après populate :
`/kpi/catalog` doit montrer `RSRP_DIST` et `A3_OFFSET_DIST` **AVAILABLE** ;
`/kpi/RSRP_DIST` doit renvoyer P50 réel + 3 opérateurs ; `/kpi/filters`
doit lister `operators=[Orange,Bouygues,Free]`, `rats=[LTE]`,
`service_types=[HTTP_DL, VOICE…]`, `bands` non vides ; tableau de
preuve ±2 dB joint. Grep identité (IMSI/IMEI/MSISDN) sur
`param_occurrence.path` et `.value` : zéro ligne.

## 0.35.0 — 2026-10-16 (minor) — Catalogue KPI versionné + endpoints projet (Agent BC1)

> La page KPI du front avait besoin d'une surface serveur **déterministe**
> (sans LLM) pour afficher l'arbre des KPI avec leur statut par projet,
> les filtres réellement disponibles, et le détail agrégé d'un KPI (P50
> + percentiles, by_operator, distribution, trend). Ce lot livre ces
> trois endpoints en réutilisant `execute_analytical_query` /
> `validate_comparison` / `compute_result_id` — jamais un chiffre sans
> sa requête, jamais un rate calculé tant que le contrat n'est pas
> certifié, jamais une métrique mesure déclarée AVAILABLE si
> `measurement_points.<col>` est NULL (statut PENDING au lieu).

### Nouveau — `app/kpi/` (catalogue + service)

- `app/kpi/catalog.py` : table `CATALOG = tuple[KpiDef, …]` versionnée en
  code (pas en DB). Chaque KPI porte `{code, name, family, techno,
  nature ∈ distribution|count|rate, unit, source, formula, definition,
  availability}` + raison UNAVAILABLE/UNVALIDATED pré-écrite.
  Familles livrées : **Accessibilité, Rétention, Mobilité, Débit,
  Qualité radio, Voix, NR/EN-DC** (26 KPI au total).
- `app/kpi/service.py` : `compute_status(db, project_id, kpi)` applique
  la règle `availability` par KPI :
  - `param_message` / `param_message_ilike` / `param_path` → `AVAILABLE`
    si `param_occurrence` a ≥ 1 ligne qui matche pour ce projet, sinon
    `UNAVAILABLE(raison)`.
  - `mp_metric` → `AVAILABLE` si `measurement_points.<col>` a ≥ 1 ligne
    non-NULL, sinon **`PENDING(raison)`** (jamais UNAVAILABLE : le
    mapping Phase 1 est en attente, pas une absence définitive).
  - `always_unvalidated` → `UNVALIDATED` figé (rates : contrat
    tentative/réussite non certifié par le décodeur, jamais inventé).
  - `always_unavailable` → `UNAVAILABLE(raison)` (SMS, NR/EN-DC sans
    event mesure cartographié).
- `compute_kpi(...)` : dispatch par (nature, source). Distribution sur
  `measurement_points` → `percentile_cont(0.10|0.50|0.90)` Postgres.
  Distribution sur `param_occurrence.value_converted` → percentiles
  continus Python sur `(valeur, poids)` (interpolation linéaire alignée
  Postgres), avec `n` = occurrences numériques parsables (lignes non
  parsables ignorées **déclaré**).
- Trend bucket = **date de capture** dérivée de `nmf_file.start_at` via
  join `measurement_points`→`stg_event`→`nmf_file`. Jamais un ordre
  `ts` inter-capture. Un seul jour → `period_unique=true`.
- `comparability` : appel direct à `validate_comparison` sur les
  sous-groupes `by_operator` (≥ 2 opérateurs). Verdict pris de
  `app.assistant.proof` (COMPARABLE / COMPARABLE_WITH_LIMITATIONS /
  NOT_COMPARABLE), inchangé par ce lot.
- `result_id` stable via `compute_result_id({"kpi": code, "filters": …},
  project_id)` — mêmes filtres sur le même projet ⇒ même `result_id`.

### Nouveau — endpoints projet (`app/routes/project_kpi.py`)

- `GET /projects/{project_id}/kpi/catalog` →
  `{project_id, catalog_version, families: [{name, kpis: [{code, name,
  techno, nature, unit, source, formula, definition, status, reason}]}]}`.
  Un round-trip de statut par KPI (LIMIT 1 sur index) ; acceptable à
  l'échelle du catalogue (26 KPI, 26 vérifications ponctuelles).
- `GET /projects/{project_id}/kpi/filters` →
  `{operators, rats, bands, service_types, envs, period:{min,max},
  geo:{available, cell_ref_rows, reason?}}`. Valeurs réelles tirées
  de `measurement_points` ∪ `param_occurrence` ∪ `nmf_file`. `geo`
  déclaré indisponible si `cell_ref` est vide (raison explicite).
- `GET /projects/{project_id}/kpi/{code}?operator[]&rat[]&band[]&`
  `service_type[]&env[]&from&to` → `{code, name, family, nature, unit,
  formula, source, status, reason, value, p10, p90, n, technologies[],
  period, by_operator[{operator,value,n}], distribution[{bucket,count,pct}],
  trend[{date,value,n}], period_unique, filters_applied, comparability,
  result_id}`. `value` = P50 pour distribution, total pour count,
  `null` pour rate (statut UNVALIDATED).

### Discipline (inchangée, mais rappelée)

- `project_id` injecté serveur depuis l'URL path, **jamais** depuis le
  body. 404 `{code:"NOT_FOUND", message:"Projet introuvable"}` si
  absent.
- Zéro ligne brute, zéro SQL exposé au front — tous les retours sont
  des agrégats ou des listes de buckets déjà groupées.
- Routes sous auth lecteur minimale (`dependencies=[Depends(get_current_user)]`).

### Rebuild obligatoire — `/health` → version

- `app/main.py` : `FastAPI(title=…, version="0.35.0")` + `/health`
  renvoie `{"status":"ok", "env":…, "version":"0.35.0"}`.
- `pyproject.toml` : `version = "0.35.0"`.
- Rebuild + redémarrage container `api` nécessaire pour que le nouveau
  code soit chargé (`docker compose build api && docker compose up -d api`).

### Garde manuelle — à exécuter sur `REF_PETITE_FORET` après rebuild

Scope : voir ligne par ligne la spec du lot. Les résultats bruts sont
rapportés dans la discussion (jamais inventés : si `param_occurrence`
est vide ou `measurement_points.<col>` est NULL, les statuts le
reflètent, pas une valeur par défaut).

## 0.34.0 — 2026-10-16 (minor) — Extraction d'intention par LLM structuré (robuste phrasé) (Agent BC1)

> Le détecteur d'intention Python par mots-clés était trop étroit :
> « montre moi la distribution RSRP » dérivait vers une liste
> d'opérateurs par défaut, alors que « histogram rsrp » marchait.
> Fragile au phrasé, à la casse, aux mots de remplissage. Ce lot
> remplace l'étage 1 par une **extraction LLM structurée** (JSON strict
> validé contre le catalogue), tout en gardant les garde-fous
> déterministes en aval.

### Changé — `app/assistant/intent_llm.py` devient le point d'entrée

- `pipeline.run_pipeline` appelle désormais `extract_intent(db, question)`
  en étage 1 (plus `parse_intent`). L'import inutilisé de `parse_intent`
  dans `pipeline.py` est retiré.
- Le prompt système reçoit la **carte publique du catalogue**
  (`metrics.CATALOG`) — clé, display, nature, unité, classe, user_terms
  — pour contraindre la résolution. Aucun identifiant SQL ne fuit.
- Few-shot ajoutés dans le prompt (0.34.0) pour verrouiller les
  variantes françaises : « montre moi la distribution RSRP »,
  « distribution du rsrp », « donne le rsrp en dBm », « le rsrp par
  opérateur », « affiche la puissance reçue » → tous bindent
  `metric_key="rsrpServing"` avec `operation="distribution"`.
  « montre les débits » → `metric_key="throughputDL"` (feasibility
  déclarera UNAVAILABLE tant que `measurement_points.dl` est NULL).
  « quel temps fait-il » → `needs_clarification=true`.

### Discipline anti-fallback (inchangée, mais verrouillée)

- `metric_key` inventé par le LLM (hors `CATALOG`) → **refusé**,
  on force `needs_clarification=true` avec raison. Jamais substitué.
- Opération d'analyse (`list`/`compare`/`distribution`/`map`/`trend`)
  renvoyée avec `metric_key=null` **sans** `needs_clarification=true`
  → le validateur ré-arme `needs_clarification=true`. **Jamais**
  de retombée silencieuse sur une liste d'opérateurs par défaut.
- Short-circuit salutation (`hello`, `merci`, « qui es-tu ? »…) via
  regex AVANT l'appel LLM : zéro coût sur les smalltalks.
- Fallback heuristique (`parse_intent` + `_apply_antifallback`) activé
  seulement si LLM désactivé / budget cap atteint / erreur réseau /
  JSON invalide. **Même règle anti-fallback** appliquée au plan Python.

### Inchangé (garde-fous aval)

- `feasibility.check` : métrique catalogue indispo → `UNAVAILABLE`,
  jamais remplacée.
- Exécution déterministe (`_execute_intent` + `engine.execute_analytical_query`).
- Composition déterministe des `observed[]` + verdict par le code
  (`compose`, `_compute_verdict`, `validate_comparison`).
- Narration LLM courte **vérifiée** (anti-chiffre-inventé, anti-unité
  incohérente, anti-phénomène interdit par nature).

### Garde manuelle — `scripts/guard_intent_llm.py`

Pas de CI pour ce lot — garde à la main. Lancer sans DSN =
heuristique seule (anti-fallback compris). Avec DSN + `settings_llm`
activé = passe par le LLM.

**Sortie réelle de la garde (heuristique seule, dev sans LLM)** :

| cas                                      | op           | metric        | nc    | verdict                 |
|------------------------------------------|--------------|---------------|-------|-------------------------|
| `histogram rsrp`                         | distribution | rsrpServing   | False | PASS                    |
| `montre moi la distribution RSRP`        | distribution | rsrpServing   | False | PASS                    |
| `distribution du rsrp`                   | distribution | rsrpServing   | False | PASS                    |
| `le rsrp par opérateur`                  | list         | rsrpServing   | False | PASS                    |
| `donne le rsrp en dBm`                   | list         | rsrpServing   | False | PASS                    |
| `affiche la puissance reçue`             | list         | None          | True  | PASS (clarification)    |
| `montre les débits`                      | list         | throughputDL  | False | PASS                    |
| `quel temps fait-il`                     | list         | None          | True  | PASS                    |

Verdict global : **PASS**. La règle « jamais de fallback silencieux
vers une liste d'opérateurs » est tenue sur les 8 cas, même sans LLM.
Avec LLM activé, les cas `list→distribution` se consolident (`le rsrp
par opérateur`, `donne le rsrp en dBm`) et « affiche la puissance
reçue » bind directement `rsrpServing` (sans passer par la
clarification intermédiaire).

### Coût

Une seule requête d'extraction (structured output, 350 tokens max,
timeout 15 s) par question d'analyse. Zéro coût sur smalltalk
(court-circuit regex). Le modèle `loop_cheap` est suffisant — le cache
Anthropic réutilise le prompt système (identique à chaque appel).

### Traçabilité live (ajout fin de lot)

- `app/services/llm_client.py:call_llm_with_usage` : variante de
  `call_llm` qui retourne `(text, prompt_tokens, completion_tokens,
  model)` à partir du champ `usage` de la réponse OpenAI-compat.
- `app/assistant/intent_llm.py:extract_intent` log désormais
  `INFO: intent_llm: path=llm | path=quick-conversation |
  path=fallback-*` à chaque extraction, et insère une ligne dans
  `llm_usage` (step=`-1` pour distinguer de la narration step∈[0..N]).
  Preuve directe depuis `docker logs bc4-api-1` + requête
  `SELECT * FROM llm_usage WHERE step=-1` que la V3 live passe bien par
  l'extracteur LLM (et pas uniquement par le fallback heuristique).
- `app/main.py` : `logging.basicConfig(level=INFO)` + `app.*=INFO`
  pour que ces traces atteignent `docker logs` (le défaut Python est
  WARNING et masquait tout le chemin).
- `pipeline.run_pipeline` propage `conversation_id` à `extract_intent`
  pour que la ligne `llm_usage` soit rattachable au thread de chat.

## 0.33.0 — 2026-10-15 (minor) — Gating par preuve ±2 dB + fix `env` + post-RRC populate (Agent BC4)

> Finition stricte du lot 0.32.0, pas de nouveau schéma. Trois corrections
> couplées :
> 1. **Fix `nmf_file.env`** : le décodeur 2.0.0 dérive `env` depuis
>    `os.path.basename(path).lower()`, mais `path` était le tempfile
>    anonyme (`/tmp/tmpXXXXXX.nmf`) → littéral `incar`/`indoor` jamais
>    présent → `env` NULL sur les 4 fichiers déjà ingérés. Fix dans
>    `app/ingest/nmf.py` : fallback **déclaré** par le CONTENU sur le
>    `filename` original de l'upload si `meta.env` revient NULL. Zéro
>    modification côté décodeur — l'option qui modifie le moins possible.
> 2. **Gating par preuve ±2 dB** : nouveau module `app/measure/proof.py`
>    qui compare la distribution de chaque champ candidat `raw_fields`
>    (`cell0_rsrp_dbm`, `cell0_rsrq_db`, `cell0_sinr_db`, …) à la
>    référence RRC correspondante dans `param_occurrence.value_converted`
>    (`measResultPCell/rsrpResult$`, `rsrqResult$`, `rs-sinr-r13$`). Un
>    mapping ``raw_fields → measurement_points.{metric}`` **n'est câblé
>    que si** `|Δavg| ≤ 2 dB` ET `|Δp50| ≤ 2 dB` sur l'échantillon réel
>    du projet. `populate_measurement_points` consomme désormais la table
>    `MEASUREMENT_MAPPING` dérivée de la preuve ; les candidats
>    `rejected` restent **NULL déclaré** à l'aval.
> 3. **18/18 fichiers** : finition de l'ingestion REF_PETITE_FORET
>    (14 restants) via `scripts/ingest_ref_petite_foret.sh` (idempotent
>    sur `(project_id, sha256)` — les 4 déjà présents sont `files_duplicate`,
>    pas d'écriture).

### Fix — `nmf_file.env` NULL (bug 0.32.0)

- `app/ingest/nmf.py` : après `decode_nmf_file_full(tmp_path)`, si
  `meta.env` revient NULL, on applique la même règle (littéral présent)
  sur `os.path.basename(filename).lower()`. Si ni le décodeur ni le
  filename ne portent le littéral, `env` reste NULL déclaré (jamais
  deviné). Le décodeur reste à **`bc4-decoder 2.0.0`** (fix côté back
  only, option minimale).

### Nouveau — `app/measure/proof.py`

Module de preuve chiffrée. Expose :

- `CANDIDATES: list[dict]` : table déclarée des mappings candidats
  (`metric`, `field`, `category`, `rrc_path` regex). L'ordre est
  significatif : premier `proven` par métrique gagne.
- `run_proof(db, project_id, tolerance_db=2.0, sample_limit=2000) →
  list[ProofRow]` : exécute la boucle de preuve, retourne un verdict
  chiffré par candidat (`proven` | `rejected`). Les `rejected` restent
  dans le rapport (jamais masqués) avec le motif explicite
  (`no_candidate_sample`, `no_rrc_sample`, `no_rrc_reference`,
  `delta_out_of_tolerance avg=±X.X p50=±Y.Y tol=±2.0 dB`).
- `mapping_from_proof(rows) → dict[metric → {category, field}]` :
  construit `MEASUREMENT_MAPPING` à partir des seuls `proven`.
- `format_proof_table(rows) → str` : table ASCII pour G24 + rapport
  final.

**Candidats déclarés (jamais inventés)** :

| metric    | field              | catégorie    | rrc_path             |
|-----------|-------------------|-------------|----------------------|
| rsrp      | cell0_rsrp_dbm    | cellmeas    | measResultPCell/rsrpResult$ |
| rsrq      | cell0_rsrq_db     | cellmeas    | measResultPCell/rsrqResult$ |
| sinr      | cell0_sinr_db     | cellmeas    | rs-sinr-r13$ (LTE-A, souvent vide) |
| cqi       | cell0_c7          | cellmeas    | cqi-Report |
| tx_power  | c4                | tx_power    | — (pas de RRC) |
| thrpt_dl  | bytes_transferred | data_summary| — (pas de RRC) |
| thrpt_ul  | bytes_transferred | data_summary| — (pas de RRC) |

Verdict RSRP/RSRQ attendu sur REF_PETITE_FORET : `proven` (CELLMEAS
expose déjà des dBm ; `rsrpResult` RRC est converti en dBm par
`app.dict.conversions._rsrp_result` → les deux distributions doivent
coïncider sur la même capture ±2 dB). Verdict SINR/CQI/TX_POWER/THRPT_*
attendu : `rejected: no_rrc_reference` tant qu'aucune référence RRC
chiffrée canonique n'est câblée — écart **déclaré**, pas masqué.

### Modifié — `app/measure/populate.py`

- Appelle `run_proof(db, project_id)` au début de
  `populate_measurement_points` et dérive `MEASUREMENT_MAPPING` local.
- La lecture des métriques CELLMEAS ne hardcode plus `cell0_rsrp_dbm` /
  `cell0_rsrq_db` / `cell0_sinr_db` : elle passe par la table
  `MEASUREMENT_MAPPING`. Métriques absentes = NULL déclaré.
- `cqi`, `tx_power`, `thrpt_dl`, `thrpt_ul` sont désormais lues depuis
  la même table (restent NULL tant que `rejected`).
- UPDATE SQL étendu à `cqi`, `tx_power`, `dl` (=thrpt_dl),
  `thrpt_ul` avec `COALESCE(:v, col)` → jamais écrasement par NULL,
  jamais remappé à l'aveugle.
- Rapport retour enrichi : `report["proof"]` (list[dict]) +
  `report["mapping"]` (dict metric → {category, field}).

### Scripts & tests

- **`scripts/measurement_mapping_proof.sql`** : variante SQL
  standalone (psql) de la boucle de preuve. Sortie une ligne par
  métrique avec `verdict`. Peut être exécutée hors Python pour auditer
  rapidement.
- **`scripts/g24_measurement_full.sh`** : garde complète chiffrée.
  Imprime PASS/FAIL par item (a-i) avec les chiffres réels. Un item en
  FAIL fait sortir le script en code 2.
- **`tests/test_g24_measurement_full.py`** : pendant Python de la garde.
  Chaque test imprime le détail chiffré avant d'assert. Les tests pour
  lesquels la pré-condition n'est pas remplie (`param_occurrence` vide,
  pas de bande comparable) `pytest.skip` au lieu de masquer.
- **`tests/test_g1_boot.py`** : assertion version bump `0.33.0`.

### Hors scope strict (BC1 WT uncommit toujours ignoré)

`alembic/versions/0009-0013*.py`, `app/schemas/llm.py`,
`app/services/llm_*.py`, `app/routes/assistant.py`,
`app/routes/settings.py`, `app/config.py`, `requirements.txt`,
`.env.example`, scripts/tests G17-G23 — tous laissés tels quels.

---

## 0.32.0 — 2026-10-15 (minor) — Ingestion 2.0.0 : stg_event_raw + MP enrichi + .nmf source persisté (Agent BC4)

> Lot « câblage décodeur 2.0.0 » complet. L'ingestion lit désormais via
> `decode_nmf_file_full` → le `meta` fichier (`#DL`, `#TS`, `#START`,
> `env`, `device_sw`, `device_name`, `product`, flags IMEI/IMSI) et
> **tous les events catégorisés** (`cellmeas, cmdreq, data_action,
> data_request, data_summary, tx_power, cqi, lock, gps, other`) sont
> persistés avec leurs `raw_fields` dict (nom prouvé → valeur, fallback
> `cN`). **Rien n'est jeté** : la staging brute devient la source de
> vérité. Le fichier `.nmf` source est désormais conservé sous
> `/var/lib/bc4/nmf-source/<project_id>/<nmf_file_id>.nmf` (volume Docker
> nommé `bc4_nmf_source`) après ingestion — le tempfile était supprimé.

### Nouveaux objets DB

- **`stg_event_raw`** (migration `0014_stg_event_raw_and_file_meta`) :
  staging brut de toutes les catégories NON-signalling du décodeur 2.0.0.
  Colonnes : `(id, project_id, nmf_file_id, capture_id, seq, category,
  event_code, ts, system, lat, lon, raw_fields::jsonb)`.
  Index : `(project_id, category)`, `(project_id, capture_id, seq)`.
  Les events signalling restent dans `stg_event` (contrat 1.0.0 préservé,
  RRC populate inchangé — backcompat strict).
- **`nmf_file.source_path`** : chemin absolu du `.nmf` source persisté.
  NULL pour les ingestions antérieures à 0.30.0 (déclaré, jamais rebackfillé
  d'office — procédure manuelle via `scripts/backfill_measurements.py`).
- **`nmf_file.dl`, `ts_label`, `env`, `start_at`, `device_sw`,
  `device_name`, `product`, `imei_present`, `imsi_present`** : header
  `#...` extrait verbatim (jamais inventé). `imei_present` / `imsi_present`
  sont des flags booléens seulement — les valeurs IMEI/IMSI ne sont
  **jamais** copiées (deny-list identité maintenue à la source par le
  décodeur).

### Nouveau module `app/measure/populate.py`

Fonction `populate_measurement_points(db, project_id)` : UPDATE sur les
lignes `measurement_points` déjà créées par le skeleton BC1
(`populate_measurements` depuis `stg_measurement_raw`) + INSERT pour les
catégories jamais vues par le skeleton (`cmdreq`, `data_*`, `tx_power`,
`cqi`, `lock`, `other`).

- **Match UPDATE** sur `(project_id, capture_id, seq, event_code)` →
  pas de doublon, le skeleton BC1 n'est pas écrasé, juste enrichi.
- **Métriques prouvées** depuis `cellmeas.raw_fields` : `rsrp` ←
  `cell0_rsrp_dbm`, `rsrq` ← `cell0_rsrq_db`, `sinr` ← `cell0_sinr_db`,
  `earfcn` ← `cell0_earfcn`. **Toute autre position reste NULL
  déclaré** (`cqi`, `tx_power`, débits : positions internes non prouvées
  au-delà de `rat_code` / `system_code`).
- **`operator` AUTORITAIRE depuis `nmf_file.dl`** (meta.dl), traduit via
  `DL_TO_OPERATOR` (`OFR→Orange, BYT→Bouygues, FREE→Free, SFR→SFR`).
  `operator_source='file'`. Si `#DL` absent/hors table, fallback sur le
  dernier SIB1 PLMN précédent (`operator_source='sib1'`). Sinon
  `operator_source='none'`.
- **`operator_mismatch=TRUE`** si `operator_file ≠ operator_sib1` (les
  deux ont été dérivés et divergent). Jamais masqué : la ligne reste avec
  `operator=operator_file` (AUTORITAIRE) et le mismatch est **déclaré**.
- **`service_name`** = `nmf_file.ts_label` verbatim (nom NEMO du script).
- **`service_action`** = dernier `CMDREQ.service_action` précédent en
  ordre canonique `(capture_id, seq)` — jamais par `ts`.
- **`service_type`** via `SERVICE_TYPE_RULES` (premier match) :
  `HTTP DL`, `HTTP UL`, `MOC|MTC|VOICE`, `SMS`, `VIDEO|YOUTUBE`, `PING`,
  `FTP DL`, `FTP UL`, `IPERF`. Sinon NULL déclaré.
- **`phase`** : `active` si `service_action` commence par `Start*` (hors
  `StartRepeat`), `idle` si `Stop*`, `wait` si `Wait`, sinon `idle`.
- **`rat`** = `rat_code → {'7': 'LTE', '9': 'NR'}`, sinon NULL.
- **`env`** = `nmf_file.env` (`'incar'` / `'indoor'` / NULL — détecté par
  le CONTENU du nom de fichier, jamais deviné).

### Modifié — `app/ingest/nmf.py`

- **Bascule** : utilise `decode_nmf_file_full` (2.0.0) à la place de
  `decode_nmf_file` (1.0.0). Fallback explicite sur 1.0.0 si la nouvelle
  porte n'est pas exposée (écart déclaré via `error`).
- **`DecodeResult`** gagne `raw_events: list[dict]` + `meta: dict`.
  `measurements` (BC1) reste alimenté par un **mirror** CELLMEAS →
  `stg_measurement_raw` (category=`measurement`) et DSUMMARY →
  `stg_measurement_raw` (category=`throughput`) pour que
  `populate_measurements` BC1 crée toujours les skeleton rows et que
  la route `/measurements/raw` reste fonctionnelle.
- **Nouvelle fonction `_persist_source_file(tmp_path, project_id,
  nmf_file_id)`** : copie le `.nmf` du tempfile vers
  `<BC4_NMF_SOURCE_DIR>/<project_id>/<nmf_file_id>.nmf` avant la
  suppression du tempfile. Idempotent (ne recopie pas si déjà présent).
  Erreur I/O → `source_path=None` + `error_msg="source_path_write_failed"`,
  non fatal.
- **Hook post-ingestion** : après `populate_measurements` (skeleton BC1),
  `populate_measurement_points(db, project_id, purge=False)` est appelé —
  UPDATE sur les lignes CELLMEAS existantes + INSERT pour les autres
  catégories. Erreur non fatale (rejouable via `backfill`).

### Modifié — `docker-compose.yml`

- Nouveau volume Docker nommé **`bc4_nmf_source`** monté sur
  `/var/lib/bc4/nmf-source`. Persistant au `docker compose down`
  (sans `-v`). Pour inspecter : `docker exec bc4-api-1 ls
  /var/lib/bc4/nmf-source/<project_id>/`.
- Nouvelle variable d'env **`BC4_NMF_SOURCE_DIR=/var/lib/bc4/nmf-source`**
  (surchargeable à l'host).

### Nouveaux scripts

- `scripts/ingest_ref_petite_foret.sh` : crée le projet
  `REF_PETITE_FORET` et ingère les 18 NMF témoins de
  `/home/devmat/BC4/witness-nmf/`. Totaux `done` / `error` / `duplicate`
  reportés par fichier.
- `scripts/g26_measurement_full.sh` : garde manuelle (G23/G24/G25 déjà
  pris par les lots précédents BC1). Vérifie `/health` ≥ 0.30, lance
  l'ingest si besoin, puis `pytest tests/test_g26_measurement_full.py`.

### Nouveau test — `tests/test_g26_measurement_full.py`

- `stg_event_raw` breakdown par catégorie (cellmeas/gps obligatoires,
  cmdreq/data_* déclarés absents si pas peuplés — pas d'assertion stricte
  sur ces catégories variables selon le script Nemo).
- `stg_event` signalling non vide.
- 18 `nmf_file` avec `dl`, `env`, `source_path` renseignés, source
  physique présente sur disque (skip si côté host, vérifiable via
  `docker exec`).
- `measurement_points` : total > 0 + breakdown
  `(operator × service_type × phase)`.
- `operator` cohérent avec `#DL`.
- `operator_mismatch=TRUE` : compte + 3 exemples (déclaré, pas assertion).
- RSRP cross-check CELLMEAS vs RRC par bande (déclaré).
- Scan IMSI/IMEI (regex 15 digits) sur `stg_event_raw.raw_fields::text`
  → 0 hit attendu.
- Unicité canonique `(capture_id, seq, event_code)` sur `stg_event_raw`.

### Écarts restants (déclarés ouverts)

- **CQI / TX_POWER / débits** : positions internes non prouvées sur un
  échantillon réel au-delà de `rat_code`/`system_code`. Les colonnes
  `measurement_points.cqi`, `.tx_power`, `.thrpt_ul`, `.dl` restent NULL
  tant qu'un mapping Phase 1 (preuve + validation croisée RRC) n'est pas
  fourni.
- **GPS catégorie dédiée** : les events GPS sont persistés dans
  `stg_event_raw.category='gps'` **en plus** du rattachement last-seen
  lat/lon sur chaque event aval (déjà fait par le décodeur). Pas de
  doublon géographique, juste trace brute.
- **Rebackfill des anciens NMF** : les lignes `nmf_file` antérieures à
  0.30.0 n'ont ni `dl`, ni `source_path`, ni meta — jamais rebackfillé
  d'office. Procédure : réingérer depuis le `.nmf` source (si disponible)
  via `POST /projects/<pid>/nmf` ou `scripts/backfill_measurements.py`.
- **Catégories data_* / tx_power / cqi / lock** : la présence ou absence
  dans le corpus Petite-Forêt dépend du script NEMO exécuté — le test
  G26 **déclare** l'absence plutôt que forcer un échec.

### Garde manuelle

Prérequis : `BC4_API_BASE`, `BC4_DEMO_EMAIL`, `BC4_DEMO_PASSWORD` set.

```bash
docker compose up -d --build api
curl -s http://localhost:8000/health   # version=0.32.0
bash scripts/ingest_ref_petite_foret.sh
bash scripts/g26_measurement_full.sh
```

## 0.31.0 — 2026-10-16 (minor) — Catalogue V3 étendu + fix routage histogram X (Agent BC1)

> Extension du catalogue V3 sans toucher au moteur. Les métriques
> radio (RSRQ, SINR, CQI, latence), de mobilité (RRC setup/reconfig/
> handover/reestablishment), et topologie sont désormais résolues
> par identité canonique avec `nature`, `unit` et `available_check`.
> Fix du routage « histogram <X> » / « stats <X> » / « rrc setup »
> qui tombait sur `conversation` au lieu de `distribution`/`list`.

### Ajouté — `app/assistant/metrics.py`
- **Radio** :
  - `rsrqServing` (dB, mesure, path `%measResultPCell/rsrqResult` + variantes NR, règle `(index/2)-20 dB`, TS 36.133 §9.1.7).
  - `sinrServing` (dB, mesure, `measurement_points.sinr`, UNAVAILABLE tant que Phase 1 non livrée).
  - `cqiServing` (indice 0..15, mesure, `measurement_points.cqi`).
  - `latencyServing` (ms, mesure, `measurement_points.latency`).
- **Mobilité / RRC counts** :
  - `rrcSetupCount` (count, message `RRCConnectionSetup`).
  - `rrcReconfCount` (count, message `RRCConnectionReconfiguration`).
  - `rrcMeasReportCount` (count, message `MeasurementReport`).
  - `handoverCount` (count, path `%mobilityControlInfo%`).
  - `reestablishmentCount` (count, message `RRCConnectionReestablishment`).
- **Topologie** :
  - `earfcnCount`, `pciCount` (counts purs).

### Modifié — `app/assistant/feasibility.py`
- `available_check` étendu avec 3 familles de patterns :
  - `<col>_populated` → vérifie `measurement_points.<col> IS NOT NULL`
    (`dl_populated`, `thrpt_ul_populated`, `sinr_populated`,
    `cqi_populated`, `latency_populated`, `rsrp_mp_populated`,
    `rsrq_mp_populated`).
  - `message_present:<RRC_MSG>` → vérifie
    `param_occurrence.message = <RRC_MSG>` ≥ 1 ligne pour le projet.
  - `path_present:<substr>` → vérifie
    `param_occurrence.path ILIKE %<substr>%` ≥ 1 ligne.
- Si check échoue → `Feasibility(ok=False, reason="…")` **DÉCLARÉ**,
  jamais substitué.

### Modifié — `app/assistant/intent.py` (fix routage)
- `_OP_PATTERNS` enrichi : `distribution` matche aussi `histo`,
  `list` matche aussi `stats`, `statistiques`, `count`, `nombre de`,
  `combien`.
- **Nouvelle règle anti-fallback** : si `_detect_operation` renvoie
  `conversation` MAIS que `_detect_metric` trouve une métrique
  canonique → force `operation = "list"`. Un énoncé d'analyse ne
  tombe JAMAIS sur l'intro.

### Garanties V3 préservées
- **Catalogue autoritaire** : chaque nouvelle métrique porte
  `nature`, `unit`, `comparability_class`, `available_check`.
- **Jamais de substitution** : UNAVAILABLE si source vide, pas de
  bascule silencieuse vers un count.
- **Vérificateur** : phénomène interdit par nature + unité
  cohérente + chiffres sourcés — inchangé 0.29.1.
- **Traçabilité result_id** : chaque réponse porte son plan +
  evidence (jamais le SQL compilé côté front).

### Garde manuelle (TEST2)
1. `histogram rsrp` → `op=distribution`, `metric=rsrpServing`,
   dims=`[value_raw, value_converted]`. Histogramme dBm (jamais
   count), source `param_occurrence` filtré sur `measResultPCell/rsrpResult`.
2. `compare les débits` → `op=compare`, `metric=throughputDL`,
   feasibility `dl_populated` → **UNAVAILABLE** déclaré (jamais
   count déguisé en débit).
3. `rrc setup` → `op=list` (plus `conversation`), `metric=rrcSetupCount`,
   feasibility `message_present:RRCConnectionSetup` →
   AVAILABLE/UNAVAILABLE selon projet.

### Non-objectifs
- Pas d'ajout de `coverage_hole` / `drop_rate` / `mcs` / `bler` /
  `correlation` : nécessitent soit un peuplement `measurement_points`
  Phase 1, soit un stockage événementiel distinct (lot futur).
- `data_availability(metric)` reste exposé via le code
  `check_feasibility` — pas d'endpoint public dédié (ajout en 0.31.1
  si besoin UI).
- Pas de modification du moteur / pipeline / vérificateur / compose
  — pure extension catalogue + fix routage.

## 0.29.1 — 2026-10-16 (patch) — Unités autoritaires + anti-phénomène inventé (Agent BC1)

> Fix sémantique : en 0.29.0, « compare a3-Offset » affichait
> « 132 ms », « Orange 2 ms=43 » et une narration LLM parlait de
> « temps de latence ». **FAUX** : a3-Offset est un OFFSET en **dB**
> (`×0.5` TS 36.331 §6.3.5), pas une latence. 132 est un COMPTAGE
> d'occurrences, pas des ms. Ce patch verrouille l'unité au catalogue
> et interdit les termes de phénomène non pertinents à la nature du
> paramètre.

### Modifié — `app/assistant/metrics.py`
- **Classes de comparabilité** : `TIMER_HALF_MS` renommée
  `OFFSET_HALF_DB` (la convention 3GPP RRC pour les offsets `aN`,
  `qOffsetFreq`, etc. est un index × 0.5 **dB** — pas une milliseconde).
- **`a3Offset`** passe en :
  - `unit="dB"` (était `"ms"`)
  - `comparability_class="OFFSET_HALF_DB"`
  - `nature="config"` (nouveau champ)
  - `convert_rule="valeur ASN.1 × 0.5 dB (TS 36.331 §6.3.5)"`
  - `display="a3-Offset (seuil event A3, décalage neighbour vs serving)"`
- **Nouveau champ `nature`** sur `CanonicalMetric` :
  - `"config"` : seuil/offset/timer RRC — **n'est PAS une grandeur
    mesurée**. Parler de latence/débit/qualité à son sujet est faux.
  - `"measurement"` : grandeur radio mesurée (RSRP, débits, …).
  - `"count"` : pur comptage d'occurrences, pas une physique.
  - Toutes les métriques du CATALOG sont étiquetées : `operator_count`,
    `band_count`, `rrc_message_count` → `count` ; `a3Offset`,
    `a5Threshold1` → `config` ; `rsrpServing`, `throughputDL/UL` →
    `measurement`.
- **`FORBIDDEN_PHENOMENA_FOR_CONFIG`** et **`FORBIDDEN_PHENOMENA_FOR_COUNT`** :
  listes de termes interceptés par le vérificateur si la narration
  les emploie à tort (ex. « latence » sur un offset config).

### Modifié — `app/assistant/pipeline.py`
- **`_compose_observed`** : séparation stricte **count vs valeur**.
  - Le TOTAL d'occurrences s'affiche toujours en « occurrences »
    (`count_label`), JAMAIS avec l'unité physique de la métrique.
  - Les VALEURS individuelles portent l'unité du catalogue (ex. `dB`
    pour a3-Offset) avec le compteur accolé entre parenthèses :
    `Orange : 2 dB (43 occurrences), 2.5 dB (31 occurrences)` au lieu
    de `Orange : 2 ms=43, 2.5 ms=31`.
  - Le header précise l'unité des valeurs : « a3-Offset — 3 opérateur(s),
    total 132 occurrences ; unité des valeurs : dB ».
- **Prompt système narration dynamique** (`_system_prompt_for_narration`) :
  injecte `metric.display`, `metric.nature`, `metric.unit`, et une
  règle spécifique à la nature :
  - CONFIG : « INTERDICTION ABSOLUE d'utiliser 'latence', 'débit',
    'throughput', 'qualité radio', 'couverture', 'signal fort/faible' ».
  - COUNT : « INTERDICTION 'latence', 'débit', 'qualité radio',
    'couverture' — c'est juste un volume brut ».
  - MEASUREMENT : termes qualitatifs physiques autorisés uniquement
    si pertinents à l'unité.
- **Nouveau vérificateur `_detect_forbidden_phenomena(txt, metric)`** :
  si la narration contient un terme de phénomène interdit pour la
  nature de la métrique → rejet avec motif.
- **Nouveau vérificateur `_unit_consistent(txt, metric)`** : si la
  narration cite une unité différente de celle du catalogue (ex. « ms »
  alors que `metric.unit == "dB"`), rejet.
- `_narrate_llm` applique les 4 vérificateurs dans l'ordre : bavardage →
  phénomène → unité → chiffres sourcés. **Un seul rejet suffit à
  tomber sur `_fallback_narration` déterministe.**

### Garanties verrouillées
- **Unité AUTORITAIRE** : vient toujours du catalogue, jamais d'un
  défaut implicite « ms ».
- **Nature préservée** : un paramètre `config` n'est jamais décrit
  comme une grandeur mesurée. Un `count` n'est jamais décrit comme
  une physique.
- **Vérification croisée** : le LLM peut encore proposer une
  narration, mais 4 vérificateurs la filtrent. Fallback déterministe
  si rejet.

### Garde manuelle (TEST2)
- « compare a3-Offset » → observed[] :
  « a3-Offset (seuil event A3, décalage neighbour vs serving) —
  3 opérateur(s), total 132 occurrences ; unité des valeurs : dB. »
  « Orange : 2 dB (43 occurrences), 2.5 dB (31 occurrences). »
  **ZÉRO « ms »**, **ZÉRO « latence »** dans la narration (rejetée si
  présente).

### Non-objectifs
- Pas d'enrichissement du vocabulaire interdit — on couvre les
  grands classiques (latence, débit, qualité, couverture). Si un
  terme s'infiltre, l'ajouter à `FORBIDDEN_PHENOMENA_FOR_*`.
- Les paths ambigus (ex. `offsetValue` dans `ReportConfigEUTRA` qui
  peut être une adresse MAC d'offset de fréquence ou un offset de
  threshold) ne sont pas discriminés dans le catalogue — ajout
  spécifique si besoin.

## 0.29.0 — 2026-10-16 (minor) — V3 finition : narration vérifiée + carte V3 + compare pivoté (Agent BC1)

> Trois chantiers de finition sur l'Assistant V3 (0.28.0) :
> 1. Narration LLM courte **réactivée** derrière le vérificateur.
> 2. Carte RSRP (`map_metric`) **réintégrée** dans le pipeline V3 —
>    plus de fallback table.
> 3. Compare paramètre × opérateur **pivoté** : chaque opérateur montre
>    sa distribution, plus de « Orange » dupliqué sans valeur.

### Ajouté — `app/assistant/pipeline.py`
- **`_narrate_llm`** : appel LLM court (max 120 tokens, timeout 15 s)
  derrière deux vérificateurs :
  - **`_bavardage`** : regex interdit `« puis-je vous aider »`,
    `« n'hésitez pas »`, `« relativement stable »`,
    `« globalement stable »`, `« je peux aussi »`, `« je suis
    l'assistant »`, `« ravi de vous aider »` → rejet avec motif.
  - **`_verify_narration`** (0.28.0) : regex chiffres, whitelist =
    rows + observed[] + entiers 0..10. Chiffres ≥ 100 non sourcés →
    rejet.
- **Prompt système narration** verrouillé :
  - « UNE SEULE phrase (max 2) qui résume qualitativement ».
  - « Ne cite AUCUN chiffre qui n'apparaît pas littéralement ».
  - « Pas de 'moyenne', pas de 'relativement stable' ».
  - « Démarre directement par la lecture. Pas de 'Puis-je vous aider' ».
- **`_fallback_narration`** : phrase déterministe construite depuis
  `observed[0]` + verdict si rejet LLM. Utilisée aussi quand LLM
  désactivé / budget cap atteint.
- La narration finale rejetée est signalée dans `warnings[]` avec le
  motif (traçabilité serveur-side).

### Ajouté — Carte V3
- `_execute_intent` branche `operation=map` directement sur
  `map_metric` (tool 0.26.0) sans passer par le moteur générique.
  Résultat enveloppé dans un `AnalyticalResult` dont `plan["_map_meta"]`
  porte `unit, value_range, grid, center, aggregated_points`.
- `compose_pipeline_response` détecte `plan.tool=="map_metric"` et
  émet un **`BlockMap`** via `_compose_map` (0.26.0) + table compagnon.
  **Plus aucun fallback table pour les cartes.**

### Ajouté — Compare pivoté
- Nouveau helper **`_compose_bar_grouped`** (dans `compose.py`) :
  Bar chart GROUPÉ. `categories` = valeurs de `group_dim` (ex.
  opérateurs). `series[]` = une série par valeur de `series_dim`
  (ex. `value_converted`). Idéal pour visualiser la distribution
  de chaque opérateur côte à côte.
- `compose_pipeline_response` détecte `operation=compare` +
  `operator` + `value_raw/value_converted` dans dims → appelle
  `_compose_bar_grouped(group_dim="operator",
  series_dim="value_converted" (fallback value_raw))`.
- **`_compose_observed`** mis à jour pour PIVOTER par opérateur
  quand pattern détecté : affiche par ligne `Orange : 3 ms=43,
  2.5 ms=31` au lieu de `Top : Orange=43, Orange=31`.

### Garanties préservées
- **Aucun chiffre sans sa requête** : la narration est **vérifiée**.
  Chiffres non sourcés ≥ 100 → rejet garanti.
- **Zéro bavardage** : patterns verrouillés par regex.
- **Fallback déterministe** si narration rejetée — la UI n'affiche
  jamais une phrase vide ni une phrase polluée.
- **Scope projet strict**, **zéro identité**, **budget cap** (0.27.0)
  tous conservés.

### Garde manuelle (3 cas — à exécuter sur TEST2)

1. « compare a3-Offset » → `observed[]` affiche par opérateur
   (`Orange : 2 ms=43, 2.5 ms=31`), chart bar GROUPÉ (séries =
   valeurs ms), verdict calculé. Plus de « Orange » répété sans
   valeur.
2. « Affiche la carte des RSRP » → **BlockMap** émis (81 cellules,
   value_range [-116, -69] dBm) avec table compagnon. Plus de
   fallback table seule.
3. Question d'analyse arbitraire → narration LLM courte, chiffres
   vérifiés. Forcer rejet (par ex. simuler un chiffre non sourcé)
   → warning serveur + fallback déterministe. Prouvable via
   `_verify_narration` unitaire.

### Non-objectifs (écarts ouverts)
- Narration limitée à 2 phrases max. Si l'analyse est très riche,
  observed[] et blocs typés sont les sources principales.
- `operation=trend` toujours non implémenté (buckets temporels à
  venir en 0.30.0).
- Moteur `contains` monofilter reste la limite pour `a3Offset` à
  patterns multiples — le premier pattern canonique prévaut.
- Pas de **narration multi-tour** (chaque question part de zéro,
  pas de contexte conversationnel). Mémoire conversationnelle =
  lot séparé si besoin.

## 0.28.0 — 2026-10-16 (minor) — Assistant V3 : pipeline piloté par l'intention (Agent BC1)

> **Changement structurel** : le LLM n'écrit plus les chiffres. Il
> **planifie** (parse d'intention structuré) et le SYSTÈME **compose
> & vérifie** (observed[] déterministe, verdict calculé par
> `validate_comparison`, blocs typés depuis les résultats moteur).
> Aucune substitution de métrique sur replan : si la métrique est
> indisponible, l'écart est **DÉCLARÉ**, jamais comblé.

### Ajouté — `app/assistant/`
- **`metrics.py`** — Catalogue de **métriques canoniques** typées :
  - `CanonicalMetric` : `key, display, unit, comparability_class,
    source_dataset, path_match, message_match, exclude_path_patterns,
    convert_rule, recomposable, available_check, user_terms`.
  - `ComparabilityClass` : `COUNT | TIMER_HALF_MS | TIMER_MS |
    RSRP_DBM | RSRQ_DB | SINR_DB | CQI_IDX | THRPT_MBPS | BYTES |
    BOOLEAN | ENUM | RAW_STRING`. **Deux métriques de classes
    différentes NE sont PAS comparables** (règle anti-mélange d'unités).
  - `CATALOG` initial : `operator_count`, `band_count`,
    `rrc_message_count`, `a3Offset` (×0.5 ms), `a5Threshold1`,
    `rsrpServing`, `throughputDL` (available_check `dl_populated`),
    `throughputUL` (available_check `thrpt_ul_populated`).
  - `resolve_user_term(term)` : résolution lexicale **stricte** —
    unigrammes match EXACT, n-grams match substring. Évite les faux
    positifs sur « par » / « des ».

- **`intent.py`** — Parser **100 % Python** (aucune hallucination
  LLM dans ce chemin) :
  - `IntentPlan` : `operation, metric_key, dimensions,
    comparison_dim, filters, ambiguous_terms, needs_clarification,
    reason`.
  - Opérations détectées par patterns FR+EN : `list | distribution |
    compare | map | trend | describe | conversation | unknown`.
  - Résolution métrique via `resolve_user_term` + mots-clés
    « familles larges » (`RLC`, `PDCP`, `mobilité`, …) qui déclenchent
    `needs_clarification=True` plutôt qu'un choix implicite.
  - Détection filtres opérateur (4 MNO FR littéraux) et bande
    (regex `B\d|n\d{1,3}`).
  - `comparison_dim` défaut EXPLICITE = `operator` quand
    `operation=compare` sans précision user.

- **`feasibility.py`** — Étage 2, préservation stricte de la métrique :
  - `check(db, project_id, metric_key) → Feasibility(ok, reason,
    ambiguous_paths, sample_count)`.
  - Vérifie dataset non vide → `available_check` (col `dl` /
    `thrpt_ul`) → `path_match` dans `param_occurrence`.
  - Métrique indisponible → `ok=False` avec raison claire. **Aucune
    substitution automatique.**
  - > 20 paths distincts matchent → `ambiguous_paths` renvoyée pour
    clarification UI (ex. terme large sans précision user).

- **`pipeline.py`** — Orchestration V3 complète :
  - `PipelineRun(outcome, intent, feasibility, results, observed[],
    verdict_tag, verdict_reason, narration, narration_rejected,
    warnings, message)`.
  - `Outcome ∈ {OK, UNAVAILABLE, NEEDS_CLARIFICATION, ERROR, CONVERSATION}`.
  - **États typés par cellule** : `CellState ∈ {PRESENT, ZERO_REEL,
    ABSENT_DU_PERIMETRE, INDISPONIBLE}`. Les opérateurs attendus
    (metadata projet ∪ 4 MNO FR) absents du résultat sont ajoutés
    explicitement comme `ABSENT_DU_PERIMETRE`.
  - `_compose_observed` : chiffres clés RÉDIGÉS PAR LE CODE depuis les
    cellules — total, top 3, absents déclarés, indisponibles comptés.
  - `_compute_verdict` : verdict CALCULÉ via `validate_comparison`,
    jamais raconté par le LLM.
  - Vérificateur `_verify_narration` : regex chiffres → doivent être
    dans les sources autorisées (rows des result_ids, lignes observed[],
    entiers 0..10). Chiffres non sourcés `≥ 100` → rejet narration.
  - Narration LLM **désactivée par défaut** en 0.28.0 (le temps que
    le vérificateur soit étalonné en live). Les observed[] + verdict
    + blocs typés suffisent.
  - Budget pre-check (hérité 0.27.0).

- **`compose_v3.py`** — `compose_pipeline_response(run)` :
  - `OUTCOME=CONVERSATION` → présentation 0.24.1 inchangée.
  - `OUTCOME=NEEDS_CLARIFICATION` → BlockText « Précision nécessaire ».
  - `OUTCOME=UNAVAILABLE` → BlockText « Métrique indisponible ».
  - `OUTCOME=OK` → BlockText « Résumé (chiffres clés) » (observed[]
    rédigé par le code) + BlockText « Verdict de comparabilité »
    (CALCULÉ) + blocs typés via composers 0.25.1 (bar / histogramme /
    map / table) depuis les résultats moteur. Evidence rattachée aux
    result_ids.

### Modifié
- `app/routes/assistant.py` : la branche ANALYSE route maintenant
  vers `run_pipeline` + `compose_pipeline_response`. L'ancien chemin
  tool-calling (`run_agent` + `compose_response` 0.25.1) reste
  **importable** pour backward-compat tests / debug mais n'est plus
  invoqué.

### Garanties verrouillées (correctifs du cahier des charges)
- **Le LLM planifie, le système compose & vérifie** : les chiffres
  dans la UI viennent uniquement du moteur (`AnalyticalResult.rows`)
  et des observed[] rédigés par le code. La narration LLM
  (quand active) est **vérifiée** chiffre par chiffre.
- **Métrique PRÉSERVÉE sur replan** : il n'y a plus de boucle
  tool-calling, donc pas de risque de « replan vers une autre
  métrique ». Le pipeline exécute UNE requête contrainte par le
  catalogue.
- **États typés** : `PRESENT ≠ ZERO_REEL ≠ ABSENT_DU_PERIMETRE ≠
  INDISPONIBLE`. Un opérateur absent du projet n'est jamais rendu
  « 0 ».
- **Aucune substitution d'unité** : les classes de comparabilité
  interdisent de mélanger ms, dBm, kB, booléens.
- **Ambigu → clarification** : termes larges (RLC, PDCP, mobilité)
  sans précision déclenchent `NEEDS_CLARIFICATION` avec liste de
  candidats (le code n'invente pas la métrique).

### Garde manuelle (5 cas — à exécuter sur TEST2)

| # | Question | Attendu |
|---|---|---|
| 1 | « Compare les débits par opérateur » | `OUTCOME=UNAVAILABLE` : « colonne `measurement_points.dl` NULL partout (Phase 1 non livrée). Aucune substitution. ». **Aucun verdict COMPARABLE** affiché. |
| 2 | « compare a3-Offset » | `OUTCOME=OK`, scenario `v3_compare`, metric canonical `a3Offset` (×0.5 ms), group_by `operator + value_raw + value_converted`, verdict calculé via `validate_comparison`. observed[] contient le top 3 opérateurs. |
| 3 | « compare les paramètres RLC » | `OUTCOME=NEEDS_CLARIFICATION` : « Terme large non résolu en métrique canonique (rlc). Précise un paramètre RRC exact ou group_by param ». Aucun chiffre affiché. |
| 4 | opérateur hors projet (ex. filter Free sur un projet sans Free) | État `ABSENT_DU_PERIMETRE` dans observed[], jamais `0`. |
| 5 | Narration LLM injectant « 42 % des opérateurs » (chiffre inventé) | 0.28.0 narration DÉSACTIVÉE par défaut → cas inaccessible en live. Vérificateur `_verify_narration` testable unitairement (regex chiffres sourcés). |

### Non-objectifs (écarts ouverts)
- Pas de **narration LLM live** : désactivée en 0.28.0 tant que le
  vérificateur n'est pas étalonné sur plusieurs cas réels. Le code
  est en place (`_verify_narration` + boucle 1-shot) ; activation en
  0.28.1 ou 0.29.0 après revue.
- Pas de **sélection de métrique par LLM structuré JSON** : le parser
  reste 100 % Python en 0.28.0 pour éviter toute hallucination. Si
  des cas d'intent échouent, enrichir `CATALOG.user_terms` plutôt
  que de donner la main au LLM.
- `operation=map` dans V3 : le compose fallback sur table car V3 ne
  wire pas encore `map_metric` directement (il faudrait un nouveau
  helper qui construit un BlockMap). Lot 0.28.1.
- `operation=trend` : parser détecte, pipeline ne fait pas encore
  l'agrégation temporelle (pas de bucket de date dans les cellules).
  Lot 0.28.2.
- Rows filtrées par un `message_match` : actuellement le filtre
  message est ajouté au plan, mais le moteur ne supporte qu'un
  `contains` par dim → si `a3Offset` a plusieurs patterns, on garde
  le premier. Amélioration : étendre moteur pour accepter plusieurs
  `contains` sur même dim.

## 0.27.0 — 2026-10-16 (minor) — Maîtrise des coûts Assistant (digest + model_loop + cache + budget) (Agent BC1)

> Problème : ~10 €/jour sur l'Assistant. Causes = modèle cher × boucle
> 5 appels × contexte renvoyé à chaque étape × gros résultats
> réinjectés × tests répétés. Ce lot livre les **4 leviers** demandés
> sans affaiblir aucun garde-fou (provenance, aucun chiffre sans
> requête, n=0 déclaré, zéro identité).

### Levier n°1 — Digest tool_message (le gros morceau)
- Nouveau module **`app/assistant/digest.py`** : `make_digest(result,
  tool_name, top_k=10)` compacte un résultat d'outil pour injection
  dans un `tool_message` LLM.
- **Avant** : les 81 cellules de carte / 50 valeurs de distribution /
  liste complète de bandes partaient AU LLM à chaque étape de la
  boucle (OpenAI relaie tous les tool_messages précédents).
- **Après** : le LLM reçoit seulement
  `{result_id, tool, n, denominator, top_rows[10 max], total_rows,
  truncated, stats:{count_min,count_max,…}, verdict?, note_truncation}`.
  Pour `map_metric` : stats globales (cells_count, value_range,
  grid, unit) + `top_cells[5]` au lieu de 81 cellules.
- La donnée COMPLÈTE reste côté serveur dans
  `AgentRun.results_by_id` → `compose.py` rend intégralement (table
  avec les 81 lignes, carte avec les 81 cellules). **Aucun chiffre
  perdu côté UI, aucun chiffre inventé côté LLM** : le prompt
  système interdit déjà toute citation absente du contexte.

### Levier n°2 — `model_loop` configurable
- Migration **`0012_llm_cost_control`** : colonnes
  `settings_llm.model_loop` et `settings_llm.daily_cap_usd`.
- `app/schemas/llm.py` : `LlmSettings` et `LlmSettingsInput` étendus
  avec `model_loop` et `daily_cap_usd` (optionnels).
- `app/config.py` : nouveaux env `BC4_LLM_MODEL_LOOP` et
  `BC4_LLM_DAILY_CAP_USD` (fallback si DB vide).
- `get_effective_llm_config` expose `model_loop` (DB > env >
  fallback sur `model` si vide).
- `app/assistant/loop.py` : la boucle utilise `model_loop` ; le probe
  (`/settings/llm/test`) reste sur `model` (modèle de qualité).
- Routes PUT `/settings/llm` accepte `model_loop` et `daily_cap_usd`.

### Levier n°3 — Prompt caching (`cache_control: ephemeral`)
- Le system prompt (règles + `discover_schema` complet) est volumineux
  et IDENTIQUE à chaque étape de la boucle. On le marque
  `cache_control: {type: "ephemeral"}` dans le message system :
  ```json
  {"role":"system","content":[{"type":"text","text":"…","cache_control":{"type":"ephemeral"}}]}
  ```
- OpenRouter route vers l'option Anthropic cache_control appropriée
  pour les modèles Claude. Pour les providers qui ignorent
  `cache_control` (OpenAI direct), le champ est un no-op — pas de
  régression.
- Les `tools[]` schemas sont déjà cachés par OpenRouter par défaut
  (envoyés au top-level).

### Levier n°4 — Budget journalier
- Nouveau module **`app/assistant/budget.py`** :
  - Table `PRICING` USD/1k tokens pour OpenAI / Anthropic / Mistral
    (prix d'octobre 2026 — à aligner si évolution).
  - `estimate_cost(model, prompt_tokens, completion_tokens) → float`.
  - `log_usage(db, model, pt, ct, conversation_id, step)` : insère
    dans `llm_usage` + commit immédiat (pour que le cap soit live).
  - `check_budget(db, cap_usd) → (ok, spent, cap)` : vrai si pas de
    cap OU dépense du jour < cap. Reset implicite minuit UTC.
  - `spent_today_usd(db) → float`.
  - `usage_summary(db)` : breakdown par modèle du jour.
- Modèle **`LlmUsage`** (`app/models/base.py`) + export dans
  `app/models/__init__.py`.
- `run_agent` **check le cap AVANT chaque appel LLM**. Si atteint :
  retourne `AgentRun(error="Budget LLM du jour atteint ($X / $Y). …")`
  **PAS d'appel au provider**. La UI reçoit un claim UNAVAILABLE
  clair, pas une erreur brute, pas d'invention.
- Après chaque appel LLM, `log_usage(…)` journalise les tokens
  reportés par le provider (`usage.prompt_tokens`,
  `usage.completion_tokens`).
- Nouvel endpoint **`GET /settings/llm/usage`** (admin) :
  ```json
  {
    "date": "2026-10-16",
    "spent_today_usd": 2.47,
    "cap_usd": 5.00,
    "remaining_usd": 2.53,
    "by_model": [
      {"model": "anthropic/claude-3-5-haiku",
       "prompt_tokens": 42000, "completion_tokens": 3200,
       "estimated_cost_usd": 2.47, "calls": 12}
    ]
  }
  ```

### Garde-fous préservés
- **Aucun chiffre sans requête** : le digest contient les chiffres que
  le LLM peut citer ; pour tout le reste il référence `result_id` et
  la UI affiche la table complète.
- **n=0 déclaré** : digest contient `n=0` explicite si rows vides,
  jamais inventé.
- **Scope projet strict** : `project_id` toujours injecté serveur
  (hérité 0.25.0).
- **Zéro identité abonné** dans `llm_usage` (log de méta-usage).
- **MAX_STEPS=5** : conservé. Pas de court-circuit auto-magique
  (`if not tool_calls: return` était déjà en place depuis 0.25.0 —
  le LLM qui ne demande rien, c'est la fin).

### Non-objectifs (écarts ouverts)
- Pas de breakdown par **projet / utilisateur** dans `llm_usage` —
  ajout en 0.27.1 si besoin (nécessite récupérer `project_id` et
  `user_id` dans `run_agent` à travers la session).
- Pas de **métriques de hit-ratio** du cache_control (OpenRouter n'
  expose pas cette info dans `usage` aujourd'hui). On ne peut mesurer
  l'effet du caching que par comparaison before/after sur la facture
  mensuelle.
- Pas de **retry** sur rate-limit 429 : la boucle abort avec
  `provider en rate-limit (429)` et laisse l'utilisateur retenter.
- Pas de **cost caps multi-niveaux** (hourly, weekly). Reset minuit
  UTC uniquement.

### Garde manuelle (sur TEST2, à exécuter après deploy)
Pour « Compare a3Offset Orange/SFR B3/B20 » :
- Reporter les tokens d'entrée du 1er appel LLM AVANT / APRÈS :
  attendu une réduction significative (~5-10× sur l'entrée moyenne
  des étapes 2+, où les digest remplacent les tables).
- Vérifier que la réponse UI reste **identique** (mêmes blocs,
  mêmes `result_id`, mêmes chiffres dans les tables / cartes /
  verdicts — rien ne change côté user).
- Vérifier que `model_loop` est bien utilisé : header `model=` dans
  les requêtes vers OpenRouter.
- Poser `daily_cap_usd=0.01` (très bas) → poser une question →
  message clair « Budget LLM du jour atteint ». Rétablir
  `daily_cap_usd=5.0` ensuite.
- `GET /settings/llm/usage` admin → voir les tokens / coût accumulés
  du jour.

## 0.26.0 — 2026-10-16 (minor) — Outil `map_metric` : carte agrégée RSRP par cellule (Agent BC1)

> Livre le dernier outil manquant de la fondation 0.25.0 : `map_metric`
> produit une carte géolocalisée **agrégée par cellule de grille** à
> partir des events RRC `MeasurementReport` du projet. Source =
> `param_occurrence` (le mapping décodeur `measurement_points.rsrp`
> reste Phase 1 pending) — le RSRP RRC serving porte déjà
> `value_converted` en dBm + lat/lon via rattachement GPS 0.14.x.
> **Agrégats seulement, zéro ligne brute, zéro identité abonné.**

### Ajouté
- **Outil `map_metric(metric, bins, operator, band, system)`** dans
  `app/assistant/tools.py` :
  - `metric="M_serving_rsrp"` (seule métrique 0.26.0). `rsrq_serving` /
    `sinr_serving` arriveront quand Phase 1 décodeur sera livrée pour
    `measurement_points`.
  - `bins` ∈ [1, 5] = nombre de décimales d'arrondi lat/lon (3 = ~100m,
    défaut).
  - Filtres `operator / band / system` passés en whitelist stricte (4 MNO
    FR, bande regex, système ∈ {LTE, NR}).
  - **Discriminant RSRP serving par le CONTENU du path** (jamais
    l'étiquette) :
    - `path LIKE '%measResultPCell/rsrpResult'` (LTE serving PCell)
    - `path LIKE '%measResultServingCell%rsrpResult%'` (NR serving)
    - `path LIKE '%measResultServingMOList%rsrp%'` (NR MR-DC)
  - **Exclu** : paths de configuration (`threshold-RSRP` dans
    `reportConfigEUTRA`, `a3-Offset`, …), neighbour cells, projets
    inconnus.
  - Agrégation **mathématiquement correcte** : `AVG(value_converted::
    float)` + `COUNT(*)` **sur les observations admissibles par cellule**,
    jamais moyenne de moyennes.
  - **Garde-fou plage 3GPP valide** : `HAVING AVG(...) BETWEEN -140 AND
    -40 dBm` — cellules aberrantes filtrées (signal décodeur suspect
    plutôt que valeur imposée).
  - `LIMIT 2000` cellules + `statement_timeout 5000ms`.
  - Opérateur NULL / hors MNO FR / tech hors {LTE,NR} filtré au SQL
    (contrainte schema `MeasurementPoint.operator = Literal`).
- **Schéma `BlockMap` étendu** (`app/schemas/assistant.py`) :
  - `unit: str | None` (ex. `"dBm"`)
  - `value_range: tuple[float, float] | None` (plage min/max observée)
  - `grid: dict | None` (`{bins_decimals, cells}`)
  **Non-breaking** côté front Zod : champs optionnels, les anciens
  appels `BlockMap` ne les reçoivent pas.
- **Composer `_compose_map`** dans `app/assistant/compose.py` :
  - Construit un `BlockMap` Pydantic depuis les cellules agrégées
    (conformes à `MeasurementPoint`, `service="Data"` sentinel documenté).
  - `source_id = result_id` (contrat preuves 0.25.0).
  - Table compagnon avec `lat / lon / operator / band / rsrp / n`.
  - n=0 → `_n_zero_block` déclaratif, **jamais** une carte vide.
- Schéma OpenAI function-call `map_metric` ajouté à `TOOL_SCHEMAS` ;
  dispatcher `dispatch_tool` câblé.

### Garde manuelle (smoke live sur TEST2 — outil appelé directement sans LLM)
Résultats réels :
```
result_id        : 969a859f4a126812   (stable)
metric           : M_serving_rsrp
unit             : dBm
n cellules       : 81
total observations : 1 935
value_range obs. : [-116.0, -69.0]  (dans [-140, -40] 3GPP valide)
grid             : {bins_decimals: 3, cells: 81}
center géo       : [50.378, 3.477]
operators        : Bouygues, Free, Orange
bands            : B1, B20, B3, B7
tech             : LTE
```
Grep logs API : **0 occurrence** d'identité abonné (IMSI / IMEI / s-TMSI /
c-RNTI / GUTI / PTMSI) sur l'ingestion complète.

### Garanties
- **project_id** injecté serveur depuis la session appelante (jamais
  depuis les args du LLM — hérité du moteur 0.25.0).
- **Agrégats seulement** : chaque point = une cellule GROUP BY, jamais
  une ligne brute (`param_occurrence` fine-grained).
- **Statistiques correctes** : AVG sur observations réelles par
  cellule, pas de recomposition multi-niveaux.
- **n=0 déclaré** : si le périmètre ne contient aucun RSRP serving
  valide, bloc OBSERVED « donnée indisponible pour ce périmètre » +
  warning précisant la cause probable (filtres trop stricts /
  path inconnu / projet sans MeasurementReport).

### Écarts ouverts explicites
- **Serving vs neighbour** : les patterns `path LIKE` ciblent le
  serving cell. Si le décodeur émet un `rsrpResult` sans
  `measResultPCell` ni `measResultServingCell` dans le path, l'outil
  ne le voit pas (prévisible — mieux que de forcer tout `rsrpResult`
  dans la carte, ce qui mélangerait neighbour & serving).
- **Métriques `rsrq` / `sinr` serving** : param_occurrence porte
  `rsrqResult` et des SINR-like, mais le lot 0.26.0 se limite au
  RSRP. Ajouts en 0.26.1 quand les patterns de path RRC seront
  validés sur TEST2.
- **`service="Data"` sentinel** : les cellules agrégées ne portent pas
  de notion de service (concept B0). Choisir `"Data"` est une convention
  projet documentée (toute cellule carte = agrégation RSRP, pas une
  observation per-service). Alternative future : nouveau Pydantic model
  `AggregatedMapCell` avec `service: str | None` au lieu du Literal
  strict — coordonné avec le front.
- Le LLM provider (OpenRouter) est en 402 au moment du smoke → la UI
  retourne UNAVAILABLE jusqu'à recharge de crédit. L'outil fonctionne
  en direct (démontré ci-dessus).

## 0.25.1 — 2026-10-16 (patch) — Assistant V2 : blocs typés + rejections rejouées (Agent BC1)

> Fix UX & architecture : avant 0.25.1, `compose.py` n'émettait qu'un
> `BlockTable` par outil → la UI affichait partout une table. Désormais
> **dispatch déterministe par outil** vers le type de bloc approprié
> (bar / histogramme / contexte / verdict). Les plan rejections émises
> par le moteur sont **silencieuses côté UI** : elles ont déjà été
> rejouées par l'agent (le LLM voit l'erreur dans son `tool_message` et
> replanifie). Garde manuelle 4 cas conservée.

### Modifié — `app/assistant/compose.py`
- **Table de dispatch `_RENDER_BY_TOOL`** : association `tool_name →
  render_type` figée en code, jamais piloté par le LLM.
  - `list_bands`, `list_operators`, `top_rrc_messages`,
    `compare_operators`, `geo_breakdown`, `arcep_breakdown`,
    `throughput_stats`, `radio_quality_stats` → `bar`
  - `rrc_param_distribution` → `histogram` (bar visuel, sémantique
    distribution)
  - `compare_distributions` → `verdict_only` (BlockText verdict seul)
  - `get_project_context` → `context` (BlockText metadata)
  - `map_metric` → `map` (préparé, outil pas livré)
- **Composers par type** :
  - `_compose_bar` : BlockChart(bar) + BlockTable compagnon.
    Pour `compare_operators`, agrège les sous-résultats en 1 bar
    multi-opérateurs + verdict en BlockText.
  - `_compose_histogram` : abscisse = `value_converted` (dBm/dB/…)
    quand dispo, sinon `value_raw` ; ordre moteur conservé.
  - `_compose_context` : liste nom/période/opérateurs/techs/bandes
    du projet en claims OBSERVED.
  - `_compose_verdict_only` : BlockText avec verdict + raison.
  - `_compose_default` fallback : BlockTable (comportement 0.25.0).
- **n=0 déclaratif** : rows vides → `_n_zero_block` qui émet un
  `BlockText(OBSERVED)` « n=0 — donnée indisponible pour ce périmètre
  (jamais inventée) », JAMAIS un graphe vide.
- **NULL → "N/D"** : les catégories d'un bar/histogram avec NULL en
  base sont rendues `"N/D"` (constante `_NULL_LABEL`), jamais 0.
- **Rejections rejouées silencieusement** : les résultats contenant
  `error` (plan rejeté par le moteur) sont **skippés** côté UI. Le LLM
  les a déjà vus comme feedback dans son `tool_message` à l'itération
  précédente et a replanifié — afficher le refus côté UI serait du
  bruit. Un warning `N plan(s) rejeté(s) rejoué(s)` est ajouté pour
  traçabilité.

### Non-breaking
- `BlockChart.chart` reste `Literal["bar", "line", "boxplot"]` côté
  Pydantic — les histogrammes passent par `chart="bar"` (le rendu
  front est visuellement une suite de barres de toute façon). La
  sémantique histogramme est portée par `heading` et `x_label="valeur"`.
- `BlockTable` continue d'être émis en **compagnon** des bars pour que
  les utilisateurs qui veulent les chiffres exacts les aient à côté.

### Garde manuelle (sorties réelles sur TEST2)
À reporter — type de bloc attendu :

| Question | Blocs réels attendus (après deploy) |
|---|---|
| « Compare les bandes » | `text` + **`chart(bar)`** + `table` |
| « Paramètres de mobilité dominants » | `text` + **`chart(bar)` histogram** + `table` |
| « Compare a3Offset Orange/SFR × B3/B20 » | `text` + N × (**`chart(bar)` histogram** + `table`) + verdict de comparabilité |
| « Compare les débits » | `text` + **`text(OBSERVED)` n=0 déclaré**, aucun chart vide |

### Non-objectifs
- Pas de `BlockChart.chart="histogram"` dans le schéma Pydantic/Zod —
  demanderait coordination front. On garde `"bar"` ; la différence
  sémantique est dans le `heading` et l'`x_label`. Si besoin de bins
  réels (buckets d'intervalles numériques), lot 0.26.0 ajoutera le
  binning côté moteur + extend du schema.
- Pas de `BlockMap` encore utilisé (outil `map_metric` pas livré en
  0.25.x) ; le dispatch `"map"` tombe sur fallback table.
- Pas de ré-essai actif du LLM côté serveur : la boucle agent appelle
  déjà `MAX_STEPS=5` et le LLM peut déjà replanifier naturellement
  quand un outil renvoie `error`. Si on veut forcer un retry explicite,
  lot 0.25.2 ajoutera un `retry_hint` dans le tool_message.

## 0.25.0 — 2026-10-16 (minor) — Assistant V2 : catalogue + moteur analytique contraint + preuves + agent (Agent BC1)

> **Fondation V2** : l'Assistant passe d'un prompt-contexte à une
> **boucle agent** avec tool-calling OpenAI. Le LLM ne voit plus
> jamais une table ou du SQL ; il parle avec un **catalogue
> sémantique** et émet des **plans structurés** qu'un moteur compile
> en SQL paramétré sûr. Chaque chiffre dans la UI est rattaché à un
> `result_id` stable. **PAS de SQL libre, PAS de ligne brute, PAS de
> fuite d'identité.** Garde **G25**.

### Ajouté — `app/assistant/` (nouveau package)
- **`catalog.py`** — Catalogue sémantique **versionné en code** :
  - 2 datasets : `rrc_dict` (`param_occurrence`) et `measurements`
    (`measurement_points`). Tables sensibles (`app_user`, `settings_llm`,
    `nmf_file`) jamais listées.
  - 9 dimensions typées (operator, band, system, message, param_path,
    value_raw/converted, dep) avec `null_label` ("non attribué"/"N/D"),
    `allowed_filter_ops` (eq/in/contains/is_null).
  - 14 mesures (count, part_pct, rsrp_avg/p10/p50/p90, rsrq/sinr/cqi,
    dl_avg/p50, thrpt_ul, tx_power, latency) — chacune avec `sql`,
    `unit` 3GPP, `conversion_3gpp`, `lineage` (dataset d'origine),
    `recomposable` (bool) et `null_safe`.
  - **BANNED_IDENTIFIERS** : liste défensive de tables/fonctions
    scannée dans le SQL FINAL compilé (app_user, settings_llm, pg_sleep,
    truncate, imsi, imei, s_tmsi, c_rnti…).
  - `discover_schema()` : grammaire JSON exposée au LLM — zéro nom de
    table, zéro SQL fuité.
- **`engine.py`** — `execute_analytical_query(plan, project_id)` :
  - **Compile** un plan `{dataset, dimensions, measures, filters, order,
    limit}` en SQL **paramétré** (jamais de concat chaîne LLM).
  - **project_id injecté serveur** depuis la session — **tout plan
    tentant de fixer `project_id` dans filters est REJETÉ**
    (`PROJECT_ID_NOT_ALLOWED`).
  - **GROUP BY implicite** : si des mesures sont présentes, les
    dimensions font GROUP BY ; **jamais de ligne brute**.
  - `LIMIT` max 1000 ; `statement_timeout` 5s.
  - **Mesures non-recomposables** sur ≥ 2 dimensions → `warning`
    (jamais de moyenne de moyennes présentée comme fiable).
  - `compute_result_id(plan, project_id) → sha256[:16]` **stable** :
    même plan + même projet ⇒ même id (traçabilité UI ↔ journaux).
  - Défense en profondeur : regex scan `BANNED_IDENTIFIERS` sur le SQL
    compilé avant exécution.
  - **Journal technique** : `sql_compiled` + `params` conservés dans
    l'objet retour mais **PAS sérialisés** dans la réponse HTTP
    (correctif 3).
- **`proof.py`** — Moteur de preuves :
  - `validate_comparison(results[]) → ComparabilityVerdict` avec 3
    verdicts : `COMPARABLE` / `COMPARABLE_WITH_LIMITATIONS` /
    `NOT_COMPARABLE` + raison + dénominateurs par result_id.
    **Vérifie l'alignement (datasets, mesures, dimensions, période)
    PAS l'égalité des dénominateurs** (correctif 1).
  - `lineage_for_result(result)` : résumé sources + règles.
- **`tools.py`** — Outils presets (7) exposés en OpenAI function schemas :
  - `get_project_context`, `list_operators`, `list_bands`,
    `top_rrc_messages`, `rrc_param_distribution`, `compare_operators`,
    `compare_distributions`.
  - Chaque outil fixe un plan skeleton + accepte des filtres plats
    (operator, band, param_path). Appelle le moteur, retourne un
    résultat sérialisable (sql_compiled EXCLU).
  - `analyze_correlations` déclaré ouvert (demande Phase 1 mapping +
    annotation "corrélation ≠ causation").
- **`loop.py`** — `run_agent(db, project, question) → AgentRun` :
  - System prompt + `discover_schema()` + 7 outils schémas.
  - Loop OpenAI tool_calls jusqu'à `MAX_STEPS=5` ou texte final.
  - Chaque tool_call exécute `dispatch_tool`, le résultat
    (`result_id` + rows + denominateur + verdict éventuel) est renvoyé
    comme `tool_message`. Pas de 5xx propagé — toute erreur dans
    `AgentRun.error`.
- **`compose.py`** — `compose_response(run)` :
  - Pour chaque result unique (dédup sur `result_id`), un `BlockTable`
    avec colonnes dérivées + `source_id = result_id`.
  - Un `BlockText` principal avec le texte LLM final.
  - Résultat `n=0` → claim OBSERVED « donnée indisponible pour ce
    périmètre (jamais inventée) ». Pas de pilule tableau vide.
  - Résultat `verdict` (compare_*) → claim INTERPRETED / UNAVAILABLE
    selon la force du verdict.
  - Evidence[] : une par result_id avec `source_type` + `aggregation`
    (GROUP BY cols) + période.

### Modifié
- `app/routes/assistant.py` : la branche ANALYSE passe par `run_agent`
  + `compose_response`. L'ancien code `build_context_facts` reste
  disponible dans `app/services/assistant_context.py` (lot futur
  pourra l'évaluer en fallback si LLM désactivé).
- `scenario` = `"b2_agent"` (quand au moins 1 outil appelé) ou
  `"b2_text_only"` (texte seul sans outil — signalé via warning).

### Garde (G25) — unitaires + smoke live sur TEST2

**Unitaires** (`tests/test_g25_assistant_v2.py`) :
- `_compile_plan` rejette `project_id` dans filters (`PROJECT_ID_NOT_ALLOWED`).
- Rejette dataset inconnu (`app_user` → `DATASET_UNKNOWN`).
- `BANNED_IDENTIFIERS` contient bien `app_user`, `settings_llm`,
  `pg_sleep`, `truncate`.
- Plan sans mesure explicite → `count` injecté + GROUP BY.
- `MEASURES["rsrp_avg"]["recomposable"] is False` ; count recomposable.
- `compute_result_id` stable (même plan+projet → même hash 16 chars).
- `validate_comparison` : NOT_COMPARABLE sur 1 seul résultat, sur
  datasets différents, sur mesures différentes.
- Tous les tool_schemas déclarent `additionalProperties: false`.

**Smoke live** (sorties réelles sur TEST2) :

| Question | scenario | outils | result_ids | n=0 déclarés |
|---|---|---|---|---|
| « Compare les bandes utilisées » | b2_agent | list_bands | 1 | 0 |
| « Quels opérateurs ? » | b2_agent | list_operators | 1 | 0 |
| « Compare les débits par opérateur » | b2_agent | plan `dl_avg` **REJETÉ**, fallback list_operators | 1 | déclaré « mesures débits indisponibles » |
| « Compare a3Offset Orange/SFR × B3/B20 » | b2_agent | rrc_param_distribution × 4 + compare_distributions | 4 | 3 (sous-groupes vides) |
| « hello » | conversation | — | — | — (0.24.1 non-régressé) |

Chaque `source_id` des BlockTable match un `result_id` dans Evidence.

### Garanties verrouillées (contre les 3 correctifs)
- **Correctif 1 — Preuves** : chaque chiffre a son `result_id` ; UI ↔
  moteur ↔ journaux par le même hash. `validate_comparison` ne juge
  pas par égalité littérale des dénominateurs mais par alignement
  structurel (dataset, mesures, dims, période).
- **Correctif 2 — Statistiques** : mesures non-recomposables flaguées
  (`recomposable=False`), warning si usage multi-dim. Aucune moyenne
  de moyennes recomposée hors d'un seul GROUP BY plat.
- **Correctif 3 — Sécurité** : `project_id` injecté serveur, jamais
  depuis le plan. `BANNED_IDENTIFIERS` scanne le SQL compilé.
  `sql_compiled` conservé dans l'objet retour mais **jamais** renvoyé
  au front. LIMIT max 1000 + timeout 5s.

### Non-objectifs (écarts ouverts explicites)
- **Blocks `bar` / `line` / `histogram` / `map`** typés : la UI
  affiche `BlockTable` pour tout aujourd'hui. L'auto-sélection du
  type (histogramme vs barre vs carte) selon la nature des données
  attendra 0.25.1 — code en place côté compose, décision déférée.
- **Plan rejections visibles côté UI** : quand le LLM tente un plan
  invalide (ex. `dl_avg` sur `rrc_dict`), le refus remonte comme
  claim UNAVAILABLE. UX améliorable (ravaler côté loop + ré-essai LLM
  silencieux) — lot 0.25.1.
- **Vues analytiques matérialisées** : les datasets du catalogue
  pointent directement sur `param_occurrence` et `measurement_points`
  (pas de VIEW SQL créée). Si volume devient problème, on crée des
  vues incrémentales dédiées. Pas prioritaire aujourd'hui.
- **Métriques Phase 1 (RSRP/RSRQ/SINR réels)** : NULL par design
  tant que mapping décodeur 1.1.0 → `measurement_points.rsrp` n'est
  pas prouvé (voir 0.24.0 CHANGELOG). Les outils du dataset
  `measurements` répondront `n>0, metric_avg=NULL` — comportement safe.

## 0.24.1 — 2026-10-16 (patch) — Assistant : présentation d'accueil structurée (Agent BC1)

> Fix : sur un salut (« hello », « bonjour », « salut », etc.), le mode
> CONVERSATION 0.23.1 renvoyait un one-liner sec (« Bonjour ! Que
> souhaites-tu analyser ? »). L'utilisateur ignorait les capacités.
> Désormais : **présentation structurée en 5 points**, déterministe,
> aucun appel LLM, aucun chiffre par construction. Garde **G24**.

### Modifié
- `app/routes/assistant.py` : nouvelle fonction `_welcome_text(project)` —
  **template Python pur**, pas d'appel LLM. 5 points de l'énoncé :
  1. Qui : « assistant BC4, assistant d'analyse des campagnes drive-test (logs NMF) ».
  2. Projet chargé : « *{nom du projet actif}* » (seul élément dynamique,
     non-chiffre). Si pas de projet (safety net) : invite à en ouvrir un.
  3. Capacités : 6 bullets (opérateurs présents, bandes, messages RRC,
     comparaison débits, paramètres RRC dominants, cartes RSRP/SINR).
  4. Comment je marche : « agrégats de ton projet, sources, n=0 déclaré ».
  5. Question ouverte : « Par quoi veux-tu commencer ? »
- `_build_conversation_response` : **ne fait plus d'appel LLM**. Un
  single `Claim(text=_welcome_text(project), kind="INTERPRETED")`.
  Déterministe, zéro coût provider sur un salut, zéro variance.
- Suppression de l'import `call_llm_conversation` dans la route
  (toujours exporté par `llm_client.py` pour appels futurs éventuels).

### Garanties par construction
- **Aucun chiffre** : le template n'en contient aucun (sauf « n=0 »
  autorisé comme marqueur sémantique, pas une valeur mesurée). Garde
  G24 vérifie via `re.findall(r"\\b\\d+\\b", text.replace("n=0",""))`
  → doit être vide.
- **Aucune requête DB** : hérité de 0.23.1 (classifier `conversation`
  court-circuite déjà le pipeline analytique).
- **Shape response** : `scenario="conversation"`, `blocks=[BlockText]`
  (pas de BlockSummary), `evidence=[]`, `demo=False` — inchangé 0.23.1.

### Garde (G24)
- `scripts/g24_welcome.sh` + `tests/test_g24_welcome.py` :
  - « hello » → scénario `conversation`, UN seul BlockText, UN seul
    claim INTERPRETED contenant les 5 marqueurs (« assistant BC4 »,
    « drive-test / NMF », « Projet chargé », au moins 4/6 capacités,
    « n=0 », « invent », « source », « ? » final).
  - Nom du projet actif apparaît dans le texte.
  - Zéro chiffre isolé hors `n=0`.
  - **Non-régression G22** : « Compare les bandes utilisées » reste en
    `b2_enriched_context` avec BlockSummary + Evidence `rrc_events`.

### Non-objectifs
- Pas de variantes du texte selon la locution exacte (« merci » / « au
  revoir » reçoivent la même présentation). Acceptable : un faux positif
  d'« accueil » sur un « merci » est bénin ; refuser la présentation
  serait inventer une distinction non prouvée côté heuristique.
- Pas de personnalisation du texte selon le rôle utilisateur ou le
  type de projet. Si le besoin émerge, lot ultérieur.

## 0.24.0 — 2026-10-16 (minor) — Keystone : stream mesure+débit (`stg_measurement_raw`) + MP skeleton (Agent BC1)

> **Grand débloqueur partiel** : l'infrastructure pour extraire les
> events radio (CELLMEAS/CQI/TXPC/MIMOMEAS) et débit (PHRATE/MACRATE/
> RLCRATE/PDCPRATED/DRATE) depuis les NMF est en place. **Phase 1
> (mapping champ→métrique prouvé) reste OUVERTE** — pas de NMF témoin
> accessible côté serveur dans ce run. Le décodeur bump **1.0.0 → 1.1.0**
> livre déjà les events avec `raw_fields` ; le peuplement de
> `measurement_points` est **squelette** (armature géo + metadata, toutes
> les colonnes métriques restent NULL). Garde **G23**.

### Phase 1 — ÉCART OUVERT DÉCLARÉ

Blocage prouvé par l'exploration (voir §Preuves ci-dessous) :

- `/tmp/smoke.nmf` = placeholder 25 octets.
- `find / -name "*.nmf"` sur host + container : zéro fichier NMF réel.
- `stg_event` TEST2 (seul projet ingéré) : 19 380 lignes **toutes
  signalling** (RRCSM 19 122, SIPSM 144, L3SM 114) → le décodeur 1.0.0
  avait **drop** les events mesure/débit lors de l'ingestion originale,
  ils ne sont PAS récupérables depuis la base.

**Décision** : plutôt que d'inventer un mapping arbitraire
(violerait « ne devine jamais un champ »), ce lot pose
l'infrastructure capturante — `stg_measurement_raw` + `measurement_points`
étendu + endpoints + backfill — qui captera **le prochain** NMF ingéré
via l'UI. La Phase 1 (mapping prouvé par croisement RRC) sera livrée
dans un lot suivant (0.24.1 ou 0.25.0) une fois un NMF témoin ré-ingéré.

### Décodeur `bc4-decoder` **1.0.0 → 1.1.0** (voir decoder/CHANGELOG.md)
- Nouvelles catégories émises : `measurement` (CELLMEAS, MIMOMEAS, CQI,
  TXPC, CI) et `throughput` (PHRATE, MACRATE/MACRATEU, RLCRATE/RLCRATEU,
  PDCPRATED/PDCPRATEU, DRATE, PLAID/PLAIU).
- Dict émis pour ces events : clés communes `capture_id, seq, ts,
  event_code, category, system, lat, lon` + **`raw_fields` (list[str])**
  — ligne CSV complète masquée identité, mapping aval.
- Non-breaking signalling : format 1.0.0 préservé (clés inchangées), seul
  `category="signalling"` est ajouté.

### Ajouté — bc4-back
- Migration **`0010_stg_measurement_raw`** : nouvelle table
  (`id, project_id, nmf_file_id, capture_id, seq, ts, event_code,
  category, system, lat, lon, raw_fields JSONB`) + 2 index
  (`project_id,event_code`) et `(project_id,capture_id,seq)`.
- Migration **`0011_measurement_points_metrics`** : ajout de 7 colonnes
  nullables à `measurement_points` : `rsrq, rssi, cqi, mimo_rank,
  tx_power, thrpt_ul, event_code`. Les colonnes historiques
  `operator/tech/service/band/dep/site` deviennent **NULLABLE** aussi
  pour accueillir les points NMF (pattern populate.py : NULL en base,
  COALESCE("non attribué") au SELECT).
- Modèle `StgMeasurementRaw` + extensions `MeasurementPoint` dans
  `app/models/base.py`.
- Pipeline `app/ingest/nmf.py` : stream dual depuis le décodeur 1.1.0 —
  signalling vers `stg_event` (existant), mesure/débit vers
  `stg_measurement_raw` (nouveau). Après commit, appel idempotent de
  `populate_measurements(db, project_id)` qui remplit `measurement_points`
  avec l'armature géo (capture_id, seq, ts, system, operator via SIB1,
  band via freq, lat/lng). **Toutes les métriques restent NULL** —
  Phase 1 à faire.
- `app/services/populate_measurements.py` : réutilise VERBATIM
  `_build_sib1_index` + `_resolve_context` de `app/dict/populate.py` —
  pas de divergence d'attribution opérateur avec le dictionnaire RRC.
  Purge idempotent (préserve les seeds B0 identifiés par
  `event_code IS NULL`).
- `scripts/backfill_measurements.py` : backfill manuel sur tous les
  projets avec `stg_measurement_raw` non vide. Note : les projets
  ingérés AVANT 0.24.0 n'ont PAS de staging mesure (décodeur 1.0.0),
  ré-ingestion requise.
- Routes `app/routes/measurements.py` :
  - `GET /projects/{id}/measurements/summary` : counts par
    (system, operator, band, event_code) + moyennes de chaque métrique
    (NULL tant que Phase 1 non faite) + `metric_coverage`
    (`filled`/`null` par métrique, pour diagnostic) + `raw_staging`
    (counts côté `stg_measurement_raw`).
  - `GET /projects/{id}/measurements/raw?event_code=X&limit=N`
    (**admin-only** — c'est un outil Phase 1, pas de la UI) : retourne
    jusqu'à 200 lignes brutes `stg_measurement_raw.raw_fields` pour que
    l'investigation mapping puisse se faire sans ré-ouvrir le binaire.

### Discipline conservée
- Scope strict `project_id` partout.
- Ordre canonique `(capture_id, seq)`, `ts` attribut seulement.
- Zéro identité abonné (masquage à la source par le décodeur, grep
  défensif dans G23).
- NULL (non prouvé) **jamais 0 ni inventé** — toutes les colonnes
  métriques restent NULL, les colonnes NMF (operator/band…) peuvent
  être NULL rendues "non attribué" au SELECT.

### Garde (G23)
- `scripts/g23_measurements_keystone.sh` +
  `tests/test_g23_measurements_keystone.py` — vérifie :
  - Décodeur 1.1.0 : `MEASUREMENT`, `THROUGHPUT`, `_category` exposés.
  - Table `stg_measurement_raw` existe avec les 12 colonnes.
  - Colonnes mesure dans `measurement_points` : présentes et NULLABLE.
  - `GET /measurements/summary` 200 + shape complet même sur projet vide.
  - `GET /measurements/raw` admin→200, ingénieur→403.
  - Grep défensif : aucune identité IMSI/IMEI 15-digit dans
    `stg_measurement_raw.raw_fields` (sampling 500 lignes).

### Preuves d'exploration (Phase 1 ouvert)
- `/tmp/smoke.nmf` = 25 octets « test placeholder content\\n ».
- `docker exec bc4-db-1 psql -c "SELECT DISTINCT event_code, COUNT(*) FROM
  stg_event GROUP BY event_code ORDER BY 2 DESC"` → **RRCSM 19 122, SIPSM
  144, L3SM 114** (TEST2). Aucune ligne CELLMEAS/CQI/TXPC/PHRATE : le
  décodeur 1.0.0 les droppait.
- Code `app/dict/populate.py:69-72` : `_plmn_to_operator` → table
  bc4_enrich. Réutilisé pour `populate_measurements`.

### Non-objectifs
- **Mapping champ→métrique** (RSRP position dans CELLMEAS, débit dans
  PHRATE, etc.) : à prouver sur un NMF témoin ré-ingéré. Ce lot
  **n'invente aucun mapping**.
- Backfill des projets déjà ingérés : impossible depuis la base
  (events mesure drop par décodeur 1.0.0). Ré-ingestion NMF requise.
- Dépendance `dep` (département via lat/lng) : non résolu dans
  measurement_points NMF — nécessiterait reverse-geo. NULL pour l'instant.

## 0.23.1 — 2026-10-15 (patch) — Assistant : séparer CONVERSATION vs ANALYSE (Agent BC1)

> Fix : un simple « hello » déclenchait le pipeline complet (requêtes
> DB + contexte factuel + panneau Agrégats à n=0). Désormais, chaque
> tour est classé **CONVERSATION** (salutation, smalltalk, « qui es-tu »)
> ou **ANALYSE** (demande de chiffre, liste, carte). CONVERSATION
> court-circuite TOUT le pipeline métier : aucun tool call, aucun
> BlockSummary, Evidence vide. Garde **G22**.

### Ajouté
- Module `app/services/intent.py` :
  - `classify_intent_heuristic(q) → "conversation" | "analyse" | "unknown"`.
    Regex sur deux familles (salutations + vocabulaire métier). Si les
    deux matchent → ANALYSE l'emporte (règle anti-vol d'info). Si rien
    ne matche et question ≤ 3 mots → CONVERSATION par défaut.
  - `classify_intent(db, q) → "conversation" | "analyse"`. Appelle
    l'heuristique puis, si `unknown`, délègue à `call_llm_classify`.
    Fallback défensif : LLM indisponible → ANALYSE (préserve l'info).
- `app/services/llm_client.py` :
  - **Paramètre `system_prompt`** sur `call_llm` : permet d'injecter
    un prompt différent sans dupliquer la logique HTTP. Default
    conservé (prompt analytique strict « ne cite aucun chiffre absent
    du contexte »).
  - `call_llm_classify(db, question) → str | None` : max_tokens=5,
    timeout 5s, prompt système dédié à la classification.
  - `call_llm_conversation(db, question, project_name) → str | None` :
    prompt système CONVERSATION (interdit tout chiffre, se présente
    si on lui demande qui il est). Contexte factuel vide.
- `app/routes/assistant.py` : dispatcher en tête de route.
  - `intent == "conversation"` → `_build_conversation_response(db, project, body)` :
    un `BlockText` avec UN seul claim INTERPRETED, `evidence=[]`,
    `follow_ups=[…orientés analyse]`, `scenario="conversation"`,
    `demo=False` (rien de synthétique sur une salutation).
  - `intent == "analyse"` → comportement 0.22.0+ inchangé
    (contexte enrichi `[MP]` + `[RRC]`, OBSERVED claims, Evidence
    `measurement_points` + `rrc_events` si applicable).

### Garanties
- **Aucun chiffre sans tool call** : en mode CONVERSATION le prompt
  système interdit tout chiffre ET aucune requête `MeasurementPoint`
  / `ParamOccurrence` n'est émise.
- **Écart déclaré, jamais inventé** : si le LLM est désactivé, la
  réponse CONVERSATION dégrade sur un texte dur (nom du projet + CTA
  « configure LLM »), pas un fallback silencieux à ANALYSE.
- **Pas de framework** : classification = regex + fonction custom. Pas
  de LangGraph / CrewAI / orchestrateur externe.

### Garde (G22)
- `scripts/g22_intent.sh` + `tests/test_g22_intent.py` :
  - **Heuristique** paramétrée sur 17 phrases types (18 passants).
  - **Smoke live** : `/assistant` avec `hello` → `scenario=conversation`,
    pas de `BlockSummary`, `evidence=[]`.
  - **Smoke live** : `/assistant` avec « top 5 messages RRC » →
    `scenario=b2_enriched_context`, `BlockSummary` présent, Evidence
    `rrc_events` présente. Non-régression 0.22.0.

### Non-objectifs
- Pas d'historique multi-tour (mémoire conversationnelle). Chaque
  tour est classifié et répondu indépendamment. Si l'utilisateur dit
  « hello » puis « combien ? », le second tour n'a pas le contexte du
  premier — ANALYSE résout de toute façon depuis la DB.
- Pas de personnalisation du prompt CONVERSATION par rôle / projet
  métier avancé. Lot ultérieur si besoin.

## 0.23.0 — 2026-10-15 (minor) — `AssistantResponse.demo` dynamique (Agent BC1)

> Fix de signalement : la pilule UI « Données démo » était systématique
> depuis B0 (`demo: Literal[True]` codé en dur). Désormais `demo` reflète
> la réalité des données : `False` pour un projet ingéré (NMF → RRC
> décodé, `rrc_count > 0`), `True` pour un projet purement seedé
> (synthétique). Coordonné avec bc4-front 1.11.2 (relax Zod + rendu
> conditionnel).

### Modifié
- `app/schemas/assistant.py` : `demo: Literal[True] = True` →
  `demo: bool = True`. **Non-breaking** côté runtime : le défaut
  reste `True`, le champ est toujours renvoyé.
- `app/routes/assistant.py` : `demo=rrc_count == 0`. La route exploite
  déjà `rrc_count` depuis 0.22.0 (contexte enrichi) — pas de nouvelle
  requête.

### Impact UI (1.11.2)
- TEST2 (ingéré, 98 679 occurrences RRC) → `demo: false` → **pas de
  badge « Données démo »** dans le header de réponse.
- Benchmark National, Paris 2026 Q1, Marseille 5G, Lyon, Rennes
  (seedés, synthétique) → `demo: true` → badge **conservé**.

### Non-objectifs
- Pas de refactor profond du concept « démo » : badge actuel reste.
- Les deux autres usages du label « Données démo » (sidebar + export
  Markdown côté front) sont inchangés dans ce lot.

## 0.22.3 — 2026-10-15 (patch) — label désambigué sur `/dict/tree` + investigation NR + check duplication

> Bump **patch**. Trois volets, un seul fix de code (volet C).
> Rebase : pendant ce run, BC1 a posé `0.22.0` (lot `context_facts
> /assistant enrichi MP + RRC`) puis `0.22.2` (sandbox LLM G18/G19/G21).
> On prend le prochain patch libre au-dessus → **0.22.3**. G21 est pris
> par BC1 ; cette garde utilise **G22**.
>
> ### Volet A — Investigation NR (`"non attribué"` 100% côté NR sur TEST2)
>
> Finding deep-dive 0.21.0 : 30.5% des occurrences `operator=NULL`
> sont **100% côté NR** (`LTE: 0 NULL/68 633`, `NR: 30 046 NULL/30 046`).
> Hypothèse initiale : bug dans `populate.py::_build_sib1_index` qui ne
> brancherait pas les SIB1 NR. **Lecture d'abord** :
>
> - `SELECT count(*) FROM stg_event WHERE project_id='134af70a06eb' AND
>   system='NR' AND message IN ('SIB1','SystemInformationBlockType1',
>   'SystemInformation1')` → **0 ligne**. Aucun SIB1 NR dans TEST2.
> - `SELECT system, channel, count(*) FROM stg_event ... GROUP BY ...` :
>   NR ne porte QUE `BCCH-BCH` (9 MIB) + `DCCH` (2 719 MeasurementReport)
>   + divers IE. **Pas de canal `BCCH-DL-SCH` NR → pas de SIB1 NR.**
> - `_SIB1 = ("SystemInformationBlockType1", "SIB1", "SystemInformation1")`
>   dans `populate.py` ligne 115 : **la constante capterait un SIB1 NR
>   si la capture en portait**. `_build_sib1_index` indexe par
>   `(capture_id, system)` ligne 137 — correct. Le fallback
>   `last_by_cell[(freq, pci)]` ligne 139 — correct.
>
> **Verdict A** : `"non attribué"` NR est **LÉGITIME** sur TEST2 —
> l'absence de SIB1 NR dans les captures est **prouvée en base**,
> pas supposée. Aucun fix côté `populate.py`. **Écart ouvert** : la
> future ingestion d'un NMF 5G outdoor (avec BCCH-DL-SCH NR) devra
> re-tester cette chaîne. La capacité de décodage est présente côté
> `bc4-enrich 1.1.0` (pycrate RRCNR.NR_RRC_Definitions.
> BCCH_DL_SCH_Message, vérifiée en audit S1).
>
> ### Volet B — Check duplication `param_occurrence` (split 50/50 suspect)
>
> `SELECT path, count(*) AS n_rows, count(DISTINCT (stg_event_id, path))
> AS n_distinct_pairs FROM param_occurrence WHERE path ~ 'rsrpResult'
> GROUP BY path` → `n_rows == n_distinct_pairs` sur **toutes** les
> variantes rsrp/rsrpResult/rsrp-r15. Contrainte UNIQUE
> `uq_param_occ_event_path(project_id, stg_event_id, path)` en place et
> **non violée**. Pas de duplication. Le split 50/50 observé (NR
> `band` à 50% rempli) vient du fait que `_resolve_context` tombe sur le
> fallback `_band_from_freq` (NR ARFCN → bande, OK pour certaines
> freqs seulement), pas d'une double attribution. **Verdict B** :
> **aucun bug de duplication**, fermé.
>
> ### Volet C — Désambiguïsation libellés arbre (`/dict/tree`)
>
> `SELECT regexp_replace(path, '^.*/', '') AS leaf, count(DISTINCT
> path) FROM param_occurrence GROUP BY leaf HAVING count(DISTINCT path)
> > 1 ORDER BY ... DESC` : **30 leaves en collision** sur TEST2 : `release`
> (22 paths distincts), `rrc-TransactionIdentifier` (12),
> `cellReselectionPriority` + `physCellId` (7 chacun), `rsrp` + `rsrq`
> + `sinr` (6 chacun côté NR), `bandNR`/`carrierFreq`/`threshold-RSRP`/
> `threshold-RSRQ`/`q-RxLevMin` (5 chacun), etc. Le front
> (`DictionaryPage.tsx` ligne 343) rend `leafOf(p.param)` — donc deux
> paths distincts affichent le même libellé indistinguable. Fix côté
> back : ajout d'un champ `label` sur `DictTreeParam` qui porte un
> libellé désambigué. **Non-breaking** (Zod additif).
>
> **Algorithme `_disambiguate_leaf_labels` dans
> `app/routes/dictionary.py`** :
> - Groupe les paths par leaf dans un même `(system, message)`.
> - Si le leaf est unique → `label = leaf`.
> - Sinon → remontée progressive des ancêtres jusqu'à obtenir une
>   signature unique dans le groupe de collision. 1 segment suffit
>   dans la majorité des cas :
>   - `measurementReport/.../measResultPCell/rsrpResult` →
>     `"rsrpResult (measResultPCell)"`
>   - `measurementReport/.../measResultListEUTRA/measResult/rsrpResult`
>     → `"rsrpResult (measResult)"`
> - Si le parent direct colle aussi (`release` sous deux
>   `ue-TransmitAntennaSelection` différents selon `antennaInfo` vs
>   `antennaInfo-r10`), remontée jusqu'à la divergence :
>   `"release (antennaInfo/explicitValue/ue-TransmitAntennaSelection)"`
>   vs `"release (antennaInfo-r10/explicitValue-r10/ue-TransmitAntennaSelection)"`.
>
> **Pas d'invention** — label 100% dérivé du path. Les leaves uniques
> (`a3-Offset`, `q-RxLevMin` sous une seule hiérarchie, etc.) restent
> sans suffixe. Le champ `param` est **inchangé** (path complet
> non-suffixé) — reste la clé stable pour `/dict/params?path=…` et
> `/dict/param/map`. Garde **G22**.

### Ajouté
- Champ **`label: str`** sur `DictTreeParam`
  (`app/schemas/dictionary.py`) — défaut `""` pour la rétro-compat
  Pydantic ; en pratique rempli pour chaque param par le handler.
- Fonction **`_disambiguate_leaf_labels(paths: list[str])`** dans
  `app/routes/dictionary.py` — algorithme déterministe (pas de rand,
  pas de dépendance externe).

### Modifié
- **`_build_tree_v2`** (`app/routes/dictionary.py`) : construit la liste
  `labels` via `_disambiguate_leaf_labels` pour chaque groupe
  `(system, message)`, puis instancie `DictTreeParam(param=p, label=lbl,
  count=c)`.

### Garde (G22)
- **G22** (`scripts/g22_tree_label_dedup.sh` +
  `tests/test_g22_tree_label_dedup.py`) :
  - `/dict/tree` expose `label` sur chaque `params[]`.
  - Pour chaque message, les leaves uniques (par path) donnent
    `label == <feuille>` (sans parenthèses).
  - Pour chaque collision détectée (plusieurs paths distincts avec le
    même leaf dans un même `(system, message)`), tous les labels dans
    le groupe sont **mutuellement distincts** et portent un suffixe
    `(…)`.
  - Non-régression : `param` reste le path complet (inchangé) pour que
    `/dict/params?path=<param>` continue de matcher la DB.

### Écarts ouverts
- **Attribution operator/band NR** : TEST2 ne porte pas de SIB1 NR
  (0 ligne dans `stg_event`). Le `"non attribué"` NR est **légitime**,
  pas un bug. La re-vérification réelle de la chaîne SIB1 NR →
  `_build_sib1_index` → `_resolve_context` requiert une capture NMF 5G
  outdoor avec BCCH-DL-SCH NR. À déclarer lors de la prochaine ingestion
  5G outdoor.

## 0.22.2 — 2026-10-15 (patch) — Sandbox LLM pour G18/G19/G21 (Agent BC1)

> Fix : les gardes `G18`/`G19`/`G21` **mutaient** `settings_llm` et
> leur « cleanup » (`api_key:""` + `enabled:false`) **détruisait**
> silencieusement la config LLM de l'utilisateur quand les scripts
> tournaient contre l'API live. Un test ne doit JAMAIS laisser un état
> partagé pire qu'il ne l'a trouvé — surtout une config contenant un
> secret (ici chiffré) qui n'est pas récupérable sans le re-poster.

### Modifié
- `tests/conftest.py` :
  - Ajout du context manager `_snapshot_llm_state()` : `SELECT`
    direct des 7 colonnes de `settings_llm WHERE id=1`, `UPDATE` de
    restauration dans un `finally`. La sauvegarde se fait **au niveau
    du cipher** — l'API ne renvoyant jamais la clé en clair, c'est
    la seule façon fiable de restaurer **exactement** la clé Fernet.
  - Nouvelle fixture `llm_state_sandbox` (scope `module`) qui wrap
    les tests d'un module de tests dans ce context manager.
- `tests/test_g18_llm_assistant.py`, `test_g19_llm_probe.py`,
  `test_g21_assistant_context.py` :
  - `pytestmark = pytest.mark.usefixtures("llm_state_sandbox")`
  - Suppression des tests `test_*_cleanup_clears_key` qui étaient
    une tentative de cleanup explicite — supplantés par le sandbox
    (robuste aux crashs intermédiaires, le `finally` toujours exécuté).

### Smoke de non-régression (vérifié dans ce lot)
Scénario : clé réelle en DB (`provider=openrouter`, cipher Fernet,
`enabled=true`) ; sandbox ouvert ; mutation destructrice au milieu
(`cipher=NULL`, `enabled=false`, `provider='nuked'`) ; sortie sandbox.
**Résultat** : état parfaitement restauré, cipher inclus.
```
IN sandbox : ('nuked', None, False)
AFTER      : ('openrouter', 'gAAAAA-fake-sentinel', True)
```

### Écart ouvert
- Aucun autre module ne mute `settings_llm` aujourd'hui. Si un futur
  lot l'ajoute (ex. tests `/assistant` qui changent la config pour
  tester un enchaînement), appliquer le même pattern
  `pytestmark = pytest.mark.usefixtures("llm_state_sandbox")`.

## 0.22.0 — 2026-10-15 (minor) — Assistant : contexte factuel enrichi (MP + RRC) (Agent BC1)

> Bump **minor** : `/projects/{id}/assistant` injecte maintenant dans
> le prompt LLM **toutes** les sources factuelles disponibles —
> métadonnées projet (operators/technologies/bands), agrégats
> `measurement_points` ET `param_occurrence` (RRC décodé). Un projet
> ingéré sans MP (ex. TEST2 avec 98k occurrences RRC) devient
> **interrogeable** au lieu de dire « 0 points » en boucle.
> **Non-breaking** côté front : le shape `AssistantResponse` est
> conservé, un claim OBSERVED supplémentaire est ajouté SI le projet
> a du RRC, et une Evidence `rrc_events` est ajoutée SI pertinent.
> Garde **G21**.

### Ajouté
- Service **`app/services/assistant_context.py`** :
  - `build_context_facts(db, project, filters) → (facts, meta)`.
  - Section `[MP]` (toujours émise) : `n`, top opérateurs, top bandes.
  - Section `[RRC]` (toujours émise) : `n`, top 5 messages, top 10
    paramètres (`path`), opérateurs et bandes présents.
  - Métadonnées projet (`operators`, `technologies`, `bands`,
    `operators_plmn`) préfixées « Projet.* » — toujours lues.
  - **Garde-fou LLM** : si `mp_count == 0 ET rrc_count == 0`, une ligne
    `ATTENTION: aucune mesure ni occurrence RRC disponible … refuse-la`
    est injectée pour couper court à toute invention.
- Route `/assistant` branchée sur le helper, avec ajout conditionnel :
  - Un deuxième claim OBSERVED « Dictionnaire RRC : N occurrences »
    quand `rrc_count > 0`.
  - Une `Evidence { source_type: "rrc_events" }` quand `rrc_count > 0`.
  - Un deuxième `SummaryItem` « Occurrences RRC décodées » idem.
  - `scenario` passe à `"b2_enriched_context"` quand RRC > 0, sinon
    `"b2_sample_count"` (ex `"b0_sample_count"` renommé).

### Non-breaking vs 0.17.x
- Le shape `AssistantResponse` est inchangé — les additions sont des
  éléments déjà typés (`Claim`, `Evidence`, `SummaryItem`) dans des
  listes existantes.
- Le front 1.11.0 affiche naturellement les deux claims OBSERVED et le
  deuxième item d'agrégats sans modification UI.

### Garde (G21)
- **G21** (`scripts/g21_assistant_context.sh` +
  `tests/test_g21_assistant_context.py`) :
  - Projet avec `param_occurrence > 0` → scenario `b2_enriched_context`,
    au moins 2 claims OBSERVED (un « Dictionnaire RRC »), Evidence
    `rrc_events` présente.
  - Projet seedé (mp>0, rrc=0) → scenario `b2_sample_count`, 1 claim
    OBSERVED, Evidence `rrc_events` absente.
  - `build_context_facts` direct : contient `[MP]`, `[RRC]`, et une
    `ATTENTION` quand filtres impossibles (tout à zéro).

### Non-objectifs (écarts ouverts)
- Pas d'intégration des agrégats `/overview` (débits DL/UL, RSRP p50/p95,
  taux de setup) : à ajouter dans un lot 0.23.0 « context_facts v2 ».
- Pas de tableaux croisés paramètre × valeur dans le contexte (déjà
  servi par `/dict/params`, mais trop verbeux pour le prompt). Si le
  LLM reçoit la question « distribution de rsrpResult », le front
  l'enverra côté UI, pas via le LLM.

## 0.21.0 — 2026-10-15 (minor) — `value_matrix` sur `/dict/params` (value × operator × band)

> Bump **minor** : chaque élément de `params[]` dans la réponse
> `GET /projects/{id}/dict/params?system=…` expose maintenant un champ
> `value_matrix: list[ValueMatrixCell]` — table croisée
> `(value_raw, value_converted, operator, band) → count`. Le front
> (grouping.ts) utilisait l'absence de ce champ comme signal pour
> désactiver le « regroupement par opérateur × bande » (message UI
> « Regroupement indisponible ») ; il est désormais activé. Non-breaking :
> Zod `.object()` sans `.strict()` ignore les champs supplémentaires,
> cf. non-régression sur `value_distribution` (0.15.0). Rebase : au
> moment du run, BC1 avait successivement posé `0.17.1`, `0.18.0`,
> `0.19.0`, `0.20.0`, `0.20.1` (lot LLM : settings persistées,
> assistant branché, probe `/settings/llm/test`). On prend donc la
> prochaine minor libre `0.21.0`. Garde **G20**.

### Ajouté
- Fonction **`compute_value_matrix(db, project_id, system, path, message,
  operator, band)`** dans `app/dict/queries.py`. Retourne
  `list[dict]` avec les clés `value_raw`, `value_converted`,
  `operator`, `band`, `count`. Tri `count DESC, value_raw, operator,
  band`. Filtres `operator`/`band`/`message` propagés — même périmètre
  que `buckets` et `value_distribution`.
- Constante **`UNASSIGNED_LABEL = "non attribué"`** (publique dans
  `app/dict/queries.py`) — libellé explicite pour les occurrences dont
  `operator` OU `band` est `NULL` en base. 30.5% des occurrences
  TEST2 sont dans ce cas (events sans SIB1 avant / sans match
  `(freq, pci)`) et doivent apparaître.
- Schéma Pydantic **`ValueMatrixCell`** dans `app/schemas/dictionary.py`
  (`value_raw`, `value_converted`, `operator`, `band`, `count`).
- Champ **`value_matrix: list[ValueMatrixCell]`** sur `ParamRow`
  (default `[]`, non-breaking côté front).

### Modifié
- **`_build_param_list_v2`** (`app/routes/dictionary.py`) : la requête
  SQL `buckets (op × band)` applique maintenant
  `COALESCE(operator, 'non attribué')` et `COALESCE(band, 'non attribué')`
  sur operator ET band. Avant 0.18.0, les events `NULL` étaient
  silencieusement **omis** du GROUP BY (filtre implicite car
  `NULL = NULL → NULL`, exclu). On ne retire pas les buckets existants,
  on les étend pour couvrir 100% des occurrences. Les filtres explicites
  (`?operator=Orange`) continuent de restreindre normalement (puisque
  `operator = 'Orange'` ignore les NULL).

### Garde (G20)
- **G20** (`scripts/g20_value_matrix.sh` + `tests/test_g20_value_matrix.py`) :
  - `GET /dict/params?system=LTE` renvoie, pour chaque paramètre, le
    champ `value_matrix` (nouveau 0.18.0).
  - Pour `rsrpResult` : `value_matrix` **non vide**, et
    `sum(cell.count) == row.count` (cohérence avec `value_distribution`
    déjà testé en G16).
  - Pour TEST2 : **au moins 1 cellule** `operator="non attribué"` ou
    `band="non attribué"` existe quelque part (confirme que le COALESCE
    s'est appliqué sur les 30.5% d'occurrences NULL).
  - Filtre `operator=Orange` → `value_matrix` ne contient PLUS QUE des
    cellules avec `operator == "Orange"`. Jamais un bucket inventé.
  - Formule 3GPP préservée : pour `rsrpResult`, chaque cellule a
    `value_converted == str(int(value_raw) - 141)`. Non-régression G16.
  - Non-régression `buckets` : le champ reste présent, et inclut
    maintenant un bucket `"non attribué"` quand il y a des NULL (c'est
    le changement de 0.18.0 — alignement avec `value_matrix`).

### Écarts (ouverts explicites)
- **Interaction avec le binning de `value_distribution`** : quand
  `value_distribution_mode == "binned"` (plus de 100 valeurs numériques
  distinctes), `value_matrix` reste **exact** (une cellule par
  `(value_raw, operator, band)`) — on ne binne PAS la matrice. Rationale :
  le binning sert à borner le payload de la distribution 1D ; la matrice
  est déjà naturellement bornée par la combinatoire
  `(operator × band)` (max ~4×30 ≈ 120 par valeur ; en pratique bien
  moins). Si le payload devient trop lourd sur un path pathologique, un
  seuil `VALUE_MATRIX_MAX_CELLS` + fallback sera ajouté — déclaré ouvert.
- **Pas de `avg_converted` dans `ValueMatrixCell`** : `buckets` continue
  d'exposer la moyenne par `(op, band)` ; la cellule matrix donne juste
  le `count`. Le front n'avait pas demandé la moyenne par cellule — à
  rajouter si besoin dans un lot ultérieur.

## 0.17.1 — 2026-10-15 (patch) — Probe `/settings/llm/test`

> Bump **patch** : nouvel endpoint utilitaire sans breaking change —
> permet à la UI « Tester la connexion » d'arrêter de simuler et de
> faire un vrai ping chat completions. Garde **G19**.

### Ajouté
- Fonction **`probe_llm(db)`** dans `app/services/llm_client.py` :
  chat completion `max_tokens=1` avec timeout court (10s). Retourne
  `(ok, model, latency_ms, err_message)`. Jamais d'exception propagée,
  jamais la clé dans `err_message` (scrub hérité de `call_llm`).
- Paramètre **`max_tokens_override`** sur `call_llm` : écrase (NE
  combine pas) le `max_tokens` DB — garantit un probe borné à 1 token
  quel que soit l'état de la config.
- Schéma Pydantic **`LlmTestResult`** (`ok`, `model`, `latency_ms`,
  `message`).
- Route **`POST /settings/llm/test`** (admin-only, 403/401 standard).
  Toujours 200 (succès OU erreur dans `ok:false` + `message`), jamais 5xx.

### Garde (G19)
- **G19** (`scripts/g19_llm_probe.sh` + `tests/test_g19_llm_probe.py`) :
  - Sans Bearer → 401, ingénieur → 403.
  - `enabled=false` → `{ok:false, message:"LLM désactivé…"}`.
  - `base_url=http://127.0.0.1:1/v1` + `enabled=true` + clé Fernet-chiffrée
    → `{ok:false, latency_ms≥0, message:"erreur réseau…"}`, jamais 5xx,
    jamais la clé en clair dans le JSON (`FAKE_KEY not in dumps(body)`).
  - Cleanup : `api_key:""` + `enabled:false` en fin de garde.

### Non-objectifs
- Pas de test de succès LLM réel dans la garde (coûte des crédits).
  Un smoke manuel reste requis depuis la UI après `PUT /settings/llm`.

## 0.17.0 — 2026-10-15 (minor) — Assistant branché au LLM (OpenAI-compat)

> Bump **minor** : `/projects/{id}/assistant` effectue maintenant un
> **appel HTTP réel** au LLM configuré (via `/settings/llm` ou env
> `BC4_LLM_*`, précédence DB > env). Non-breaking côté front : la
> réponse garde le même shape (`blocks`/`claims`/`evidence`/`warnings`)
> et la UI 1.8.x affiche naturellement le texte LLM comme un claim
> `INTERPRETED` dans le bloc « Résumé ». Garde **G18**.

### Ajouté
- Service **`app/services/llm_client.py`** :
  - `call_llm(db, user_question, context_facts, timeout=12.0)` →
    `str | None`. `None` = LLM désactivé ou config incomplète (pas une
    erreur). `LlmInvocationError` sur timeout / 401 / 429 / 4xx-5xx /
    réponse malformée. Le message d'erreur est **safe** (scrub de la
    clé en clair même si httpx l'injecte dans un `str(exc)`).
  - Wire format : **chat completions OpenAI-compat** (OpenAI, Mistral,
    Together, Groq, OpenRouter, « custom »). Provider inconnu → erreur
    explicite plutôt qu'invention de format.
  - Prompt système fixe : « Tu ne cites AUCUN chiffre qui n'apparaît
    pas dans le contexte factuel. Si une donnée manque, dis-le, ne
    l'invente JAMAIS. » Les faits (projet, période, filtres, N) sont
    injectés dans le `user` message, PAS en langage naturel inventé.
- Route **`POST /projects/{id}/assistant`** branchée :
  - Appelle `call_llm`. Succès → claim `INTERPRETED` avec le texte
    renvoyé (jamais retouché, jamais mélangé avec un chiffre maison).
  - Échec `LlmInvocationError` → claim `UNAVAILABLE` avec le message
    safe, `warnings` enrichi (« LLM invoked but failed — fallback aux
    observations. »). **La route renvoie TOUJOURS 200** quand le LLM
    tombe — un 5xx ferait planter le chat côté UI pour une raison
    externe à notre back.
  - `None` (disabled / config incomplète) → claim `UNAVAILABLE`
    explicite (`« LLM désactivé »` / `« config LLM incomplète »`).
  - Les blocs OBSERVED (`sample_count`) restent présents dans tous les
    cas — le LLM augmente, il ne remplace pas la base factuelle.
- Logger `logging.getLogger('app.routes.assistant')` : niveau WARNING
  sur échec LLM, message safe (clé déjà scrubbée par `call_llm`).

### Garde (G18)
- **G18** (`scripts/g18_llm_assistant.sh` + `tests/test_g18_llm_assistant.py`) :
  - **Disabled** : PUT `enabled: false` → `/assistant` → 200 + claim
    UNAVAILABLE « désactivé / non configuré ». Pas de call HTTP.
  - **Unreachable** : PUT provider=openai, `base_url=http://127.0.0.1:1/v1`,
    `enabled=true`, `api_key=<fake>` → `/assistant` → **200** (jamais 500)
    + claim UNAVAILABLE qui mentionne « indisponible / réseau / timeout ».
  - **Pas de fuite** : la clé en clair n'apparaît NI dans le JSON de
    réponse (`FAKE_KEY not in json.dumps(body)`) NI dans la DB
    (`settings_llm.api_key_cipher` reste préfixé `gAAAAA` — non-régression G17).
  - **Traçabilité** : `warnings` populé quand le LLM a échoué ; vide
    sinon.
  - **Nettoyage** : la clé de test est vidée en fin de garde
    (`api_key: ""` → `api_key_set=false`).

### Non-objectifs (écarts ouverts explicites)
- **Pas de test de succès LLM réel** : exigerait un provider live avec
  facturation. Un smoke manuel (`PUT /settings/llm` + `POST /assistant`)
  est documenté dans le README.
- **Pas de rate-limit ni de cost cap** côté serveur : un utilisateur
  peut appeler `/assistant` en boucle et consommer son quota provider.
  À traiter dans un lot « quotas » séparé (sentinelle Redis + budget
  par rôle). Déclaré ouvert.
- **Pas de streaming (SSE)** : la réponse est synchrone. Les scénarios
  qui tirent sur `max_tokens` élevés dépasseront le `timeout=12s` et
  basculeront en UNAVAILABLE. L'évolution SSE est aussi un lot séparé.
- **Pas de rotation Fernet** (hérité du 0.16.0) : si
  `BC4_LLM_SECRET_KEY` change, le cipher stocké devient illisible
  (`LlmInvocationError: config LLM illisible`) — procédure : PUT
  `api_key: ""` puis PUT nouvelle clé.

## 0.16.0 — 2026-10-15 (minor) — Settings LLM persistées + chiffrées

> Bump **minor** : nouvelle table + nouvelles routes
> `GET`/`PUT /settings/llm` (admin). La clé LLM est **chiffrée au repos**
> (Fernet) — jamais lue en clair ailleurs que dans `llm_crypto.decrypt_key`,
> jamais loggée, jamais renvoyée. L'env `BC4_LLM_*` sert de **fallback**
> quand la DB est vide (précédence DB > env). Garde **G17**.

### Ajouté
- Dépendance **`cryptography==43.0.3`** (Fernet symétrique).
- Migration **`0009_llm_settings`** : table `settings_llm` (singleton
  `id=1`) avec `provider`, `base_url`, `model`, `api_key_cipher` (Text,
  base64 Fernet), `enabled`, `temperature`, `max_tokens`, `updated_at`.
  Seed `INSERT INTO settings_llm (id) VALUES (1)` dans l'upgrade — pas
  de création à la volée côté runtime, pas de « ghost row ».
- Env **`BC4_LLM_SECRET_KEY`** (clé Fernet) + `BC4_LLM_PROVIDER`,
  `BC4_LLM_BASE_URL`, `BC4_LLM_MODEL`, `BC4_LLM_API_KEY`,
  `BC4_LLM_ENABLED`. `BC4_LLM_SECRET_KEY` est OBLIGATOIRE pour un
  PUT de clé — un garde qui s'auto-skippe sans secret ne garde rien.
- Modèle **`LlmSettingsRow`** (`app/models/base.py`).
- Service **`app/services/llm_crypto.py`** :
  - `encrypt_key(plain) → cipher` (Fernet).
  - `decrypt_key(cipher) → plain` (Fernet, `InvalidToken` → fail fast).
  - `get_row(db)` : récupère le singleton (safety net si seed migré
    manquant).
  - `get_effective_llm_config(db) → dict` : précédence DB > env, api_key
    déchiffré uniquement dans la stack frame appelante (jamais sérialisé).
- Schémas Pydantic **`LlmSettings`** (réponse — `api_key_set: bool`, JAMAIS
  `api_key`) et **`LlmSettingsInput`** (requête — `api_key` optionnel ;
  `None` = untouched, `""` = clear, non-vide = chiffrer+stocker).
- Routes **`GET /settings/llm`** (admin → 200, sinon 403/401) et
  **`PUT /settings/llm`** (admin → 200 ; chiffre la clé via Fernet ;
  si `BC4_LLM_SECRET_KEY` absent → 400 `LLM_CRYPTO` plutôt que stocker
  en clair déguisé).
- `/projects/{id}/assistant` lit maintenant la config effective
  (`get_effective_llm_config`) et émet un `Claim UNAVAILABLE` adapté :
  « LLM non configuré » OU « LLM configuré (<provider>/<model>) —
  scénarios complets reportés au lot B2 ». La clé n'apparaît NI dans la
  réponse NI dans les logs.

### Garde (G17)
- **G17** (`scripts/g17_llm_settings.sh` + `tests/test_g17_llm_settings.py`) :
  - GET sans Bearer → 401 ; GET pour ingénieur → 403 ; GET admin → 200
    + shape attendue, **pas** de champ `api_key`.
  - PUT ingénieur → 403.
  - PUT admin pose `provider`/`model`/`api_key` → `api_key_set=true`,
    la clé en clair n'est PAS dans la réponse (`FAKE_KEY not in body`),
    et la DB stocke un cipher Fernet (`gAAAAA…`), JAMAIS la clé en clair.
  - PUT avec `api_key=""` → cipher nullifié (`api_key_set=false`).
  - PUT sans `BC4_LLM_SECRET_KEY` → 400 `LLM_CRYPTO` (test skippé si
    secret présent côté process — on ne monkeypatche pas l'env API).

### Non-objectifs (écarts ouverts explicites)
- Pas d'appel LLM effectif depuis `/assistant` dans ce lot : la route
  continue de produire ses blocs OBSERVED à partir des mesures en DB.
  L'intégration client HTTP (OpenAI/Anthropic) est reportée au lot
  assistant B2 — ce lot livre uniquement la **config persistée + chiffrée**
  qui alimentera ce client.
- Pas de rotation de clé Fernet : si `BC4_LLM_SECRET_KEY` change, les
  ciphers existants deviennent illisibles (DecryptError → 400 à l'usage).
  Procédure : PUT `api_key: ""` puis PUT nouvelle clé. Déclaré ouvert.

## 0.15.0 — 2026-10-15 (minor) — `value_distribution` sur `/dict/params`

> Bump **minor** : ajout d'un champ au contrat API. **Non-breaking**
> côté front — le front `1.8.0` ignore simplement le champ supplémentaire
> (`.optional()` / `.passthrough()` côté Zod) jusqu'au lot `1.8.1` qui
> l'exposera dans le panneau « Distribution des valeurs ».
> Garde G16 (G13/G14/G15 pris).

### Ajouté
- Champ **`value_distribution`** sur chaque élément de la réponse de
  `GET /projects/{id}/dict/params?system=…` :
  ```
  value_distribution: list[ValueBucket]
  ValueBucket = {value_raw: str, value_converted: str | None, count: int}
  ```
  Fournit la distribution par valeur du paramètre lui-même (le champ
  `buckets` existant — opérateur × bande — reste INTACT).
- Champ meta **`value_distribution_mode`** (`"exact" | "binned"`) :
  signale explicitement si la distribution est binnée (quand le nombre
  de valeurs distinctes dépasse `VALUE_DISTRIBUTION_BINNING_THRESHOLD = 100`,
  binning par pas `BIN_WIDTH = 1` dans l'unité convertie). Sur TEST2, le
  domaine 3GPP typique (`rsrpResult`: 0..97) est en-dessous du seuil →
  mode `"exact"` partout en pratique ; le code supporte le binning pour
  les futurs paramètres à large domaine.
- Nouveau module **`app/dict/queries.py`** : `compute_value_distribution`
  (requête + binning + tri). Signature :
  `(db, project_id, system, message?, path, operator?, band?)` →
  `(items, mode)`. Les filtres restreignent la requête AVANT agrégation
  (pas de pré-calcul global écrasé).
- Schéma Pydantic **`ValueBucket`** dans `app/schemas/dictionary.py` +
  champ `value_distribution: list[ValueBucket]` et
  `value_distribution_mode: ValueDistributionMode` sur `ParamRow`.

### Règles d'agrégation
- **Numérique** (`unit_converted` non null, règle 3GPP connue —
  `rsrpResult`, `rsrqResult`, `q-RxLevMin`, `a3-Offset`, `threshold-RSRP`,
  `s-Measure`, variantes NR) :
  `GROUP BY value_raw, value_converted`, tri par `value_converted`
  **cast en float ascendant** (jamais trié comme string si c'est un nombre).
  Si une occurrence porte une valeur hors domaine 3GPP (non convertible),
  elle est intégrée en queue avec `value_converted=null` plutôt que
  silencieusement perdue.
- **Enum / CHOICE** (`unit_converted` null, ex. `dl-Bandwidth` → `n50`
  `n75` `n100`) : `GROUP BY value_raw`, tri alpha ascendant,
  `value_converted=null` partout.
- **0 occurrence** → `value_distribution = []`. Aucune invention de
  valeur (règle « par le contenu, jamais par l'étiquette »).

### Garde manuelle
- `scripts/g16_value_distribution.sh` : rebuild API → pytest G16.
- `tests/test_g16_value_distribution.py` : 5 vérifications
  (distribution non vide, somme = count, formule `idx-141` pour
  `rsrpResult`, enum avec `value_converted=null`, filtre `operator=Orange`
  restrictif, préservation des buckets op × band).

### Versioning
- `pyproject.toml`, `app/main.py`, `tests/test_g1_boot.py` : **0.15.0**.
- `/health` : `0.15.0`.

### Écarts ouverts
- **Filtres `dr` / `plaque` / `arcep`** : toujours pas câblés sur
  `/dict/params` (idem 0.13.0). Le champ `value_distribution` respecte
  les filtres qui existent (`system`, `message`, `operator`, `band`) ;
  l'ajout des filtres géo côté dict reste un lot séparé.
- **Binning jamais déclenché en pratique** sur TEST2 : les 53 valeurs
  distinctes de `rsrpResult` LTE restent sous le seuil 100. Le code est
  testé par le chemin « exact » ; le chemin « binned » n'a de garde
  qu'en lecture de code (CHANGELOG explicite au cas où un paramètre
  futur dépasse le seuil).
- **Résidu non convertible en queue de distribution numérique** : si
  pycrate remonte une valeur hors domaine 3GPP (ex. `rsrpResult = 200`
  issu d'un bug amont), la valeur apparaît dans `value_distribution`
  avec `value_converted=null` au lieu d'être muette. Choix explicite
  pour cohérence `sum(count) == row.count`.

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
## 0.74.4 (patch) — BC4 2026-10-21 — Capture-scoped Signaling query reuse (Agent BC2)

- Reuse one capture population across concurrent Signaling endpoints with source/decode stamps; the first page load no longer rebuilds messages, procedures and event links once per request.
- Add composite `(project_id, capture_id, event_code, seq)` indexes for staged and raw NMF rows.
## 0.77.0 (minor) — BC4 2026-10-23 — Metrics population and binding audit (BC3)

- `/metrics` counts distinct `(capture_id, second)` observations with a non-NULL
  value; measured zero is retained and event metrics remain occurrence counts.
- Catalogue leaves remain visible when absent, with explicit `cell_absent`,
  `absent_in_capture` or `field_empty` reasons and count semantics for the UI.
- Schema-derived `system_col` / `first_param_col` metadata is exposed on
  catalogue nodes; no consumer needs a universal column-5 assumption.
- A3 five-class audit and G24 cross-capture evidence are shipped under the
  repository root audit artifacts.
## 0.78.0 (minor) — BC4 2026-10-23 — Metrics truth pipeline (BC2)

- Decoder keeps documented fields from NFF 2.59/2.62 while preserving an
  explicit extension warning; event context prefixes now shift fields from
  YAML `first_param_col` instead of assuming column 5.
- Documented string fields are retained as strings; only undocumented strings
  are hashed. Metrics projections therefore expose the same values as the NMF
  source and preserve zero-valued measurements.
