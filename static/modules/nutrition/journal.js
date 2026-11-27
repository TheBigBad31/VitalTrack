// static/modules/nutrition/journal.js - Journal des repas, optimiste & sélection catalogue

// ============================================================================
// 5. JOURNAL DES REPAS DU QUOTIDIEN (4 DROP ZONES MODULAIRES)
// ============================================================================

// ----------------------------------------------------------------------------
// Utilitaires cache mémoire, calcul local des totaux & mutations optimistes
// ----------------------------------------------------------------------------

function journalTodayIso() {
  return new Date().toISOString().split('T')[0];
}

/**
 * Date du journal actuellement affichée (BALI-99 / Lot B).
 * Contrat unique pour tout ajout de repas : plus aucune écriture ne doit
 * utiliser `new Date()` en dur, sinon un plat ajouté depuis une date passée
 * atterrit sur aujourd'hui et le clic paraît sans effet.
 * Exposé sur `window` car `currentJournalDate` est un `let` de portée script
 * (invisible depuis les autres modules).
 */
function getActiveMealDate() {
  return currentJournalDate || journalTodayIso();
}
window.getActiveMealDate = getActiveMealDate;

/** Force la date active du journal (sans rechargement) pour les modules appelants. */
function setActiveMealDate(isoDate) {
  if (!isoDate) return getActiveMealDate();
  currentJournalDate = isoDate;
  const dateInput = document.getElementById('journal-date-input');
  if (dateInput && dateInput.value !== isoDate) dateInput.value = isoDate;
  return currentJournalDate;
}
window.setActiveMealDate = setActiveMealDate;

/** Libellé humain d'une date ISO pour les toasts et en-têtes. */
function formatJournalDateLabel(isoDate) {
  const target = isoDate || getActiveMealDate();
  if (target === journalTodayIso()) return "aujourd'hui";
  const parts = String(target).split('-');
  if (parts.length !== 3) return target;
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}
window.formatJournalDateLabel = formatJournalDateLabel;

/** Décale une date ISO (YYYY-MM-DD) de N jours, sans dérive de fuseau horaire. */
function shiftIsoDate(isoDate, days) {
  const parts = String(isoDate || journalTodayIso()).split('-').map(Number);
  const dt = new Date(Date.UTC(parts[0], (parts[1] || 1) - 1, parts[2] || 1));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().split('T')[0];
}

function roundJournalValue(value) {
  return Math.round((Number(value) || 0) * 10) / 10;
}

function cloneJournalJson(value) {
  try {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  } catch (e) {
    return value;
  }
}

/** Récupère les données du journal d'une date (cache mémoire ou date courante). */
function getJournalForDate(date) {
  if (date === currentJournalDate && currentJournalData) return currentJournalData;
  return journalCacheByDate.get(date) || null;
}

/** Écrit le journal en cache et, si la date est affichée, met à jour la référence courante. */
function storeJournalForDate(date, journal) {
  if (!date || !journal) return;
  journalCacheByDate.set(date, journal);
  if (date === currentJournalDate) currentJournalData = journal;
}

function setJournalLoading(isLoading) {
  const container = document.getElementById('journal-slots-container');
  if (!container) return;
  if (isLoading) {
    container.classList.add('opacity-50', 'pointer-events-none', 'transition-opacity');
    container.setAttribute('aria-busy', 'true');
  } else {
    container.classList.remove('opacity-50', 'pointer-events-none');
    container.removeAttribute('aria-busy');
  }
}

/**
 * Recalcule en mémoire les totaux des 4 repas et le day_summary de la journée,
 * avec exactement la même formule et les mêmes arrondis que le serveur
 * (app.py: sum des items, macros en % des kcal P/G/L).
 */
function recalculateJournalTotals(journal) {
  if (!journal) return journal;
  const meals = Array.isArray(journal.meals) ? journal.meals : (journal.meals = []);

  let dayCal = 0, dayProt = 0, dayCarbs = 0, dayFat = 0, dayFiber = 0;

  meals.forEach(meal => {
    const items = Array.isArray(meal.items) ? meal.items : (meal.items = []);
    let mCal = 0, mProt = 0, mCarbs = 0, mFat = 0, mFiber = 0;
    items.forEach(it => {
      mCal += Number(it.calories) || 0;
      mProt += Number(it.protein_g) || 0;
      mCarbs += Number(it.carbs_g) || 0;
      mFat += Number(it.fat_g) || 0;
      mFiber += Number(it.fiber_g) || 0;
    });
    meal.total_calories = roundJournalValue(mCal);
    meal.total_protein_g = roundJournalValue(mProt);
    meal.total_carbs_g = roundJournalValue(mCarbs);
    meal.total_fat_g = roundJournalValue(mFat);
    meal.total_fiber_g = roundJournalValue(mFiber);

    dayCal += mCal; dayProt += mProt; dayCarbs += mCarbs; dayFat += mFat; dayFiber += mFiber;
  });

  const pCal = dayProt * 4.0;
  const cCal = dayCarbs * 4.0;
  const fCal = dayFat * 9.0;
  const macroCal = pCal + cCal + fCal;

  journal.day_summary = {
    total_calories: roundJournalValue(dayCal),
    total_protein_g: roundJournalValue(dayProt),
    total_carbs_g: roundJournalValue(dayCarbs),
    total_fat_g: roundJournalValue(dayFat),
    total_fiber_g: roundJournalValue(dayFiber)
  };
  return journal;
}

