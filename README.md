# VitalTrack

Plateforme PWA Mobile-First de suivi quotidien du poids, d'estimation calorique et macronutritionnelle par photo d'assiette et de synchronisation biométrique avec objets connectés de santé.

## Architecture & Modules

### 1. Vision & Nutrition IA (`src/vision_nutrition.py`)
- **Mode Multimodal Gemini Vision (`gemini-2.5-flash`)** : Analyse fine de clichés d'assiettes avec prompt structuré JSON renvoyant aliments détectés, portions estimées en grammes, calories, protéines, glucides, lipides, fibres et conseil diététique.
- **Mode Déterministe Hybride Hors-ligne & Démo** :
  - Base nutritionnelle locale riche d'aliments et plats complets français et internationaux.
  - Recherche en fallback sur l'API publique OpenFoodFacts (`search_openfoodfacts`).
- **Multiplicateur de Portion Interactif (`portion_scale`)** : Ajustement dynamique de `0.5x` à `2.0x`.

### 2. Journal des Repas & Bilan Métabolique (`src/nutrition_engine.py`)
- Suivi structuré par repas : `breakfast` (Petit-déjeuner), `lunch` (Déjeuner), `dinner` (Dîner), `snack` (Collation).
- Agrégation quotidienne des calories et pourcentages de macronutriments (Protéines / Glucides / Lipides).
- Calcul du **BMR** selon la formule validée de **Mifflin-St Jeor** (poids, taille, âge, sexe).
- Calcul de la Dépense Énergétique Totale (**TDEE** = BMR + Pas + Exercice actif).
- Calcul du **Bilan Énergétique Net** (`Calories Ingérées - Dépenses Totales`) et projection de gain/perte de poids hebdomadaire (`kg/semaine`).

### 3. Connecteurs Objets Connectés & IoT Santé (`src/connectors/`)
- Connecteur Withings Scale v2 (poids, masse grasse %, masse musculaire kg, eau %, IMC).
- Connecteur Oura Ring v2 (pas, calories actives, score de sommeil, VRC / HRV ms, fréquence cardiaque au repos).
- Connecteur Universel Mobile Webhook (Apple Santé / Health Connect).

### 4. Base de Données & Persistance SQLite (`src/db.py`)
- Schéma multi-tables : `weights`, `activities`, `meals`.
- Tendance glissante lissée sur 7 jours (EMA/SMA).
- Pré-chargement automatique d'un jeu de données réaliste sur 30 jours (pesées et activités) et 7 jours de repas détaillés lors de l'initialisation.

### 5. Application PWA Mobile-First & Dashboards (`static/index.html`, `src/app.py`, `api/index.py`)
- **FastAPI Backend Serverless** : endpoints unifiés `/api/dashboard`, `/api/weights`, `/api/activities`, `/api/meals`, `/api/meals/estimate`, `/api/devices`.
- **5 Vues de Dashboards Interactifs (Chart.js & Tailwind CSS)** :
  1. *Synthèse Quotidienne & Balance Énergétique* : Jauges poids/7j, calories in vs out, TDEE, déficit/surplus net, pas, donut de macronutriments P/G/L.
  2. *Suivi du Poids & Composition Corporelle* : Pesées quotidiennes réelles + tendance lissée 7 jours + cible de poids + cartes impédancemétrie (% masse grasse, masse musculaire, % hydratation, IMC).
  3. *Journal Alimentaire & Calories par Repas* : Barres empilées par repas (Petit-déjeuner, Déjeuner, Dîner, Collation) sur 7 jours avec ligne cible 2000 kcal, liste détaillée des repas avec miniatures.
  4. *Pas, Exercice & Bague Connectée* : Graphique combiné pas quotidiens et calories actives, cartes biométriques (score de sommeil, fréquence cardiaque repos, HRV ms).
  5. *Hub Objets Connectés* : Statut des balances (Withings/Garmin), bague (Oura Ring) et webhooks (Apple Santé / Health Connect) avec simulation et déclencheur de synchronisation.
- **Action Rapide Mobile 1-Clic** : Upload photo appareil photo smartphone (`capture="environment"`), détection IA d'aliments, curseur de portion interactif `0.5x` - `2.0x` et enregistrement direct.
## Architecture de Persistance Hybride & Base de Données Cloud (Neon Serverless)

