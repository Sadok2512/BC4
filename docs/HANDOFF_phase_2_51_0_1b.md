# HANDOFF — Phase 2.51.0 1b (reprise après audit 1a)

Ouvert par BC3 le 2026-10-25 ~14:35Z. Lock relâché. Audit 1a livré sur
branche `feat/bc3-catalog-2.51` (pas encore mergé en main).

## État actuel

- Branche `feat/bc3-catalog-2.51` locale (bc4-back), **non pushée**.
- 5 YAMLs NR créés dans `app/nmf_decoder/schemas/` : CELLMEAS_NR,
  MIMOMEAS_NR, TAD_NR, TXPC_NR + PHRATE encore à refacto.
- Audit par contenu validé (toutes valeurs ∈ plage spec sur témoins
  LTE 4b7bfd50ddb6/44621571bccc et NR UE 134af70a06eb/723547b196b3).
- Convention validée : `cN = 3 + field_no` = `yaml_col = 4 + field_no`,
  Measured system fixe à c3, LTE et NR.

## Scope restant 1b (ordre d'exécution impératif)

### 1. Decoder 1.7.0 — modifs Python

- `app/nmf_decoder/light.py`
  - **SUPPRIMER** `txpc_cell_type()` (hack 2.62 `index=-2` + clamp 0-4
    FAUX pour NR, confirmé par audit 1a : NR expose 101, 108, 117, 199).
  - **SUPPRIMER** la ligne `if r.event_code=='TXPC':b['cell_type']=
    txpc_cell_type(r)` dans `Light.add()`.
  - **SUPPRIMER** `cell_type=txpc_cell_type(r)` dans `dimensions()`.
  - **AJOUTER** boucle sur `s.get('groups',[])` dans `dimensions()`
    pour extraire `cell.type` des cells group (CELLMEAS, MIMOMEAS) :
    chaque record devient N buckets Light, un par (cell_type, meas_type)
    distinct. ARCHITECTURAL — `Light.add(r)` doit émettre plusieurs
    buckets au lieu d'un.
  - Alternative plus simple : rester en 1 bucket par record mais
    exposer les cells comme un list[dict] dans `b['per_cell']`, puis
    au stockage DB (`store.py`) exploser en lignes `nmf_event_light`
    par cell_type. Évite de toucher `Light.add` directement.

- `app/nmf_decoder/schemas/PHRATE.yaml`
  - Refacto en **dispatch conditionnel** par c4 (`Ph. ch. type`) :
    - `c4=1` (PBCH) : 3 fields, cell_type #3 → c7
    - `c4=2` (PDSCH) : 12+ fields, cell_type #8 → c12 ← CIBLE PNG #2
    - `c4=3` (PUSCH) : 2 fields, cell_type #2 → c6
    - section « Parameters for NR » : 4 fields, cell_type #3 → c6
  - Marquer `dimension: true` sur chaque cell_type.

### 2. Sentinelles out-of-range → NULL + compteur (BC3 add 1)

`app/nmf_decoder/decoder.py:181-186` déjà NULLe out-of-range via
`ValueError('range')`. **Ajouter** un compteur global `r.range_violations`
`dict[code → int]` incrémenté dans le `except`. Puis à la fin du redécode,
dumper les compteurs dans un log `exports/decoder_1_7_0_sentinels.log` et
copier le top-20 dans `CHANGELOG_DECODER.md` section « Sentinelles
rencontrées ».

Liste sentinelles connues de l'audit :
- `CELLMEAS NR cell.band = 99999` (observé c10 sur 723547b196b3)
- `CELLMEAS NR cell.pci = 99999` (par cascade LTE YAML sur NR data)
- autres à découvrir au redécode.

### 3. Colonnes FF 2.62 non documentées (BC3 add 2)

Noms déjà posés dans YAMLs 1a :
- `MIMOMEAS NR` : `mimomeas.params_per_measurement` (header c6), `cell.extra_1` (c18), `cell.extra_2` (c19)
- `TAD NR` : `tad.scope` (c4, FF 2.62 motif)
- `CELLMEAS NR` : fields #16-18 undoc à nommer `cell.rsrp_fil`, `cell.rsrq_fil`, `cell.sinr_fil` ou `cell.extra_N` selon lecture PDF