/** Retourne le repas d'un créneau, en le créant à 0 kcal si le serveur ne l'a pas fourni. */
function ensureJournalMealSlot(journal, slot) {
  const meals = Array.isArray(journal.meals) ? journal.meals : (journal.meals = []);
  let meal = meals.find(m => m.meal_type === slot);
  if (!meal) {
    meal = {
      id: null,
      date: journal.date,
      meal_type: slot,
      photo_url: null,
      total_calories: 0,
      total_protein_g: 0,
      total_carbs_g: 0,
      total_fat_g: 0,
      total_fiber_g: 0,
      items: []
    };
    meals.push(meal);
  }
  if (!Array.isArray(meal.items)) meal.items = [];
  return meal;
}

/** Construit l'objet item affiché immédiatement, avec la formule exacte du backend. */
function buildOptimisticJournalItem(catalogItem, quantity) {
  const baseQty = Number(catalogItem.default_quantity) || (catalogItem.item_type === 'dish' ? 1 : 100);
  const ratio = quantity / baseQty;
  return {
    id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    meal_log_id: null,
    food_item_id: catalogItem.id,
    name: catalogItem.name,
    quantity: quantity,
    unit: catalogItem.default_unit || 'g',
    calories: roundJournalValue((catalogItem.calories_per_unit || 0) * ratio),
    protein_g: roundJournalValue((catalogItem.protein_per_unit_g || 0) * ratio),
    carbs_g: roundJournalValue((catalogItem.carbs_per_unit_g || 0) * ratio),
    fat_g: roundJournalValue((catalogItem.fat_per_unit_g || 0) * ratio),
    fiber_g: roundJournalValue((catalogItem.fiber_per_unit_g || 0) * ratio),
    _optimistic: true
  };
}

// --- Suivi des mutations optimistes (évite qu'une revalidation écrase l'état local) ---

function beginJournalMutation(date) {
  journalPendingMutations.set(date, (journalPendingMutations.get(date) || 0) + 1);
}

function endJournalMutation(date) {
  const remaining = (journalPendingMutations.get(date) || 0) - 1;
  if (remaining > 0) journalPendingMutations.set(date, remaining);
  else journalPendingMutations.delete(date);
}

function restoreJournalSnapshot(snapshot) {
  if (!snapshot) return;
  const { date, data } = snapshot;
  if (data) journalCacheByDate.set(date, data);
  if (date === currentJournalDate) {
    currentJournalData = data || journalCacheByDate.get(date) || null;
    renderMealsJournal();
    syncDashboardSummary(date, currentJournalData);
  }
}

/** Ajout optimiste : l'item et les totaux sont calculés et rendus sans attendre le réseau. */
function applyOptimisticItemAdded(date, slot, optimisticItem) {
  const journal = getJournalForDate(date);
  if (!journal) return null;

  const snapshot = { date, data: cloneJournalJson(journal) };
  ensureJournalMealSlot(journal, slot).items.push(optimisticItem);
  recalculateJournalTotals(journal);
  storeJournalForDate(date, journal);

  if (date === currentJournalDate) {
    renderMealsJournal();
    syncDashboardSummary(date, journal);
  }
  return snapshot;
}

/** Suppression optimiste : l'item disparaît et les totaux sont recalculés avant le réseau. */
function applyOptimisticItemRemoved(date, itemId) {
  const journal = getJournalForDate(date);
  if (!journal) return null;

  const snapshot = { date, data: cloneJournalJson(journal) };
  let removed = false;
  (journal.meals || []).forEach(meal => {
    const items = Array.isArray(meal.items) ? meal.items : [];
    const idx = items.findIndex(it => String(it.id) === String(itemId));
    if (idx >= 0) {
      items.splice(idx, 1);
      removed = true;
    }
  });
  if (!removed) return null;

  recalculateJournalTotals(journal);
  storeJournalForDate(date, journal);

  if (date === currentJournalDate) {
    renderMealsJournal();
    syncDashboardSummary(date, journal);
  }
  return snapshot;
}

/**
 * Consolidation de la réponse serveur (POST/DELETE) sans aucun rechargement :
 * on remplace uniquement le repas concerné et le day_summary renvoyés par l'API.
 */
