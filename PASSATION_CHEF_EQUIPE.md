# 🎯 Passation — il ne reste que la vidéo et le formulaire Devpost

> Tout le code est **fini, testé et validé** contre le vrai cluster CockroachDB Cloud :
> les 6 tests de crash passent (`6 passed`), la fraude est bien BLOCKED, les données
> démo sont en base, les documents sont dans S3. Il ne reste que la **livraison**.

## 1️⃣ Installer l'environnement (5 min)

```powershell
git pull
pip install -r requirements.txt
```

Puis colle le fichier **`.env`** (envoyé en privé, jamais commité) à la racine du repo.

⚠️ **UNE modification obligatoire dans le `.env`** : dans `DATABASE_URL`, le paramètre
`sslrootcert=...` pointe vers un chemin **propre à chaque machine**. Récupère le tien avec :
```powershell
python -c "import certifi; print(certifi.where())"
```
et remplace le chemin après `sslrootcert=` par ce résultat (garde des `/`, pas des `\`).

Vérification rapide que tout est branché :
```powershell
python -m payguard status     # doit afficher le tableau des paiements du cluster
```

## 2️⃣ Tourner la vidéo (< 3 min) — LE livrable manquant

👉 **Tout est dans [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md)** : script minuté, texte à dire,
et les commandes avec les **vrais IDs de factures** déjà insérés (copier-coller direct).

Points d'attention :
- Lance `python -m payguard status` dans un 2e terminal AVANT de commencer (split-screen).
- Chaque facture propre ne se paie qu'**une seule fois** (c'est l'idempotence !). Il reste
  2 factures de rechange, listées en bas du script. Si tu les épuises en répétant,
  demande à Claude (ou relance `python -m payguard seed` après avoir vidé les tables).
- **Bedrock (le chat `python -m payguard chat`) est peut-être encore en quota épuisé**
  ("Too many tokens per day" au niveau du compte AWS). Réessaie avant de tourner —
  le quota se réinitialise vers minuit UTC. Si toujours bloqué : le **plan B est écrit
  dans le script** (démo fraude via le moteur + audit en langage naturel via le serveur
  MCP CockroachDB configuré dans `.mcp.json`). La soumission reste 100 % valide :
  Bedrock est intégré dans le code, et Lambda + S3 couvrent l'exigence AWS.
- Upload YouTube en **PUBLIC** (exigence du hackathon).

## 3️⃣ Remplir Devpost (15 min)

👉 **Tout le texte est pré-rédigé dans [`DEVPOST_SUBMISSION.md`](DEVPOST_SUBMISSION.md)** :
pitch, description complète, sections "CockroachDB tools used" / "AWS services used", tags.

À faire :
1. Copier-coller chaque section dans le formulaire.
2. Remplacer `<YOUTUBE_URL_HERE>` par le lien de la vidéo.
3. Lien repo : https://github.com/YannDOm07/HackPayGuard
4. **Vérifier que le repo est PUBLIC** (Settings → General → visibility) — licence MIT déjà à la racine.
5. Soumettre **avec de la marge**, pas à la dernière minute.

## 4️⃣ Après la soumission — sécurité (5 min, important)

Les clés AWS et le mot de passe CockroachDB ont circulé en clair entre nous :
- Console AWS IAM → créer une nouvelle access key, **désactiver l'ancienne**.
- Console CockroachDB Cloud → changer le mot de passe SQL de l'utilisateur `algodemo`.

## 📁 Carte des fichiers

| Fichier | Rôle |
|---|---|
| `VIDEO_SCRIPT.md` | Script vidéo minuté, commandes + IDs réels, plan B Bedrock |
| `DEVPOST_SUBMISSION.md` | Texte complet du formulaire Devpost, prêt à coller |
| `README.md` | README de soumission (EN) — les juges le liront |
| `EQUIPE_ETAT_ET_ACTIONS.md` | État détaillé du projet (historique) |
| `tests/test_crash.py` | La preuve : `python -m pytest tests/ -v` → 6 passed |
| `.mcp.json` | Config du serveur MCP CockroachDB (outil n°2 exigé) |
| `.env.example` | Modèle du `.env` (le vrai est envoyé en privé) |

Bonne chance chef — le projet est béton, il n'y a plus qu'à le montrer. 🚀
