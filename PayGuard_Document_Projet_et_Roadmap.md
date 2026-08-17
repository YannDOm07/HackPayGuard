# PayGuard — L'agent financier qui ne paie jamais deux fois

**Hackathon CockroachDB × AWS — Document de projet & Roadmap**

---

## 1. Pitch (30 secondes)

PayGuard est un directeur financier autonome pour PME : un agent IA qui vérifie les factures, détecte les fraudes et exécute les paiements fournisseurs — avec une garantie absolue : **aucun paiement perdu, aucun paiement dupliqué, jamais**. Sa mémoire d'état, portée par CockroachDB, survit aux crashs de l'agent, aux redémarrages et même aux pannes de la base de données elle-même.

> *« La mémoire n'est pas une feature. C'est ce qui sépare un jouet d'un agent de production. »*

---

## 2. Le problème

2026 est l'année des **paiements agentiques** : les agents IA commencent à exécuter des paiements de manière autonome (fournisseurs, abonnements, salaires). Mais un agent qui manipule de l'argent a un risque mortel : le **double paiement**.

Scénario catastrophe classique :

1. L'agent envoie le virement au fournisseur ✅
2. L'agent crashe **avant** d'enregistrer que le virement est parti 💥
3. Au redémarrage, l'agent ne trouve aucune trace du paiement
4. Il repaie → **le fournisseur est payé deux fois**

L'inverse est tout aussi grave : l'agent croit avoir payé alors que non → fournisseur impayé, pénalités, relation commerciale dégradée.

Le problème de fond : les LLM sont **amnésiques par nature**. Toute mémoire doit être externalisée — et cette mémoire externe doit être **toujours disponible et transactionnellement fiable**. Un agent dont la mémoire est indisponible ne se dégrade pas : il s'arrête, ou pire, il agit à l'aveugle.

---

## 3. La solution

PayGuard externalise 100 % de son état dans CockroachDB et suit un principe strict : **écrire avant d'agir** (write-ahead). Chaque paiement traverse une machine à états persistée ; à chaque redémarrage, l'agent relit son état et reprend exactement où il en était.

### Ce que fait l'agent

| Capacité | Description |
|---|---|
| **Réception & vérification de factures** | Analyse la facture (montant, fournisseur, IBAN/compte mobile money), la compare à l'historique |
| **Détection d'anomalies (RAG)** | Recherche vectorielle sur les factures passées : « ce fournisseur a changé de numéro de compte après 14 factures identiques → suspect » |
| **Exécution de paiement idempotente** | Machine à états persistée : INTENT → VALIDATED → EXECUTING → EXECUTED → CONFIRMED, avec clé d'idempotence |
| **Reprise après crash** | Au démarrage : « où en étais-je ? » → relit les paiements non terminés, vérifie, complète — sans jamais dupliquer |
| **Audit en langage naturel** | « Montre-moi tous les paiements de mars supérieurs à 100 000 FCFA » → réponse issue directement de la base |
| **Relances & échéances** | Suit les factures à échéance et déclenche les paiements planifiés |

---

## 4. Les 4 types de mémoire démontrés

| Type | Contenu | Stockage CockroachDB |
|---|---|---|
| **Transactionnelle** | Paiements, factures, fournisseurs, soldes | Tables SQL ACID |
| **État de tâche** | Étape courante de chaque paiement, transitions horodatées | Table `payments` + `step_history` (JSONB) |
| **Sémantique** | Embeddings des factures et incidents passés (anti-fraude) | Indexation vectorielle distribuée |
| **Conversationnelle** | Historique des échanges et décisions | Table `conversations` |

---

## 5. Architecture technique

