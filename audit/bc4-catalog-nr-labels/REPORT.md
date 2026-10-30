# BC4 — Catalogue 2.58.0, libellés LTE/NR

## Périmètre et règle

Le classement de système ne lit jamais le libellé. Il utilise :

- `event` (`CELLMEAS` ou `MIMOMEAS`) ;
- `field_system=7|9` quand la section NFF est explicite ;
- sinon `cell_type` selon les enums NFF 2.50 propres à l'événement.

La release ajoute `label_system` pour tracer cette décision sans modifier le
champ fonctionnel `field_system`. Le front n'est pas modifié.

## Audit 2.57.0 par contenu

Commande reproductible :

```bash
python scripts/catalog/audit_nr_labels.py \
  --catalog app/kpi/catalog_release/catalog_2.57.0.json \
  --spec-zip /home/devmat/BC4/specs/nff_2.50_pack.zip
```

La jointure est `(event, field_system, field_no)` vers le paramètre du CSV NFF,
pas une comparaison de libellés. Paramètres exposés dans les deux systèmes :

| Event | Paramètre NFF | LTE field | NR field | Feuilles LTE | Feuilles NR |
|---|---|---:|---:|---:|---:|
| CELLMEAS | #Params/cell | 3 | 4 | 5 | 5 |
| CELLMEAS | Band | 5 | 7 | 5 | 5 |
| CELLMEAS | PCI | 7 | 9 | 5 | 5 |
| CELLMEAS | RSRP | 9 | 12 | 5 | 5 |
| CELLMEAS | RSRQ | 10 | 13 | 5 | 5 |
| CELLMEAS | RSSI | 8 | 15 | 5 | 5 |
| MIMOMEAS | Band | 3 | 6 | 5 | 9 |
| MIMOMEAS | PCI | 5 | 8 | 5 | 9 |
| MIMOMEAS | Port | 6 | 4 | 5 | 9 |
| MIMOMEAS | RSRQ/P | 9 | 11 | 5 | 9 |
| MIMOMEAS | RSSI/P | 8 | 13 | 5 | 9 |

La même commande donne les quatre collisions visuelles de 2.57.0 :
`Measured system @ SCell 1`, `2`, `3` et `4` sous `ev_mimomeas`, chacune
portée par une feuille LTE et une feuille NR.

La spec NFF 2.50 définit pour NR `Measurement type: 1=SSB, 2=CSI-RS`.
Le catalogue statique utilise donc `RSRP (NR)` plutôt que le seul
`SS-RSRP` : ce dernier serait faux pour une mesure CSI-RS. Le suffixe système
reste explicite et le paramètre NFF original est conservé.

## Artefact et conservation

Préparation hors base :

```bash
python scripts/catalog/bootstrap_catalog_release.py \
  --from 2.57.0 --to 2.58.0 --transform nr-labels --prepare-only
sha256sum app/kpi/catalog_release/catalog_2.58.0.json
```

```text
relabeled=270 lte=110 nr=160 duplicate_labels=0
sha256=e871335d334210d4f9e69a529631fa2e3941bcbf02ce977de783cf8b6e900bf7
database_write=FALSE
```

Conservation des feuilles :

```bash
python - <<'PY'
import json
a=json.load(open('app/kpi/catalog_release/catalog_2.57.0.json'))
b=json.load(open('app/kpi/catalog_release/catalog_2.58.0.json'))
x={n['node_id'] for n in a['nodes'] if n.get('node_type')=='leaf'}
y={n['node_id'] for n in b['nodes'] if n.get('node_type')=='leaf'}
print(len(x),len(y),len(x-y),len(y-x))
print('VERDICT', 'PASS' if x==y else 'FAIL')
PY
```

Sortie : `7713 7713 0 0`, `VERDICT PASS`.

## Unicité visuelle et gardes

```bash
python scripts/catalog/audit_nr_labels.py \
  --catalog app/kpi/catalog_release/catalog_2.58.0.json \
  --spec-zip /home/devmat/BC4/specs/nff_2.50_pack.zip \
  --expect-unique
```

Sortie : `duplicate_parent_label_groups=0`, `VERDICT=PASS`. Cela couvre tout
l'arbre et donc également les blocs répétés `#Variables` et
`CCE aggregation`.

G36, avant la pile de preuve :

```text
free_gib=184.28 threshold_gib=20 verdict=PASS
G36_EXIT=0 VERDICT=PASS
```

Tests dans le runner jetable `bc4a4-catalog-tests`, réseau
`bc4a4-catalog-net`, avec DSN/JWT de test et sans conteneur DB :

```text
18 passed
BC4A4_CATALOG_TESTS exit=0 VERDICT=PASS
```

La préparation a également été rejouée dans `bc4a4-catalog-prepare` avec le
conteneur DB volontairement absent : exit 0, SHA avant/après identique et
`database_write=FALSE`. Aucune activation catalogue n'a été exécutée.

## SemVer

- catalogue : **MINOR 2.58.0** ;
- back proposé : **MINOR**, numéro attribué par BC3 ;
- front : aucun changement.
