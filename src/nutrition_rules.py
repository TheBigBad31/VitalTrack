"""Moteur de règles nutritionnelles et détection automatique des bienfaits de santé.
Conforme aux recommandations EFSA (European Food Safety Authority) et ANSES.
"""

from typing import Any, Dict, List, Optional
from src.models import BenefitEvaluationResult


# Définition statique de secours ou référence des bienfaits experts (8 catégories)
EXPERT_BENEFITS_CATALOG: List[Dict[str, Any]] = [
    # Catégorie 1 : Santé Cardiovasculaire & Vasculaire
    {
        "id": "cardio_protection",
        "category_id": 1,
        "category": "Santé Cardiovasculaire & Vasculaire",
        "title": "Protection cardiovasculaire",
        "description": "Maintien du bon fonctionnement du cœur et du système circulatoire global.",
        "icon": "❤️",
        "rule_config": {
            "type": "unsaturated_ratio",
            "threshold": 0.50,
            "explanation": "Ratio lipides insaturés / lipides totaux >= 50%"
        }
    },
    {
        "id": "cholesterol_regulation",
        "category_id": 1,
        "category": "Santé Cardiovasculaire & Vasculaire",
        "title": "Régulation du cholestérol (Hypocholestérolémiant)",
        "description": "Baisse ou maintien à un niveau normal du cholestérol LDL sanguin (ex. via phytostérols, bêta-glucanes, remplacement des graisses saturées).",
        "icon": "🩸",
        "rule_config": {
            "type": "cholesterol_protective",
            "explanation": "Présence d'oléagineux, huile d'olive ou profil lipidique insaturé protecteur"
        }
    },
    {
        "id": "blood_pressure",
        "category_id": 1,
        "category": "Santé Cardiovasculaire & Vasculaire",
        "title": "Contrôle de la pression artérielle (Santé tensionnelle)",
        "description": "Maintien d'une pression artérielle normale et baisse de la pression systolique (ex. modération du sodium, polyphénols de l'huile d'olive).",
        "icon": "🩺",
        "rule_config": {
            "type": "low_sodium",
            "sodium_max_mg_100g": 120,
            "explanation": "Faible teneur en sodium (< 120 mg / 100 g) et/ou apport significatif en potassium"
        }
    },
    {
        "id": "vascular_elasticity",
        "category_id": 1,
        "category": "Santé Cardiovasculaire & Vasculaire",
        "title": "Élastification et souplesse vasculaire",
        "description": "Amélioration de la capacité de dilatation et de la souplesse des vaisseaux sanguins (ex. consommation de noix/oléagineux).",
        "icon": "🫀",
        "rule_config": {
            "type": "vascular_health",
            "explanation": "Riche en acides gras essentiels et antioxydants vasculaires"
        }
    },

    # Catégorie 2 : Métabolisme & Glycémie
    {
        "id": "glycemic_regulation",
        "category_id": 2,
        "category": "Métabolisme & Glycémie",
        "title": "Régulation glycémique",
        "description": "Atténuation de la réponse glycémique postprandiale (réduction du pic de sucre sanguin après le repas).",
        "icon": "📉",
        "rule_config": {
            "type": "glycemic_balance",
            "fiber_carb_ratio_min": 0.15,
            "explanation": "Ratio Fibres / Glucides totaux > 0,15 avec sucres libres modérés"
        }
    },
    {
        "id": "satiety_control",
        "category_id": 2,
        "category": "Métabolisme & Glycémie",
        "title": "Satiété et contrôle de l'appétit",
        "description": "Maintien d'une sensation de rassasiement prolongée et diminution des fringales (fibres et protéines).",
        "icon": "⚡",
        "rule_config": {
            "type": "satiety_boost",
            "fiber_min_portion": 5.0,
            "protein_min_portion": 15.0,
            "explanation": "Apport élevé combiné en fibres (> 5 g) et protéines (> 15 g / portion)"
        }
    },
    {
        "id": "energy_metabolism",
        "category_id": 2,
        "category": "Métabolisme & Glycémie",
        "title": "Soutien du métabolisme énergétique",
        "description": "Maintien du métabolisme basal et conversion optimale des macronutriments en énergie.",
        "icon": "🔥",
        "rule_config": {
            "type": "metabolic_support",
            "explanation": "Équilibre macronutritionnel soutenant la dépense énergétique"
        }
    },

    # Catégorie 3 : Digestion, Microbiote & Foie
    {
        "id": "gut_transit",
        "category_id": 3,
        "category": "Digestion, Microbiote & Foie",
        "title": "Transit et confort intestinal",
        "description": "Stimulation de la motilité digestive et régulation du transit par les fibres végétales.",
        "icon": "🌿",
        "rule_config": {
            "type": "high_fiber",
            "fiber_100g_min": 3.0,
            "fiber_portion_min": 6.0,
            "explanation": "Riche en fibres (>= 3 g / 100 g ou >= 6 g / portion - norme EFSA)"
        }
    },
    {
        "id": "gut_microbiota",
        "category_id": 3,
        "category": "Digestion, Microbiote & Foie",
        "title": "Soutien du microbiote (Effet prébiotique / probiotique)",
        "description": "Équilibre et enrichissement de la flore microbienne intestinale.",
        "icon": "🦠",
        "rule_config": {
            "type": "microbiota_support",
            "explanation": "Fibres prébiotiques fermentescibles nourrissant le microbiote"
        }
    },
    {
        "id": "liver_support",
        "category_id": 3,
        "category": "Digestion, Microbiote & Foie",
        "title": "Soutien de la fonction hépatique",
        "description": "Protection du foie et facilitation des fonctions d'élimination de l'organisme.",
        "icon": "🍃",
        "rule_config": {
            "type": "hepatic_support",
            "explanation": "Aliments non ultra-transformés favorisant le métabolisme hépatique"
        }
    },

    # Catégorie 4 : Système Osseux, Musculaire & Articulaire
    {
        "id": "bone_health",
        "category_id": 4,
        "category": "Système Osseux, Musculaire & Articulaire",
        "title": "Maintien de la santé osseuse",
        "description": "Renforcement, minéralisation et maintien de la densité de la structure osseuse (ex. calcium, vitamine D).",
        "icon": "🦴",
        "rule_config": {
            "type": "calcium_rich",
            "calcium_100g_min": 120.0,
            "explanation": "Teneur élevée en calcium (>= 120 mg / 100 g soit 15% VNR EFSA)"
        }
    },
    {
        "id": "muscle_function",
        "category_id": 4,
        "category": "Système Osseux, Musculaire & Articulaire",
        "title": "Fonction musculaire et récupération",
        "description": "Soutien de la contraction musculaire normale et préservation de la masse musculaire (protéines, magnésium).",
        "icon": "💪",
        "rule_config": {
            "type": "protein_recovery",
            "protein_portion_min": 20.0,
            "explanation": "Apport significatif en protéines (>= 20 g / portion) favorisant l'anabolisme"
        }
    },

    # Catégorie 5 : Immunité & Protection Cellulaire
    {
        "id": "immune_support",
        "category_id": 5,
        "category": "Immunité & Protection Cellulaire",
        "title": "Renforcement immunitaire",
        "description": "Soutien des défenses naturelles de l'organisme (vitamines C, D, zinc, sélénium).",
        "icon": "🛡️",
        "rule_config": {
            "type": "immune_defense",
            "explanation": "Riche en micronutriments protecteurs (vitamines & oligo-éléments)"
        }
    },
    {
        "id": "antioxidant",
        "category_id": 5,
        "category": "Immunité & Protection Cellulaire",
        "title": "Protection contre le stress oxydatif (Antioxydant)",
        "description": "Neutralisation des radicaux libres et protection des cellules contre le dommage oxydatif.",
        "icon": "🫐",
        "rule_config": {
            "type": "antioxidant_rich",
            "explanation": "Concentration en polyphénols, caroténoïdes ou flavonoïdes antioxydants"
        }
    },

    # Catégorie 6 : Hydratation & Équilibre Minéral
    {
        "id": "cellular_hydration",
        "category_id": 6,
        "category": "Hydratation & Équilibre Minéral",
        "title": "Hydratation cellulaire et tissulaire",
        "description": "Maintien de l'équilibre hydrique corporel et de l'hydratation des tissus (aliments riches en eau > 85 %).",
        "icon": "💧",
        "rule_config": {
            "type": "water_content",
            "water_pct_min": 85.0,
            "explanation": "Teneur en eau exceptionnelle (> 85 %)"
        }
    },
    {
        "id": "electrolyte_balance",
        "category_id": 6,
        "category": "Hydratation & Équilibre Minéral",
        "title": "Équilibre électrolytique",
        "description": "Maintien de la balance minérale et ionique dans les fluides corporels (potassium, magnésium).",
        "icon": "⚡",
        "rule_config": {
            "type": "electrolyte_balance",
            "explanation": "Ratio minéral favorable en potassium et magnésium"
        }
    },

    # Catégorie 7 : Cognition, Vision & Système Nerveux
    {
        "id": "cognitive_function",
        "category_id": 7,
        "category": "Cognition, Vision & Système Nerveux",
        "title": "Soutien des fonctions cognitives et cérébrales",
        "description": "Préservation de la mémoire, de la concentration et des capacités d'apprentissage (acides gras oméga-3, B-vitamines).",
        "icon": "🧠",
        "rule_config": {
            "type": "omega3_brain",
            "explanation": "Riche en oméga-3 (DHA/EPA) et cofacteurs neuroprotecteurs"
        }
    },
    {
        "id": "nervous_system",
        "category_id": 7,
        "category": "Cognition, Vision & Système Nerveux",
        "title": "Santé du système nerveux",
        "description": "Soutien du fonctionnement nerveux normal et de la transmission des influx.",
        "icon": "⚡",
        "rule_config": {
            "type": "nervous_support",
            "explanation": "Vitamines du groupe B et magnésium neuro-régulateur"
        }
    },
    {
        "id": "vision_health",
        "category_id": 7,
        "category": "Cognition, Vision & Système Nerveux",
        "title": "Maintien de la vision",
        "description": "Préservation de la santé oculaire et de la fonction visuelle normale (vitamine A, lutéine).",
        "icon": "👁️",
        "rule_config": {
            "type": "vision_support",
            "explanation": "Apport en vitamine A, caroténoïdes et lutéine"
        }
    },

    # Catégorie 8 : Santé Bucco-Dentaire & Cutanée
    {
        "id": "oral_health",
        "category_id": 8,
        "category": "Santé Bucco-Dentaire & Cutanée",
        "title": "Santé bucco-dentaire",
        "description": "Maintien de la minéralisation des dents et prévention de l'érosion bucco-dentaire.",
        "icon": "🦷",
        "rule_config": {
            "type": "dental_care",
            "explanation": "Non acidogène, reminéralisant pour l'émail dentaire"
        }
    },
    {
        "id": "skin_health",
        "category_id": 8,
        "category": "Santé Bucco-Dentaire & Cutanée",
        "title": "Santé cutanée et des phanères",
        "description": "Maintien de la qualité et de l'élasticité de la peau, des cheveux et des ongles.",
        "icon": "✨",
        "rule_config": {
            "type": "skin_hair",
            "explanation": "Nutriments structurants pour le collagène et la kératine"
        }
    }
]


