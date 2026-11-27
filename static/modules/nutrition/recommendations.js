// static/modules/nutrition/recommendations.js - Suggestions de repas & préférences

function getActiveJournalDateKey() {
  const dateInput = document.getElementById('journal-date-picker') || document.getElementById('journal-date-input');
  return (dateInput && dateInput.value) || (typeof currentJournalDate === 'string' && currentJournalDate) || new Date().toISOString().slice(0, 10);
}

function getSkippedMealSuggestions(dateKey = getActiveJournalDateKey()) {
  const storageKey = `vitaltrack_skipped_meals_${dateKey}`;
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed) : new Set();
  } catch (_) {
    return _skippedMealSuggestionsFallback;
  }
}

function saveSkippedMealSuggestions(skippedSet, dateKey = getActiveJournalDateKey()) {
  const storageKey = `vitaltrack_skipped_meals_${dateKey}`;
  try {
    localStorage.setItem(storageKey, JSON.stringify(Array.from(skippedSet)));
  } catch (_) {
    _skippedMealSuggestionsFallback.clear();
    skippedSet.forEach((s) => _skippedMealSuggestionsFallback.add(s));
  }
}

function isMealSuggestionSkipped(mealType) {
  if (!mealType) return false;
  return getSkippedMealSuggestions().has(mealType);
}

function skipMealSuggestion(mealType) {
  if (!mealType) return;
  const skipped = getSkippedMealSuggestions();
  skipped.add(mealType);
  saveSkippedMealSuggestions(skipped);
  if (typeof renderMealsJournal === 'function') renderMealsJournal();
}

function restoreMealSuggestion(mealType) {
  if (!mealType) return;
  const skipped = getSkippedMealSuggestions();
  skipped.delete(mealType);
  saveSkippedMealSuggestions(skipped);
  if (typeof renderMealsJournal === 'function') renderMealsJournal();
}

window.skipMealSuggestion = skipMealSuggestion;
window.restoreMealSuggestion = restoreMealSuggestion;

function renderMealRecommendationHint(rec) {
  if (!rec || !rec.calories) return '';
  const mealType = rec.meal_type || '';
  const escapedMealType = escapeHtml(mealType);

  if (isMealSuggestionSkipped(mealType)) {
    return `
      <div class="mt-2 px-3 py-2.5 rounded-xl bg-slate-800/40 border border-slate-700/50 text-left w-full flex flex-wrap items-center justify-between gap-2" data-meal-recommendation-skipped="${escapedMealType}">
        <span class="text-[11px] font-medium text-slate-400">Repas sauté / Rien mangé</span>
        <button type="button"
          onclick="restoreMealSuggestion('${escapedMealType}')"
          class="px-2.5 py-1 rounded-lg bg-brand-500/15 hover:bg-brand-500/30 border border-brand-500/35 text-brand-300 text-[11px] font-semibold transition-colors">
          Relancer les suggestions
        </button>
      </div>
    `;
  }

  const calMin = Math.round(rec.calories.min || 0);
  const calMax = Math.round(rec.calories.max || 0);
  const calTarget = Math.round(rec.calories.target || 0);
  const prot = Math.round(rec.protein_g?.target || 0);
  const carbs = Math.round(rec.carbs_g?.target || 0);
  const fat = Math.round(rec.fat_g?.target || 0);
  const calText = calMin !== calMax ? `${calMin}–${calMax} kcal` : `${calTarget} kcal`;
  const suggested = rec.suggested_meal;
  const suggestedHtml = suggested && Array.isArray(suggested.items) && suggested.items.length > 0
    ? `
      <div class="mt-2 pt-2 border-t border-brand-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div class="min-w-0 flex-1">
          <div class="text-xs font-semibold text-emerald-300 break-words leading-snug">
            Idée : ${escapeHtml(suggested.title || '')}
          </div>
          <div class="text-[11px] text-slate-400 mt-0.5">
            ${Math.round(suggested.calories || 0)} kcal &bull; P: ${Math.round(suggested.protein_g || 0)}g &bull; G: ${Math.round(suggested.carbs_g || 0)}g &bull; L: ${Math.round(suggested.fat_g || 0)}g
          </div>
        </div>
        <button type="button"
          onclick="applySuggestedMeal('${escapedMealType}')"
          class="shrink-0 self-start sm:self-center px-2.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-500/40 text-emerald-200 text-[11px] font-bold transition-colors">
          Appliquer
        </button>
      </div>
    `
    : '';

  return `
    <div class="mt-2 px-3 py-2.5 rounded-xl bg-brand-500/10 border border-brand-500/25 text-left w-full" data-meal-recommendation="${escapedMealType}">
      <div class="flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <span class="font-bold text-brand-300">Suggestion : ~${calTarget} kcal <span class="font-normal text-slate-400">(${calText})</span></span>
        <button type="button"
          onclick="skipMealSuggestion('${escapedMealType}')"
          title="Je n'ai rien mangé pour ce repas / Ignorer la suggestion"
          class="px-2 py-0.5 rounded-lg bg-slate-800/60 hover:bg-slate-700/70 border border-slate-700/70 text-slate-300 hover:text-white text-[10px] font-semibold transition-colors">
          Rien mangé
        </button>
      </div>
      <div class="text-[11px] text-slate-300 mt-1">
        P: ${prot}g &bull; G: ${carbs}g &bull; L: ${fat}g
      </div>
      ${suggestedHtml}
    </div>
  `;
}

async function applySuggestedMeal(mealType) {
  const rec = currentJournalData?.nutrition_guidance?.recommendations?.[mealType];
  const suggested = rec?.suggested_meal;
  if (!suggested || !Array.isArray(suggested.items) || suggested.items.length === 0) return;

  const dateInput = document.getElementById('journal-date-picker') || document.getElementById('journal-date-input');
  const targetDate = (dateInput && dateInput.value) || currentJournalDate || new Date().toISOString().slice(0, 10);
  const items = suggested.items.map((it) => ({
    food_item_id: it.food_item_id || null,
    name: it.name,
    quantity: Number(it.quantity) > 0 ? Number(it.quantity) : 1,
    unit: it.unit || 'g',
    calories: it.calories ?? null,
    protein_g: it.protein_g ?? null,
    carbs_g: it.carbs_g ?? null,
    fat_g: it.fat_g ?? null,
    fiber_g: it.fiber_g ?? null,
  }));

  try {
    const res = await apiFetch(`/api/meals/journal/${encodeURIComponent(mealType)}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: targetDate, items }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json().catch(() => null);
    if (typeof showToast === 'function') showToast('Repas suggéré ajouté au journal', 'success');
    if (payload && typeof consolidateJournalMutationResponse === 'function') {
      consolidateJournalMutationResponse(targetDate, payload, mealType);
    } else if (typeof loadMealsJournal === 'function') {
      await loadMealsJournal(true);
    }
  } catch (err) {
    console.error('applySuggestedMeal error:', err);
    if (typeof showToast === 'function') showToast('Impossible d’ajouter le repas suggéré', 'error');
  }
}
window.applySuggestedMeal = applySuggestedMeal;

