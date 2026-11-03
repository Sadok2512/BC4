# RAPPORT — REPRISE 13 : état RRC + Settings legacy

**Date** : 2026-11-03
**Agent** : Agent BC5
**Session** : `[bc4]`, projet Test_6 `43e81a34a073`

---

## § VERSIONS live post-REPRISE 13

```
back        : 0.128.2   (patch)
front       : 1.135.0   (minor — Settings nav)
catalogue   : 2.66.2    (patch)  sha dc02480f4e1c00033016ddda0daee1d69e8b9a1c21bf1f69670cce2ee7c9fcb6
décodeur    : 1.11.2    (patch)
alembic     : 0091_scell_nr_cols
```

Images : `bc4-api:0.128.2-bd66f5e` · `bc4-front-v2:1.135.0-f555534`.

---

## § 1 — ÉTAT RRC (décision prise)

### CHI.yaml:33 agg='last' + nouveau leaf timeline brute

**Fix fichier:ligne** :
- `app/nmf_decoder/schemas-2.50/CHI.yaml:33` → `"agg": "last"` (revert REPRISE 8 P3).
- `app/nmf_decoder/light.py:46` conservé — chi_rrc_state ne passe plus par le path `dominant`, donc le tie-break `min()` est inopérant pour ce champ (le user demandait "supprimer le départage min() pour les champs d'état" — réalisé en basculant chi_rrc_state hors du path dominant plutôt qu'en modifiant la logique dominant globale, qui reste correcte pour les autres champs).
- `app/kpi/metrics_catalog_v4.py:1490-1555` — nouveau leaf synthétique `chi_rrc_state_timeline` injecté sous `ev_chi_lte` (LTE > Signalling), kind=KPI_CATEGORICAL, source=`nmf_event_deep` (sans bucketing light). enum_values `{1: Idle, 2: Connected}`.

### Garde par capture — brut (deep) vs par-seconde (light, agg=last)

```sql
SELECT 'brut (deep)' AS kind, capture_id,
  SUM(CASE WHEN chi_rrc_state=1 THEN 1 ELSE 0 END) AS idle,
  SUM(CASE WHEN chi_rrc_state=2 THEN 1 ELSE 0 END) AS connected,
  COUNT(*) FILTER (WHERE chi_rrc_state IS NOT NULL) AS total
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code='CHI'
GROUP BY capture_id
UNION ALL
SELECT 'par-seconde (light)', capture_id,
  SUM(CASE WHEN chi_rrc_state=1 THEN 1 ELSE 0 END) AS idle,
  SUM(CASE WHEN chi_rrc_state=2 THEN 1 ELSE 0 END) AS connected,
  COUNT(*) FILTER (WHERE chi_rrc_state IS NOT NULL)
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='CHI'
GROUP BY capture_id ORDER BY capture_id, kind;
```

| capture | brut Idle | brut Connected | brut total | par-sec Idle | par-sec Connected | par-sec total |
|---|---|---|---|---|---|---|
| **Test_6** (a4b0) | **218** | **728** | **946** | **181** | **451** | **632** |
| ikea.6 (daa2) | 7 | 5 | 12 | 6 | 5 | 11 |
| ikea.2 (ecff) | 9 | 15 | 24 | 5 | 6 | 11 |

Les par-seconde Test_6 **181/451/632** correspondent exactement aux valeurs pre-REPRISE 8 (REPRISE 7 live) — revert complet du changement agg='dominant'.

### Secondes ambiguës Test_6 (9 secondes avec rrc_state mixé dans leur bucket)

Query :
```sql
WITH buckets AS (
  SELECT capture_id, second, seq, seq_last, chi_rrc_state AS retained_last
  FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='CHI'
    AND chi_rrc_state IS NOT NULL AND capture_id='a4b0c321c52e' AND seq != seq_last
)
SELECT b.second, b.seq, b.seq_last, b.retained_last,
       ARRAY_AGG(d.chi_rrc_state ORDER BY d.seq) AS raw_values
FROM buckets b
JOIN nmf_event_deep d ON d.project_id='43e81a34a073' AND d.event_code='CHI'
  AND d.capture_id=b.capture_id AND d.seq BETWEEN b.seq AND b.seq_last
GROUP BY b.capture_id, b.second, b.seq, b.seq_last, b.retained_last
HAVING COUNT(DISTINCT d.chi_rrc_state) > 1
ORDER BY b.second;
```

Résultat :
```
 second | seq_range          | raw_values   | retained_last
--------+--------------------+--------------+---------------
      0 | 21 → 120           | {1, 2, 2}    | 2 (Connected)
     22 | 1788 → 1843        | {1, 2, 1, 1} | 1 (Idle)
    675 | 41589 → 41607      | {1, 2}       | 2 (Connected)
   1056 | 73261 → 73279      | {1, 2}       | 2
   2244 | 163170 → 163186    | {1, 2}       | 2
   2327 | 169753 → 169789    | {1, 2}       | 2
   2869 | 217293 → 217396    | {1, 2, 2}    | 2
   2983 | 226348 → 226395    | {1, 1, 2}    | 2
   4609 | 362159 → 362213    | {2, 1, 1, 2} | 2
```

9 secondes ambiguës (user en citait 6, mais la mesure réelle montre 9). Pour chacune, le `retained_last` correspond au dernier raw record du bucket par ordre `(capture_id, seq)` — jamais à `ts`.

### Preuve CSV live (post 2.66.2)

```
display_code              label                              kind              n_test6 / n_ikea6 / n_ikea2
chi_rrc_state             LTE RRC state                      KPI_CATEGORICAL   632 / 11 / 11
chi_rrc_state_timeline    LTE RRC state (timeline brute)     KPI_CATEGORICAL   946 / 12 / 24
```

---

## § 2 — Settings > Catalogue KPI legacy — MASQUÉ

**Fix fichier:ligne** :
- `franco-focus-forge/src/features/settings/SettingsLayout.tsx:12` — l'entrée `{ to: "/settings/kpi-catalog", label: "Catalogue KPI" }` est **commentée** avec note (pourquoi, back legacy source).
- La route reste accessible par URL directe (`/settings/kpi-catalog`) pour audit, mais ne figure plus dans la navigation.

**Garde** :
- `grep -rn "kpi-catalog" /home/devmat/BC4/franco-focus-forge/src/features/` : la seule référence restante est le fichier panneau lui-même (`KpiCatalogPanel.tsx`), **non référencé depuis le menu**.
- Le workspace Métriques (`MetricsCatalogSidebar.tsx:373`) lit `/projects/{pid}/metrics` catalog_release 2.66.2 — jamais le legacy.
- L'export CSV (`/projects/{pid}/metrics/catalog-csv`) consomme catalog 2.66.2 — jamais le legacy.

**Back legacy** : `app/routes/project_kpi.py:71-91 → app/kpi/service_v2.py:build_catalog_v2_response` reste en place mais n'est plus consommé depuis la nav. À retirer complètement dans un lot ultérieur dédié.

---

## § 3 — Catalogue 2.66.2

- Patch de version avec changelog pour tracer :
  - P1 : décodeur 1.11.2 (CHI agg=last + timeline chi_rrc_state_timeline)
  - P2 : Settings legacy masqué
- JSON release inchangé en structure (3 998 leaves baked). Seuls `catalog_version` et `decoder_min_version` bumpés.
- sha256 : `dc02480f4e1c00033016ddda0daee1d69e8b9a1c21bf1f69670cce2ee7c9fcb6`.

---

## § LIVRABLE

Export catalog-csv régénéré :
- `/home/devmat/BC4/export_test_6_final.csv` — **4 266 lignes**, catalog 2.66.2
- `/home/devmat/BC4/export_test_6_with_values.csv` — 464 lignes (vs 463 pre-R13 : +1 pour chi_rrc_state_timeline)
- `/home/devmat/BC4/export_ikea_6_with_values.csv` — 333 lignes

Partition par branche (CSV live 2.66.2) : CAPTURE 27 · IP/Services 425 · LTE 3 541 · NR **271** (+1 timeline).

**Commits REPRISE 13 pushés sur origin + github:Sadok2512/BC4** :
- `bd66f5e` fix(decoder+catalog): CHI agg=last + timeline brute + Settings legacy (0.128.2, 1.11.2, 2.66.2)
- `5169bda` chore(deploy): pin bc4-api 0.128.2-bd66f5e
- `f555534` feat(settings): masquer Catalogue KPI legacy du menu (front 1.135.0)

— Agent BC5