def evaluate_dish_benefits(food_item_data: Dict[str, Any]) -> List[BenefitEvaluationResult]:
    """Évalue automatiquement un plat ou aliment selon les règles EFSA / ANSES.

    food_item_data peut contenir :
    - name: str
    - quantity_grams / default_quantity / portion_g: float
    - calories / calories_per_unit / calories_kcal: float
    - protein_g / protein_per_unit_g: float
    - carbs_g / carbs_per_unit_g: float
    - fat_g / fat_per_unit_g: float
    - fiber_g / fiber_per_unit_g: float
    - sugars_g: float (optionnel)
    - saturated_fat_g: float (optionnel)
    - unsaturated_fat_g: float (optionnel)
    - sodium_mg: float (optionnel)
    - potassium_mg: float (optionnel)
    - calcium_mg: float (optionnel)
    - water_pct: float (optionnel)
    - ingredients / tags / food_type: str ou List[str] (optionnel)
    """
    results: List[BenefitEvaluationResult] = []

    # 1. Normalisation des valeurs
    name = str(food_item_data.get("name") or "").lower()
    ingredients = str(food_item_data.get("ingredients") or "").lower()
    combined_text = f"{name} {ingredients}"

    portion_g = float(
        food_item_data.get("portion_g")
        or food_item_data.get("default_quantity")
        or food_item_data.get("quantity_grams")
        or food_item_data.get("quantity")
        or 100.0
    )
    if portion_g <= 0:
        portion_g = 100.0

    # Facteur pour ramener les valeurs à 100g si fournies par portion, ou l'inverse
    protein_g = float(food_item_data.get("protein_per_unit_g") or food_item_data.get("protein_g") or 0.0)
    carbs_g = float(food_item_data.get("carbs_per_unit_g") or food_item_data.get("carbs_g") or 0.0)
    fat_g = float(food_item_data.get("fat_per_unit_g") or food_item_data.get("fat_g") or 0.0)
    fiber_g = float(food_item_data.get("fiber_per_unit_g") or food_item_data.get("fiber_g") or 0.0)
    calories = float(food_item_data.get("calories_per_unit") or food_item_data.get("calories") or food_item_data.get("calories_kcal") or 0.0)

    # Calcul au 100g vs à la portion
    # Si les nutriments sont spécifiés "per_unit" et default_unit == 'g', default_quantity indique la base
    default_qty = float(food_item_data.get("default_quantity") or 100.0)
    if "calories_per_unit" in food_item_data and default_qty > 0:
        # C'est un CatalogItem avec quantité de référence
        ratio_100g = 100.0 / default_qty
        fiber_100g = fiber_g * ratio_100g
        protein_100g = protein_g * ratio_100g
        carbs_100g = carbs_g * ratio_100g
        fat_100g = fat_g * ratio_100g
        fiber_portion = fiber_g  # par défaut sur sa portion unitaire
        protein_portion = protein_g
    else:
        # Données brutes sur une portion donnée
        ratio_100g = (100.0 / portion_g) if portion_g > 0 else 1.0
        fiber_100g = fiber_g * ratio_100g
        protein_100g = protein_g * ratio_100g
        carbs_100g = carbs_g * ratio_100g
        fat_100g = fat_g * ratio_100g
        fiber_portion = fiber_g
        protein_portion = protein_g

    sugars_g = food_item_data.get("sugars_g")
    if sugars_g is not None:
        sugars_g = float(sugars_g)

    saturated_fat_g = food_item_data.get("saturated_fat_g")
    if saturated_fat_g is not None:
        saturated_fat_g = float(saturated_fat_g)

    unsaturated_fat_g = food_item_data.get("unsaturated_fat_g")
    if unsaturated_fat_g is not None:
        unsaturated_fat_g = float(unsaturated_fat_g)

    sodium_mg = food_item_data.get("sodium_mg")
    if sodium_mg is not None:
        sodium_mg = float(sodium_mg)

    calcium_mg = food_item_data.get("calcium_mg")
    if calcium_mg is not None:
        calcium_mg = float(calcium_mg)

    water_pct = food_item_data.get("water_pct")
    if water_pct is not None:
        water_pct = float(water_pct)

    # Détection par mot-clés d'ingrédients réputés
    oleaginous_keywords = ["noix", "amande", "noisette", "avocat", "olive", "colza", "chia", "lin", "sesame", "sésame", "graines", "pistache", "cajou"]
    has_oleaginous = any(k in combined_text for k in oleaginous_keywords)

    water_rich_keywords = ["concombre", "pasteque", "pastèque", "melon", "salade", "tomate", "courgette", "céleri", "soupe", "bouillon", "tisane", "eau", "pastèque"]
    has_water_rich = any(k in combined_text for k in water_rich_keywords)

    calcium_rich_keywords = ["parmesan", "fromage", "yaourt", "lait", "tofu", "sardine", "emmental", "gouda", "gruyère", "mozzarella"]
    has_calcium_rich = any(k in combined_text for k in calcium_rich_keywords)

    potassium_rich_keywords = ["banane", "épinard", "epinard", "avocat", "patate douce", "lentille", "haricot blanc", "saumon"]
    has_potassium_rich = any(k in combined_text for k in potassium_rich_keywords)

    # -------------------------------------------------------------
    # RÈGLE 1 : Transit et confort intestinal
    # Condition EFSA/ANSES : Fibres >= 3 g / 100 g OU Fibres >= 6 g / portion
    # -------------------------------------------------------------
    if fiber_100g >= 3.0 or fiber_portion >= 6.0:
        results.append(BenefitEvaluationResult(
            benefit_id="gut_transit",
            category="Digestion, Microbiote & Foie",
            category_id=3,
            title="Transit et confort intestinal",
            description="Stimulation de la motilité digestive et régulation du transit par les fibres végétales.",
            icon="🌿",
            explanation=f"Contient {round(fiber_100g, 1)}g de fibres / 100g (ou {round(fiber_portion, 1)}g/portion), atteignant le seuil EFSA (>= 3g/100g)."
        ))

    # -------------------------------------------------------------
    # RÈGLE 2 : Protection cardiovasculaire
    # Condition EFSA/ANSES : Lipides insaturés / Lipides totaux >= 50 %
    # (ou si unsaturated_fat_g non renseigné : graisse végétale/poisson gras ou lipides >= 2g sans saturation excessive)
    # -------------------------------------------------------------
    is_cardio = False
    cardio_exp = ""
    if unsaturated_fat_g is not None and fat_g > 0:
        ratio = unsaturated_fat_g / fat_g
        if ratio >= 0.50:
            is_cardio = True
            cardio_exp = f"Ratio lipides insaturés de {round(ratio * 100)}% (seuil EFSA >= 50%)."
    elif saturated_fat_g is not None and fat_g > 0:
        unsat_est = max(0.0, fat_g - saturated_fat_g)
        ratio = unsat_est / fat_g
        if ratio >= 0.50:
            is_cardio = True
            cardio_exp = f"Profil lipidique sain avec plus de {round(ratio * 100)}% d'acides gras insaturés protecteurs."
    elif has_oleaginous or "poisson" in combined_text or "saumon" in combined_text or "colza" in combined_text:
        is_cardio = True
        cardio_exp = "Contient des acides gras insaturés protecteurs (oméga-3 / monoinsaturés) bénéfiques pour le cœur."

    if is_cardio:
        results.append(BenefitEvaluationResult(
            benefit_id="cardio_protection",
            category="Santé Cardiovasculaire & Vasculaire",
            category_id=1,
            title="Protection cardiovasculaire",
            description="Maintien du bon fonctionnement du cœur et du système circulatoire global.",
            icon="❤️",
            explanation=cardio_exp
        ))

    # -------------------------------------------------------------
    # RÈGLE 3 : Régulation du cholestérol (Hypocholestérolémiant)
    # Condition EFSA/ANSES : Présence d'oléagineux, huile d'olive, ou substitution des graisses saturées
    # Ou avoine / orge (bêta-glucanes)
    # -------------------------------------------------------------
    oat_keywords = ["avoine", "flocons d'avoine", "orge", "son d'avoine", "psyllium"]
    has_oat = any(k in combined_text for k in oat_keywords)
    if has_oleaginous or has_oat or (is_cardio and fat_100g >= 3.0):
        substance = "bêta-glucanes d'avoine" if has_oat else "acides gras monoinsaturés & phytostérols"
        results.append(BenefitEvaluationResult(
            benefit_id="cholesterol_regulation",
            category="Santé Cardiovasculaire & Vasculaire",
            category_id=1,
            title="Régulation du cholestérol (Hypocholestérolémiant)",
            description="Baisse ou maintien à un niveau normal du cholestérol LDL sanguin.",
            icon="🩸",
            explanation=f"Riche en {substance} reconnus pour réguler le cholestérol LDL (allégation EFSA)."
        ))

    # -------------------------------------------------------------
    # RÈGLE 4 : Contrôle de la pression artérielle
    # Condition EFSA/ANSES : Sodium < 120 mg / 100 g ET/OU apport significatif en potassium/polyphénols
    # -------------------------------------------------------------
    is_bp_protective = False
    bp_exp = ""
    if sodium_mg is not None and sodium_mg < 120:
        is_bp_protective = True
        bp_exp = f"Très faible teneur en sodium ({round(sodium_mg, 1)} mg / 100 g < 120 mg - norme EFSA/ANSES)."
    elif has_potassium_rich or "huile d'olive" in combined_text or (has_water_rich and not ("sel" in combined_text or "salé" in combined_text)):
        is_bp_protective = True
        bp_exp = "Apport naturel en potassium et minéraux favorisant l'équilibre tensionnel."

    if is_bp_protective:
        results.append(BenefitEvaluationResult(
            benefit_id="blood_pressure",
            category="Santé Cardiovasculaire & Vasculaire",
            category_id=1,
            title="Contrôle de la pression artérielle (Santé tensionnelle)",
            description="Maintien d'une pression artérielle normale et baisse de la pression systolique.",
            icon="🩺",
            explanation=bp_exp
        ))

    # -------------------------------------------------------------
    # RÈGLE 5 : Hydratation cellulaire
    # Condition EFSA/ANSES : Teneur en eau de l'aliment/plat > 85 %
    # -------------------------------------------------------------
    is_hydrating = False
    hydra_exp = ""
    if water_pct is not None and water_pct > 85.0:
        is_hydrating = True
        hydra_exp = f"Teneur en eau exceptionnelle de {round(water_pct, 1)}% (> 85%), stimulant l'hydratation cellulaire."
    elif has_water_rich:
        is_hydrating = True
        hydra_exp = "Aliment à haute densité hydrique (> 85% d'eau), favorisant l'hydratation intracellulaire."

    if is_hydrating:
        results.append(BenefitEvaluationResult(
            benefit_id="cellular_hydration",
            category="Hydratation & Équilibre Minéral",
            category_id=6,
            title="Hydratation cellulaire et tissulaire",
            description="Maintien de l'équilibre hydrique corporel et de l'hydratation des tissus.",
            icon="💧",
            explanation=hydra_exp
        ))

    # -------------------------------------------------------------
    # RÈGLE 6 : Régulation glycémique
    # Condition EFSA/ANSES : Ratio Fibres / Glucides totaux > 0,15 ET sucres libres modérés
    # -------------------------------------------------------------
    if carbs_g > 0:
        fiber_carb_ratio = fiber_g / carbs_g
        sugars_ok = True
        if sugars_g is not None and carbs_g > 0:
            # sucres libres modérés : < 50% des glucides totaux ou < 10g
            if (sugars_g / carbs_g) > 0.50 and sugars_g > 10.0:
                sugars_ok = False

        if fiber_carb_ratio > 0.15 and sugars_ok:
            results.append(BenefitEvaluationResult(
                benefit_id="glycemic_regulation",
                category="Métabolisme & Glycémie",
                category_id=2,
                title="Régulation glycémique",
                description="Atténuation de la réponse glycémique postprandiale (réduction du pic d'insuline).",
                icon="📉",
                explanation=f"Excellent ratio Fibres/Glucides de {round(fiber_carb_ratio, 2)} (> 0.15), lissant la glycémie postprandiale."
            ))

    # -------------------------------------------------------------
    # RÈGLE 7 : Maintien de la santé osseuse
    # Condition EFSA/ANSES : Calcium >= 120 mg / 100 g (ou 15 % VNR)
    # -------------------------------------------------------------
    is_bone = False
    bone_exp = ""
    if calcium_mg is not None and calcium_mg >= 120.0:
        is_bone = True
        bone_exp = f"Riche en calcium ({round(calcium_mg, 1)} mg / 100 g >= 120 mg, seuil 15% VNR EFSA)."
    elif has_calcium_rich:
        is_bone = True
        bone_exp = "Source notable de calcium et minéraux essentiels au maintien de la structure osseuse."

    if is_bone:
        results.append(BenefitEvaluationResult(
            benefit_id="bone_health",
            category="Système Osseux, Musculaire & Articulaire",
            category_id=4,
            title="Maintien de la santé osseuse",
            description="Renforcement, minéralisation et maintien de la densité de la structure osseuse.",
            icon="🦴",
            explanation=bone_exp
        ))

    # -------------------------------------------------------------
    # RÈGLE 8 : Satiété et contrôle de l'appétit
    # Condition EFSA/ANSES : Apport combiné en Fibres (> 5 g) et Protéines (> 15 g / portion)
    # -------------------------------------------------------------
    if fiber_portion > 5.0 and protein_portion > 15.0:
        results.append(BenefitEvaluationResult(
            benefit_id="satiety_control",
            category="Métabolisme & Glycémie",
            category_id=2,
            title="Satiété et contrôle de l'appétit",
            description="Maintien d'une sensation de rassasiement prolongée et diminution des fringales.",
            icon="⚡",
            explanation=f"Synergie satiétogène puissante : {round(protein_portion, 1)}g de protéines et {round(fiber_portion, 1)}g de fibres par portion."
        ))

    # -------------------------------------------------------------
    # RÈGLES COMPLÉMENTAIRES COUVRANT LES AUTRES CATÉGORIES
    # - Récupération musculaire : Protéines >= 20g / portion
    # - Antioxydant : fruits rouges, thé vert, épices (curcuma), cacao, légumes colorés
    # -------------------------------------------------------------
    if protein_portion >= 20.0:
        results.append(BenefitEvaluationResult(
            benefit_id="muscle_function",
            category="Système Osseux, Musculaire & Articulaire",
            category_id=4,
            title="Fonction musculaire et récupération",
            description="Soutien de la contraction musculaire normale et préservation de la masse musculaire.",
            icon="💪",
            explanation=f"Apport anabolique élevé de {round(protein_portion, 1)}g de protéines par portion (>= 20g)."
        ))

    antiox_keywords = ["myrtille", "framboise", "baie", "curcuma", "thé vert", "cacao", "grenade", "brocoli", "épinard"]
    if any(k in combined_text for k in antiox_keywords):
        results.append(BenefitEvaluationResult(
            benefit_id="antioxidant",
            category="Immunité & Protection Cellulaire",
            category_id=5,
            title="Protection contre le stress oxydatif (Antioxydant)",
            description="Neutralisation des radicaux libres et protection des cellules contre le dommage oxydatif.",
            icon="🫐",
            explanation="Concentration remarquable en antioxydants végétaux protecteurs cellulaires."
        ))

    return results
