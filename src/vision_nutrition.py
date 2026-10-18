"""Moteur d'estimation de calories et de macronutriments par photo d'assiette.

Supporte :
- Mode Gemini Vision multimodal (via google-genai / GEMINI_API_KEY)
- Mode déterministe / Hybride hors-ligne avec base nutritionnelle locale (française & internationale)
  et recherche OpenFoodFacts
- Détection / décomposition multi-aliments avec portions estimées
- Multiplicateur de portion interactif (portion_scale: 0.5x à 2.0x)
- Conseils nutritionnels automatisés et calcul du score de confiance
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.models import FoodItem, MealType

logger = logging.getLogger(__name__)

# Base nutritionnelle locale de référence (valeurs pour 100g)
# [calories_kcal, protein_g, carbs_g, fat_g, fiber_g, portion_standard_g]
LOCAL_NUTRITION_DATABASE: Dict[str, Dict[str, float]] = {
    # Féculents et céréales
    "riz basmati": {"cal_100g": 130.0, "p": 2.7, "c": 28.0, "f": 0.3, "fib": 0.4, "portion_g": 180.0},
    "riz": {"cal_100g": 130.0, "p": 2.7, "c": 28.0, "f": 0.3, "fib": 0.4, "portion_g": 180.0},
    "pâtes": {"cal_100g": 158.0, "p": 5.8, "c": 31.0, "f": 0.9, "fib": 1.8, "portion_g": 200.0},
    "pates": {"cal_100g": 158.0, "p": 5.8, "c": 31.0, "f": 0.9, "fib": 1.8, "portion_g": 200.0},
    "pain de campagne": {"cal_100g": 265.0, "p": 9.0, "c": 50.0, "f": 1.5, "fib": 4.0, "portion_g": 60.0},
    "pain": {"cal_100g": 265.0, "p": 9.0, "c": 50.0, "f": 1.5, "fib": 4.0, "portion_g": 60.0},
    "quinoa": {"cal_100g": 120.0, "p": 4.4, "c": 21.3, "f": 1.9, "fib": 2.8, "portion_g": 160.0},
    "patate douce": {"cal_100g": 86.0, "p": 1.6, "c": 20.0, "f": 0.1, "fib": 3.0, "portion_g": 180.0},
    "pommes de terre": {"cal_100g": 87.0, "p": 2.0, "c": 20.0, "f": 0.1, "fib": 1.8, "portion_g": 180.0},
    "flocons d'avoine": {"cal_100g": 365.0, "p": 13.5, "c": 58.0, "f": 7.0, "fib": 10.0, "portion_g": 50.0},

    # Protéines animales et végétales
    "blanc de poulet": {"cal_100g": 120.0, "p": 26.0, "c": 0.0, "f": 1.8, "fib": 0.0, "portion_g": 150.0},
    "poulet": {"cal_100g": 140.0, "p": 24.0, "c": 0.0, "f": 4.5, "fib": 0.0, "portion_g": 150.0},
    "steak haché 5%": {"cal_100g": 128.0, "p": 21.0, "c": 0.0, "f": 5.0, "fib": 0.0, "portion_g": 125.0},
    "steak haché": {"cal_100g": 170.0, "p": 20.0, "c": 0.0, "f": 10.0, "fib": 0.0, "portion_g": 125.0},
    "boeuf": {"cal_100g": 210.0, "p": 26.0, "c": 0.0, "f": 12.0, "fib": 0.0, "portion_g": 150.0},
    "saumon pavé": {"cal_100g": 208.0, "p": 20.0, "c": 0.0, "f": 13.0, "fib": 0.0, "portion_g": 140.0},
    "saumon": {"cal_100g": 208.0, "p": 20.0, "c": 0.0, "f": 13.0, "fib": 0.0, "portion_g": 140.0},
    "thon au naturel": {"cal_100g": 116.0, "p": 26.0, "c": 0.0, "f": 1.0, "fib": 0.0, "portion_g": 130.0},
    "cabillaud": {"cal_100g": 82.0, "p": 18.0, "c": 0.0, "f": 0.7, "fib": 0.0, "portion_g": 150.0},
    "oeuf": {"cal_100g": 143.0, "p": 12.6, "c": 0.7, "f": 9.5, "fib": 0.0, "portion_g": 110.0},  # ~2 oeufs
    "oeufs": {"cal_100g": 143.0, "p": 12.6, "c": 0.7, "f": 9.5, "fib": 0.0, "portion_g": 110.0},
    "tofu": {"cal_100g": 83.0, "p": 10.0, "c": 1.2, "f": 5.0, "fib": 0.5, "portion_g": 120.0},
    "lentilles corail": {"cal_100g": 116.0, "p": 9.0, "c": 17.0, "f": 0.5, "fib": 3.8, "portion_g": 180.0},
    "lentilles": {"cal_100g": 116.0, "p": 9.0, "c": 17.0, "f": 0.5, "fib": 3.8, "portion_g": 180.0},

    # Légumes & Salades
    "brocoli": {"cal_100g": 35.0, "p": 2.8, "c": 7.0, "f": 0.4, "fib": 2.6, "portion_g": 150.0},
    "haricots verts": {"cal_100g": 31.0, "p": 1.8, "c": 7.0, "f": 0.2, "fib": 2.7, "portion_g": 150.0},
    "salade verte": {"cal_100g": 15.0, "p": 1.4, "c": 2.9, "f": 0.2, "fib": 1.3, "portion_g": 60.0},
    "salade": {"cal_100g": 15.0, "p": 1.4, "c": 2.9, "f": 0.2, "fib": 1.3, "portion_g": 60.0},
    "tomates": {"cal_100g": 18.0, "p": 0.9, "c": 3.9, "f": 0.2, "fib": 1.2, "portion_g": 120.0},
    "tomate": {"cal_100g": 18.0, "p": 0.9, "c": 3.9, "f": 0.2, "fib": 1.2, "portion_g": 120.0},
    "avocat": {"cal_100g": 160.0, "p": 2.0, "c": 8.5, "f": 14.7, "fib": 6.7, "portion_g": 80.0},
    "courgettes": {"cal_100g": 17.0, "p": 1.2, "c": 3.1, "f": 0.3, "fib": 1.0, "portion_g": 160.0},
    "carottes": {"cal_100g": 41.0, "p": 0.9, "c": 9.6, "f": 0.2, "fib": 2.8, "portion_g": 120.0},

    # Matières grasses et assaisonnements
    "huile d'olive": {"cal_100g": 884.0, "p": 0.0, "c": 0.0, "f": 100.0, "fib": 0.0, "portion_g": 10.0},
    "huile": {"cal_100g": 884.0, "p": 0.0, "c": 0.0, "f": 100.0, "fib": 0.0, "portion_g": 10.0},
    "beurre": {"cal_100g": 717.0, "p": 0.9, "c": 0.1, "f": 81.0, "fib": 0.0, "portion_g": 12.0},

    # Fruits
    "pomme": {"cal_100g": 52.0, "p": 0.3, "c": 14.0, "f": 0.2, "fib": 2.4, "portion_g": 150.0},
    "banane": {"cal_100g": 89.0, "p": 1.1, "c": 23.0, "f": 0.3, "fib": 2.6, "portion_g": 120.0},
    "baies": {"cal_100g": 57.0, "p": 0.7, "c": 14.0, "f": 0.3, "fib": 2.4, "portion_g": 100.0},

    # Plats composés courants
    "poke bowl saumon": {"cal_100g": 145.0, "p": 7.5, "c": 18.0, "f": 5.2, "fib": 2.1, "portion_g": 400.0},
    "salade césar": {"cal_100g": 150.0, "p": 8.5, "c": 7.0, "f": 10.5, "fib": 1.5, "portion_g": 300.0},
    "lasagnes": {"cal_100g": 165.0, "p": 8.0, "c": 16.0, "f": 7.5, "fib": 1.5, "portion_g": 350.0},
    "pizza margherita": {"cal_100g": 240.0, "p": 10.0, "c": 32.0, "f": 7.5, "fib": 2.0, "portion_g": 300.0},
}


class PhotoCalorieEstimator:
    """Moteur IA et Hybride d'estimation calorique par photo ou description."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = "gemini-2.5-flash"

    @property
    def has_gemini_api(self) -> bool:
        """Vérifie si une clé API Gemini Vision est configurée."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def search_openfoodfacts(self, query: str) -> Optional[Dict[str, Any]]:
        """Interroge l'API publique OpenFoodFacts (fallback en ligne)."""
        clean_query = query.strip().lower()
        if not clean_query:
            return None
        
        encoded_query = quote(clean_query)
        url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={encoded_query}&search_simple=1&action=process&json=1&page_size=1"
        req = Request(url, headers={"User-Agent": "VitalTrack-NutritionEngine/0.1.0 (https://vitaltrack.local)"})
        
        try:
            with urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                products = data.get("products", [])
                if not products:
                    return None
                prod = products[0]
                nutriments = prod.get("nutriments", {})
                cal_100g = nutriments.get("energy-kcal_100g") or (nutriments.get("energy_100g", 0) / 4.184)
                if not cal_100g or cal_100g <= 0:
                    return None

                return {
                    "name": prod.get("product_name_fr") or prod.get("product_name") or query,
                    "cal_100g": float(cal_100g),
                    "p": float(nutriments.get("proteins_100g", 0.0)),
                    "c": float(nutriments.get("carbohydrates_100g", 0.0)),
                    "f": float(nutriments.get("fat_100g", 0.0)),
                    "fib": float(nutriments.get("fiber_100g", 0.0)),
                    "portion_g": float(prod.get("serving_quantity", 150.0) or 150.0),
                }
        except (URLError, TimeoutError, ValueError, KeyError, Exception) as exc:
            logger.debug(f"OpenFoodFacts lookup failed for '{query}': {exc}")
            return None

    def lookup_ingredient(self, query: str) -> Optional[Dict[str, float]]:
        """Cherche un ingrédient dans la base locale d'abord, puis OpenFoodFacts."""
        query_norm = query.strip().lower()
        
        # Correspondance exacte dans la base locale
        if query_norm in LOCAL_NUTRITION_DATABASE:
            return LOCAL_NUTRITION_DATABASE[query_norm]

        # Correspondance par sous-chaîne
        for key, val in LOCAL_NUTRITION_DATABASE.items():
            if key in query_norm or query_norm in key:
                return val

        # Fallback OpenFoodFacts si disponible
        off_result = self.search_openfoodfacts(query_norm)
        if off_result:
            return off_result

        return None

    def estimate_from_description(
        self,
        description: str,
        portion_scale: float = 1.0,
        meal_type: MealType = "lunch"
    ) -> Dict[str, Any]:
        """Décompose une description textuelle d'assiette et calcule les nutriments."""
        portion_scale = max(0.5, min(2.0, portion_scale))
        items: List[FoodItem] = []

        # Découpe des items par virgule, 'et', '+' ou saut de ligne
        raw_parts = re.split(r"[,+\n]|\bet\b|\band\b", description, flags=re.IGNORECASE)
        parts = [p.strip() for p in raw_parts if p.strip()]

        if not parts:
            parts = ["assiette équilibrée"]

        for part in parts:
            # Recherche de portion explicite (ex: "150g de poulet" ou "200 g riz")
            portion_match = re.search(r"(\d+)\s*(?:g|grammes|gr)\b", part, flags=re.IGNORECASE)
            extracted_portion_g = float(portion_match.group(1)) if portion_match else None
            
            # Nettoyage du nom pour la recherche
            clean_name = re.sub(r"\b\d+\s*(?:g|grammes|gr)\b", "", part, flags=re.IGNORECASE)
            clean_name = re.sub(r"^(?:de|d'|du|des|un|une|le|la|les)\s+", "", clean_name.strip(), flags=re.IGNORECASE)

            nutri = self.lookup_ingredient(clean_name)
            if nutri:
                base_portion = extracted_portion_g or nutri.get("portion_g", 150.0)
                final_portion = round(base_portion * portion_scale, 1)
                ratio = final_portion / 100.0

                cal = round(nutri["cal_100g"] * ratio, 1)
                prot = round(nutri["p"] * ratio, 1)
                carbs = round(nutri["c"] * ratio, 1)
                fat = round(nutri["f"] * ratio, 1)
                fiber = round(nutri.get("fib", 0.0) * ratio, 1)
                confidence = 0.90 if extracted_portion_g else 0.85
                
                items.append(FoodItem(
                    name=clean_name.capitalize() if clean_name else "Aliment",
                    portion_g=final_portion,
                    calories_kcal=cal,
                    protein_g=prot,
                    carbs_g=carbs,
                    fat_g=fat,
                    fiber_g=fiber,
                    confidence_score=confidence
                ))
            else:
                # Ingrédient générique avec estimation raisonnable
                final_portion = round(150.0 * portion_scale, 1)
                items.append(FoodItem(
                    name=clean_name.capitalize() if clean_name else "Aliment composé",
                    portion_g=final_portion,
                    calories_kcal=round(180.0 * portion_scale, 1),
                    protein_g=round(8.0 * portion_scale, 1),
                    carbs_g=round(20.0 * portion_scale, 1),
                    fat_g=round(7.0 * portion_scale, 1),
                    fiber_g=round(2.5 * portion_scale, 1),
                    confidence_score=0.70
                ))

        return self._format_analysis_result(items, portion_scale, source="local_database", meal_type=meal_type)

    def estimate_from_gemini_vision(
        self,
        image_data: bytes,
        mime_type: str = "image/jpeg",
        user_notes: Optional[str] = None,
        portion_scale: float = 1.0,
        meal_type: MealType = "lunch"
    ) -> Optional[Dict[str, Any]]:
        """Appelle l'API Gemini Vision multimodal pour analyser la photo."""
        if not self.has_gemini_api:
            return None

        try:
            # Import dynamique pour ne pas bloquer les environnements sans google-genai
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            system_prompt = (
                "Tu es un nutritionniste expert en vision par ordinateur. "
                "Analyse la photo de ce repas et renvoie UNIQUEMENT un objet JSON valide avec cette structure exacte :\n"
                "{\n"
                '  "items": [\n'
                '    {"name": "Nom aliment", "portion_g": 150, "calories_kcal": 220, "protein_g": 25, "carbs_g": 10, "fat_g": 4, "fiber_g": 2, "confidence_score": 0.88}\n'
                "  ],\n"
                '  "dietary_advice": "Conseil nutritionnel court et bienveillant",\n'
                '  "overall_confidence": 0.85\n'
                "}\n"
                "Sois précis sur l'estimation des portions en grammes et la décomposition en macronutriments."
            )

            prompt_text = "Analyse cette assiette."
            if user_notes:
                prompt_text += f" Précisions de l'utilisateur : {user_notes}"

            response = client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Part.from_bytes(data=image_data, mime_type=mime_type),
                    prompt_text
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0.2,
                )
            )

            raw_text = getattr(response, "text", "{}")
            if not isinstance(raw_text, str):
                raw_text = str(raw_text)
            data = json.loads(raw_text)

            portion_scale = max(0.5, min(2.0, portion_scale))
            items: List[FoodItem] = []
            for raw_item in data.get("items", []):
                p_g = (raw_item.get("portion_g") or 100.0) * portion_scale
                scale = portion_scale
                items.append(FoodItem(
                    name=raw_item.get("name", "Aliment"),
                    portion_g=round(p_g, 1),
                    calories_kcal=round(raw_item.get("calories_kcal", 0.0) * scale, 1),
                    protein_g=round(raw_item.get("protein_g", 0.0) * scale, 1),
                    carbs_g=round(raw_item.get("carbs_g", 0.0) * scale, 1),
                    fat_g=round(raw_item.get("fat_g", 0.0) * scale, 1),
                    fiber_g=round((raw_item.get("fiber_g") or 0.0) * scale, 1),
                    confidence_score=raw_item.get("confidence_score", 0.85)
                ))

            res = self._format_analysis_result(items, portion_scale, source="gemini_vision", meal_type=meal_type)
            if data.get("dietary_advice"):
                res["dietary_advice"] = data["dietary_advice"]
            return res

        except Exception as e:
            logger.warning(f"Échec de l'appel Gemini Vision: {e}. Bascule sur le mode déterministe.")
            return None

    def analyze_meal(
        self,
        image_bytes: Optional[bytes] = None,
        mime_type: str = "image/jpeg",
        description: Optional[str] = None,
        portion_scale: float = 1.0,
        meal_type: MealType = "lunch"
    ) -> Dict[str, Any]:
        """Point d'entrée principal : analyse via Gemini Vision ou base locale/OpenFoodFacts."""
        portion_scale = max(0.5, min(2.0, portion_scale))

        # 1. Tentative Gemini Vision si image fournie et clé configurée
        if image_bytes and self.has_gemini_api:
            vision_result = self.estimate_from_gemini_vision(
                image_data=image_bytes,
                mime_type=mime_type,
                user_notes=description,
                portion_scale=portion_scale,
                meal_type=meal_type
            )
            if vision_result:
                return vision_result

        # 2. Mode Démo / Hors-ligne / Fallback Base locale & OpenFoodFacts
        effective_desc = description
        if not effective_desc:
            # Description démo intelligente basée sur le type de repas
            default_meals = {
                "breakfast": "Flocons d'avoine, oeuf, banane et baies",
                "lunch": "Blanc de poulet 150g, riz basmati 180g, brocoli et huile d'olive",
                "dinner": "Saumon pavé 140g, patate douce, haricots verts et avocat",
                "snack": "Pomme et pain de campagne"
            }
            effective_desc = default_meals.get(meal_type, "Blanc de poulet, riz basmati et brocoli")

        return self.estimate_from_description(
            description=effective_desc,
            portion_scale=portion_scale,
            meal_type=meal_type
        )

    def _format_analysis_result(
        self,
        items: List[FoodItem],
        portion_scale: float,
        source: str,
        meal_type: MealType
    ) -> Dict[str, Any]:
        """Agrège les items et calcule les totaux et pourcentages de macros."""
        total_cal = round(sum(i.calories_kcal for i in items), 1)
        total_prot = round(sum(i.protein_g for i in items), 1)
        total_carbs = round(sum(i.carbs_g for i in items), 1)
        total_fat = round(sum(i.fat_g for i in items), 1)
        total_fiber = round(sum(i.fiber_g or 0.0 for i in items), 1)

        # Calcul des pourcentages caloriques
        # Protéines: 4 kcal/g, Glucides: 4 kcal/g, Lipides: 9 kcal/g
        cal_prot = total_prot * 4.0
        cal_carbs = total_carbs * 4.0
        cal_fat = total_fat * 9.0
        macro_sum = cal_prot + cal_carbs + cal_fat

        if macro_sum > 0:
            pct_prot = round((cal_prot / macro_sum) * 100.0, 1)
            pct_carbs = round((cal_carbs / macro_sum) * 100.0, 1)
            pct_fat = round((cal_fat / macro_sum) * 100.0, 1)
        else:
            pct_prot, pct_carbs, pct_fat = 0.0, 0.0, 0.0

        avg_confidence = round(
            sum((i.confidence_score or 0.8) for i in items) / len(items), 2
        ) if items else 0.8

        # Conseil nutritionnel automatique
        advice = self._generate_nutrition_advice(total_prot, total_carbs, total_fat, total_fiber, meal_type)

        return {
            "meal_type": meal_type,
            "portion_scale": portion_scale,
            "source": source,
            "total_calories_kcal": total_cal,
            "macros": {
                "protein_g": total_prot,
                "protein_pct": pct_prot,
                "carbs_g": total_carbs,
                "carbs_pct": pct_carbs,
                "fat_g": total_fat,
                "fat_pct": pct_fat,
                "fiber_g": total_fiber,
            },
            "items": items,
            "confidence_score": avg_confidence,
            "dietary_advice": advice,
        }

    def _generate_nutrition_advice(
        self,
        protein_g: float,
        carbs_g: float,
        fat_g: float,
        fiber_g: float,
        meal_type: MealType
    ) -> str:
        """Génère un conseil nutritionnel contextuel pertinent."""
        if protein_g >= 30.0:
            return "Excellente teneur en protéines pour la récupération musculaire et la satiété."
        elif fiber_g >= 8.0:
            return "Riche en fibres alimentaires, très favorable pour le microbiote et le contrôle glycémique."
        elif carbs_g > 80.0 and protein_g < 15.0:
            return "Repas riche en glucides : pensez à ajouter une source de protéines ou de fibres pour lisser la glycémie."
        elif fat_g > 35.0:
            return "Teneur élevée en lipides : privilégiez les bonnes graisses (acides gras insaturés oméga-3/9)."
        else:
            return "Assiette bien équilibrée, idéale pour maintenir une énergie constante tout au long de la journée."
