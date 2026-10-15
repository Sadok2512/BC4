"""Dictionnaire RRC LTE+NR — décodage pycrate + populate `param_occurrence`.

0.12.0 (2026-10-15, Agent BC1) : lot « dictionnaire complet ».

- `app.dict.decode` : adapté de `/home/devmat/BC4/decoder-archive/build_dict.py`.
  Logique `walk()` et deny-list `DENY`/`DROP` RÉUTILISÉES telles quelles,
  étendues au NR (BCCH/CCCH/DCCH NR + IEs capability).
- `app.dict.conversions` : table 3GPP (TS 36.133 / TS 38.133) qui
  convertit certains paramètres (rsrp-Result, rsrq-Result, q-RxLevMin,
  a3-Offset, threshold-RSRP, q-Hyst, s-Measure, rsrp/rsrq-ThresholdSSB)
  en valeur physique (dBm / dB).
- `app.dict.populate` : lit `stg_event` d'un projet (RRCSM, payload_hex
  non null), décode, aplatit en (message, path, value), rattache
  operator (via SIB1 PLMN du même capture) et band (EARFCN/ARFCN), et
  insère dans `param_occurrence` (idempotent via UNIQUE
  `(project_id, stg_event_id, path)`).

Jamais d'identité abonné : la regex DENY écarte au niveau du walk,
PUIS un filet final `_matches_deny_path()` sur le path aplati — même
règle, deux niveaux.
"""