```
┌─────────────────────────────────────────────────────────┐
│                      UTILISATEUR                        │
│              (Interface web — chat + dashboard)         │
└──────────────────────────┬──────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │   AGENT PayGuard    │
                │  Amazon Bedrock     │
                │  (Claude — raisonne │
                │   et orchestre)     │
                └───┬──────────┬──────┘
                    │          │
        ┌───────────▼──┐   ┌───▼──────────────┐
        │  AWS Lambda  │   │  Serveur MCP     │
        │  (exécution  │   │  CockroachDB     │
        │  des étapes  │   │  (requêtes agent │
        │  de paiement,│   │  → cluster)      │
        │  relances)   │   └───┬──────────────┘
        └───────┬──────┘       │
                │              │
        ┌───────▼──────────────▼──────────────────┐
        │        COCKROACHDB CLUSTER (3 nœuds)     │
        │  • Tables transactionnelles (paiements)  │
        │  • Indexation vectorielle (factures)     │
        │  • État de tâches + audit trail          │
        └──────────────────┬───────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Amazon S3  │
                    │  (factures  │
                    │  PDF, bilans│
                    └─────────────┘
```

### Outils CockroachDB utilisés (exigence : minimum 2)

1. **Serveur MCP géré** — l'agent interroge directement le cluster (état des paiements, audit en langage naturel). Endpoint : `https://cockroachlabs.cloud/mcp`
2. **Indexation vectorielle distribuée** — embeddings des factures historiques pour la détection d'anomalies (RAG anti-fraude), sans base vectorielle séparée
3. *(Bonus)* **CLI ccloud** — l'agent surveille la santé de sa propre mémoire et peut déclencher des sauvegardes
4. *(Bonus)* **Dépôt de compétences d'agent** — skills CockroachDB pour la conception de schéma et l'observabilité

### Services AWS utilisés (exigence : minimum 1)

1. **Amazon Bedrock** — modèle de fondation (Claude) : raisonnement, vérification, dialogue
2. **AWS Lambda** — exécution serverless des étapes de paiement et des relances planifiées
3. **Amazon S3** — stockage des factures PDF et des bilans générés

---

## 6. La machine à états du paiement (cœur du projet)

```
                  ┌─────────┐
   facture reçue  │ INTENT  │  ← écrit AVANT toute action
                  └────┬────┘
                       │ vérifications OK (RAG anti-fraude, budget)
                  ┌────▼──────┐
                  │ VALIDATED │
                  └────┬──────┘
                       │ déclenchement du paiement
                  ┌────▼──────┐     crash ici ? → au redémarrage,
                  │ EXECUTING │     l'agent vérifie auprès du PSP
                  └────┬──────┘     avant toute nouvelle tentative
                       │ confirmation du prestataire de paiement
                  ┌────▼──────┐
                  │ EXECUTED  │
                  └────┬──────┘
                       │ réconciliation + écriture audit
                  ┌────▼──────┐
                  │ CONFIRMED │  état terminal
                  └───────────┘

   À tout moment : → FAILED (avec raison) ou → BLOCKED (anomalie détectée,
   validation humaine requise)
```

**Règles d'or :**
- Chaque transition est écrite dans CockroachDB **avant** l'action correspondante
- Chaque paiement porte une **clé d'idempotence unique** : toute tentative de duplication est rejetée par contrainte d'unicité
- L'agent ne garde **aucun état en RAM** : sa première action au démarrage est toujours `SELECT ... WHERE status NOT IN ('CONFIRMED','FAILED')`

### Schéma de données (simplifié)

