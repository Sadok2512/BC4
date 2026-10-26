# Analyse des 86 YAMLs 2.50 supprimés (Lot A nuit)

## Résumé classification

| action | n | raison |
|---|---|---|
| ABSENT_CORPUS | 22 | event 0 occurrences dans stg_event_raw — restent supprimés, pas de risque régression |
| RESTORE | 5 | YAML 2.50 complet (égalité stricte avec CSV + 1 section) — restaurés après vérif tests |
| LAYOUT_A_FAIRE | 59 | YAML 2.50 partiel (champs CSV manquants OU sections ignorées) — build_yamls.py doit reconstruire |

## RESTORE — restaurés après vérification tests

| event | corpus | 2.50 h+g | 1.5.1 h+g | csv | sections |
|---|---|---|---|---|---|
| PPPRATE | 58521 | 4 | 2 | 4 | 1 |
| GPS | 15913 | 12 | 7 | 12 | 1 |
| DAA | 1200 | 7 | 5 | 7 | 1 |
| DAC | 1148 | 1 | 1 | 1 | 1 |
| AQI | 57 | 4 | 4 | 4 | 1 |

## LAYOUT_A_FAIRE — build_yamls.py doit reconstruire (feuilles catalog grises avec raison)

| event | corpus | 2.50 h+g | 1.5.1 h+g | csv | sections | raison partiel |
|---|---|---|---|---|---|---|
| MACRATE | 339458 | 9 | 10 | 47 | 6 | perte 1 champ(s) 1.5.1 |
| PLAID | 339456 | 17 | 16 | 103 | 6 | 6 sections CSV avec 86 champs non capturés par when |
| CQI | 334845 | 12 | 14 | 52 | 5 | perte 2 champ(s) 1.5.1 |
| RTPSM | 302016 | 3 | 5 | 4 | 1 | perte 2 champ(s) 1.5.1 |
| CI | 246994 | 4 | 5 | 30 | 5 | perte 1 champ(s) 1.5.1 |
| MACRATEU | 199294 | 9 | 7 | 20 | 3 | 3 sections CSV avec 11 champs non capturés par when |
| PLAIU | 199294 | 17 | 13 | 91 | 5 | 5 sections CSV avec 74 champs non capturés par when |
| TXPC | 186416 | 10 | 9 | 98 | 9 | 9 sections CSV avec 88 champs non capturés par when |
| CELLMEAS | 115225 | 11 | 10 | 203 | 15 | 15 sections CSV avec 192 champs non capturés par when |
| RLCRATE | 104587 | 7 | 8 | 35 | 5 | perte 1 champ(s) 1.5.1 |
| PDCPRATED | 94156 | 4 | 6 | 19 | 3 | perte 2 champ(s) 1.5.1 |
| TAD | 86966 | 2 | 1 | 6 | 5 | 5 sections CSV avec 4 champs non capturés par when |
| MIMOMEAS | 86316 | 9 | 10 | 35 | 4 | perte 1 champ(s) 1.5.1 |
| RLCRATEU | 42465 | 7 | 8 | 23 | 3 | perte 1 champ(s) 1.5.1 |
| PDCPRATEU | 42179 | 4 | 6 | 19 | 3 | perte 2 champ(s) 1.5.1 |
| MEI | 28834 | 2 | 3 | 7 | 5 | perte 1 champ(s) 1.5.1 |
| DRATE | 16659 | 1 | 4 | 5 | 2 | perte 3 champ(s) 1.5.1 |
| RTPJITTER | 8203 | 1 | 1 | 24 | 5 | 5 sections CSV avec 23 champs non capturés par when |
| PCHI | 6568 | 2 | 3 | 98 | 10 | perte 1 champ(s) 1.5.1 |
| RABA | 3067 | 0 | 0 | 7 | 2 | 2 sections CSV avec 7 champs non capturés par when |
| RABC | 3067 | 0 | 0 | 4 | 2 | 2 sections CSV avec 4 champs non capturés par when |
| RABD | 3067 | 0 | 0 | 5 | 2 | 2 sections CSV avec 5 champs non capturés par when |
| RACHI | 2595 | 22 | 15 | 94 | 7 | 7 sections CSV avec 72 champs non capturés par when |
| AQRX | 2346 | 1 | 1 | 2 | 2 | 1 champs CSV absents du YAML |
| NLIST | 1878 | 1 | 2 | 26 | 7 | perte 1 champ(s) 1.5.1 |
| MARK | 1608 | 1 | 2 | 2 | 1 | perte 1 champ(s) 1.5.1 |
| RRA | 1357 | 1 | 2 | 4 | 4 | perte 1 champ(s) 1.5.1 |
| RRC | 1329 | 0 | 1 | 2 | 2 | perte 1 champ(s) 1.5.1 |
| RRD | 1329 | 2 | 3 | 6 | 4 | perte 1 champ(s) 1.5.1 |
| DAD | 1148 | 2 | 2 | 36 | 35 | 35 sections CSV avec 34 champs non capturés par when |
| DCOMP | 1148 | 2 | 2 | 47 | 35 | 35 sections CSV avec 45 champs non capturés par when |
| DREQ | 1148 | 2 | 2 | 104 | 34 | 34 sections CSV avec 102 champs non capturés par when |
| DSUMMARY | 1148 | 1 | 0 | 58 | 5 | 5 sections CSV avec 57 champs non capturés par when |
| HOI | 961 | 3 | 4 | 4 | 1 | perte 1 champ(s) 1.5.1 |
| HOA | 649 | 9 | 10 | 63 | 12 | perte 1 champ(s) 1.5.1 |
| CREL | 539 | 9 | 19 | 61 | 10 | perte 10 champ(s) 1.5.1 |
| SCELLMOD | 454 | 5 | 0 | 15 | 2 | 2 sections CSV avec 10 champs non capturés par when |
| PBA | 331 | 1 | 2 | 4 | 3 | perte 1 champ(s) 1.5.1 |
| PBC | 326 | 3 | 3 | 8 | 3 | 3 sections CSV avec 5 champs non capturés par when |
| PBD | 326 | 1 | 2 | 3 | 3 | perte 1 champ(s) 1.5.1 |
| AQDL | 306 | 1 | 1 | 20 | 5 | 5 sections CSV avec 19 champs non capturés par when |
| LOCK | 263 | 1 | 14 | 38 | 14 | perte 13 champ(s) 1.5.1 |
| SEI | 209 | 1 | 6 | 8 | 3 | perte 5 champ(s) 1.5.1 |
| CAC | 164 | 2 | 4 | 6 | 3 | perte 2 champ(s) 1.5.1 |
| FER | 163 | 1 | 1 | 16 | 7 | 7 sections CSV avec 15 champs non capturés par when |
| VOIPI | 155 | 1 | 2 | 6 | 3 | perte 1 champ(s) 1.5.1 |
| PAC | 136 | 2 | 3 | 3 | 1 | perte 1 champ(s) 1.5.1 |
| ROAM | 136 | 1 | 2 | 2 | 1 | perte 1 champ(s) 1.5.1 |
| AMRS | 102 | 4 | 3 | 21 | 6 | 6 sections CSV avec 17 champs non capturés par when |
| GAA | 98 | 0 | 1 | 1 | 1 | perte 1 champ(s) 1.5.1 |
| GAC | 98 | 0 | 1 | 1 | 1 | perte 1 champ(s) 1.5.1 |
| GAD | 98 | 3 | 4 | 4 | 1 | perte 1 champ(s) 1.5.1 |
| SIPREGA | 98 | 0 | 1 | 4 | 4 | perte 1 champ(s) 1.5.1 |
| SIPREGD | 98 | 0 | 1 | 12 | 4 | perte 1 champ(s) 1.5.1 |
| PAD | 96 | 3 | 4 | 4 | 1 | perte 1 champ(s) 1.5.1 |
| PAA | 68 | 0 | 1 | 11 | 4 | perte 1 champ(s) 1.5.1 |
| CAA | 65 | 7 | 7 | 8 | 1 | 1 champs CSV absents du YAML |
| CAD | 65 | 3 | 4 | 21 | 19 | perte 1 champ(s) 1.5.1 |
| ANRI | 14 | 1 | 3 | 10 | 2 | perte 2 champ(s) 1.5.1 |

## ABSENT_CORPUS — restent supprimés (0 risque régression)

#BF, #DL, #DN, #DS, #DT, #FF, #HASH, #HV, #HW, #ID, #LICENSE, #MF, #PRODUCT, #SP, #START, #STOP, #SW, #TS, #UT, L3SM, RRCSM, SIPSM

**Preuve corpus** : requête `SELECT event_code, COUNT(*) FROM stg_event_raw GROUP BY 1`
sortie dans `/tmp/corpus_events.csv` (114 events, 83 UE + 10 scanner captures).
