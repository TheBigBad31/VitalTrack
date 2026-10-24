# Spécification UI/UX & Design System VitalTrack (Nuit Indigo / Violet)

Ce document établit la spécification complète de la nouvelle identité visuelle, du système de tokens CSS / Tailwind et de l'architecture d'information réorganisée en **6 vues clés** pour l'application VitalTrack.

---

## 1. Nouvelle Palette & Tokens CSS (Nuit Indigo / Violet)

L'ancienne charte basée sur un vert émeraude omniprésent évolue vers un univers nocturne, technologique, élégant et premium, centré sur une base **Nuit Indigo** magnifiée par un dégradé signature **Violet Électrique** et des accents contrastés.

### 1.1 Variables CSS (`tokens.css`)

```css
:root {
  /* Surfaces & Fonds (Dark Mode par défaut) */
  --bg-primary: #0B0B1A;         /* Nuit indigo profonde */
  --surface-primary: #14142B;    /* Surface cartes et conteneurs */
  --surface-secondary: #1E1E38;  /* Éléments surélevés / inputs */
  --surface-hover: #26264A;      /* États hover */
  --border-subtle: #25254A;      /* Bordures de base */
  --border-focus: #7C3AED;       /* Bordures focus / actives */

  /* Couleurs Primaires & Dégradés */
  --primary-purple: #7C3AED;     /* Violet vibrant */
  --primary-blue: #2563FF;       /* Bleu électrique */
  --gradient-primary: linear-gradient(135deg, #7C3AED 0%, #2563FF 100%);
  --gradient-accent: linear-gradient(135deg, #22D3EE 0%, #7C3AED 100%);
  --gradient-magenta: linear-gradient(135deg, #C026D3 0%, #7C3AED 100%);

  /* Accents & Statuts */
  --accent-cyan: #22D3EE;        /* Cyan électrique (infos, trackers, eau) */
  --accent-magenta: #C026D3;     /* Magenta / Fuchsia (objectifs, highlights) */
  --status-success: #10B981;     /* Vert validation / synchro */
  --status-warning: #F59E0B;     /* Orange alerte */
  --status-danger: #EF4444;      /* Rouge erreur / déficit critique */

  /* Typographie & Textes */
  --text-primary: #F8FAFC;       /* Titres et textes forts */
  --text-secondary: #94A3B8;     /* Libellés, unités, métadonnées */
  --text-muted: #64748B;         /* Textes tertiaires, placeholders */

  /* Glassmorphism & Effets */
  --glass-bg: rgba(20, 20, 43, 0.75);
  --glass-blur: blur(16px);
  --glass-border: 1px solid rgba(124, 58, 237, 0.20);
  --shadow-glow-purple: 0 8px 32px -4px rgba(124, 58, 237, 0.25);
  --shadow-glow-blue: 0 8px 32px -4px rgba(37, 99, 255, 0.25);
  --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.4);
}
```

### 1.2 Configuration Tailwind CSS (`tailwind.config.js`)

```javascript
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        night: {
          bg: '#0B0B1A',
          card: '#14142B',
          elevated: '#1E1E38',
          border: '#25254A',
          hover: '#26264A'
        },
        primary: {
          violet: '#7C3AED',
          blue: '#2563FF'
        },
        accent: {
          cyan: '#22D3EE',
          magenta: '#C026D3'
        }
      },
      backgroundImage: {
        'gradient-vital': 'linear-gradient(135deg, #7C3AED 0%, #2563FF 100%)',
        'gradient-cyan-violet': 'linear-gradient(135deg, #22D3EE 0%, #7C3AED 100%)',
        'gradient-magenta-violet': 'linear-gradient(135deg, #C026D3 0%, #7C3AED 100%)'
      },
      boxShadow: {
        'glow-violet': '0 0 25px -5px rgba(124, 58, 237, 0.35)',
        'glow-blue': '0 0 25px -5px rgba(37, 99, 255, 0.35)',
        'glow-cyan': '0 0 20px -5px rgba(34, 211, 238, 0.35)'
      }
    }
  }
}
```

---

## 2. Nouvelle Organisation des 6 Vues & Parcours

La barre de navigation desktop et la bottom-bar mobile passent à **6 vues logiques** :