```sql
CREATE TABLE suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name STRING NOT NULL,
  payment_account STRING NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id UUID REFERENCES suppliers(id),
  amount DECIMAL NOT NULL,
  currency STRING DEFAULT 'XOF',
  s3_key STRING,                        -- PDF dans S3
  embedding VECTOR(1024),               -- indexation vectorielle
  status STRING DEFAULT 'RECEIVED',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key STRING UNIQUE NOT NULL,   -- ⭐ anti-doublon
  invoice_id UUID REFERENCES invoices(id),
  amount DECIMAL NOT NULL,
  status STRING NOT NULL DEFAULT 'INTENT',
  step_history JSONB DEFAULT '[]',          -- transitions horodatées
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor STRING NOT NULL,                    -- 'agent' ou user id
  action STRING NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 7. Les preuves de persistance (plan de démo)

| # | Preuve | Ce qu'on montre | Ce que ça prouve |
|---|---|---|---|
| 1 | **Test d'amnésie** | Nouvelle session, contexte LLM vierge → « quels paiements as-tu faits ? » → réponse exacte | La mémoire vit dans la base, pas dans le contexte |
| 2 | **Crash de l'agent** | Kill du process en état EXECUTING → redémarrage → reprise propre, un seul paiement | Mémoire d'état + idempotence |
| 3 | **Chaos test CockroachDB** | Kill d'un nœud du cluster en pleine écriture → aucun impact, zéro perte | Disponibilité de la mémoire (thèse du hackathon) |
| 4 | **Split-screen SQL** | Console SQL en direct à côté de l'agent : les statuts changent en temps réel | L'agent ne « hallucine » pas ses souvenirs |
| 5 | **Anomalie fournisseur** | Facture avec nouveau compte bancaire → agent bloque en citant 14 factures passées | Mémoire sémantique longue durée utile |

### Script vidéo (3 minutes max)

| Temps | Séquence |
|---|---|
| 0:00 – 0:30 | Le problème : un agent qui paie et qui oublie = double paiement |
| 0:30 – 1:15 | Démo nominale en split-screen : la mémoire s'écrit en direct |
| 1:15 – 2:00 | **Kill de l'agent** en plein paiement → reprise, zéro doublon |
| 2:00 – 2:30 | **Kill d'un nœud CockroachDB** → l'agent continue sans broncher |
| 2:30 – 2:50 | Test d'amnésie + détection d'anomalie fournisseur |
| 2:50 – 3:00 | Slide architecture + punchline finale |

---

## 8. Conformité aux exigences du hackathon

| Exigence | Statut |
|---|---|
| App agentique avec CockroachDB comme couche mémoire | ✅ Cœur du projet |
| Déployée sur AWS | ✅ Bedrock + Lambda + S3 |
| ≥ 2 outils CockroachDB | ✅ MCP + vectoriel (+ ccloud en bonus) |
| ≥ 1 service AWS | ✅ 3 services |
| Dépôt public open source + licence (MIT) | ✅ À créer en Phase 0 |
| README + instructions d'installation | ✅ Rédigé en continu |
| URL de démo fonctionnelle | ✅ Phase 4 |
| Vidéo < 3 min (YouTube/Vimeo) | ✅ Script prêt, tournage Phase 5 |
| Explication des outils utilisés | ✅ Section dédiée du README |
| Schéma d'architecture (facultatif) | ✅ Inclus |
| Feedback sur les outils IA CockroachDB (facultatif) | ✅ À rédiger pendant le build |

---

## 9. Roadmap

> Planning en 5 phases sur ~4 semaines. À recaler dès que la deadline exacte du hackathon est confirmée — toujours garder **une marge de 3-4 jours avant la soumission**.

### Phase 0 — Fondations (Jours 1-2)

- [ ] Créer le compte CockroachDB Cloud (cluster gratuit 3 nœuds) et le compte AWS
- [ ] Activer le serveur MCP depuis la console CockroachDB Cloud, tester la connexion
- [ ] Créer le dépôt GitHub public, licence MIT visible, README squelette
- [ ] Vérifier l'accès Bedrock (Claude) et créer le bucket S3
- [ ] Poser l'architecture du repo (backend agent / lambdas / frontend / infra)

**Livrable : environnement complet opérationnel, "hello world" agent ↔ CockroachDB via MCP.**

### Phase 1 — Le cœur mémoire (Jours 3-7)

- [ ] Implémenter le schéma SQL complet (suppliers, invoices, payments, audit_log)
- [ ] Coder la machine à états avec écriture write-ahead et clé d'idempotence
- [ ] Simulateur de PSP (prestataire de paiement fictif) avec latence et pannes simulables
- [ ] Logique de reprise au démarrage : détection des paiements orphelins + résolution
- [ ] **Tests de crash automatisés** : kill du process à chaque étape → vérifier zéro doublon

**Livrable : moteur de paiement idempotent prouvé par des tests — sans IA encore. C'est la fondation ; si elle est solide, tout le reste suit.**

### Phase 2 — L'agent intelligent (Jours 8-13)

- [ ] Intégrer Bedrock (Claude) : boucle agentique avec outils (créer paiement, consulter état, requêter l'audit)
- [ ] Connecter le serveur MCP CockroachDB comme source de vérité de l'agent
- [ ] Pipeline d'ingestion de factures : upload S3 → extraction → embedding → indexation vectorielle
- [ ] RAG anti-fraude : comparaison de chaque nouvelle facture à l'historique vectoriel
- [ ] Audit en langage naturel (« paiements de mars > 100k »)
- [ ] Lambdas : exécution des étapes de paiement + relances planifiées

**Livrable : agent complet fonctionnel de bout en bout.**

### Phase 3 — Interface & chaos (Jours 14-18)

- [ ] Interface web : chat avec l'agent + dashboard des paiements en temps réel
- [ ] Vue "mémoire en direct" (les statuts qui changent — l'équivalent du split-screen)
- [ ] Jeu de données de démo réaliste : ~15 fournisseurs, ~60 factures historiques, dont anomalies
- [ ] Répéter les 5 preuves de persistance manuellement jusqu'à fiabilité totale
- [ ] Chaos test CockroachDB : procédure de kill d'un nœud documentée et répétable

**Livrable : démo complète exécutable en moins de 5 minutes, à la demande.**

### Phase 4 — Déploiement & documentation (Jours 19-22)

- [ ] Déploiement production sur AWS (URL publique de démo)
- [ ] README final : installation, architecture, outils utilisés et comment, exemples
- [ ] Schéma d'architecture propre (diagramme soigné)
- [ ] Rédiger le feedback sur les outils IA CockroachDB (point facultatif = points bonus)
- [ ] Revue de code, nettoyage du repo, vérification licence visible

**Livrable : projet soumissible tel quel.**

### Phase 5 — Vidéo & soumission (Jours 23-26)

- [ ] Tournage de la vidéo selon le script (plusieurs prises du chaos test !)
- [ ] Montage < 3 min, upload YouTube en public
- [ ] Remplir le formulaire de soumission (Devpost) : repo, démo URL, vidéo, descriptions
- [ ] **Soumettre 2-3 jours avant la deadline** (jamais le dernier jour)

**Livrable : soumission complète et validée.**

---

## 10. Risques & parades

| Risque | Parade |
|---|---|
| Vrais paiements impossibles en démo | PSP simulé (mock) — assumé et expliqué ; le cœur démontré est la mémoire, pas le PSP |
| Chaos test qui échoue en direct | Répéter la procédure 10× avant tournage ; la vidéo permet plusieurs prises |
| Coûts AWS/Bedrock | Free tier + cluster CockroachDB gratuit ; couper les ressources hors démo |
| Manque de temps | La Phase 1 (moteur idempotent) est le minimum vital — le RAG anti-fraude peut être simplifié si nécessaire |
| Deadline inconnue | Vérifier la page du hackathon dès maintenant et recaler la roadmap |

---

## 11. Stack technique proposée

- **Agent** : Python (ou TypeScript) + SDK Bedrock, boucle agentique avec tool use
- **Mémoire** : CockroachDB Cloud (serverless/dedicated, 3 nœuds) — SQL + VECTOR
- **Connexion agent ↔ DB** : serveur MCP géré CockroachDB + driver PostgreSQL
- **Exécution** : AWS Lambda (étapes de paiement, relances)
- **Stockage** : Amazon S3 (factures, bilans)
- **Frontend** : React (chat + dashboard temps réel)
- **CI/CD** : GitHub Actions (tests de crash automatisés à chaque commit — argument DevOps en plus)

---

*Document de travail — PayGuard, Hackathon CockroachDB × AWS 2026*
