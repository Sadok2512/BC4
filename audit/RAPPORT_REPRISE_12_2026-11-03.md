# RAPPORT — REPRISE 12 régressions catalogue 2.66.0

**Date** : 2026-11-03
**Agent** : Agent BC5
**Session** : `[bc4]`, projet Test_6 `43e81a34a073`

---

## VERSIONS live post-REPRISE 12

```
back        : 0.128.1  (patch — fixes 4 points REPRISE 12)
front       : 1.134.0  (inchangé)
catalogue   : 2.66.1   (patch — restaure 10 leaves perdues + NR reparent)
              sha ab1cb101c7e28fb221d25a5d2297e3f7479e3469a8ce804e14d8d2a1f7ee21e9
décodeur    : 1.11.1   (patch — fix enum JSON clés string)
alembic     : 0091_scell_nr_cols
```

Image : `bc4-api:0.128.1-65e3da7`.

---

## § 1 — NR VIDÉ (fermé)

**Cause** : les 13 feuilles PSCell NR (`plaid_prbs @nr-type-199`, `plaid_mcs0`, `plaiu_prbs`, `plaiu_mcs0`, `macrate_mac_dl_bitrate`, `macrateu_mac_ul_bitrate`, `cqi_rank`, `cqi_wb_cqi_0`, `dci_ul_grants`, `dci_dl_grants`, `cell_rsrp`, `cell_rsrq`, `cell_sinr`) étaient parentées sous les events `ev_plaid`, `ev_cellmeas`, etc. — tous dans la branche LTE. Les variantes @nr-type-* héritaient donc du parent LTE.

**Fix fichier:ligne** :
- `app/kpi/metrics_catalog_v4.py:913-980` — pré-pass qui crée les events NR miroirs `ev_X_nr` sous des catégories NR miroirs (`cat_NR_allocation_mcs`, `cat_NR_throughput_per_layer`, `cat_NR_link_quality`, `cat_NR_serving_radio`, `cat_NR_signalling`) pour tout event dont au moins une leaf a `field_system=9`. Redirection des leaves BAKED.
- `app/kpi/metrics_catalog_v4.py:1282-1298` — même redirection pour les leaves DYNAMIC.

**Garde par capture (NR with values)** :

| capture | 2.66.0 | 2.66.1 | ≥ 2.65.2 ? |
|---|---|---|---|
| Test_6 (a4b0) | 2 | **82** | ✓ (≥ 2.65.2) |
| ikea.6 (daa2) | 2 | **65** | ✓ |
| ikea.2 (ecff) | 2 | **55** | ✓ |

Preuve CSV live : les 13 feuilles PSCell NR sont rangées sous NR avec les valeurs correctes :
```
plaid_prbs@nr-type-199           tech=NR  parent=ev_plaid_nr    n=1796/2/79
plaid_mcs0@nr-type-199           tech=NR  parent=ev_plaid_nr    n=1796/2/79
plaiu_prbs@nr-type-199           tech=NR  parent=ev_plaiu_nr    n=1741/5/106
plaiu_mcs0@nr-type-199           tech=NR  parent=ev_plaiu_nr    n=1741/5/106
macrate_mac_dl_bitrate@nr-type-199  tech=NR parent=ev_macrate_nr n=2852/13/107
macrateu_mac_ul_bitrate@nr-type-199 tech=NR parent=ev_macrateu_nr n=2852/13/107
cqi_rank@nr-type-199             tech=NR  parent=ev_cqi_nr      n=2835/12/106
cqi_wb_cqi_0@nr-type-199         tech=NR  parent=ev_cqi_nr      n=2835/12/106
dci_ul_grants@nr-type-199        tech=NR  parent=ev_dci_nr      n=2852/13/107
dci_dl_grants@nr-type-199        tech=NR  parent=ev_dci_nr      n=2852/13/107
cell_rsrp@nr-type-199            tech=NR  parent=ev_cellmeas_nr n=2940/15/108
cell_rsrq@nr-type-199            tech=NR  parent=ev_cellmeas_nr n=2940/15/108
cell_sinr@nr-type-199            tech=NR  parent=ev_cellmeas_nr n=2919/14/108
```