Dans catalog 2.51.0, chaque feuille `extra_N` ou `*_fil` doit sortir avec
`selectable=false` + `reason="FF 2.62 non documenté 2.50 — nommage par
contenu BC3 2026-10-25"`. Tableau à collecter dans `HANDOFF_phase_2_51_0_1b.md`
(section « Table FF 2.62 non documenté » à remplir au redécode).

### 4. G28 pré-catalogue (BC3 add 3)

`scripts/guards_2026_10/G28_ranges_corpus.py` existe déjà. Le modifier
pour :
- Tourner automatiquement à la fin du nohup redécode (hook dans
  `scripts/catalog/redecode_corpus.py`)
- FAIL = SORTIR en erreur, bloquer le build catalogue
- Lister explicitement colonne + valeur + capture + seq pour chaque hit

Puis `scripts/catalog/build_catalog.py` doit vérifier `G28_VERDICT PASS`
avant d'écrire la ligne `catalog_release`. **Sans PASS, pas de 2.51.0 is_current=TRUE.**

### 5. Redécode nohup

- Script : `scripts/catalog/redecode_corpus.py` existe. Filtrer sur
  `kind='ue'` (LTE+NR), ignorer scanners (déjà bons).
- 94 captures corpus → ~15 UE LTE + ~5 UE NR = ~20 captures (vérifier)
- Nohup avec PID + log collés dans HANDOFF.
- ETA 30-60 min selon taille.

### 6. Catalogue 2.51.0

- `scripts/catalog/build_catalog.py --version 2.51.0 --decoder-min 1.7.0`
- 7 feuilles @cell_type par métrique cellule (PCell, SCell 1-4, PSCell, SCell NR 100+)
- `selectable` seulement si la colonne existe en base + cell_type observé
  dans Light. Gris + raison sinon.
- `node_id` unique garanti (post-processeur comme 2.50.5 → 2.50.6
  si besoin).
- CHANGELOG_CATALOG ajout 2.51.0.

### 7. Gardes stricts

- G25 (orphans + dup) — rejouer
- G18b (parité multiset) — rejouer
- G24 (recount LIVE) — rejouer sur 134af70a06eb ET 723547b196b3
- G28 (plages physiques) — DÉJÀ passé en #4
- G29 (fichier vs DB) — rejouer sur les 2 témoins

### 8. PNG

- #2 `PHRATE PDSCH bitrate 0 · PCell` sur `4b7bfd50ddb6/44621571bccc` :
  métrique = `phrate_pdsch_bitrate_0`, filtre `cell_type=0` + Ph. ch. type=2
- #3 `CELLMEAS NR RSRP meas type 1 · cell type 199` sur `134af70a06eb/723547b196b3` :
  métrique = `cellmeas_rsrp`, filtre `cell_type=199 AND meas_type=1`
- Arbre NR non vide : vérifier avec `shot_metrics_sidebar.ts`

Script `scripts/shot_metrics_sidebar.ts` sur front, adapter pour
pointer les métriques spécifiques + sélectionner les captures témoins.

### 9. Merge sous lock

- Prendre lock BC3
- Merger `feat/bc3-catalog-2.51` → main (back + front)
- Rebuild api + front
- /health collé = `0.81.0` (bump minor pour PHRATE refacto + NR support)
- Front : `1.108.0` ou plus (BC1 a 1.108.0 Map ; coordonner)
- CHANGELOG ×3 : main.CHANGELOG.md (0.81.0), CHANGELOG_CATALOG.md (2.51.0),
  CHANGELOG_DECODER.md (1.7.0)
- Libérer lock

## Audit 1a — artefacts à ne pas perdre

Collés dans conversation précédente (sorties par event, valeurs ∈ plage).
Les 5 YAMLs NR sont committés sur `feat/bc3-catalog-2.51`.

## Blockers connus

1. **Light.add() split per-cell** = refactor architectural. Deux
   options proposées (émission multi-bucket OU éclatement à
   `store.py`). Impact tests existants à évaluer.
2. **bc4_decoder externe** (Rust/Python) : relis les YAMLs d'un chemin.
   À vérifier qu'il voit `CELLMEAS_NR.yaml` et `MIMOMEAS_NR.yaml` sinon
   le dispatch `systems: [9]` n'opère pas. `app/nmf_decoder/schema.py`
   gère-t-il la sélection par `system` ?
3. **Dette replay-chain** encore ouverte (dette 0.79.0 commit `b3e1ce3`
   HANDOFF `docs/replay_chain_0044.patch`) — orthogonal à ce lot mais
   à mentionner si on touche aux tests.

— Agent BC3
