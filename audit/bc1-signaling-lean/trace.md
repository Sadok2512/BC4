# BC1 — signaling lean — preuve jetable 2026-10-29

Branche `bc1/signaling-lean`. Base exclusivement jetable
`bc1_signaling_lean`. Aucune lecture ni écriture de production.

## G36 et témoin

Commande exécutée avant la création/recréation de la base :

```text
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
G36_DISK ... free_gib=61.44 threshold_gib=20 verdict=PASS
```

Migration : `alembic upgrade head` jusqu'à
`0067_kpi_physical_cell_indexes`. Import Deep local :

```text
G49 project_id=bc1-kpi-lean capture_id=a4b0c321c52e file_status=done
G49 VERDICT: PASS
```

## Temps, tailles et contenu

Commande avant : appel direct de `events(..., view='rf')`, sérialisation JSON
compacte, sur le témoin `parcours_26Jun10_155941.8.nmf`.

```text
BEFORE_FULL_SECONDS=15.325272
BEFORE_FULL_BYTES=15554649
BEFORE_FULL_EVENTS=23329
WINDOW_0_30_EVENTS=206
WINDOW_0_30_SHA256=ec523b8b4cedebbf4cdd89f29ac0c3af9a802acd546e4e2d5d5c60b862bf7b16
```

Commande après : dans un processus froid, résumé, fenêtre événements
`from_s=0&to_s=30&limit=2000`, puis points
`from_s=0&to_s=30&limit=5000`. L'ordre de l'empreinte est `(seq, id)` dans
la capture ; aucune jointure inter-captures par `ts`.

```text
SUMMARY seconds=0.151244 bytes=315
EVENTS seconds=7.039848 bytes=134900 returned=206 truncated=False
POINTS seconds=0.535137 bytes=33961 returned=202 truncated=False
SHA256=ec523b8b4cedebbf4cdd89f29ac0c3af9a802acd546e4e2d5d5c60b862bf7b16
FIRST_DISPLAY_VERDICT=PASS
CONTENT_VERDICT=PASS
```

Le premier affichage est donc inférieur à une seconde et 500 Ko. Chaque
réponse est inférieure à 500 Ko. Le détail événements continue de calculer la
projection RF à froid, mais il arrive après le résumé et sa projection est
ensuite partagée avec les points. Écart déclaré : la première fenêtre de
détail n'est pas encore sous une seconde (`7.039848 s`) ; l'objectif formulé
portait sur le premier affichage, qui est PASS.

## Tests minimaux

```text
pytest -q tests/test_chronogram.py tests/test_rf_timeline.py tests/test_signaling_lean.py
............ [100%]

vitest run signaling-events-schema signaling-messages-table signaling-time-window
Test Files 3 passed (3)
Tests 29 passed (29)

tsc --noEmit
exit 2 — VERDICT FAIL global : 10 erreurs préexistantes hors lot dans
AssistantMap, client/fixtures/dictionary, mocks et overview (unions opérateurs,
technos et services). Aucune erreur dans un fichier Signaling modifié.

npm run build
exit 0
```

Le test clock couvre explicitement un reparse avec la même version de
décodeur et un `decoded_at` différent. Le test fenêtre vérifie pagination par
`after_seq`, intervalle chevauchant, ordre par `seq` et empreinte sans perte.

## SemVer

- back proposé `0.98.0`, **minor** : ajout du résumé et des paramètres de
  fenêtre/curseur au contrat API ; numérotation finale par BC3 ;
- front proposé `1.118.0`, **minor** : chargement progressif et rendu
  virtualisé ; numérotation finale par BC3.