---

## § 2 — NON-PERTE 2.65.2 → 2.66.1 (fermé)

**Cause** : `scripts/catalog/patch_2_66_0.py:71-88` retirait `tech_Other` complet, supprimant 10 leaves légitimes avec valeurs :

| metric_id | n Test_6 | ex-parent 2.65.2 |
|---|---|---|
| chi_max_tx_power | 632 | ev_chi_other (tech_Other) |
| luf_luf_status | 1 | ev_luf |
| luf_old_lac | 1 | ev_luf |
| tua_tau_type | 45 | ev_tua |
| tuf_emm_cause | 1 | ev_tuf |
| tus_mcc | 41 | ev_tus |
| tus_mnc | 41 | ev_tus |
| tus_tac | 41 | ev_tus |
| rrre_re_est_cause | 3 | ev_rrre |
| rrre_re_est_status | 3 | ev_rrre |

**Fix fichier:ligne** : `scripts/catalog/patch_2_66_1.py` — depuis 2.66.0, restaure les 5 events réseau légitimes (`ev_luf`, `ev_lua`, `ev_lus`, `ev_tua`, `ev_tuf`, `ev_tus`, `ev_rrre`, `ev_sei`) sous `cat_IP_network_events`, et les leaves `chi_*` sont fusionnées dans `ev_chi_lte` (branche LTE > Signalling).

**Garde** (Python build pour Test_6 2.65.2 vs 2.66.1) :
```
2.65.2 with_values Test_6: 413
2.66.1 with_values Test_6: 413
Diff: 0   ← perte zéro
```

Côté CSV live : 463 with_values (vs 462 avant REPRISE 12).

---

## § 3 — ÉCARTS LTE/NR serving (réfuté)

**Les 4 935 et 2 940 cités en REPRISE 11 §3 n'étaient pas des régressions**. Ils proviennent du query `app/kpi/metrics_catalog_v4.py:356-371` :

```sql
SELECT s.event_code, i.system, i.cell_type AS raw_cell_type, s.metric_code,
       COUNT(DISTINCT (s.capture_id, s.seq_first, i.cell_arfcn, i.cell_pci)) AS n
FROM nmf_cell_second s
JOIN nmf_cell_identity i ON i.project_id=s.project_id AND i.capture_id=s.capture_id
   AND i.seq=s.seq_first AND i.event_code=s.event_code AND i.cell_index=s.cell_index
WHERE s.project_id=:pid AND s.event_code='CELLMEAS'
GROUP BY ...
```

Résultat live sur Test_6 CELLMEAS :
```
LTE_PCELL (cell_type=0, system=7) : 4 935 cell_pci / 4 935 cell_ch / 4 935 cell_rsrp
NR_PSCELL (cell_type=199, system=9) : 2 940 cell_pci / 2 940 cell_ch / 2 940 cell_rsrp
```

Les 4 857 / 2 875 reportés en REPRISE 11 §3 venaient d'un query naïf **sans dedup identity** sur `nmf_cell_second` directement (counts bruts `cell_index=1003` ou `9670`). Le catalog utilise la version avec dedup. **Pas de régression — mon rapport REPRISE 11 §3 cite le mauvais chiffre pour la mesure "catalog"**.

---

## § 4 — RRC 181/451 → 187/445 (OUVERT, expliqué)

**Cause fichier:ligne** :
- `app/nmf_decoder/schemas-2.50/CHI.yaml:33` — changement `agg: "last" → "dominant"` (REPRISE 8 Point 3, pour label KPI_CATEGORICAL propre côté catalog).
- `app/nmf_decoder/light.py:46` — tie-breaker dominant : `min(freq, key=lambda v: (-freq[v], v))` → en cas d'égalité de fréquence, **la plus petite valeur numérique l'emporte** → Idle (1) prime sur Connected (2).

