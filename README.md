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

## Tests Unitaires

```bash
uv run --extra dev pytest
```
