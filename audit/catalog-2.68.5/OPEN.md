# OPEN — catalogue simplifié 2.68.5

Ces écarts restent explicitement non sélectionnables. Aucun zéro n'est publié
comme mesure et aucune famille de remplacement n'est déduite d'un libellé.

- `LTE_THP_UL_MAC` : **OPEN — MACRATEU LTE non décodé pour la sélection certifiée**. La définition simplifiée reste sans famille à `app/kpi/simple_tree.csv:14`; le schéma déclaratif MACRATEU commence à `app/nmf_decoder/schemas/MACRATEU.yaml:1`, mais ne constitue pas une preuve de lignes décodées dans les captures courantes.
- `LTE_BLER_UL` : **OPEN — MACRATEU LTE non décodé pour la sélection certifiée**. La définition simplifiée reste sans famille à `app/kpi/simple_tree.csv:19`.
- `LTE_THP_DL_PDCP` et `LTE_THP_UL_PDCP` : **OPEN données vides**. Familles déclarées à `app/kpi/simple_tree.csv:11` et `app/kpi/simple_tree.csv:16`; leurs groupes sont décrits à `app/nmf_decoder/schemas/PDCPRATED.yaml:95` et `app/nmf_decoder/schemas/PDCPRATEU.yaml:95`, sans ligne non nulle prouvée dans le périmètre courant.
- `LTE_CQI_WB` : **OPEN données vides**. Famille `cqi_wb_cqi@n` à `app/kpi/simple_tree.csv:29`; le schéma LTE CQI commence à `app/nmf_decoder/schemas/CQI.yaml:1`.
- `LTE_PUSCH_TX_POWER` : **OPEN données vides**. Famille `txpc_pusch_tx_power@n` à `app/kpi/simple_tree.csv:37`; champ source déclaré à `app/nmf_decoder/schemas/TXPC.yaml:13`.

La preuve chiffrée est produite exclusivement par
`scripts/guard_simple_tree.py`, qui colle sa requête avant les résultats par
capture.
