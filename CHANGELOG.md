# bc4-back — CHANGELOG

Versions SemVer. Type de bump: `patch` / `minor` / `major`. Un écart se ferme ou se déclare ouvert, jamais expliqué par hypothèse.

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
