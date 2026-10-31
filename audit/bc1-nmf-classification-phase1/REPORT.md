# BC1 — NMF decoder coverage phase 1

Date: 2026-10-31. Branche: `bc1/nmf-classification-phase1`.

## Périmètre et décision

Le changement ne décode aucun nouveau champ. Il affine uniquement les records
que l'adaptateur externe produit avec `category=other`, pour 25 types radio/KPI
déjà connus du schéma profond. Toute catégorie amont plus précise est conservée.
La structure et les champs restent explicitement `not_asserted`; NFF 2.59 reste
non certifié, car la preuve disponible s'arrête à NFF 2.50. Les layouts
variables PLAID/PLAIU et DCI/MACI ne sont pas modifiés.

## Classifieur externe observé

Commande:

```bash
nl -ba /home/devmat/BC4/decoder/bc4_decoder.py | sed -n '108,142p;486,506p'
python3 - <<'PY'
import ast
p='/home/devmat/BC4/decoder/bc4_decoder.py'
t=ast.parse(open(p).read(),p)
for n in ast.walk(t):
    if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='_CAT_BY_CODE' for x in n.targets):
        d=ast.literal_eval(n.value)
        print('EXTERNAL_CODES',len(d))
        for k,v in sorted(d.items()): print(k,v)
PY
```

Le fichier courant 2.1.0 contient 14 clés: CELLMEAS, CMDREQ, CQI, DAA, DREQ,
DSUMMARY, GPS, L2SM, L3SM, LOCK, MACSM, RRCSM, SIPSM et TXPC. L'affirmation
«13 codes» du rapport de référence n'est donc pas reproductible avec
l'artefact présent. Sur les trois témoins, 12 de ces codes sont observés;
L2SM et MACSM sont absents. Cet écart est déclaré, sans modifier l'artefact
externe non versionné.

## Classification ajoutée

- `throughput`: DRATE, MACRATE, MACRATEU, PDCPRATED, PDCPRATEU, PHRATE,
  PHRATEU, PPPRATE, RLCRATE, RLCRATEU.
- `measurement`: BSR, CI, CSI, DCI, MACI, MIMOMEAS, NLIST, PCHI, PLAID,
  PLAISUM, PLAIU, PMI, SCELL, SCELLMOD, TAD.

## Mesures complètes

Le garde G57 relit intégralement les trois fichiers avec
`bc4_decoder.py` 2.1.0, retire uniquement `category` de l'empreinte du payload,
puis compare avant/après:

```text
TOTAL_RECORDS=420243
BEFORE_OTHER=326707
AFTER_OTHER=16795
RECLASSIFIED=309912
DECODED_VALIDATED=0
NFF_259_UNCERTIFIED=309912
KPI_INPUT_DIFF=0
G57 VERDICT=PASS
```

Commande:

```bash
docker run --rm -e BC4_DSN=postgresql+psycopg://bc4:unused@127.0.0.1:1/bc4 \
  -e BC4_JWT_SECRET=unit-test-secret-not-production \
  -v "$PWD:/app" -v /home/devmat/BC4/decoder:/decoder:ro \
  -v /home/devmat/BC4/artifacts/witness-nmf:/witness:ro -w /app \
  bc1-nmf-classification:test env PYTHONPATH=/app \
  python scripts/guards_2026_10/G57_nmf_classification.py \
  --decoder /decoder/bc4_decoder.py /witness/ikea_26Jun10_172354.2.nmf \
  /witness/ikea_26Jun10_172354.6.nmf \
  /witness/parcours_26Jun10_155941.8.nmf
```

La pile jetable a restauré le dump de référence, puis importé les trois témoins
dans le projet candidat `faecb40a8e37`. Le job
`bb98d480c6174ad389b766f3d33586dc` termine avec `status=done`, trois fichiers
terminés et zéro fichier en erreur. Les nombres par capture sont:

| capture_id | total | other après |
|---|---:|---:|
| a4b0c321c52e | 383294 | 15953 |
| daa2b1df250d | 21242 | 397 |
| ecffb18dbd7f | 15707 | 445 |

La somme retrouve 420243 records et 16795 `other`. Les 25 types ciblés sont
tous présents sous leur nouvelle catégorie: 140271 `measurement` et 169641
`throughput`, soit 309912 records reclassés.

Commande de mesure (lecture seule):

