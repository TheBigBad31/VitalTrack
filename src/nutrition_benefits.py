"""Référentiel NutritionScore (EFSA / ANSES) et moteur de règles déterministe.

Encode les 21 bienfaits répartis sur 8 domaines du référentiel NutritionScore
et applique les seuils de déclenchement EFSA / ANSES sur les macronutriments
et aliments détectés.
"""

from typing import Any, Dict, List, Optional, Sequence

# Référentiel complet des 21 bienfaits (8 domaines)
NUTRITION_BENEFITS_REFERENTIAL: Dict[str, Dict[str, str]] = {
    # 1. Santé Cardiovasculaire & Vasculaire
    "Protection cardiovasculaire": {
        "tag": "Protection cardiovasculaire",
        "category": "Santé Cardiovasculaire & Vasculaire",
        "description": "Maintien du bon fonctionnement du cœur et du système circulatoire global.",
    },
    "Régulation du cholestérol (Hypocholestérolémiant)": {
        "tag": "Régulation du cholestérol (Hypocholestérolémiant)",
        "category": "Santé Cardiovasculaire & Vasculaire",
        "description": "Baisse ou maintien à un niveau normal du cholestérol LDL sanguin (phytostérols, bêta-glucanes, graisses insaturées).",
    },
    "Contrôle de la pression artérielle (Santé tensionnelle)": {
        "tag": "Contrôle de la pression artérielle (Santé tensionnelle)",
        "category": "Santé Cardiovasculaire & Vasculaire",
        "description": "Maintien d'une pression artérielle normale et baisse de la pression systolique (modération du sodium, polyphénols).",
    },
    "Élastification et souplesse vasculaire": {
        "tag": "Élastification et souplesse vasculaire",
        "category": "Santé Cardiovasculaire & Vasculaire",
        "description": "Amélioration de la capacité de dilatation et de la souplesse des vaisseaux sanguins (noix/oléagineux).",
    },
    # 2. Métabolisme & Glycémie
    "Régulation glycémique": {
        "tag": "Régulation glycémique",
        "category": "Métabolisme & Glycémie",
        "description": "Atténuation de la réponse glycémique postprandiale (réduction du pic de sucre sanguin après le repas).",
    },
    "Satiété et contrôle de l'appétit": {
        "tag": "Satiété et contrôle de l'appétit",
        "category": "Métabolisme & Glycémie",
        "description": "Maintien d'une sensation de rassasiement prolongée et diminution des fringales (fibres et protéines).",
    },
    "Soutien du métabolisme énergétique": {
        "tag": "Soutien du métabolisme énergétique",
        "category": "Métabolisme & Glycémie",
        "description": "Maintien du métabolisme basal et conversion optimale des macronutriments en énergie.",
    },
    # 3. Digestion, Microbiote & Foie
    "Transit et confort intestinal": {
        "tag": "Transit et confort intestinal",
        "category": "Digestion, Microbiote & Foie",
        "description": "Stimulation de la motilité digestive et régulation du transit par les fibres végétales.",
    },
    "Soutien du microbiote (Effet prébiotique / probiotique)": {
        "tag": "Soutien du microbiote (Effet prébiotique / probiotique)",
        "category": "Digestion, Microbiote & Foie",
        "description": "Équilibre et enrichissement de la flore microbienne intestinale.",
    },
    "Soutien de la fonction hépatique": {
        "tag": "Soutien de la fonction hépatique",
        "category": "Digestion, Microbiote & Foie",
        "description": "Protection du foie et facilitation des fonctions d'élimination de l'organisme.",
    },
    # 4. Système Osseux, Musculaire & Articulaire
    "Maintien de la santé osseuse": {
        "tag": "Maintien de la santé osseuse",
        "category": "Système Osseux, Musculaire & Articulaire",
        "description": "Renforcement, minéralisation et maintien de la densité de la structure osseuse (calcium, vitamine D).",
    },
    "Fonction musculaire et récupération": {
        "tag": "Fonction musculaire et récupération",
        "category": "Système Osseux, Musculaire & Articulaire",
        "description": "Soutien de la contraction musculaire normale et préservation de la masse musculaire (protéines, magnésium).",
    },
    # 5. Immunité & Protection Cellulaire
    "Renforcement immunitaire": {
        "tag": "Renforcement immunitaire",
        "category": "Immunité & Protection Cellulaire",
        "description": "Soutien des défenses naturelles de l'organisme (vitamines C, D, zinc, sélénium).",
    },
    "Protection contre le stress oxydatif (Antioxydant)": {
        "tag": "Protection contre le stress oxydatif (Antioxydant)",
        "category": "Immunité & Protection Cellulaire",
        "description": "Neutralisation des radicaux libres et protection des cellules contre le dommage oxydatif.",
    },
    # 6. Hydratation & Équilibre Minéral
    "Hydratation cellulaire et tissulaire": {
        "tag": "Hydratation cellulaire et tissulaire",
        "category": "Hydratation & Équilibre Minéral",
        "description": "Maintien de l'équilibre hydrique corporel et de l'hydratation des tissus (aliments riches en eau > 85 %).",
    },
    "Équilibre électrolytique": {
        "tag": "Équilibre électrolytique",
        "category": "Hydratation & Équilibre Minéral",
        "description": "Maintien de la balance minérale et ionique dans les fluides corporels (potassium, magnésium).",
    },
    # 7. Cognition, Vision & Système Nerveux
    "Soutien des fonctions cognitives et cérébrales": {
        "tag": "Soutien des fonctions cognitives et cérébrales",
        "category": "Cognition, Vision & Système Nerveux",
        "description": "Préservation de la mémoire, de la concentration et des capacités d'apprentissage (oméga-3, vitamines B).",
    },
    "Santé du système nerveux": {
        "tag": "Santé du système nerveux",
        "category": "Cognition, Vision & Système Nerveux",
        "description": "Soutien du fonctionnement nerveux normal et de la transmission des influx.",
    },
    "Maintien de la vision": {
        "tag": "Maintien de la vision",
        "category": "Cognition, Vision & Système Nerveux",
        "description": "Préservation de la santé oculaire et de la fonction visuelle normale (vitamine A, lutéine).",
    },
    # 8. Santé Bucco-Dentaire & Cutanée
    "Santé bucco-dentaire": {
        "tag": "Santé bucco-dentaire",
        "category": "Santé Bucco-Dentaire & Cutanée",
        "description": "Maintien de la minéralisation des dents et prévention de l'érosion bucco-dentaire.",
    },
    "Santé cutanée et des phanères": {
        "tag": "Santé cutanée et des phanères",
        "category": "Santé Bucco-Dentaire & Cutanée",
        "description": "Maintien de la qualité et de l'élasticité de la peau, des cheveux et des ongles.",
    },
}

