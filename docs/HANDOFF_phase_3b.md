# HANDOFF — Phase 3a + 3b (feat/bc3-metrics-v3 mergé en main)

Clos par BC3 le 2026-10-25 ~14:00Z. DEPLOY_LOCK libéré, repris par BC1
(frontend Map workspace 1.108.0) à 14:18Z.

## Livré

- Back **0.80.1** sur main (d98fb83) : `/metrics` enveloppe
  `catalog_release` + `decoder_version` + `reason` ; catalogue
  **2.50.5** `is_current=TRUE` (5115 node_ids uniques pour 5115
  feuilles, sha256 `87fb0d13…`).
- Front **1.107.0** sur main (62c7799) : MetricsCatalogSidebar lit
  l'enveloppe, pied "Catalog 2.50.5 · Decoder 1.6.0", arbre Technology
  → Catégorie → Métrique → Feuilles cellule, case "Active only", badge
  PER CELL, feuilles `selectable=false` grisées + tooltip reason.
- Guards stricts : G25 PASS (0 orphans, 0 dup_node_ids, 0 dup_metric_codes),
  G18b PASS (15/15 projets divergent=0, dup_cache=0, dup_fresh=0, mode=v4),
  G24 PASS (re-count LIVE sur 134af70a06eb, 271 cols, false_zeros=0).
- PNG `artifacts/phase3b-tree-lte-nr.png` : arbre LTE déplié (8 catégories)
  + NR déplié (vide, dette n°1) + SHARED/OTHER repliés + pied visible.

## Dette ouverte (3 lignes)

1. **Dette n°1 — NR 0 feuille + PDSCH sans @cell_type en 2.50.5.** Pas un
   dérivé de 2.2b. Le catalogue cible = `catalog_release` **2.50.4 spec
   validée** = 7 feuilles par métrique cellule (PCell, SCell1–4, PSCell,
   SCell NR) pour LTE et NR. Prochain lot = **catalogue 2.51.0** avec ces
   feuilles exigées, G25/G18b/G24 stricts, PNG `PDSCH cw0 · PCell` et
   `SS-RSRP · SCG PSCell` sur une capture **NR UE** (pas scanner). Pas de
   démarrage ce soir.

2. **Dette n°2 — patch manuel `status draft→ready` sur `nff_sample_26` et
   `test_1_6_26`**, exécuté hors Alembic pour débloquer `/projects`
   (ValidationError Pydantic literal `['ready','processing','failed']`).
   UPDATE exact rejouable collé ci-dessous, transmis à BC1 pour arbitrage
   (élargir enum `ProjectSchema.status` ou corriger les 2 lignes
   proprement). **À partir de maintenant : plus aucune écriture manuelle
   en base hors Alembic.** La ligne de code effective :

   ```sql
   UPDATE projects SET status='ready' WHERE status='draft';
   -- Impactées : nff_sample_26, test_1_6_26
   ```

3. **Pas de variante (b).** Un PNG sur une autre feuille (ex.
   `pdsch_bitrate` sans @cell ou `ofdmscan_ss_rsrp` scanner) ne prouve pas
   la feuille demandée. PNG #2 et #3 restent BLOQUÉS tant que 2.51.0
   n'est pas livré. Pas de contournement cosmétique.
