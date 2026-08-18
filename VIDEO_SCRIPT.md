# 🎬 Script vidéo PayGuard (< 3 min) — commandes exactes

> Setup : 2 terminaux côte à côte. Terminal DROIT : `python -m payguard status`
> (la vue mémoire live, lancée AVANT de commencer). Terminal GAUCHE : les commandes.
> Enregistrer avec OBS ou l'enregistreur d'écran Windows (Win+Alt+R).
> Faire PLUSIEURS prises, garder la meilleure. Parler en continu, débit rapide.

## 0:00 – 0:25 — Le problème (slide ou webcam)
« Un agent IA qui paie des factures a un risque mortel : il envoie le virement,
crashe avant de l'enregistrer, et au redémarrage… il repaie. PayGuard rend le
double paiement structurellement impossible : toute sa mémoire vit dans
CockroachDB, écrite AVANT chaque action. »

## 0:25 – 1:00 — Démo nominale en split-screen
Terminal gauche :
```
python -m payguard pay <ID_FACTURE_PROPRE>
```
Montrer à droite les statuts qui défilent en live : INTENT → VALIDATED →
EXECUTING → EXECUTED → CONFIRMED.
« Chaque transition est écrite dans CockroachDB avant l'action. Le terminal de
droite lit directement la base : l'agent n'hallucine pas ses souvenirs. »

## 1:00 – 1:45 — LE crash test (le moment fort)
```
$env:CRASH_AT = "AFTER_PSP_CALL"
python -m payguard pay <ID_FACTURE_PROPRE_2>
```
« Le process vient de MOURIR juste après l'envoi de l'argent — la base ne le
sait pas encore. Le pire scénario. On redémarre : »
```
$env:CRASH_AT = ""
python -m payguard recover
```
« L'agent relit son état, interroge le PSP AVANT tout retry : le paiement était
parti → il complète sans repayer. » Montrer la preuve :
```
python -m pytest tests/ -v
```
(ou l'avoir lancé avant et montrer le résultat : 6 passed — le process est tué
à CHAQUE étape, le fournisseur est payé exactement une fois, toujours.)

## 1:45 – 2:15 — Test d'amnésie + fraude
Nouveau terminal, contexte LLM vierge :
```
python -m payguard chat
you> quels paiements as-tu faits ?
```
« Session neuve, zéro contexte : la réponse vient de la base. »
```
you> paie la facture du Fournisseur BTP Yamoussoukro
```
→ BLOCKED : « payé 14 fois sur CI-BANK-0002-8832, cette facture demande
CI-BANK-9999-0666 ». « La mémoire sémantique longue durée qui évite une vraie
fraude. »

**Plan B si Bedrock est à sec (quota)** : remplacer cette séquence par la
détection de fraude via le moteur (`python -m payguard pay <ID_FRAUDE>` →
BLOCKED avec le message complet) + une requête en langage naturel via le
serveur MCP CockroachDB dans Claude/Cursor.

## 2:15 – 2:40 — La thèse CockroachDB
Montrer la console CockroachDB Cloud (le cluster, la table payments).
« La mémoire survit aussi côté base : CockroachDB réplique chaque écriture sur
plusieurs nœuds — un nœud tombe, l'agent continue. Et le serveur MCP géré permet
d'auditer la mémoire de l'agent en langage naturel, sans lui faire confiance. »

## 2:40 – 3:00 — Close
Slide architecture (reprendre l'ASCII du README mis au propre).
« PayGuard : Bedrock pour raisonner, Lambda pour exécuter, CockroachDB pour ne
jamais oublier. Aucun paiement perdu. Aucun paiement dupliqué. Jamais. »

---
### IDs utiles (cluster actuel)
- PROPRES : `05dcd9a6-50d2-497a-bea4-810c09fe70d4` (Imprimerie, 85 000),
  `18441477-2ac1-4542-a752-f9850ba7099b` (Sankara Tech, 320 000),
  `9a6424a7-cd69-408c-8d6e-6492c331ac89` (ProClean, 85 000),
  `2096145a-a67a-4d82-b306-e4275d509ec5` (Orange CI, 150 000)
- FRAUDE (déjà BLOCKED une fois — pour la re-démo, montrer le statut ou
  re-seeder) : `12f112ee-d673-461a-88af-cc2744d404b8`