_TAG_BY_LOWER = {k.lower(): k for k in NUTRITION_BENEFITS_REFERENTIAL}

# Mots-clés alimentaires pour les règles basées sur les ingrédients
_UNSATURATED_FAT_KEYWORDS = (
    "huile d'olive", "huile", "avocat", "saumon", "noix", "amande",
    "noisette", "oléagineux", "maquereau", "sardine", "graine",
)
_CHOLESTEROL_KEYWORDS = (
    "huile d'olive", "noix", "amande", "noisette", "oléagineux",
    "flocons d'avoine", "avoine", "avocat",
)
_WATER_RICH_KEYWORDS = (
    "salade", "tomate", "courgette", "concombre", "soupe", "bouillon",
    "brocoli", "haricots verts", "crudité", "melon", "pastèque",
)
_CALCIUM_RICH_KEYWORDS = (
    "yaourt", "fromage", "lait", "tofu", "brocoli", "amande", "sardine",
)
_ANTIOXIDANT_KEYWORDS = (
    "baies", "myrtille", "framboise", "brocoli", "tomate", "carotte",
    "épinard", "avocat", "huile d'olive", "thé",
)


def _get_item_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name", "")).lower()
    return str(getattr(item, "name", "")).lower()


def _get_item_portion(item: Any) -> float:
    if isinstance(item, dict):
        return float(item.get("portion_g", 0.0) or 0.0)
    return float(getattr(item, "portion_g", 0.0) or 0.0)


