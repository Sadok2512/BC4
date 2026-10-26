# HANDOFF — Reclassification Shared → destination (lot 2.53 pending)

| Event   | Catégorie actuelle (Shared, 2.52.0) | Sections NFF 2.50 pertinentes | Destination proposée (lot 2.53) |
|---------|-------------------------------------|-------------------------------|----------------------------------|
| AMRS    | Voice                               | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Voice" |
| APPLIST | Application throughput              | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| AQDL    | Voice                               | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| AQI     | Voice                               | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| AQRX    | Voice                               | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| CHI     | Services (tasks)                    | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Services (tasks)" |
| CMDCOMP | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| CMDREQ  | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DAA     | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DAC     | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DAD     | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DAF     | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DCOMP   | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DEVI    | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DNSQUERY | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| DREQ    | Services (tasks)                    | aucune section tech                                          | tech=NR cat="Services (tasks)" |
| DSUMMARY | Services (tasks)                    | aucune section tech                                          | tech=NR cat="Services (tasks)" |
| GAA     | Position                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| GAC     | Position                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| GAD     | Position                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| GPS     | Position                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| LOCK    | Events ⚑                            | Parameters for LTE handover forcing / Parameters for LTE sector lock | tech=LTE cat="Events ⚑" |
| LUA     | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| LUS     | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| MARK    | Position                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| MEI     | Events ⚑                            | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Events ⚑" |
| PAA     | Events ⚑                            | Parameters for GSM, UMTS, LTE, and NR                        | **rester Shared** (app-level, pas de section per-tech) |
| PAC     | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| PAD     | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| PBA     | Events ⚑                            | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Events ⚑" |
| PBC     | Events ⚑                            | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Events ⚑" |
| PBD     | Events ⚑                            | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Events ⚑" |
| PCHI    | Services (tasks)                    | Parameters for LTE / Parameters for NR                       | split tech=[LTE, NR] cat="Services (tasks)" |
| PPPRATE | Application throughput              | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| PSM     | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| PSMI    | Events ⚑                            | Parameters for LTE                                           | tech=LTE cat="Events ⚑" |
| PSMR    | Events ⚑                            | Parameters for LTE                                           | tech=LTE cat="Events ⚑" |
| QOSFLOW | Voice                               | Parameters for NR                                            | tech=NR cat="Voice" |
| RABA    | Events ⚑                            | Parameters for UMTS FDD and LTE                              | **rester Shared** (app-level, pas de section per-tech) |
| RABC    | Events ⚑                            | Parameters for UMTS FDD and LTE                              | **rester Shared** (app-level, pas de section per-tech) |
| RABD    | Events ⚑                            | Parameters for UMTS FDD and LTE                              | **rester Shared** (app-level, pas de section per-tech) |
| RBI     | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| ROAM    | Events ⚑                            | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| RTPJITTER | Voice                               | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| RTPSM   | Voice                               | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| SCRIPT  | Services (tasks)                    | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| SEI     | Events ⚑                            | Parameters for GSM, UMTS, LTE, and NR                        | **rester Shared** (app-level, pas de section per-tech) |
| SIPREGA | Application signalling              | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| SIPREGC | Application signalling              | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| SIPREGD | Application signalling              | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |
| SIPSM   | Application signalling              | aucune section tech                                          | **rester Shared** (app-level, pas de section per-tech) |


# Events classés LTE qui ont AUSSI une section « Parameters for NR » (candidat split tech=[LTE, NR])

| Event    | Catégorie actuelle (LTE) | Sections NR présentes       | Action lot 2.53                      |
|----------|--------------------------|-----------------------------|--------------------------------------|
| BSR      | Allocation & MCS         | Parameters for NR           | duplicate under tech=NR, cat="Allocation & MCS" |
| CELLMEAS | Serving radio            | Parameters for NR           | duplicate under tech=NR, cat="Serving radio" |
| CELLSCAN | Scanner                  | Parameters for NR           | duplicate under tech=NR, cat="Scanner" |
| CQI      | Link quality             | Parameters for NR           | duplicate under tech=NR, cat="Link quality" |
| CREL     | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| DCI      | Allocation & MCS         | Parameters for NR           | duplicate under tech=NR, cat="Allocation & MCS" |
| FER      | Link quality             | Parameters for NR           | duplicate under tech=NR, cat="Link quality" |
| HOA      | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| HOF      | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| MACRATE  | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| MACRATEU | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| MIMOMEAS | MIMO per port            | Parameters for NR           | duplicate under tech=NR, cat="MIMO per port" |
| OFDMSCAN | Scanner                  | Parameters for NR / Parameters for NR RS measurements | duplicate under tech=NR, cat="Scanner" |
| PDCPRATED | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| PDCPRATEU | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| PHRATE   | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| PHRATEU  | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| PLAID    | Allocation & MCS         | Parameters for NR           | duplicate under tech=NR, cat="Allocation & MCS" |
| PLAIU    | Allocation & MCS         | Parameters for NR           | duplicate under tech=NR, cat="Allocation & MCS" |
| RACHI    | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| RACHSM   | Signalling               | Parameters for NR MSG1 / Parameters for NR MSG2 / Parameters for NR MSG3 / Parameters for NR MSG4 / Parameters for NR MSG5 | duplicate under tech=NR, cat="Signalling" |
| RLCRATE  | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| RLCRATEU | Throughput per layer     | Parameters for NR           | duplicate under tech=NR, cat="Throughput per layer" |
| RRA      | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| RRCSM    | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| RRD      | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| RRF      | Signalling               | Parameters for NR           | duplicate under tech=NR, cat="Signalling" |
| SCANCONFIG | Neighbours               | Parameters for NR OFDM and band scanning / Parameters for NR frequency scanning | duplicate under tech=NR, cat="Neighbours" |
| SCELL    | Serving radio            | Parameters for NR           | duplicate under tech=NR, cat="Serving radio" |
| TXPC     | UL power                 | Parameters for NR           | duplicate under tech=NR, cat="UL power" |