| # | Onglet (`tabId`) | Icône Lucide | Rôle & Contenu Principal |
|---|---|---|---|
| 1 | `summary` (Aujourd'hui) | `layout-dashboard` | Vue d'accueil : 4 KPI du jour (Poids du jour, Kcal consommées vs cibles, Pas, Score Sommeil), carte **Prochain Repas**, badge statut synchronisation des objets connectés. |
| 2 | `weight` (Corps) | `scale` | Suivi impédancemétrie complet : Poids, Masse Grasse (%), Masse Musculaire (kg), Eau corporelle, IMC, graphique de tendance pondérale 7j/30j/90j et objectifs de recomposition corporelle. |
| 3 | `nutrition` (Nutrition) | `utensils` | **Vue active par défaut** : Journal alimentaire des 4 repas (Petit déjeuner, Déjeuner, Goûter, Dîner), macro-nutriments en direct, Catalogue d'aliments et Plats enregistrés avec Drag & Drop desktop. |
| 4 | `activity` (Activité & Santé) | `activity` | Biométrie et mouvements : Pas, Calories actives, Score de Sommeil, HRV (Variabilité de fréquence cardiaque), Fréquence Cardiaque au repos (Withings / Oura / RingConn / Health Connect). |
| 5 | `goals` (Objectifs) | `target` | Profil métabolique de l'utilisateur : BMR, TDEE, déficit/surplus calorique cible, répartition des macros (Protéines, Glucides, Lipides), suivi des jalons de transformation. |
| 6 | `devices` (Appareils & Données) | `cpu` | Hub des connecteurs matériels (Withings, RingConn, Oura, Garmin, Apple Health, Health Connect), journal des webhooks, synchronisation manuelle 1-clic et sauvegardes de données. |

---

## 3. Ergonomie Web Desktop & Drag & Drop Natif

Sur grand écran (desktop / laptop), l'espace horizontal est exploité par un layout bi-colonne asymétrique optimisé pour la vitesse de saisie :

```
+-------------------------------------------------------------------------------------------------------------+
|  HEADER (VitalTrack PWA, Profil, Statut Connecteurs, Actions Rapides: +Photo Repas, +Pesée, Rafraîchir)      |
+-------------------------------------------------------------------------------------------------------------+
|  NAV TABS: [1. Aujourd'hui] [2. Corps] [★ 3. Nutrition] [4. Activité] [5. Objectifs] [6. Appareils]         |
+-------------------------------------------------------------------------------------------------------------+
|                                                                                                             |
|  [ VOLET GAUCHE (Catalogue / Plats) : 380px ]  |  [ VOLET DROIT (Les 4 Repas & Macros) : Flex-1 ]            |
|  - Barre de recherche instantanée (raccourci /) |  - Barres de progression Macros en sticky bar              |
|  - Filtres rapides (Favoris, Petit-dèj, Recettes) |  - Grille modulaire des 4 Repas :                          |
|  - Liste de cartes d'aliments glissables :       |    ┌────────────────────────┐  ┌────────────────────────┐ |
|    ┌─────────────────────────────────────────┐  |    │ ☕ Petit Déjeuner       │  │ 🥗 Déjeuner            │ |
|    │ 🥪 Omelette Avoine & Baies  (380 kcal)  │  |    │ [ Drop Zone Réactive ] │  │ [ Drop Zone Réactive ] │ |
|    │ [Drag Handle] [Tooltip Macros] [+]     │  |    └────────────────────────┘  └────────────────────────┘ |
|    └─────────────────────────────────────────┘  |    ┌────────────────────────┐  ┌────────────────────────┐ |
|    (Ghost preview semi-transparente au drag)    |    │ 🍎 Goûter / Collation  │  │ 🍲 Dîner               │ |
|                                                 |    │ [ Drop Zone Réactive ] │  │ [ Drop Zone Réactive ] │ |
|                                                 |    └────────────────────────┘  └────────────────────────┘ |
+-------------------------------------------------------------------------------------------------------------+
```

### Directives d'Implémentation Drag & Drop
1. **Événements Drag & Drop HTML5** :
   - `draggable="true"` sur les cartes d'aliments et plats du catalogue.
   - `dragstart` : Transmission des données de l'aliment via `event.dataTransfer.setData('application/json', ...)`. Définition de la ghost preview semi-transparente avec opacité 0.75.
   - `dragover` : `event.preventDefault()` sur les drop zones des repas avec ajout de la classe visuelle `.drop-zone-active` (bordure pointillée cyan `#22D3EE` et fond `rgba(124, 58, 237, 0.12)`).
   - `dragleave` : Retrait immédiat de la classe visuelle.
   - `drop` : Réception du payload, ouverture automatique de la pop-in rapide de saisie de quantité (avec focus immédiat sur l'input et touche `Entrée` pour valider).
2. **Accessibilité & Confort Souris/Clavier** :
   - Présence d'un bouton direct `+` sur chaque carte du catalogue pour permettre l'ajout instantané en 1 clic sans obligation de glisser.
   - Navigation clavier intégrale avec focus ring visible (`focus:ring-2 focus:ring-[#7C3AED]`).

---

## 4. Plan d'Intégration Frontend & Étapes de Déploiement

### Phase 1 : Remplacement des Tokens CSS & Configuration Tailwind
- Mettre à jour `tailwind.config` dans `static/index.html` pour intégrer la palette `night`, `primary` et `accent`.
- Adapter les styles de base du `<body>`, des barres de navigation et des cartes (`bg-[#0B0B1A]`, cartes en `#14142B`, bordures `#25254A`).
- Remplacer les dégradés émeraude par le dégradé signature Violet vers Bleu électrique `linear-gradient(135deg, #7C3AED 0%, #2563FF 100%)`.

### Phase 2 : Restructuration de la Navigation en 6 Onglets
- Mettre à jour `<nav>` Desktop et Mobile pour déclarer les 6 boutons :
  - `tab-summary` (Aujourd'hui)
  - `tab-weight` (Corps)
  - `tab-nutrition` (Nutrition - actif par défaut)
  - `tab-activity` (Activité & Santé)
  - `tab-goals` (Objectifs)
  - `tab-devices` (Appareils & Données)
- Créer les sections correspondantes `<section id="view-goals">` en y déplaçant les cartes de cibles caloriques et profils métaboliques précédemment dispersées.
- Enrichir la fonction JavaScript `switchTab(tabId)` pour supporter les 6 vues de manière fluide avec mise en valeur de l'onglet actif aux couleurs violettes/bleues.

### Phase 3 : Validation & Contrôle Qualité
- Vérification de la compatibilité responsive (Mobile First PWA & Web Desktop large écran).
- Validation du contraste W3C AA/AAA (texte `#F8FAFC` sur fond `#14142B` / `#0B0B1A` offrant un ratio supérieur à 12:1).
- Test des interactions Drag & Drop et des modales de saisie rapide.
