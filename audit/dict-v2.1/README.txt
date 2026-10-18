PHASE A — AUDIT BLOQUÉ, aucune livraison déclarée.
Frontend non touché. Aucune donnée source modifiée. Aucun rebuild ni commit réalisé.

Constats vérifiés :
- /home/devmat/BC4/specs/dict_templates.html absent ; recherche étendue sans résultat.
- Prompt BC1 intégral et définition G12a/b/c non fournis.
- REF 7e656b8c6c19 absent de projects ; ref_keys.csv contient seulement les en-têtes.
  Cela ne démontre PAS l'absence d'un paramètre dans REF. Tableau présents/absents : NON ÉVALUABLE.
- HEAD e342cdb correspond au lot 0.48.2 ; working tree déjà modifié avant ce lot.
- pyproject.toml et /health valent déjà 0.49.0 (lot géographique).
- Migration 0023_nmf_import_jobs présente ET appliquée. Elle ne peut pas être remplacée par une migration de catégories.
- Tables dict_category, dict_category_map, dict_template absentes.

Affectation actuelle :
app/dict/enrich_v2.py:284 _FUNCTIONAL_GROUPS, liste ordonnée de regex.
app/dict/enrich_v2.py:343 functional_group : premier rx.search(param_key), puis message commençant UECapability => Capacités, sinon Autres.
app/dict/service_v2.py build_dict_tree : view=catalog regroupe par system/origin/message/functional_group/param_key/discriminators/unit ; identifiants exclus. Raw utilise path et groupe RAW.
Les regex existantes ne constituent pas la table de préfixes exacts demandée et ne seront pas transformées en classification supposée.

Étape 0 : PARTIELLE (audit environnement et règles effectué ; audit REF/spec impossible).
Étapes 1–2 : NOT RUN (spec/seed approuvés manquants, collision migration appliquée).
G12a / G12b / G12c : NOT RUN (définitions manquantes).
Livraison/rebuild/validation REF : NOT RUN.

À fournir : spec et prompt BC1 complets ; instance contenant le projet REF ou identifiant corrigé ; consigne de réconciliation pour les travaux existants et nouvelle numérotation migration/version.
Ne pas utiliser TEST2/Test_3 comme substitut silencieux à REF.

Reproduction SQL :
docker exec -i bc4-db-1 psql -U bc4 -d bc4 -X --csv < audit/dict-v2.1/ref_keys.sql
docker exec -i bc4-db-1 psql -U bc4 -d bc4 -X < audit/dict-v2.1/environment.sql
curl -fsS http://localhost:8000/health
Les réponses HTTP brutes et leur contexte sont conservés dans requests.json + tree.json/templates.json/summary.json. Token omis intentionnellement.
