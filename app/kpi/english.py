"""English API presentation vocabulary for KPI and Metrics.

No changes to stored catalogue definitions, raw data, codes or computations.
Only explicitly listed human-readable response fields are translated.
"""
LABELS = {'Accessibilité': 'Accessibility',
 'Accès radio': 'Radio access',
 'Appels': 'Calls',
 'Association LTE/NR non prouvée ; aucun mélange de captures': 'Unproven LTE/NR association; '
                                                               'captures are never combined',
 'Attachement': 'Attach',
 'Aucun intervalle RRC → RRD complet et admissible prouvé': 'No proven complete eligible RRC → RRD '
                                                            'interval',
 'Aucune observation ou pondération totale non prouvée': 'No observations or total weighting '
                                                         'unproven',
 'Aucune position NR documentée dans les schémas activés': 'No documented NR field positions in '
                                                           'active schemas',
 'Aucune tâche complète avec DRATE ou repli DCOMP et bornes valides': 'No complete task with DRATE '
                                                                      'or DCOMP fallback and valid '
                                                                      'boundaries',
 'CC avec trafic PDSCH observé': 'CCs with observed PDSCH traffic',
 'Cellule / CA': 'Cell / CA',
 'Compteur': 'Counter',
 'Contexte Nemo': 'Nemo context',
 'Contexte capture': 'Capture context',
 'Couverture & qualité': 'Coverage & quality',
 'Durée HO Nemo': 'Nemo HO duration',
 'Durée HOI': 'HOI duration',
 'Durée du couple Nemo': 'Nemo pair duration',
 'Débit': 'Throughput',
 'Débit APP DL agrégé': 'Aggregated APP DL throughput',
 'Débit APP UL agrégé': 'Aggregated APP UL throughput',
 'Débit applicatif': 'Application throughput',
 'Débits par couche': 'Throughput by layer',
 'ECGI non encore propagé': 'ECGI not propagated yet',
 'Forçages / repères': 'Forcing / markers',
 'Heure capture (secondes depuis minuit)': 'Capture time (seconds since midnight)',
 'Issue du couple': 'Pair outcome',
 'KPI calculé': 'Calculated KPI',
 'LTE ECGI — Cellules distinctes observées': 'LTE ECGI — Distinct observed cells',
 'Latence': 'Latency',
 'MIMO par port': 'MIMO by port',
 'Meilleure RSRP voisine': 'Best neighbour RSRP',
 'Meilleure RSRQ voisine': 'Best neighbour RSRQ',
 'Mobilité': 'Mobility',
 'Métrique mesurée': 'Measured metric',
 'NR NCGI — Cellules 5G distinctes observées': 'NR NCGI — Distinct observed 5G cells',
 'Nombre de voisines type 2': 'Type 2 neighbour count',
 'Non documentés': 'Undocumented',
 'Part SCell du débit PHY observé': 'SCell share of observed PHY throughput',
 'Puissance UL': 'UL power',
 'Qualité de lien': 'Link quality',
 'Qualité radio': 'Radio quality',
 'RSRP voisine − serving': 'Neighbour RSRP − serving',
 'RSRQ voisine − serving': 'Neighbour RSRQ − serving',
 'Rétention': 'Retainability',
 'SCell avec trafic PDSCH observé': 'SCells with observed PDSCH traffic',
 'Sessions data': 'Data sessions',
 'Voisines': 'Neighbours',
 'Voix': 'Voice',
 'attribution de cette dimension non prouvée pour les observations Nemo': 'Attribution of this '
                                                                          'dimension is unproven '
                                                                          'for Nemo observations',
 'aucun NMF ENDC ingéré avec succès dans le corpus actuel (REF = LTE uniquement).': 'No '
                                                                                    'successfully '
                                                                                    'ingested ENDC '
                                                                                    'NMF in the '
                                                                                    'current '
                                                                                    'corpus (REF = '
                                                                                    'LTE only).',
 'aucun NMF NR ingéré avec succès dans le corpus actuel (REF = LTE uniquement) ; propagation NCGI attend un release du décodeur NR.': 'No '
                                                                                                                                      'successfully '
                                                                                                                                      'ingested '
                                                                                                                                      'NR '
                                                                                                                                      'NMF '
                                                                                                                                      'in '
                                                                                                                                      'the '
                                                                                                                                      'current '
                                                                                                                                      'corpus '
                                                                                                                                      '(REF '
                                                                                                                                      '= '
                                                                                                                                      'LTE '
                                                                                                                                      'only); '
                                                                                                                                      'NCGI '
                                                                                                                                      'propagation '
                                                                                                                                      'requires '
                                                                                                                                      'an '
                                                                                                                                      'NR '
                                                                                                                                      'decoder '
                                                                                                                                      'release.',
 'aucun NMF NR ingéré avec succès dans le corpus actuel (REF = LTE uniquement).': 'No successfully '
                                                                                  'ingested NR NMF '
                                                                                  'in the current '
                                                                                  'corpus (REF = '
                                                                                  'LTE only).',
 'aucun handover décodé dans ce projet': 'No decoded handover in this project',
 'aucune mesure Nemo documentée décodée': 'No decoded documented Nemo measurements',
 'calcul non implémenté (F4)': 'Calculation not implemented (F4)',
 'cellule servante secondaire — hypothèse non prouvée': 'Secondary serving cell — unproven '
                                                        'hypothesis',
 'cellule servante secondaire — hypothèse non prouvée ; dépend de BC1 /dict/v2/scells': 'Secondary '
                                                                                        'serving '
                                                                                        'cell — '
                                                                                        'unproven '
                                                                                        'hypothesis; '
                                                                                        'requires '
                                                                                        'BC1 '
                                                                                        '/dict/v2/scells',
 'dimension non attribuée aux transferts': 'Dimension not attributed to transfers',
 'groupement géographique filtré non pris en charge': 'Filtered geographic grouping is unsupported',
 "le contrat tentative/réussite/échec n'est pas certifié par le décodeur 2.0.0 ; un taux n'est pas calculé tant que ses frères ne sont pas prouvés.": 'The '
                                                                                                                                                      'attempt/success/failure '
                                                                                                                                                      'contract '
                                                                                                                                                      'is '
                                                                                                                                                      'not '
                                                                                                                                                      'certified '
                                                                                                                                                      'by '
                                                                                                                                                      'decoder '
                                                                                                                                                      '2.0.0; '
                                                                                                                                                      'rates '
                                                                                                                                                      'remain '
                                                                                                                                                      'unavailable '
                                                                                                                                                      'until '
                                                                                                                                                      'the '
                                                                                                                                                      'corresponding '
                                                                                                                                                      'counters '
                                                                                                                                                      'are '
                                                                                                                                                      'proven.',
 'n = 0 sur ce périmètre': 'n = 0 in this scope',
 'position non prouvée (NFF 2.19)': 'Unproven field position (NFF 2.19)',
 'Événements': 'Events'}

