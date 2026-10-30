# BC1 — map-cell-links

Branche `bc1/map-cell-links`. Pile jetable uniquement :
`bc1-map-cell-links-db` / `bc1-map-cell-links-api`. Aucune écriture en
production.

## Contrat et règle de preuve

- Voisine : identité `nmf_cell_identity` au `seq` exact du point, toujours
  filtrée par `(project_id, capture_id)`.
- Ancre NR : PSCell NR (`system=9`, `cell_type=199`) dans la même seconde de
  capture que le point LTE ; elle n'est exposée que si le lien serving LTE est
  lui-même prouvé.
- `cell_ref.earfcn` contient actuellement une clé de bande (700, 800, 1800,
  2100, 2600, 3500), pas le canal brut. Le canal NMF est conservé dans
  `arfcn`, sa normalisation 3GPP est exposée dans `reference_channel`.
- Correspondance : système + bande + PCI, puis candidat géographique le plus
  proche. Rayon maximal exposé : `max_distance_m=25000`. Au-delà : aucun lien.
- Confiance : `radio_band_pci_unique` si le référentiel n'a qu'un candidat ;
  sinon `radio_band_pci_nearest_within_25000m`.

## Commandes et résultats

G36 avant création de la pile :

```text
$ python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
G36_DISK path=/ free_bytes=174498516992 free_gib=162.51 threshold_bytes=21474836480 threshold_gib=20 verdict=PASS
```

Restauration et migration :

```text
$ docker exec bc4-db-1 pg_dump -U bc4 --no-owner --no-acl bc4 | docker exec -i bc1-map-cell-links-db psql -v ON_ERROR_STOP=1 -U bc1map -d bc1_map_cell_links
$ docker run --rm --network container:bc1-map-cell-links-db ... alembic upgrade head
INFO ... Running upgrade 0075_decoder_1_9_0_plaiu -> 0076_map_cell_links
$ docker exec bc1-map-cell-links-db psql ... -Atc "SELECT version_num FROM alembic_version; SELECT count(*) FROM cell_ref; SELECT count(*) FROM nmf_cell_identity WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e';"
0076_map_cell_links
458211
58605
```

Appels HTTP dans l'image de branche, projet `43e81a34a073`, capture
`a4b0c321c52e`, code `cell_rsrp@lte-type-0`, `max_points=5000` :

```text
$ docker exec -e PYTHONPATH=/app -e BC4_API_BASE=http://127.0.0.1:8000 -e BC4_PROOF_PROJECT_ID=43e81a34a073 -e BC4_PROOF_CAPTURE_ID=a4b0c321c52e -e BC4_PROOF_USER_ID=adm-be45f070eba8 -e BC4_JWT_SECRET=<secret-jetable> bc1-map-cell-links-api python audit/bc1-map-cell-links/measure.py
```

```text
series include_map=false status 200 seconds 3.685 bytes 1127292
series include_map=true  status 200 seconds 3.621 bytes 3792835
series content_sha_without_map 5e277c34...2658c 5e277c34...2658c identical True
series map_points 4935 serving 1 neighbour_points 0 neighbour_links 0 nr_anchor 0

table include_map=false status 200 seconds 12.543 bytes 987414
table include_map=true  status 200 seconds 14.988 bytes 3652957
table content_sha_without_map 30a0bed8...2c85 30a0bed8...2c85 identical True
table map_points 4935 serving 1 neighbour_points 0 neighbour_links 0 nr_anchor 0
```

Les temps froid/chaud ci-dessus ne sont pas comparés : leur ordre diffère. La
preuve retenue ici est le statut, le contrat et l'identité du contenu hors
`map_points`.

Inventaire des ambiguïtés du référentiel, obtenu par `GROUP BY` des identités
physiques de la capture puis `LEFT JOIN cell_ref` sur système/bande/PCI :

```text
$ docker exec -i bc1-map-cell-links-db psql -U bc1map -d bc1_map_cell_links -f - < audit/bc1-map-cell-links/ambiguities.sql
```

```text
LTE: identities 382 | no_candidate 75 | unique_candidate 8 | ambiguous_candidates 299 | min 0 | max 14
NR PSCell: identities 29 | no_candidate 6 | unique_candidate 7 | ambiguous_candidates 16 | min 0 | max 9
```

Résolution sur les points rendus : **0** ambiguïté résolue, car aucun candidat
n'est dans le rayon de 25 km. Ce zéro ferme l'écart par le contenu : produire
un lien aurait été une invention.

## Cinq vérifications manuelles

Commande : CTE `picked` sur cinq identités voisines distinctes, position GPS
`previous-or-same seq`, puis candidat `cell_ref` le plus proche par distance
sphérique. Sortie :

```text
$ docker exec -i bc1-map-cell-links-db psql -U bc1map -d bc1_map_cell_links -f - < audit/bc1-map-cell-links/five_examples.sql
```

```text
seq 37265  ARFCN 351 PCI 259 band 2100 -> 466730349 MOULINS_DE_GAULLE      425776 m REJET
seq 42607  ARFCN 375 PCI 4   band 2100 -> 466738178 BOURG_LES_VENNES      497096 m REJET
seq 76646  ARFCN 375 PCI 8   band 2100 -> 466741225 BLANZAT_BOURAGE_TDF    504560 m REJET
seq 79316  ARFCN 351 PCI 101 band 2100 -> 466736757 CLERMONT_ARSENAL       510092 m REJET
seq 181281 ARFCN 351 PCI 100 band 2100 -> 466739484 CHATELGUYON_TDF        493522 m REJET
```

VERDICT : les cinq non-liens sont corrects ; chaque distance dépasse le seuil
déclaré. Écart de données ouvert : le référentiel chargé ne couvre pas la zone
du parcours avec des couples bande/PCI géographiquement admissibles.

Tests ciblés dans `bc4-api:latest` :

```text
$ python -m pytest -q tests/test_map_cell_links.py tests/test_metrics_v3.py tests/test_kpi_categorical_metrics.py
.......... [100%]
```

`ruff` est absent de l'image (`exit=127`) : déclaré, jamais présenté comme un
PASS. `python -m compileall` et les imports de modèles dans l'image passent.

## SemVer

Back **MINOR** : extension additive du contrat HTTP et migration Alembic.
Numéro final attribué par BC3.