```sql
SELECT capture_id,
 (SELECT count(*) FROM stg_event_raw r WHERE r.project_id='faecb40a8e37'
  AND r.capture_id=c.capture_id)
 +(SELECT count(*) FROM stg_event e WHERE e.project_id='faecb40a8e37'
  AND e.capture_id=c.capture_id) AS total,
 (SELECT count(*) FROM stg_event_raw r WHERE r.project_id='faecb40a8e37'
  AND r.capture_id=c.capture_id AND r.category='other') AS other
FROM nmf_capture c WHERE project_id='faecb40a8e37' ORDER BY capture_id;
SELECT category,count(*) FROM stg_event_raw
WHERE project_id='faecb40a8e37' GROUP BY category ORDER BY category;
```

Empreintes avant/après, après exclusion de `project_id` et des identifiants
techniques propres à chaque import; pour `stg_event_raw`, `category` est aussi
exclue car c'est l'unique champ volontairement modifié:

| table | lignes par projet | SHA-256 référence = candidat |
|---|---:|---|
| stg_event_raw | 399449 | `6cb5fce1ac406c6cba42c362e04edd60adde9ff241bb67d4c5366a1c309a263e` |
| stg_event | 20794 | `31d23e3f7726f82e6822ce03205efe7604a9518e921e604f47eb0784b81d08e0` |
| nmf_event_light | 233718 | `aa8fb543acb35c8941db338d2886511eeedcfe0723ac2011a35d4ba7e934b5b1` |
| nmf_cell_second | 1664775 | `95c2e564c03f8caa30e379101ef2e8f8446ca94101a42538647c750f70b24a41` |
| nmf_metric_value | 2130540 | `9bbdfb0c9a83dbf5bee4f0d454fc1453acfcf147fa934f718d1654bb537396cf` |

Forme exacte de la commande d'empreinte:

```bash
docker exec bc1-nmfclass-db psql -U bc4 -d bc4 -qAtc \
 "COPY (SELECT (to_jsonb(t)-'project_id')::text FROM nmf_metric_value t
  WHERE project_id='<project>' ORDER BY capture_id,seq,code) TO STDOUT" \
 | sha256sum
```

La même forme est appliquée aux quatre autres tables, avec l'ordre canonique
`capture_id,seq` ou `capture_id,second` imposé par leur contrat. Conclusion:
`KPI_DIFF=0` par empreinte exhaustive, pas par échantillon.

## Tests et gardes

Tests ciblés:

```bash
docker run --rm -e BC4_DSN=postgresql+psycopg://bc4:unused@127.0.0.1:1/bc4 \
  -e BC4_JWT_SECRET=unit-test-secret-not-production -v "$PWD:/app" -w /app \
  bc1-nmf-classification:test pytest -q \
  tests/test_nmf_classification_phase1.py tests/test_decoder_1_9_0_plaiu.py
```

Résultat: `6 passed`, zéro test sauté.

Gardes complètes:

- G36: 112342292 Ko disponibles, seuil 20971520 Ko, PASS.
- G46: PASS sur les trois témoins; zéro colonne précédemment peuplée vidée.
- G48: PASS sur les trois témoins. Le parcours produit 1545800 lignes cellule,
  1545800 clés uniques et zéro doublon; tous les totaux par type sont égaux.
- G57: PASS; payloads hors catégorie identiques et totaux de couverture exacts.

Commandes G46/G48 (les trois chemins complets ont été passés, sans SKIP):

```bash
python scripts/guards_2026_10/G46_decoder_column_retention.py --nmf <témoin>
python scripts/guards_2026_10/G48_cell_second_uniqueness.py \
  --nmf /witness/ikea_26Jun10_172354.2.nmf \
  --nmf /witness/ikea_26Jun10_172354.6.nmf \
  --nmf /witness/parcours_26Jun10_155941.8.nmf
```

La finalisation jetable a exposé une transaction `idle in transaction` pendant
un calcul Python entre deux étapes du pipeline existant. Elle s'est terminée
normalement. Cet écart de durée de transaction est déclaré hors périmètre de ce
lot de classification; aucune production n'a été touchée.

## Version et verdict

- Back: 0.119.0, MINOR.
- Décodeur profond: 1.9.0, inchangé.
- Adaptateur externe: bc4-decoder 2.1.0, inchangé.
- Contrat de classification interne: 1.0.0.

Le déploiement est interdit avant validation indépendante Codex67. Aucun
DEPLOY_LOCK n'a donc été pris et aucune action de production n'a été faite.

VERDICT: PASS, prêt pour validation indépendante Codex67; NON DÉPLOYÉ.
