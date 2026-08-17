# 🚨 PayGuard — État du projet & actions immédiates (deadline : CE SOIR 23h30)

> Dernière mise à jour : 17 août, ~20h45. **On soumet à 23h00 max, pas 23h30.**

## ✅ Ce qui est FAIT (code complet et commité)

| Composant | Fichier | État |
|---|---|---|
| Schéma SQL (5 tables + index vectoriel) | `db/schema.sql` | ✅ prêt |
| Moteur de paiement idempotent (machine à états write-ahead) | `payguard/engine.py` | ✅ prêt |
| Simulateur PSP (ledger dédupliqué, pannes injectables) | `payguard/psp.py` | ✅ prêt |
| Tests de crash automatisés (5 points de crash + double exécution) | `tests/test_crash.py` | ✅ écrits, à lancer contre le cluster |
| Agent Claude sur Bedrock (7 outils, mémoire 100% en base) | `payguard/agent.py`, `payguard/tools.py` | ✅ prêt |
| RAG anti-fraude (Titan v2 1024 dims + vector index) | `payguard/fraud.py` | ✅ prêt (mode `fake` dispo hors-ligne) |
| Jeu de données démo (15 fournisseurs, ~60 factures, 1 fraude) | `payguard/seed.py` | ✅ prêt |
| Vue live "mémoire" (split-screen) | `python -m payguard status` | ✅ prêt |
| Script démo crash | `scripts/demo_crash.ps1` | ✅ prêt |
| Lambda (exécution serverless + relances) | `lambda/handler.py` | ✅ prêt |
| README de soumission (EN) + licence MIT | `README.md`, `LICENSE` | ✅ prêt |

## 🔥 CE QU'IL RESTE — dans l'ordre, qui peut le prendre

### 1. Comptes & branchement (~15 min) — BLOQUANT, à faire MAINTENANT
- [ ] **CockroachDB Cloud** : créer un cluster gratuit (Basic/Serverless) sur cockroachlabs.cloud → bouton **Connect** → copier la connection string.
- [ ] Créer `.env` à la racine (copier `.env.example`) et coller la string dans `DATABASE_URL`.
- [ ] **AWS** : `aws configure` (région `us-east-1`) + console **Bedrock → Model access** : activer **Claude Sonnet** et **Titan Text Embeddings V2**.
  - Plan B si Bedrock bloque : mettre `EMBEDDINGS_PROVIDER=fake` dans `.env` → tout marche sauf le chat.
- [ ] **(Bonus MCP)** : dans la console CockroachDB Cloud, activer le **serveur MCP** du cluster (c'est un des 2 outils CockroachDB exigés, avec le vectoriel — déjà documenté dans le README).

### 2. Validation technique (~20 min) — dès que le .env est prêt
```powershell
pip install -r requirements.txt
python -m payguard init-db     # applique le schéma
python -m payguard seed        # charge les données démo (note les IDs de factures affichés !)
pytest tests/ -v               # LES TESTS DE CRASH — la preuve n°1 pour le jury
python -m payguard chat        # test du chat Bedrock
```

### 3. Répétition des 5 preuves (~20 min)
| Preuve | Commande |
|---|---|
| Amnésie | quitter le chat, relancer `python -m payguard chat`, demander « quels paiements as-tu faits ? » |
| Crash agent | `.\scripts\demo_crash.ps1 <invoice_id_propre>` |
| Split-screen | `python -m payguard status` dans un 2e terminal pendant que l'agent paie |
| Anomalie fournisseur | demander à l'agent de payer la facture **Fournisseur BTP Yamoussoukro** → BLOCKED avec les 14 factures citées |
| Chaos CockroachDB | sur cluster gratuit on ne peut pas tuer un nœud → montrer la console cluster + expliquer la réplication (ou couper/rétablir le réseau pendant un paiement : la reprise fait le reste) |

### 4. Vidéo (< 3 min) — À TOURNER DÈS QUE LES PREUVES PASSENT (~21h15)
Script minuté déjà prêt dans `PayGuard_Document_Projet_et_Roadmap.md` section 7.
Ordre de tournage conseillé : split-screen nominal → crash+reprise → amnésie → fraude → slide archi.
Upload YouTube en **public** (exigence du hackathon).

### 5. Soumission Devpost (~22h15) — NE PAS ATTENDRE 23h
- [ ] Lien repo GitHub (public, licence MIT visible ✅)
- [ ] Lien vidéo YouTube
- [ ] Description : reprendre le pitch + la section « CockroachDB tools used » et « AWS services used » du README
- [ ] Champ feedback outils IA CockroachDB : section déjà rédigée dans le README (points bonus)

## Répartition suggérée (3 personnes)
- **Personne A** : comptes cloud + .env + étape 2 (validation)
- **Personne B** : formulaire Devpost pré-rempli + slide d'architecture (reprendre l'ASCII du README)
- **Personne C** : setup enregistrement écran + répète le déroulé vidéo à vide

## Notes techniques importantes
- Les réponses de l'agent viennent **toujours** de la base (outils SQL/vectoriel), jamais de son contexte → c'est ça l'argument massue.
- `CRASH_AT` (variable d'env) permet de tuer le process à n'importe quelle étape : `AFTER_INTENT`, `AFTER_VALIDATED`, `AFTER_EXECUTING_WRITE`, `AFTER_PSP_CALL` (le pire cas), `AFTER_EXECUTED`.
- Le PSP simulé a son propre ledger (`psp_ledger`) : c'est LA table qui prouve « payé exactement une fois ».
- Modèle Bedrock configurable via `BEDROCK_MODEL_ID` dans `.env` si le modèle par défaut n'est pas activé sur le compte.