function consolidateJournalMutationResponse(date, payload, slot) {
  if (!payload) return;
  const journal = getJournalForDate(date);
  if (!journal) return;

  const meals = Array.isArray(journal.meals) ? journal.meals : (journal.meals = []);
  const mealLog = payload.meal_log;
  if (mealLog) {
    const targetSlot = mealLog.meal_type || slot;
    const idx = meals.findIndex(m => m.meal_type === targetSlot);
    if (idx >= 0) meals[idx] = mealLog;
    else meals.push(mealLog);
  }

  if (payload.day_summary) journal.day_summary = payload.day_summary;
  else recalculateJournalTotals(journal);

  storeJournalForDate(date, journal);
  journalFetchedAtByDate.set(date, Date.now());

  if (typeof currentData !== 'undefined' && currentData && Array.isArray(currentData.recent_meals) && mealLog) {
    const targetSlot = mealLog.meal_type || slot;
    const normDate = String(date).slice(0, 10);
    const idx = currentData.recent_meals.findIndex(m => String(m.date || '').slice(0, 10) === normDate && m.meal_type === targetSlot);
    const itemsList = Array.isArray(mealLog.items) ? mealLog.items : [];
    if (itemsList.length === 0) {
      if (idx >= 0) currentData.recent_meals.splice(idx, 1);
    } else {
      const projected = {
        id: mealLog.id,
        date: normDate,
        meal_type: targetSlot,
        total_calories_kcal: Number(mealLog.total_calories || 0),
        protein_g: Number(mealLog.total_protein_g || 0),
        carbs_g: Number(mealLog.total_carbs_g || 0),
        fat_g: Number(mealLog.total_fat_g || 0),
        fiber_g: Number(mealLog.total_fiber_g || 0),
        photo_data_url: mealLog.photo_url || null,
        items: itemsList.map(it => ({
          name: it.name,
          portion_g: it.unit === 'g' ? it.quantity : 100,
          calories_kcal: it.calories,
          protein_g: it.protein_g || 0,
          carbs_g: it.carbs_g || 0,
          fat_g: it.fat_g || 0,
          fiber_g: it.fiber_g || 0
        }))
      };
      if (idx >= 0) currentData.recent_meals[idx] = projected;
      else currentData.recent_meals.push(projected);
    }
  }

  if (date === currentJournalDate) {
    renderMealsJournal();
    syncDashboardSummary(date, journal);
  }
  if (typeof renderNutritionView === 'function') {
    try { renderNutritionView(); } catch (e) { console.warn('[nutrition] renderNutritionView:', e); }
  }
}

/** Le résumé du tableau de bord ne suit que les modifications du jour même. */
function syncDashboardSummary(date, journal) {
  if (!journal || date !== journalTodayIso()) return;
  if (typeof applyJournalDaySummaryToDashboard === 'function') {
    applyJournalDaySummaryToDashboard(journal.day_summary);
  }
}

// ----------------------------------------------------------------------------
// Chargement du journal : cache mémoire (0 ms) + stale-while-revalidate
// ----------------------------------------------------------------------------

/**
 * Charge (ou recharge) une date puis met en cache le résultat.
 * Les requêtes concurrentes sur la même date sont dédupliquées.
 * @param {string} targetDate
 * @param {{render?: boolean}} [options]
 */