def evaluate_nutrition_benefits(
    items: Sequence[Any],
    total_calories: float,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
    fiber_g: float,
) -> List[Dict[str, str]]:
    """Applique les seuils EFSA / ANSES et retourne 1 à 4 bienfaits clés."""
    selected_tags: List[str] = []
    item_names = [_get_item_name(i) for i in items]
    joined_names = " ".join(item_names)
    total_weight_g = sum(_get_item_portion(i) for i in items)

    # 1. Satiété et contrôle de l'appétit : Fibres > 5 g ET Protéines > 15 g / portion
    if fiber_g > 5.0 and protein_g > 15.0:
        selected_tags.append("Satiété et contrôle de l'appétit")

    # 2. Transit et confort intestinal : Fibres >= 3 g / 100 g OU Fibres >= 6 g / portion
    fiber_per_100g = (fiber_g / total_weight_g * 100.0) if total_weight_g > 0 else 0.0
    if fiber_g >= 6.0 or fiber_per_100g >= 3.0:
        selected_tags.append("Transit et confort intestinal")

    # 3. Régulation glycémique : Ratio Fibres / Glucides totaux > 0,15
    if carbs_g > 0 and (fiber_g / carbs_g) > 0.15:
        selected_tags.append("Régulation glycémique")

    # 4. Protection cardiovasculaire : Lipides insaturés / Lipides totaux >= 50 %
    if fat_g > 0 and any(kw in joined_names for kw in _UNSATURATED_FAT_KEYWORDS):
        selected_tags.append("Protection cardiovasculaire")

    # 5. Régulation du cholestérol : oléagineux, huile d'olive, avoine, avocat
    if any(kw in joined_names for kw in _CHOLESTEROL_KEYWORDS):
        selected_tags.append("Régulation du cholestérol (Hypocholestérolémiant)")

    # 6. Hydratation cellulaire et tissulaire : Teneur en eau > 85 %
    if any(kw in joined_names for kw in _WATER_RICH_KEYWORDS):
        selected_tags.append("Hydratation cellulaire et tissulaire")

    # 7. Maintien de la santé osseuse : Calcium >= 120 mg / 100 g (sources calciques)
    if any(kw in joined_names for kw in _CALCIUM_RICH_KEYWORDS):
        selected_tags.append("Maintien de la santé osseuse")

    # 8. Fonction musculaire et récupération (apport protéique élevé)
    if protein_g >= 20.0:
        selected_tags.append("Fonction musculaire et récupération")

    # 9. Protection contre le stress oxydatif (Antioxydant)
    if any(kw in joined_names for kw in _ANTIOXIDANT_KEYWORDS):
        selected_tags.append("Protection contre le stress oxydatif (Antioxydant)")

    # Fallback minimal si aucun seuil spécifique n'est déclenché
    if not selected_tags:
        if total_calories > 0:
            selected_tags.append("Soutien du métabolisme énergétique")

    # Dédoublonnage en conservant l'ordre et limitation stricte à 4 bienfaits
    unique_tags: List[str] = []
    for tag in selected_tags:
        if tag in NUTRITION_BENEFITS_REFERENTIAL and tag not in unique_tags:
            unique_tags.append(tag)
        if len(unique_tags) == 4:
            break

    return [dict(NUTRITION_BENEFITS_REFERENTIAL[t]) for t in unique_tags]


def validate_and_normalize_benefits(
    raw_benefits: Optional[Sequence[Any]],
    fallback_benefits: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Valide les bienfaits retournés par Gemini contre le référentiel EFSA/ANSES."""
    if not raw_benefits:
        return fallback_benefits[:4]

    validated: List[Dict[str, str]] = []
    seen = set()

    for entry in raw_benefits:
        raw_tag = entry.get("tag", "") if isinstance(entry, dict) else str(entry)
        norm = raw_tag.strip().lower()
        matched_key = _TAG_BY_LOWER.get(norm)
        if not matched_key:
            # Correspondance partielle sur le début du tag (ex: "Régulation du cholestérol")
            for k_lower, k_orig in _TAG_BY_LOWER.items():
                if norm and (norm in k_lower or k_lower.startswith(norm)):
                    matched_key = k_orig
                    break
        if matched_key and matched_key not in seen:
            seen.add(matched_key)
            validated.append(dict(NUTRITION_BENEFITS_REFERENTIAL[matched_key]))
        if len(validated) == 4:
            break

    return validated if validated else fallback_benefits[:4]


def generate_nutritional_quality(
    total_calories: float,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
    fiber_g: float,
    pct_prot: float,
    pct_carbs: float,
    pct_fat: float,
) -> str:
    """Génère une synthèse clinique ultra-concise (1-2 phrases max) de la qualité du repas."""
    parts: List[str] = []

    if protein_g >= 25.0 and fiber_g >= 5.0:
        parts.append(
            f"Profil nutritionnel dense et rassasiant ({pct_prot:.0f}% protéines, {fiber_g:.1f} g de fibres), "
            "favorable à la préservation musculaire et à la stabilité glycémique."
        )
    elif protein_g >= 25.0:
        parts.append(
            f"Apport protéique élevé ({protein_g:.1f} g, {pct_prot:.0f}% des calories) soutenant la synthèse musculaire."
        )
    elif carbs_g > 70.0 and fiber_g < 4.0:
        parts.append(
            f"Charge glucidique marquée ({carbs_g:.1f} g, {pct_carbs:.0f}%) avec un apport modéré en fibres ({fiber_g:.1f} g), "
            "induisant une réponse glycémique plus rapide."
        )
    elif fat_g > 30.0 and pct_fat > 45.0:
        parts.append(
            f"Repas à dominante lipidique ({pct_fat:.0f}% des calories, {fat_g:.1f} g), "
            "à densité énergétique élevée."
        )
    else:
        parts.append(
            f"Répartition équilibrée des macronutriments (P {pct_prot:.0f}% / G {pct_carbs:.0f}% / L {pct_fat:.0f}%, {total_calories:.0f} kcal)."
        )

    if fiber_g >= 6.0 and not (protein_g >= 25.0 and fiber_g >= 5.0):
        parts.append(f"Teneur élevée en fibres ({fiber_g:.1f} g) limitant le pic glycémique postprandial.")

    return " ".join(parts[:2])