VitalTrack propose un connecteur universel (`src/db.py`) adapté aux déploiements Serverless et au développement local :
1. **Production Cloud (Neon PostgreSQL Serverless)** :
   - Détection automatique via `DATABASE_URL` ou `POSTGRES_URL` (avec gestion de `sslmode=require` et pooling adapté à PGBouncer / Vercel cold-starts).
   - Architecture relationnelle multi-utilisateurs avec tables `users`, `user_profile`, `weights`, `activities`, `meals`, `user_devices` associées par clé étrangère `user_id`.
   - Indexation optimisée composite sur `(user_id, date DESC)`.
2. **Fallback Développement Local & Tests (SQLite)** :
   - Bascule automatique transparente sur SQLite (`data/vitaltrack.db` ou base temporaire) si aucune variable d'environnement PostgreSQL n'est fournie.
   - 100% autonome et immédiat pour `pytest` et le travail hors-ligne.

### Guide de Connexion Neon sur Vercel (1 Clic)
1. Rendez-vous sur votre projet sur le tableau de bord **Vercel**.
2. Allez dans l'onglet **Storage** puis sélectionnez l'intégration **Neon (Postgres Serverless)**.
3. Cliquez sur **Connect Store** : Vercel injecte automatiquement les variables d'environnement `POSTGRES_URL` et `DATABASE_URL` avec pooling activé.
4. Redéployez votre application : les migrations et schémas relationnels s'initialisent de façon idempotente dès la première requête.

## Déploiement Vercel Serverless

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FTheBigBad31%2FVitalTrack&project-name=vitaltrack&repository-name=vitaltrack)

VitalTrack est optimisé pour un déploiement Vercel Serverless sans configuration complexe :
- **Fichier de configuration** : `vercel.json` (réécriture des routes `/api/(.*)` vers `api/index.py` et `/` vers `static/index.html`).
- **Persistance Serverless** : Base PostgreSQL Neon en production ou fallback SQLite dans `/tmp/vitaltrack.db` sur les lambdas avec seed de 30 jours de pesées et d'activités démo.
- **Variables d'environnement (production)** :
  - `DATABASE_URL` / `POSTGRES_URL` : Chaîne de connexion PostgreSQL Serverless Neon (SSL activé).
  - `JWT_SECRET` (**obligatoire en production**) : Clé secrète pour la signature des jetons de session JWT (HS256). Une `RuntimeError` (`MissingJWTSecretError`) est levée au démarrage si elle est absente lorsque `VERCEL=1` ou `ENV=production` / `ENVIRONMENT=production`. En développement local, une clé aléatoire éphémère est générée automatiquement.
  - `DATA_ENCRYPTION_KEY` (**obligatoire en production**, ou fallback `SECRET_KEY`) : Clé maîtresse pour le chiffrement symétrique au repos (Fernet AES-128-CBC + HMAC-SHA256) des clés d'API et jetons d'objets connectés. Une `RuntimeError` (`MissingEncryptionKeyError`) est levée au démarrage si elle est absente en production. En développement local, une clé aléatoire éphémère est générée automatiquement.
  - `GOOGLE_CLIENT_ID` : Client ID OAuth 2.0 pour Google Identity Services (GIS).
  - `GEMINI_API_KEY` : Clé API Google Gemini Vision pour l'analyse photo multimodale temps réel.
  - `WITHINGS_CLIENT_ID` & `WITHINGS_ACCESS_TOKEN` : Identifiants API OAuth Withings.
  - `OURA_PERSONAL_ACCESS_TOKEN` : Token personnel Oura Ring Cloud API v2.

## Démarrage Local

```bash
uv run uvicorn src.app:app --reload --port 8000
```
Ouvrir ensuite `http://localhost:8000` sur navigateur ou smartphone (PWA).

## Tests Unitaires & CI/CD

```bash
uv run pytest
```

Les workflows GitHub Actions (`.github/workflows/ci.yml` et `.github/workflows/daily-sync.yml`) assurent :
1. **CI Test Suite** : Exécution automatique de la suite de tests `pytest` (40 tests validés à 100%) à chaque push ou Pull Request sur `main`.
2. **Daily Health Sensors Sync** : Synchronisation planifiée quotidienne (cron `0 6 * * *`) des capteurs Withings et Oura Ring.


