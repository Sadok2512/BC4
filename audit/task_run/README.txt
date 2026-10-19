ÉTAPE 0 — AUDIT AVANT CODE — 2026-10-19
Projet retenu : Test_3 = 4b7bfd50ddb6.
TEST2 = 134af70a06eb reste failed/error ; aucun replay sur TEST2.
Version active GET localhost:8000/health = 0.52.3 ; HEAD d5574eb.
Migration actuelle : 0024_dict_templates ; 0025 libre à cet instant.

Source projet :
SELECT id,name,status,status_ingest,n_captures_ingest,n_events_ingest,n_points,last_populate_at
FROM projects WHERE id IN ('134af70a06eb','4b7bfd50ddb6');
Test_3 ready/ready ; 58 captures annoncées ; 96965 événements annoncés ;
349703 points annoncés ; last_populate_at 2026-10-18 16:46:40.613183+00.
Ces compteurs projet ne remplacent pas les comptes staging de l'inventaire.
Aucune table captures dans cette base : capture_id est porté par le staging.

INVENTAIRE : inventory.csv, requête et écarts dans inventory.json.
Reproduction : docker exec -i bc4-api-1 python < audit/task_run/audit_inventory.py
Scan limité aux événements concernés, ordre capture_id,seq ; aucune valeur privée exportée.
58 captures ; CMDREQ 3188 ; DAA 754 ; DRATE 9079 ; DCOMP 724 ; DSUMMARY 724 ; AQDL 143.
CMDREQ : StartHTTPTransfer 754, StopHTTPTransfer 754, StartRepeat 769,
StartScript 50, StopScript 50, Wait 757, VoiceCallStart/Stop 15 chacun,
ReceiveCallStart/Stop 12 chacun.
Fenêtres de tâches délimitées par la commande de démarrage suivante dans la même capture :
27 sans DAA (voix) ; 57 sans DCOMP (dont 30 HTTP). Liste exhaustive dans inventory.json.
Ces absences restent déclarées ; aucun marqueur de fin/début n'est fabriqué.
HTTP XML (champs non privés uniquement) : Direction=1, NumberOfThreads=1 ;
MaximeDuration=10 pour 703 commandes, =60 pour 51 commandes.

EXISTANT À RÉUTILISER
app/measure/throughput.py: compute_transfers (ligne 111) scanne CMDREQ/DSUMMARY,
calcule 8*bytes_transferred/dt, rejette hors 0..300 Mbit/s, puis
apply_transfers_to_measurement_points (ligne 221) propage une moyenne sur la fenêtre.
Cette interprétation DSUMMARY est incorrecte : remplacement requis, pas une seconde formule.
app/kpi/service_v2.py: compute_status_v2 (lignes 228-245), transfers_cache
(lignes 276-290), compute_kpi_v2 (lignes 1137-1195) consomment compute_transfers.
transfers_cache est une liste Python locale à une requête, pas une table.
app/services/populate_chain.py : A mesures, B points, C ECGI, puis snapshot D actuel.
Le nouveau D tâches doit s'insérer avant ce snapshot, en conservant le chemin existant.
Aucune table/route task_run, task_sample ou /results existante repérée.

CHAMPS ET ORDRE
DRATE stocke bps dans c6 et cumul dans c8. DCOMP expose sa valeur octets dans c10.
Le décodeur _label_raw énumère fields depuis zéro (bc4_decoder.py:286-301) :
ne pas confondre numéro de colonne du fichier et nom cN.
AQDL c4 porte MOS. Les autres valeurs restent hors du modèle faute de contrat.
Aucune reconstruction temporelle inter-captures.

ÉCART CONFIDENTIALITÉ OUVERT
15 payloads VoiceCallStart contiennent encore un PhoneNumber non masqué après décompression.
Comptage uniquement ; aucune identité copiée dans le rapport, le CSV ou les logs.
La garde G14e n'est pas PASS. La prévention à l'ingestion et le masquage ciblé de ce
champ dans le staging existant sont nécessaires, sans retirer les mesures.

PERFORMANCE AUDIT
Le premier scan incluant tous les raw_fields a été interrompu (requête puis processus
Python d'audit) ; remplacé par un scan ciblé des six codes. Aucun serveur redémarré.
Aucune table/donnée source modifiée pendant cette étape ; seuls les fichiers d'audit sont écrits.