FRAGMENTS = {' (CELLMEAS prouvé)': ' (proven CELLMEAS)',
 ' (frères Compteur du catalogue)': ' (corresponding catalogue counters)',
 ' (tous opérateurs)': ' (all operators)',
 ' NULL partout': ' is NULL throughout',
 ' NULL partout — SIB1 non décodé ou populate_ecgi pas exécuté.': ' is NULL throughout — SIB1 not '
                                                                  'decoded or populate_ecgi not '
                                                                  'run.',
 ' NULL partout — latence pas encore extraite des events data_* (écart 0.24.0).': ' is NULL '
                                                                                  'throughout — '
                                                                                  'latency not yet '
                                                                                  'extracted from '
                                                                                  'data_* events '
                                                                                  '(gap 0.24.0).',
 ' NULL partout — mapping décodeur non prouvé (écart 0.24.0 / 0.25.0, lot 0.39.0 en cours).': ' is '
                                                                                              'NULL '
                                                                                              'throughout '
                                                                                              '— '
                                                                                              'decoder '
                                                                                              'mapping '
                                                                                              'unproven '
                                                                                              '(gap '
                                                                                              '0.24.0 '
                                                                                              '/ '
                                                                                              '0.25.0; '
                                                                                              'work '
                                                                                              'package '
                                                                                              '0.39.0 '
                                                                                              'in '
                                                                                              'progress).',
 ' NULL partout — relancer populate_measurement_points sur ce projet (profil CELLMEAS prouvé en cellmeas_profile).': ' '
                                                                                                                     'is '
                                                                                                                     'NULL '
                                                                                                                     'throughout '
                                                                                                                     '— '
                                                                                                                     'rerun '
                                                                                                                     'populate_measurement_points '
                                                                                                                     'for '
                                                                                                                     'this '
                                                                                                                     'project '
                                                                                                                     '(CELLMEAS '
                                                                                                                     'profile '
                                                                                                                     'proven '
                                                                                                                     'in '
                                                                                                                     'cellmeas_profile).',
 ' NULL partout — relancer populate_measurement_points sur ce projet.': ' is NULL throughout — '
                                                                        'rerun '
                                                                        'populate_measurement_points '
                                                                        'for this project.',
 ' documenté': ' documented',
 ' filtré par path LIKE ': ' filtered by path LIKE ',
 ' non adossé à un event prouvé par le décodeur 2.0.0 (écarts 0.24.0 / 0.33.0 : RACH/E-RAB/DATA_* et HO par type intra/inter/irat sans distinction certifiée).': ' '
                                                                                                                                                                 'is '
                                                                                                                                                                 'not '
                                                                                                                                                                 'backed '
                                                                                                                                                                 'by '
                                                                                                                                                                 'an '
                                                                                                                                                                 'event '
                                                                                                                                                                 'proven '
                                                                                                                                                                 'by '
                                                                                                                                                                 'decoder '
                                                                                                                                                                 '2.0.0 '
                                                                                                                                                                 '(gaps '
                                                                                                                                                                 '0.24.0 '
                                                                                                                                                                 '/ '
                                                                                                                                                                 '0.33.0: '
                                                                                                                                                                 'RACH/E-RAB/DATA_* '
                                                                                                                                                                 'and '
                                                                                                                                                                 'intra/inter/IRAT '
                                                                                                                                                                 'HO '
                                                                                                                                                                 'types '
                                                                                                                                                                 'lack '
                                                                                                                                                                 'certified '
                                                                                                                                                                 'distinctions).',
 ' sans mapping prouvé côté décodeur.': ' has no proven decoder mapping.',
 ' sans règle de rattachement événementielle.': ' has no event attribution rule.',
 ' · champs non documentés': ' · undocumented fields',
 ' · ensembles': ' · sets',
 ': pondérations inter-échantillons absentes ; agrégat seconde N/D, série par seq conservée': ': '
                                                                                              'missing '
                                                                                              'inter-sample '
                                                                                              'weights; '
                                                                                              'per-second '
                                                                                              'aggregate '
                                                                                              'unavailable, '
                                                                                              'per-seq '
                                                                                              'series '
                                                                                              'preserved',
 'Cellule type ': 'Cell type ',
 'ECGI non propagé : ': 'ECGI not propagated: ',
 'Statistique par tâche complète : mean(DRATE.bps)/1e6, sinon 8×bytes_dcomp/duration_s/1e6 avec bornes prouvées': 'Statistic '
                                                                                                                  'per '
                                                                                                                  'complete '
                                                                                                                  'task: '
                                                                                                                  'mean(DRATE.bps)/1e6, '
                                                                                                                  'otherwise '
                                                                                                                  '8×bytes_dcomp/duration_s/1e6 '
                                                                                                                  'with '
                                                                                                                  'proven '
                                                                                                                  'boundaries',
 'aucune occurrence RRC pour message=': 'No RRC occurrence for message=',
 'aucune occurrence RRC pour path LIKE ': 'No RRC occurrence for path LIKE ',
 'available_check.arg vide': 'available_check.arg is empty',
 'compteur ': 'Counter ',
 'métrique mesurée ': 'Measured metric ',
 'percentile_cont sur ': 'percentile_cont on ',
 'référentiel non chargé : cell_ref.': 'Reference data not loaded: cell_ref.',
 'événement source absent (': 'Source event absent ('}

DISPLAY_FIELDS = frozenset({"label", "name", "family", "category_label", "category", "nature", "reason", "note", "event_group", "connected_reason", "formula"})

def english_text(value):
    if not isinstance(value, str):
        return value
    if value in LABELS:
        return LABELS[value]
    for source, target in sorted(FRAGMENTS.items(), key=lambda item: -len(item[0])):
        value = value.replace(source, target)
    for source, target in sorted(LABELS.items(), key=lambda item: -len(item[0])):
        if source == "cellule servante secondaire — hypothèse non prouvée":
            value = value.replace(source, target)
    return value

def english_response(value):
    if isinstance(value, list):
        return [english_response(item) for item in value]
    if isinstance(value, dict):
        return {key: english_text(item) if key in DISPLAY_FIELDS and isinstance(item, str)
                else english_response(item) for key, item in value.items()}
    return value