**Mécanisme** : pour 6 buckets `(seq, dimension)` ayant 2+ records avec états mixés `{Idle, Connected}` (freq {1:1, 2:1}), l'ancien `agg='last'` retournait la valeur du dernier record ajouté (souvent Connected), le nouveau `agg='dominant'` retourne la plus petite valeur (Idle). Net : +6 Idle, -6 Connected.

**Byte-level ground-truth** sur Test_6 fichier `b45c82572ca1421f.nmf` (218 Idle + 728 Connected = 946 CHI LTE raw records, bucketés en 632 light) :

6 records bruts du fichier (lignes extraites, col 6 = chi_rrc_state) :
```
L43   : CHI,15:59:42.267,,7,70003,1,75,1675,195,107575889,6209,23.0,,1,,...  col6=1 (Idle)
L105  : CHI,15:59:42.748,,7,70003,2,75,1675,195,107575889,6209,23.0,4,1,,... col6=2 (Connected)
L142  : CHI,15:59:43.258,,7,70003,2,75,1675,195,107575889,6209,23.0,4,1,,... col6=2 (Connected)
L1509 : CHI,16:00:00.886,,7,70003,2,75,1675,195,107575889,6209,23.0,4,1,,... col6=2 (Connected)
L1723 : CHI,16:00:03.351,,7,70003,1,75,1675,195,107575889,6209,23.0,,1,,...  col6=1 (Idle)
L1810 : CHI,16:00:04.643,,7,70003,1,75,1675,195,107575889,6209,23.0,,1,,...  col6=1 (Idle)
```

**Spec NFF 2.50 p.326 (CHI Parameters for LTE #2 — RRC state)** :
```
RRC state   Integer   RRC state
  1 = Idle
  2 = Connected
```

**Déclaration** : OUVERT. L'écart s'explique par la convention d'agrégation nouvelle (`dominant`) et le tie-breaker favorisant la valeur numérique minimale. 2 options pour fermer :
- (A) Revenir à `agg: "last"` sur chi_rrc_state : retour à 181/451, mais perte du kind KPI_CATEGORICAL propre.
- (B) Documenter 187/445 comme nouvelle référence post-REPRISE 8 : conserver `agg: "dominant"` qui est sémantiquement correct pour un enum (le "mode" statistique) et noter que les valeurs 1.10.5 étaient dépendantes de l'ordre d'insertion arbitraire du bucket.

---

## § LIVRABLE

**Artefacts** (`/home/devmat/BC4/`) :
- `export_test_6_final.csv` — 4 265 lignes, catalog 2.66.1
- `export_test_6_with_values.csv` — 463 lignes
- `export_ikea_6_with_values.csv` — 332 lignes

Partition par branche (CSV live 2.66.1) :
```
CAPTURE          27 feuilles
IP / Services   425 feuilles
LTE           3 541 feuilles  (vs 3 714 en 2.66.0 : 173 leaves @nr-type-* migrées vers NR)
NR              270 feuilles  (vs 58 en 2.66.0 : +212 leaves NR miroirs)
```

Partition **avec valeurs** par capture (CSV live) :
| capture | CAPTURE | LTE | NR | IP / Services |
|---|---|---|---|---|
| Test_6 | 26 | 282 | **82** | 42 |
| ikea.6 | 26 | 221 | **65** | 20 |
| ikea.2 | 26 | 234 | **55** | 20 |

**Commits REPRISE 12 pushés** :
- `65e3da7` fix(catalog): NR reparent dynamic + restore 10 lost leaves (0.128.1, 2.66.1)
- `f54eb68` chore(deploy): pin bc4-api 0.128.1-65e3da7

— Agent BC5