async function fetchJournalDate(targetDate, options = {}) {
  if (!targetDate) return null;
  const render = options.render === true;

  let promise = journalInflightByDate.get(targetDate);
  if (!promise) {
    promise = (async () => {
      const readOnlyParam = (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active && window.currentReadOnlyFriend.friend_id) ? `&user_id=${window.currentReadOnlyFriend.friend_id}` : '';
      const res = await apiFetch(`/api/meals/journal?date=${encodeURIComponent(targetDate)}${readOnlyParam}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })();
    journalInflightByDate.set(targetDate, promise);
    const cleanup = () => journalInflightByDate.delete(targetDate);
    promise.then(cleanup, cleanup);
  }

  try {
    const data = await promise;
    // Une mutation optimiste est en cours sur cette date : la réponse est déjà obsolète.
    if ((journalPendingMutations.get(targetDate) || 0) > 0) return null;

    journalCacheByDate.set(targetDate, data);
    journalFetchedAtByDate.set(targetDate, Date.now());
    if (targetDate === currentJournalDate) {
      currentJournalData = data;
      setJournalLoading(false);
      if (render) {
        renderMealsJournal();
        syncDashboardSummary(targetDate, data);
      }
    }
    return data;
  } catch (err) {
    console.error("Erreur chargement journal repas:", err);
    return null;
  }
}

async function loadMealsJournal(dateStr) {
  const targetDate = dateStr || currentJournalDate || journalTodayIso();
  currentJournalDate = targetDate;

  const dateInput = document.getElementById('journal-date-input');
  if (dateInput && dateInput.value !== targetDate) dateInput.value = targetDate;

  const cached = journalCacheByDate.get(targetDate);

  if (cached) {
    // 0 ms : la date est déjà en cache, on peint immédiatement puis on revalide en silence
    // (uniquement si la donnée a plus de 30 s, pour ne pas spammer l'API au changement de layout).
    currentJournalData = cached;
    setJournalLoading(false);
    renderMealsJournal();
    syncDashboardSummary(targetDate, cached);
    const lastFetch = journalFetchedAtByDate.get(targetDate) || 0;
    if (Date.now() - lastFetch > JOURNAL_REVALIDATE_MS) {
      fetchJournalDate(targetDate, { render: true });
    }
    return;
  }

  // Pas encore en cache : on estompe l'ancien jour (pas de flash de zéros) puis on rend.
  setJournalLoading(true);
  const data = await fetchJournalDate(targetDate, { render: true });
  if (targetDate === currentJournalDate) {
    setJournalLoading(false);
    if (!data) {
      // BALI-99 / Lot A : plus jamais d'échec silencieux — l'utilisateur voit
      // que la date n'a pas pu être chargée et peut relancer.
      renderJournalLoadError(targetDate);
      if (typeof showToast === 'function') {
        showToast(`Impossible de charger le journal du ${formatJournalDateLabel(targetDate)}.`, "error");
      }
    }
  }
}

/** Affiche une carte d'erreur explicite (avec relance) dans la zone des 4 repas. */
function renderJournalLoadError(targetDate) {
  const container = document.getElementById('journal-slots-container');
  if (!container) return;
  container.innerHTML = `
    <div class="col-span-full bg-rose-500/10 border border-rose-500/30 rounded-2xl p-4 space-y-2 text-center">
      <p class="text-sm font-bold text-rose-300">Journal indisponible pour le ${formatJournalDateLabel(targetDate)}</p>
      <p class="text-xs text-slate-400">Le serveur n'a pas pu renvoyer les repas de cette date (réseau ou erreur API).</p>
      <button type="button" onclick="loadMealsJournal(getActiveMealDate())" class="px-3 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/30 text-rose-200 text-xs font-semibold transition-colors">
        Réessayer
      </button>
    </div>
  `;
  if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
}
window.renderJournalLoadError = renderJournalLoadError;

/** Précharge silencieusement J-1 à l'ouverture de l'onglet Nutrition (1 seule fois). */
function prefetchAdjacentJournalDates() {
  if (journalPrefetchDone) return;
  journalPrefetchDone = true;

  const yesterday = shiftIsoDate(journalTodayIso(), -1);
  if (journalCacheByDate.has(yesterday) || yesterday === currentJournalDate) return;
  fetchJournalDate(yesterday, { render: false });
}

/** Vide le cache journal (actualisation manuelle) pour forcer une relecture serveur. */
function invalidateJournalCache(date) {
  if (date) {
    journalCacheByDate.delete(date);
    journalFetchedAtByDate.delete(date);
    return;
  }
  journalCacheByDate.clear();
  journalFetchedAtByDate.clear();
  journalPrefetchDone = false;
}

/**
 * Change la date affichée (BALI-99 / Lot B).
 * Après chargement, le tableau récapitulatif et l'histogramme 7 jours sont
 * ré-alignés sur la date sélectionnée (fin de fenêtre = date affichée).
 */
async function changeJournalDate(offset) {
  await loadMealsJournal(shiftIsoDate(currentJournalDate, offset));
  refreshNutritionDayViews();
}

async function handleJournalDateChange(e) {
  const value = e.target.value;
  if (!value) return;
  await loadMealsJournal(value);
  refreshNutritionDayViews();
}

async function setJournalToToday() {
  await loadMealsJournal(journalTodayIso());
  refreshNutritionDayViews();
}

/** Re-rend les agrégats de la vue nutrition (tableau + histogramme) sur la date active. */
function refreshNutritionDayViews() {
  if (typeof renderNutritionView === 'function') {
    try {
      renderNutritionView();
    } catch (err) {
      console.warn("[journal] rafraîchissement vue nutrition impossible:", err);
    }
  }
}
window.refreshNutritionDayViews = refreshNutritionDayViews;

const _skippedMealSuggestionsFallback = new Set();


function renderMealsJournal() {
  if (!currentJournalData) return;

  // 1. Synthèse globale du jour
  const sum = currentJournalData.day_summary || {};
  const elCal = document.getElementById('journal-day-cals');
  const elProt = document.getElementById('journal-day-prot');
  const elCarbs = document.getElementById('journal-day-carbs');
  const elFat = document.getElementById('journal-day-fat');
  const elFiber = document.getElementById('journal-day-fiber');

  if (elCal) elCal.textContent = Math.round(sum.total_calories || 0);
  if (elProt) elProt.textContent = `${Math.round(sum.total_protein_g || 0)}g P`;
  if (elCarbs) elCarbs.textContent = `${Math.round(sum.total_carbs_g || 0)}g G`;
  if (elFat) elFat.textContent = `${Math.round(sum.total_fat_g || 0)}g L`;
  if (elFiber) elFiber.textContent = `${Math.round(sum.total_fiber_g || 0)}g F`;

  if (typeof renderJournalDayMacroBars === 'function') {
    renderJournalDayMacroBars(sum);
  }

  const bonusPill = document.getElementById('journal-workout-bonus-pill');
  if (bonusPill) {
    const workoutBonus = Math.round(currentJournalData.workout_calories_kcal || 0);
    if (workoutBonus > 0) {
      bonusPill.textContent = `+${workoutBonus} kcal séance`;
      bonusPill.title = `+${workoutBonus} kcal débloqués par votre séance du jour`;
      bonusPill.classList.remove('hidden');
    } else {
      bonusPill.classList.add('hidden');
    }
  }

  // 2. Les 4 repas
  const slotConfig = {
    breakfast: { name: "Petit-déjeuner", emoji: "🥐", border: "border-amber-500/30", color: "text-amber-400", bgBadge: "bg-amber-500/10" },
    lunch: { name: "Déjeuner", emoji: "🥗", border: "border-brand-500/30", color: "text-brand-400", bgBadge: "bg-brand-500/10" },
    snack: { name: "Goûter", emoji: "🍎", border: "border-pink-500/30", color: "text-pink-400", bgBadge: "bg-pink-500/10" },
    dinner: { name: "Dîner", emoji: "🍲", border: "border-indigo-500/30", color: "text-indigo-400", bgBadge: "bg-indigo-500/10" }
  };

  const meals = currentJournalData.meals || [];
  const mealsByType = {};
  meals.forEach(m => { mealsByType[m.meal_type] = m; });
  const guidanceRecs = (currentJournalData.nutrition_guidance && currentJournalData.nutrition_guidance.recommendations) || {};

  const container = document.getElementById('journal-slots-container');
  if (!container) return;

  container.innerHTML = ['breakfast', 'lunch', 'snack', 'dinner'].map(slot => {
    const cfg = slotConfig[slot];
    const m = mealsByType[slot] || { total_calories: 0, total_protein_g: 0, total_carbs_g: 0, total_fat_g: 0, items: [] };
    const items = m.items || [];

    return `
      <div 
        id="meal-zone-${slot}"
        class="meal-drop-zone bg-[#151D2A] border ${cfg.border} hover:border-brand-500/50 rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3.5 shadow-sm transition-all duration-150"
        ondragover="handleMealDragOver(event, '${slot}')"
        ondragleave="handleMealDragLeave(event, '${slot}')"
        ondrop="handleMealDrop(event, '${slot}')"
      >
        <div class="flex items-center justify-between border-b border-[#1F2A3C] pb-3">
          <div class="flex items-center space-x-2.5">
            <span class="text-2xl">${cfg.emoji}</span>
            <div>
              <h4 class="font-bold text-white text-base">${cfg.name}</h4>
              <div class="text-xs text-slate-400">${items.length} aliment${items.length > 1 ? 's' : ''}</div>
            </div>
          </div>
          <div class="text-right">
            <span class="text-lg font-black ${cfg.color}">${Math.round(m.total_calories || 0)}</span>
            <span class="text-xs text-slate-400 font-semibold">kcal</span>
            <div class="text-[10px] text-slate-400 flex items-center justify-end gap-1.5 pt-0.5">
              <span>P: ${Math.round(m.total_protein_g || 0)}g</span>
              <span>G: ${Math.round(m.total_carbs_g || 0)}g</span>
              <span>L: ${Math.round(m.total_fat_g || 0)}g</span>
            </div>
          </div>
        </div>

        <!-- Indicateur dynamique au survol glissé (« Déposer ici ») -->
        <div id="drop-placeholder-${slot}" class="drop-target-placeholder hidden py-3 px-4 border-2 border-dashed border-brand-400 rounded-xl bg-brand-500/10 text-brand-300 text-xs font-bold text-center flex items-center justify-center space-x-2 animate-pulse">
          <i data-lucide="arrow-down-to-dot" class="w-4 h-4"></i>
          <span>Déposer ici pour ajouter à ce repas</span>
        </div>

        <!-- Liste des aliments consommés -->
        <div class="space-y-2 min-h-[50px]">
          ${items.length === 0 ? `
            <div class="py-4 text-center text-xs text-slate-500 border border-dashed border-[#1F2A3C] rounded-xl flex flex-col items-center justify-center space-y-1">
              <span>Aucun aliment composé pour ce repas.</span>
              <span class="text-[11px] text-slate-400 font-medium">Glissez un aliment depuis le catalogue de gauche 👈</span>
              ${renderMealRecommendationHint(guidanceRecs[slot])}
            </div>
          ` : items.map(it => {
            const isPending = it._optimistic === true || String(it.id).startsWith('tmp-');
            return `
            <div class="flex items-center justify-between p-2 rounded-xl bg-[#0B0F17] border border-[#1F2A3C] hover:border-slate-700 transition-colors ${isPending ? 'opacity-70' : ''}"${isPending ? ' title="Enregistrement en cours…"' : ''}>
              <div class="flex-1 pr-2">
                <div class="text-xs font-bold text-white line-clamp-1">${escapeHtml(it.name)}${isPending ? ' <span class="text-[10px] font-normal text-slate-500">• en cours</span>' : ''}</div>
                <div class="text-[11px] text-slate-400">
                  <span class="font-semibold text-slate-300">${escapeHtml(it.quantity)} ${escapeHtml(it.unit)}</span> &bull; 
                  <span class="text-brand-400 font-bold">${Math.round(it.calories)} kcal</span> 
                  (P:${Math.round(it.protein_g || 0)}g G:${Math.round(it.carbs_g || 0)}g L:${Math.round(it.fat_g || 0)}g)
                </div>
              </div>
              ${(isPending || (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active)) ? '' : `
              <button onclick="removeMealLogItem('${it.id}')" title="Retirer l'aliment" class="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 shrink-0 write-action-btn">
                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              </button>`}
            </div>
          `;
          }).join('')}
        </div>

        <!-- Boutons d'actions -->
        <div class="flex items-center gap-2 pt-2 border-t border-[#1F2A3C]/70 ${(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active) ? 'hidden' : ''}">
          <button onclick="openSelectFromCatalogModal('${slot}')" class="flex-1 py-2 px-3 rounded-xl bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/30 text-brand-300 text-xs font-bold flex items-center justify-center space-x-1.5 transition-colors">
            <i data-lucide="plus" class="w-4 h-4"></i>
            <span>+ Ajouter un aliment</span>
          </button>
          <button onclick="openMealModal('${slot}')" title="Analyser ce repas par photo" aria-label="Analyser ce repas par photo" class="py-2 px-3 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 text-indigo-300 text-xs font-semibold flex items-center space-x-1 transition-colors">
            <i data-lucide="camera" class="w-3.5 h-3.5"></i>
            <span>Photo</span>
          </button>
          ${items.length > 0 ? `
            <button onclick="saveSlotAsDishModal('${slot}')" title="Créer un plat réutilisable à partir de ce repas" class="py-2 px-3 rounded-xl bg-[#0B0F17] hover:bg-[#1F2A3C] border border-[#1F2A3C] text-amber-400 text-xs font-semibold flex items-center space-x-1 transition-colors">
              <i data-lucide="star" class="w-3.5 h-3.5"></i>
              <span class="hidden sm:inline">Créer plat</span>
            </button>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');

  // Icônes rendues uniquement dans le journal (pas de scan complet du document)
  refreshIcons(container);

  // 3. Synthèse des bienfaits du jour (Stage 13)
  renderJournalDayBenefitsSummary(meals);
}

function aggregateDayBenefits(meals) {
  const byId = new Map();
  const catalogById = new Map(
    (Array.isArray(currentCatalogItems) ? currentCatalogItems : []).map(it => [String(it.id), it])
  );

  (Array.isArray(meals) ? meals : []).forEach(meal => {
    (Array.isArray(meal && meal.items) ? meal.items : []).forEach(it => {
      const catItem = it.food_item_id != null ? catalogById.get(String(it.food_item_id)) : null;
      const benefits = Array.isArray(it.benefits) && it.benefits.length > 0
        ? it.benefits
        : (catItem && Array.isArray(catItem.benefits) ? catItem.benefits : []);

      benefits.forEach(b => {
        const key = String(b.benefit_id || b.id || b.title || '');
        if (!key) return;
        let entry = byId.get(key);
        if (!entry) {
          entry = {
            benefit_id: b.benefit_id || b.id || key,
            title: b.title || key,
            explanation: b.explanation || '',
            icon: b.icon || '🛡️',
            foodNames: []
          };
          byId.set(key, entry);
        }
        if (it.name && !entry.foodNames.includes(it.name)) {
          entry.foodNames.push(it.name);
        }
      });
    });
  });

  return Array.from(byId.values());
}

function renderJournalDayBenefitsSummary(meals) {
  const container = document.getElementById('journal-day-benefits-tags') || document.getElementById('journal-day-benefits-summary');
  const countBadge = document.getElementById('journal-benefits-count-badge') || document.getElementById('journal-day-benefits-count');
  if (!container) return;

  const benefitsList = aggregateDayBenefits(meals);

  if (countBadge) {
    countBadge.textContent = `${benefitsList.length} bienfait${benefitsList.length > 1 ? 's' : ''} actif${benefitsList.length > 1 ? 's' : ''}`;
  }

  if (benefitsList.length === 0) {
    container.innerHTML = '<span class="text-xs text-slate-500 italic">Ajoutez des aliments à vos repas pour découvrir les bienfaits métaboliques et santé de votre journée.</span>';
    return;
  }

  container.innerHTML = benefitsList.map(b => {
    const bTitle = escapeHtml(b.title || '');
    const bExp = b.explanation ? ' : ' + escapeHtml(b.explanation) : '';
    const bFoods = escapeHtml((b.foodNames || []).join(', '));
    const bIcon = escapeHtml(b.icon || '🛡️');
    return `
    <div 
      class="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-brand-500/10 border border-brand-500/25 text-brand-300 text-xs shadow-sm cursor-help hover:bg-brand-500/20 hover:scale-105 transition-all"
      title="${bTitle}${bExp} (Apporté par : ${bFoods})"
    >
      <span class="text-base">${bIcon}</span>
      <span class="text-[10px] font-bold text-brand-300 font-mono">${(b.foodNames || []).length}</span>
    </div>
  `;
  }).join('');
}

async function removeMealLogItem(itemId) {
  // Un item encore en cours d'enregistrement n'a pas d'ID serveur : on ignore le clic.
  if (String(itemId).startsWith('tmp-')) return;

  const targetDate = currentJournalDate;
  const journal = getJournalForDate(targetDate);
  if (!journal) return;

  const item = (journal.meals || [])
    .flatMap(m => m.items || [])
    .find(it => String(it.id) === String(itemId));
  const itemName = item ? item.name : "l'aliment";

  // 1) Retrait immédiat en mémoire + rendu (l'UI ne bloque plus sur le DELETE)
  const snapshot = applyOptimisticItemRemoved(targetDate, itemId);
  if (!snapshot) return;

  // 2) Persistance en arrière-plan puis consolidation de la réponse serveur
  beginJournalMutation(targetDate);
  try {
    const res = await apiFetch(`/api/meals/journal/items/${itemId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const payload = await res.json().catch(() => null);
    endJournalMutation(targetDate);
    consolidateJournalMutationResponse(targetDate, payload, null);

    if (typeof showToast === 'function') showToast(`${itemName} retiré du repas`, "success");
  } catch (err) {
    endJournalMutation(targetDate);
    console.error("[journal] Suppression impossible, rollback :", err);
    restoreJournalSnapshot(snapshot);
    if (typeof showToast === 'function') {
      showToast(`Impossible de retirer ${itemName} — modification annulée`, "error");
    } else {
      alert("Erreur lors de la suppression de l'aliment");
    }
    // Réconciliation silencieuse avec le serveur (le DELETE a pu aboutir malgré l'erreur réseau)
    fetchJournalDate(targetDate, { render: true });
  }
}

// ============================================================================
// 6. MODALE ALTERNATIVE DE SÉLECTION CLIC / DOUBLE-CLIC
// ============================================================================

let currentSelectedCatalogItem = null;

function openSelectFromCatalogModal(slot) {
  currentActiveMealSlot = slot || 'lunch';
  currentSelectedCatalogItem = null;

  const slotTitles = {
    breakfast: "Petit-déjeuner 🥐",
    lunch: "Déjeuner 🥗",
    snack: "Goûter 🍎",
    dinner: "Dîner 🍲"
  };
  const titleEl = document.getElementById('modal-select-cat-slot-title');
  if (titleEl) titleEl.textContent = slotTitles[currentActiveMealSlot] || currentActiveMealSlot;

  renderModalCatalogList();

  const modal = document.getElementById('modal-select-catalog-item');
  if (modal) modal.classList.remove('hidden');
}

function closeSelectFromCatalogModal() {
  const modal = document.getElementById('modal-select-catalog-item');
  if (modal) modal.classList.add('hidden');
}

function promptAddToMeal(itemId, slot) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  if (!item) return;
  const targetSlot = slot || currentActiveMealSlot || 'lunch';
  currentActiveMealSlot = targetSlot;
  openDropPortionModal(item, targetSlot);
}

function renderModalCatalogList(searchQuery = '') {
  const container = document.getElementById('modal-catalog-picker-list');
  if (!container) return;

  const q = searchQuery.toLowerCase().trim();
  const filtered = currentCatalogItems.filter(it => !q || it.name.toLowerCase().includes(q));

  if (filtered.length === 0) {
    container.innerHTML = '<div class="py-8 text-center text-xs text-slate-500">Aucun ingrédient ou plat correspondant trouvé.</div>';
    return;
  }

  container.innerHTML = filtered.map(it => {
    const isDish = it.item_type === 'dish';
    const isPublic = Boolean(it.is_public || it.user_id === 0 || it.user_id === null || it.source === 'public');
    const isFriend = Boolean(it.owner_name || it.friend_name || (it.source === 'friend' || it.source === 'friends'));
    let badge = '';
    if (isPublic) {
      badge = '<span class="inline-flex items-center justify-center w-4 h-4 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30" title="Catalogue public"><i data-lucide="globe" class="w-2.5 h-2.5"></i></span>';
    } else if (isFriend) {
      badge = `<span class="inline-flex items-center justify-center w-4 h-4 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30" title="Partagé par ${escapeHtml(it.owner_name || it.friend_name || 'Ami')}"><i data-lucide="user-check" class="w-2.5 h-2.5"></i></span>`;
    } else {
      badge = '<span class="inline-flex items-center justify-center w-4 h-4 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30" title="Création personnelle"><i data-lucide="user" class="w-2.5 h-2.5"></i></span>';
    }
    const naturePill = isDish
      ? '<span class="text-[9px] px-1.5 py-0.2 rounded-md font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/35">🍲 Plat composé</span>'
      : '<span class="text-[9px] px-1.5 py-0.2 rounded-md font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">Ingrédient</span>';
    const itId = escapeHtml(String(it.id));
    const itName = escapeHtml(it.name || '');
    const itRef = escapeHtml(`${it.default_quantity} ${it.default_unit || 'g'}`);
    const catMeta = getCatalogCategoryMeta(resolveCatalogItemCategory(it));
    const catBadge = `<span class="text-[9px] px-1.5 py-0.2 rounded-md border ${catMeta.badgeClass}">${catMeta.emoji} ${escapeHtml(catMeta.shortLabel)}</span>`;
    return `
      <div onclick="selectCatalogItemForPortion('${itId}')" class="p-2.5 rounded-xl bg-[#0B0F17] hover:bg-[#1F2A3C] border border-[#1F2A3C] hover:border-brand-500/50 cursor-pointer flex items-center justify-between transition-colors">
        <div class="flex-1 pr-2">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-xs font-bold text-white">${itName}</span>
            ${naturePill}
            ${catBadge}
            ${badge}
          </div>
          <div class="text-[11px] text-slate-400">Réf: ${itRef} &bull; ${Math.round(it.calories_per_unit)} kcal</div>
        </div>
        <button class="px-2 py-1 rounded-lg bg-brand-500/20 text-brand-300 text-xs font-semibold shrink-0">Choisir</button>
      </div>
    `;
  }).join('');
  refreshIcons(container);
}

function selectCatalogItemForPortion(itemId) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  if (!item) return;

  currentSelectedCatalogItem = item;
  document.getElementById('picker-step-select').classList.add('hidden');
  document.getElementById('picker-step-portion').classList.remove('hidden');

  document.getElementById('picker-selected-item-name').textContent = item.name;
  document.getElementById('picker-portion-qty').value = item.default_quantity || 100;
  document.getElementById('picker-portion-unit-label').textContent = item.default_unit || 'g';

  updatePickerLiveMacros();
}

function backToPickerList() {
  document.getElementById('picker-step-select').classList.remove('hidden');
  document.getElementById('picker-step-portion').classList.add('hidden');
}

function updatePickerLiveMacros() {
  if (!currentSelectedCatalogItem) return;
  const item = currentSelectedCatalogItem;
  const qty = parseFloat(document.getElementById('picker-portion-qty').value) || 0;
  const ratio = qty / (item.default_quantity || 100);

  const cal = Math.round(item.calories_per_unit * ratio);
  const prot = Math.round((item.protein_per_unit_g || 0) * ratio * 10) / 10;
  const carbs = Math.round((item.carbs_per_unit_g || 0) * ratio * 10) / 10;
  const fat = Math.round((item.fat_per_unit_g || 0) * ratio * 10) / 10;

  document.getElementById('picker-live-cals').textContent = `${cal} kcal`;
  document.getElementById('picker-live-macros').textContent = `Protéines: ${prot}g | Glucides: ${carbs}g | Lipides: ${fat}g`;
}

/**
 * Ajout d'un aliment au repas actif (modale de sélection) en Optimistic UI :
 * l'item et les totaux sont affichés immédiatement, la requête part ensuite.
 */
function confirmAddCatalogItemToMeal() {
  if (!currentSelectedCatalogItem) return;
  const item = currentSelectedCatalogItem;
  const qty = parseFloat(document.getElementById('picker-portion-qty').value);
  if (!qty || qty <= 0) {
    alert("Veuillez saisir une quantité valide.");
    return;
  }

  const slot = currentActiveMealSlot || 'lunch';
  const targetDate = currentJournalDate;
  const payload = {
    date: targetDate,
    food_item_id: item.id,
    quantity: qty,
    unit: item.default_unit || 'g'
  };

  // Fermeture immédiate des modales (retour du focus utilisateur)
  closeSelectFromCatalogModal();
  backToPickerList();

  // Mise à jour optimiste + rendu AVANT la fin de la requête réseau (< 16 ms)
  const optimisticItem = buildOptimisticJournalItem(item, qty);
  const snapshot = applyOptimisticItemAdded(targetDate, slot, optimisticItem);
  if (typeof showToast === 'function') {
    showToast(`'${item.name}' (${qty}${item.default_unit || 'g'}) ajouté !`, 'success');
  }

  persistOptimisticAddition(payload, targetDate, slot, snapshot, item);
}

/**
 * Envoie l'ajout au serveur puis consolide la réponse (meal_log + day_summary)
 * sans rappeler loadMealsJournal() ni loadDashboardData().
 */
async function persistOptimisticAddition(payload, targetDate, slot, snapshot, catalogItem) {
  beginJournalMutation(targetDate);
  try {
    const res = await apiFetch(`/api/meals/journal/${slot}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json().catch(() => null);
    endJournalMutation(targetDate);
    consolidateJournalMutationResponse(targetDate, data, slot);
  } catch (err) {
    endJournalMutation(targetDate);
    console.error("[journal] Ajout impossible, rollback :", err);
    restoreJournalSnapshot(snapshot);
    if (typeof showToast === 'function') {
      showToast(`Échec de l'ajout de '${catalogItem.name}' — modification annulée`, "error");
    } else {
      alert("Erreur réseau : l'ajout a été annulé.");
    }
    // Réconciliation silencieuse avec le serveur (le POST a pu aboutir malgré l'erreur réseau)
    fetchJournalDate(targetDate, { render: true });
  }
}

async function saveSlotAsDishModal(slot) {
  const defaultName = prompt("Nom du nouveau plat à enregistrer dans votre catalogue :");
  if (!defaultName || !defaultName.trim()) return;

  const payload = {
    name: defaultName.trim(),
    date: currentJournalDate
  };

  try {
    const res = await apiFetch(`/api/meals/journal/${slot}/save-as-dish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      if (typeof showToast === 'function') showToast(`Plat '${payload.name}' créé dans votre catalogue !`, 'success');
      loadCatalogItems(true);
    } else {
      alert("Erreur lors de la création du plat.");
    }
  } catch (err) {
    alert("Erreur réseau.");
  }
}

