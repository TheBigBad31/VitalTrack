// static/modules/dashboard.js - Gestion du tableau de bord, pesées, graphiques & modales



    

    let currentData = FALLBACK_DASHBOARD_DATA;

    let chartWeightSummary = null;

    let chartMacrosDonut = null;

    let chartWeightDetail = null;

    let chartMealsStacked = null;

    let chartActivity = null;

    let chartHRIntraday = null;

    let chartBiometricsTrends = null;

    let chartCrossCorrelations = null;

    let currentMetricsData = null;

    let currentTrendsDays = 30;

    let currentCorrelationMode = 'weight_cals';



    // --- Lot 2 (BALI-90) : rendu ciblé par onglet actif ---

    // Seule la vue de l'onglet visible est rendue ; les autres sont marquées "dirty"

    // puis rendues à la demande (à la première ouverture de l'onglet).

    let currentActiveTab = 'summary';

    const dirtyTabs = new Set();

    const TAB_VIEW_IDS = ['summary', 'weight', 'nutrition', 'activity', 'goals', 'devices'];



    let currentEstimatedMeal = null;
    let currentUploadedPhotoUrl = null;

    // Constantes de configuration servees par le backend (/api-config).
    // Aucune valeur magique en dur cote client : remplie au chargement.
    let CONFIG = {};

    // Charge les constantes de configuration depuis le backend (source de verite).
    async function loadConfig() {
      try {
        const res = await apiFetch('/api/config');
        if (res.ok) CONFIG = await res.json();
      } catch (err) {
        console.warn('[config] Impossible de charger /api/config, valeurs par defat neutres.', err);
      }
    }

    // Profils métaboliques 1-clic

    let activeGoalProfileId = "weight_loss";

    const GOAL_PROFILES = {

      weight_loss: {

        id: "weight_loss",

        title: "🔥 Perte de Poids Durable",

        badge: "-0,5 kg/sem",

        delta: -500,

        steps: 10000,

        protein_per_kg: 1.8,

        desc: "Déficit cible -500 kcal/j, 1,8g/kg de protéines, 10 000 pas/j",

        recommendation: "Déficit modéré optimal (-500 kcal) ciblant la perte de tissu adipeux tout en préservant le muscle avec 1,8g/kg de protéines."

      },

      maintenance: {

        id: "maintenance",

        title: "⚖️ Maintien & Équilibre Vitalité",

        badge: "0 kcal",

        delta: 0,

        steps: 8500,

        protein_per_kg: 1.4,

        desc: "Équilibre 0 kcal, répartition équilibrée P/G/L, 8 500 pas/j",

        recommendation: "Équilibre métabolique et vitalité stable au quotidien. Apport énergétique à l'équilibre avec dépense réelle."

      },

      recomposition: {

        id: "recomposition",

        title: "💪 Recomposition Corporelle & Sport",

        badge: "-200 kcal & P+ 2.2g/kg",

        delta: -200,

        steps: 10000,

        protein_per_kg: 2.2,

        desc: "Léger déficit -200 kcal/j, protéines 2,2g/kg, focus masse musculaire",

        recommendation: "Léger déficit propice au développement musculaire et à l'oxydation des graisses via un ratio protéiné athlétique (2,2g/kg)."

      }

    };



    function initDates() {

      const todayIso = new Date().toISOString().split('T')[0];

      const elMealDate = document.getElementById('meal-date-input');

      const elWeightDate = document.getElementById('input-weight-date');

      const elActDate = document.getElementById('input-act-date');

      if (elMealDate) elMealDate.value = todayIso;

      if (elWeightDate) elWeightDate.value = todayIso;

      if (elActDate) elActDate.value = todayIso;

    }



    // Gestion des onglets

    // switchTab est délégué à static/modules/lazy.js (Architecture 6 onglets & lazy loading)



    // Chargement des données depuis FastAPI avec fallback

    async function loadDashboardData() {
      const refreshIcon = document.getElementById('refresh-icon');
      if (refreshIcon) refreshIcon.classList.add('animate-spin');

      try {

        const readOnlyParam = (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active && window.currentReadOnlyFriend.friend_id) ? `?user_id=${window.currentReadOnlyFriend.friend_id}` : '';

        // Chargement parallèle de la configuration backend et du dashboard pour réduire le TTFB initial
        const [, res] = await Promise.all([
          loadConfig(),
          apiFetch(`/api/dashboard${readOnlyParam}`)
        ]);

        if (res.ok) {

          currentData = await res.json();

          if (currentData && currentData.profile && currentData.profile.goal_profile_id && GOAL_PROFILES[currentData.profile.goal_profile_id]) {
            activeGoalProfileId = currentData.profile.goal_profile_id;
          }

        } else {

          console.warn("API dashboard indisponible, bascule sur les données fallback.");

          currentData = FALLBACK_DASHBOARD_DATA;

        }

      } catch (err) {

        console.warn("Erreur réseau API, utilisation fallback :", err);

        currentData = FALLBACK_DASHBOARD_DATA;

      } finally {

        if (refreshIcon) refreshIcon.classList.remove('animate-spin');

        renderAllViews();

      }

    }



    function refreshData() {

      // Actualisation manuelle : on invalide tous les caches (onglets + journal + métriques)

      currentMetricsData = null;

      if (typeof invalidateTabCaches === 'function') invalidateTabCaches();

      if (typeof invalidateJournalCache === 'function') invalidateJournalCache();

      if (typeof markAllTabsDirty === 'function') markAllTabsDirty();

      loadDashboardData();

    }



    // --- Rendu ciblé (Lot 2 - BALI-90) ---------------------------------------

    /** Rend la vue d'un onglet donné (sans toucher aux autres onglets). */

    function renderTabView(tabId) {

      switch (tabId) {

        case 'summary': renderSummaryView(); break;

        case 'weight': renderWeightView(); break;

        case 'nutrition': renderNutritionView(); break;

        case 'activity': renderActivityView(); break;

        case 'goals': if (typeof renderGoalsView === 'function') renderGoalsView(); break;

        case 'devices': renderDevicesView(); break;

        default: break;

      }

    }



    /** Marque un onglet à rafraîchir lors de sa prochaine ouverture. */

    function markTabDirty(tabId) {

      if (!tabId || tabId === currentActiveTab) return;

      dirtyTabs.add(tabId);

    }



    function markAllTabsDirty() {

      TAB_VIEW_IDS.forEach(markTabDirty);

    }



    /**

     * Rend la vue d'un onglet si elle a été invalidée (données rafraîchies alors

     * qu'elle était masquée). Retourne true si un rendu a eu lieu.

     */

    function renderTabViewIfDirty(tabId) {

      if (!dirtyTabs.has(tabId)) return false;

      dirtyTabs.delete(tabId);

      try {

        renderTabView(tabId);

        refreshIcons(document.getElementById(`view-${tabId}`));

      } catch (err) {

        console.warn(`[render] Vue ${tabId} non rendue :`, err);

      }

      return true;

    }



    // Rendu global de l'interface : ne rend immédiatement que l'onglet actif.

    function renderAllViews() {

      const active = currentActiveTab || 'summary';

      TAB_VIEW_IDS.forEach(tabId => {

        if (tabId === active) {

          dirtyTabs.delete(tabId);

          renderTabView(tabId);

        } else {

          dirtyTabs.add(tabId);

        }

      });

      // Icônes recréées uniquement dans la vue affichée

      refreshIcons(document.getElementById(`view-${active}`) || document.body);

    }



    // 1. Rendu Synthèse Quotidienne

    function renderNutritionView() {

      const meals = currentData.recent_meals || [];

      const badge = document.getElementById('meals-count-badge');

      if (badge) badge.innerText = `${meals.length} repas récents`;



      // Calcul des 7 derniers jours (utilisé par le graphique ET le tableau récapitulatif)

      const days = [];

      for (let i = 6; i >= 0; i--) {

        const d = new Date();

        d.setDate(d.getDate() - i);

        days.push(d.toISOString().split('T')[0]);

      }



      const bfast = [];

      const lunch = [];

      const dinner = [];

      const snack = [];



      days.forEach(day => {

        const dayMeals = meals.filter(m => m.date === day);

        let b = 0, l = 0, d = 0, s = 0;

        dayMeals.forEach(m => {

          if (m.meal_type === 'breakfast') b += m.total_calories_kcal;

          else if (m.meal_type === 'lunch') l += m.total_calories_kcal;

          else if (m.meal_type === 'dinner') d += m.total_calories_kcal;

          else if (m.meal_type === 'snack') s += m.total_calories_kcal;

        });



        bfast.push(b); lunch.push(l); dinner.push(d); snack.push(s);

      });



      // Graphique empilé des 7 derniers jours

      const ctx = document.getElementById('chart-meals-stacked');

      if (ctx) {

        if (chartMealsStacked) { try { chartMealsStacked.destroy(); } catch (e) { /* ignore */ } }



        try {

        chartMealsStacked = new Chart(ctx, {

          type: 'bar',

          data: {

            labels: days.map(d => d.slice(5)),

            datasets: [

              { label: 'Petit-déjeuner', data: bfast, backgroundColor: '#f59e0b' },

              { label: 'Déjeuner', data: lunch, backgroundColor: '#22D3EE' },

              { label: 'Dîner', data: dinner, backgroundColor: '#7C3AED' },

              { label: 'Collation', data: snack, backgroundColor: '#C026D3' },

              {

                type: 'line',

                label: `Cible (${(currentData && currentData.summary && currentData.summary.target_calories_intake) || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0} kcal)`,
                data: days.map(() => (currentData && currentData.summary && currentData.summary.target_calories_intake) || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0),

                borderColor: '#ef4444',

                borderDash: [4, 4],

                pointRadius: 0,

                borderWidth: 2

              }

            ]

          },

          options: {

            responsive: true,

            maintainAspectRatio: false,

            scales: {

              x: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } },

              y: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } }

            },

            plugins: {

              legend: { position: 'top', labels: { color: '#cbd5e1' } }

            }

          }

        });

        } catch (err) {

          console.warn('[render] Graphique repas non rendu', err);

          chartMealsStacked = null;

        }

      }



      // Rendu du Tableau Récapitulatif des Calories par Jour & par Repas

      const tableCaloriesBody = document.getElementById('table-meals-calories-body');

      const todayBadge = document.getElementById('calories-table-today-badge');

      if (tableCaloriesBody) {

        const todayStr = new Date().toISOString().split('T')[0];

        let todayTotal = 0;



        const reversedDays = [...days].reverse();

        tableCaloriesBody.innerHTML = reversedDays.map(day => {

          const idx = days.indexOf(day);

          const b = bfast[idx] || 0;

          const l = lunch[idx] || 0;

          const s = snack[idx] || 0;

          const d = dinner[idx] || 0;

          const total = Math.round(b + l + s + d);

          const isToday = day === todayStr;

          if (isToday) todayTotal = total;



          const target = (currentData && currentData.summary && currentData.summary.target_calories_intake) || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0;

          const pct = target > 0 ? Math.min(Math.round((total / target) * 100), 100) : 0;

          const diff = total - target;



          let statusBadge = '';

          if (total === 0) {

            statusBadge = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-500 font-medium">Non renseigné</span>';

          } else if (total <= target) {

            statusBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/20">🟢 Conforme (-${target - total} kcal)</span>`;

          } else {

            statusBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 font-bold border border-amber-500/20">🟡 Dépassé (+${diff} kcal)</span>`;

          }



          return `

            <tr class="hover:bg-[#1F2A3C]/40 transition-colors ${isToday ? 'bg-indigo-500/10 font-medium' : ''}">

              <td class="py-2.5 px-3">

                <div class="flex items-center space-x-1.5">

                  <span class="font-bold text-white">${day}</span>

                  ${isToday ? `<span class="text-[9px] px-1.5 py-0.2 rounded bg-indigo-500/30 text-indigo-300 font-bold">Aujourd'hui</span>` : ""}

                </div>

              </td>

              <td class="py-2.5 px-3 text-amber-400 font-semibold">${b > 0 ? Math.round(b) + ' kcal' : '<span class="text-slate-600">-</span>'}</td>

              <td class="py-2.5 px-3 text-brand-300 font-semibold">${l > 0 ? Math.round(l) + ' kcal' : '<span class="text-slate-600">-</span>'}</td>

              <td class="py-2.5 px-3 text-pink-400 font-semibold">${s > 0 ? Math.round(s) + ' kcal' : '<span class="text-slate-600">-</span>'}</td>

              <td class="py-2.5 px-3 text-indigo-400 font-semibold">${d > 0 ? Math.round(d) + ' kcal' : '<span class="text-slate-600">-</span>'}</td>

              <td class="py-2.5 px-3">

                <span class="text-sm font-extrabold text-white">${total} kcal</span>

              </td>

              <td class="py-2.5 px-3">

                <div class="flex items-center space-x-2">

                  <div class="w-16 bg-[#0B0F17] rounded-full h-1.5 overflow-hidden border border-[#1F2A3C]">

                    <div class="h-full ${total > target ? 'bg-amber-400' : 'bg-emerald-400'}" style="width: ${pct}%"></div>

                  </div>

                  <span class="text-[10px] text-slate-400 font-mono">${pct}%</span>

                </div>

              </td>

              <td class="py-2.5 px-3">${statusBadge}</td>

            </tr>

          `;

        }).join('');



        const todayTarget = (currentData && currentData.summary && currentData.summary.target_calories_intake) || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0;

        if (todayBadge) {

          todayBadge.textContent = `Aujourd'hui : ${todayTotal} kcal / ${todayTarget} kcal`;

          if (todayTotal > todayTarget) {

            todayBadge.className = "text-xs font-bold px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 self-start sm:self-auto";

          } else {

            todayBadge.className = "text-xs font-bold px-3 py-1.5 rounded-xl bg-brand-500/10 text-brand-400 border border-brand-500/20 self-start sm:self-auto";

          }

        }

      }



      // Liste des cartes de repas

      const container = document.getElementById('meals-list-container');

      if (container) {

        const mealTypeLabels = {

          breakfast: { label: "Petit-déjeuner", color: "text-amber-400 bg-amber-400/10 border-amber-400/20" },

          lunch: { label: "Déjeuner", color: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20" },

          dinner: { label: "Dîner", color: "text-indigo-400 bg-indigo-400/10 border-indigo-400/20" },

          snack: { label: "Collation", color: "text-pink-400 bg-pink-400/10 border-pink-400/20" }

        };



        const typeFilterEl = document.getElementById('meals-history-type-filter');
        const dateFilterEl = document.getElementById('meals-history-date-filter');
        const filterType = typeFilterEl ? typeFilterEl.value : '';
        const filterDate = dateFilterEl ? dateFilterEl.value : '';

        const filteredMeals = meals.filter(m => {
          if (filterType && m.meal_type !== filterType) return false;
          if (filterDate && String(m.date || '').slice(0, 10) !== filterDate) return false;
          return true;
        });

        if (badge) badge.innerText = `${filteredMeals.length} repas${filteredMeals.length !== meals.length ? ' / ' + meals.length : ''}`;

        if (filteredMeals.length === 0) {
          container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-slate-400 bg-[#0B0F17] border border-[#1F2A3C] rounded-xl">Aucun repas enregistré pour ces critères.</div>';
        } else {
        container.innerHTML = filteredMeals.map(m => {

          const typeInfo = mealTypeLabels[m.meal_type] || { label: m.meal_type, color: "text-slate-400" };

          const itemsStr = escapeHtml((m.items || []).map(i => `${i.name} (${Math.round(i.portion_g || 100)}g)`).join(', '));

          const photoUrl = sanitizeUrl(m.photo_data_url);

          const mealIdx = meals.indexOf(m);

          

          return `

            <div class="bg-[#0B0F17] border border-[#1F2A3C] rounded-xl p-4 flex flex-col justify-between space-y-3">

              <div class="flex items-start justify-between">

                <div>

                  <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border ${typeInfo.color}">

                    ${escapeHtml(typeInfo.label)}

                  </span>

                  <div class="text-xs text-slate-400 mt-1">${escapeHtml(m.date || '')}</div>

                </div>

                <div class="text-right">

                  <span class="text-base font-extrabold text-white">${Math.round(m.total_calories_kcal)}</span>

                  <span class="text-xs text-slate-400">kcal</span>

                </div>

              </div>



              <!-- Photo éventuelle -->

              ${photoUrl ? `

                <div class="rounded-lg overflow-hidden border border-[#1F2A3C] max-h-32">

                  <img src="${photoUrl}" alt="Photo repas" class="w-full h-full object-cover">

                </div>

              ` : ''}



              <!-- Aliments -->

              <p class="text-xs text-slate-300 line-clamp-2">

                <span class="font-medium text-slate-400">Aliments:</span> ${itemsStr || 'Repas composé'}

              </p>



              <!-- Macros -->

              <div class="flex items-center justify-between text-[11px] pt-2 border-t border-[#1F2A3C]/70">

                <span class="text-brand-400 font-medium">P: ${Math.round(m.protein_g)}g</span>

                <span class="text-sky-400 font-medium">G: ${Math.round(m.carbs_g)}g</span>

                <span class="text-amber-400 font-medium">L: ${Math.round(m.fat_g)}g</span>

                <span class="text-slate-400">Fibres: ${m.fiber_g ? Math.round(m.fiber_g) + 'g' : '--'}</span>

              </div>



              <!-- Actions : Copier aujourd'hui & Sauvegarde Plat Type -->

              <div class="pt-1 flex flex-wrap items-center justify-end gap-2">
                <button type="button" onclick="copyMealToToday(${mealIdx})" class="write-action-btn text-[11px] font-semibold text-brand-400 hover:text-brand-300 bg-brand-500/10 hover:bg-brand-500/20 border border-brand-500/25 px-2.5 py-1 rounded-lg flex items-center space-x-1 transition-colors" title="Copier ce repas au même repas d'aujourd'hui">
                  <i data-lucide="copy" class="w-3 h-3"></i>
                  <span>Copier aujourd'hui</span>
                </button>

                <button onclick="saveLoggedMealAsTemplate(${mealIdx})" class="text-[10px] text-amber-400 hover:text-amber-300 flex items-center space-x-1 py-1 px-2 rounded-lg bg-amber-400/10 hover:bg-amber-400/20 border border-amber-400/20 transition-colors">

                  <i data-lucide="star" class="w-3 h-3"></i>

                  <span>⭐ Enregistrer comme plat type</span>

                </button>

              </div>

            </div>

          `;

        }).join('');
        }

      }

    }

    function resetMealsHistoryFilters() {
      const typeEl = document.getElementById('meals-history-type-filter');
      const dateEl = document.getElementById('meals-history-date-filter');
      if (typeEl) typeEl.value = '';
      if (dateEl) dateEl.value = '';
      renderNutritionView();
    }
    window.resetMealsHistoryFilters = resetMealsHistoryFilters;

    async function copyMealToToday(mealIdx) {
      const meals = (currentData && currentData.recent_meals) || [];
      const m = meals[mealIdx];
      if (!m) return;
      const todayIso = new Date().toISOString().split('T')[0];
      const payload = {
        date: todayIso,
        meal_type: m.meal_type,
        photo_data_url: m.photo_data_url || null,
        portion_scale: 1.0,
        items: Array.isArray(m.items) ? m.items : [],
        total_calories_kcal: Number(m.total_calories_kcal || 0),
        protein_g: Number(m.protein_g || 0),
        carbs_g: Number(m.carbs_g || 0),
        fat_g: Number(m.fat_g || 0),
        fiber_g: Number(m.fiber_g || 0)
      };
      try {
        const res = await apiFetch('/api/meals', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const saved = await res.json();
        currentData.recent_meals = currentData.recent_meals || [];
        currentData.recent_meals.push(saved);
        if (typeof invalidateJournalCache === 'function') invalidateJournalCache(todayIso);
        if (typeof loadMealsJournal === 'function' && typeof getActiveMealDate === 'function' && getActiveMealDate() === todayIso) {
          loadMealsJournal(todayIso);
        }
        renderNutritionView();
        if (typeof showToast === 'function') showToast("Repas copié pour aujourd'hui !", 'success');
      } catch (err) {
        console.error('Erreur copie repas:', err);
        if (typeof showToast === 'function') showToast('Impossible de copier ce repas.', 'error');
      }
    }
    window.copyMealToToday = copyMealToToday;



    // 4. Rendu Vue Activité & Biomécanique Avancée (Palier 3)

    async function loadMetricsData(days = 30) {

      try {

        const readOnlyParam = (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active && window.currentReadOnlyFriend.friend_id) ? `&user_id=${window.currentReadOnlyFriend.friend_id}` : '';

        const resp = await API.get(`/api/metrics?days=${days}${readOnlyParam}`);

        if (resp.ok) {

          currentMetricsData = await resp.json();

          return currentMetricsData;

        }

      } catch (err) {

        console.warn("[Metrics] Impossible de charger /api/metrics:", err);

      }

      return null;

    }



    function openMealModal(mealType) {

      if (mealType) {

        const sel = document.getElementById('meal-type-select');

        if (sel) sel.value = mealType;

      }

      const dateInp = document.getElementById('meal-date-input');

      if (dateInp && !dateInp.value) {

        const activeDate = (typeof window.getActiveMealDate === 'function')

          ? window.getActiveMealDate()

          : new Date().toISOString().split('T')[0];

        dateInp.value = activeDate;

      }

      document.getElementById('modal-meal').classList.remove('hidden');

    }

    function closeMealModal() {

      document.getElementById('modal-meal').classList.add('hidden');

    }



    function handleMealPhotoSelected(event) {

      const file = event.target.files[0];

      if (!file) return;



      const reader = new FileReader();

      reader.onload = (e) => {

        currentUploadedPhotoUrl = e.target.result;

        const preview = document.getElementById('meal-photo-preview');

        const placeholder = document.getElementById('meal-photo-placeholder');

        preview.src = currentUploadedPhotoUrl;

        preview.classList.remove('hidden');

        placeholder.classList.add('hidden');

      };

      reader.readAsDataURL(file);

    }



    async function triggerMealEstimation() {

      const btn = document.getElementById('btn-estimate-meal');

      btn.disabled = true;

      btn.innerHTML = `<span class="animate-spin mr-2">⏳</span> Analyse IA en cours...`;



      const desc = document.getElementById('meal-desc-input').value;

      const mealType = document.getElementById('meal-type-select').value;

      const scale = parseFloat(document.getElementById('portion-scale-range').value);



      try {

        const res = await apiFetch('/api/meals/estimate', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({

            photo_data_url: currentUploadedPhotoUrl,

            description: desc,

            meal_type: mealType,

            portion_scale: scale

          })

        });



        if (res.ok) {

          currentEstimatedMeal = await res.json();

        } else {

          // Fallback local estimation

          currentEstimatedMeal = {

            items: [

              { name: "Blanc de poulet", portion_g: 150 * scale, calories_kcal: 180 * scale, protein_g: 39 * scale, carbs_g: 0, fat_g: 2.7 * scale },

              { name: "Riz basmati", portion_g: 180 * scale, calories_kcal: 234 * scale, protein_g: 4.8 * scale, carbs_g: 50.4 * scale, fat_g: 0.5 * scale },

              { name: "Brocolis", portion_g: 150 * scale, calories_kcal: 52 * scale, protein_g: 4.2 * scale, carbs_g: 10.5 * scale, fat_g: 0.6 * scale }

            ],

            total_calories_kcal: Math.round(466 * scale),

            total_protein_g: Math.round(48 * scale),

            total_carbs_g: Math.round(61 * scale),

            total_fat_g: Math.round(3.8 * scale)

          };

        }

      } catch (err) {

        currentEstimatedMeal = {

          items: [

            { name: "Assiette équilibrée", portion_g: 450 * scale, calories_kcal: 550 * scale, protein_g: 35 * scale, carbs_g: 65 * scale, fat_g: 14 * scale }

          ],

          total_calories_kcal: Math.round(550 * scale),

          total_protein_g: Math.round(35 * scale),

          total_carbs_g: Math.round(65 * scale),

          total_fat_g: Math.round(14 * scale)

        };

      } finally {

        btn.disabled = false;

        btn.innerHTML = `<i data-lucide="sparkles" class="w-4 h-4 mr-1"></i> Ré-estimer les Calories & Macros`;

        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

        renderEstimationResult();

      }

    }



    function updatePortionScale(val) {

      const scale = parseFloat(val);

      const label = scale === 1.0 ? "1.0x (Normale)" : (scale < 1.0 ? `${scale}x (Petite)` : `${scale}x (Grande/Double)`);

      document.getElementById('portion-scale-val').innerText = label;



      if (currentEstimatedMeal && currentEstimatedMeal.items) {

        // Recalcul proportionnel immédiat dans l'interface

        triggerMealEstimation();

      }

    }



    function renderEstimationResult() {

      if (!currentEstimatedMeal) return;

      document.getElementById('meal-estimation-result').classList.remove('hidden');



      document.getElementById('est-calories').innerText = `${Math.round(currentEstimatedMeal.total_calories_kcal || 0)} kcal`;

      document.getElementById('est-protein').innerText = `${Math.round(currentEstimatedMeal.total_protein_g || 0)}g`;

      document.getElementById('est-carbs').innerText = `${Math.round(currentEstimatedMeal.total_carbs_g || 0)}g`;

      document.getElementById('est-fat').innerText = `${Math.round(currentEstimatedMeal.total_fat_g || 0)}g`;



      const listEl = document.getElementById('est-items-list');

      listEl.innerHTML = (currentEstimatedMeal.items || []).map(item => `

        <div class="flex items-center justify-between p-2 rounded-lg bg-[#151D2A] border border-[#1F2A3C]">

          <div>

            <span class="font-bold text-white text-xs">${escapeHtml(item.name || '')}</span>

            <span class="text-[10px] text-slate-400 block">${Math.round(item.portion_g)}g • ${Math.round(item.calories_kcal)} kcal</span>

          </div>

          <div class="text-[10px] text-slate-300">

            P: <b class="text-brand-400">${Math.round(item.protein_g)}g</b> | 

            G: <b class="text-sky-400">${Math.round(item.carbs_g)}g</b> | 

            L: <b class="text-amber-400">${Math.round(item.fat_g)}g</b>

          </div>

        </div>

      `).join('');

    }



    async function saveMealToJournal() {

      const btn = document.getElementById('btn-save-meal');

      btn.disabled = true;

      btn.innerHTML = `Enregistrement...`;



      const dateVal = document.getElementById('meal-date-input').value;

      const mealType = document.getElementById('meal-type-select').value;

      const scale = parseFloat(document.getElementById('portion-scale-range').value);



      const payload = {

        date: dateVal,

        meal_type: mealType,

        photo_data_url: currentUploadedPhotoUrl,

        portion_scale: scale,

        items: currentEstimatedMeal ? currentEstimatedMeal.items : []

      };



      try {

        await apiFetch('/api/meals', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });

      } catch (err) {

        console.warn("Save fallback");

      }



      btn.disabled = false;

      btn.innerHTML = `<i data-lucide="check" class="w-4 h-4 mr-1"></i> Enregistré !`;

      setTimeout(() => {

        closeMealModal();

        loadDashboardData();

        switchTab('nutrition');

      }, 500);

    }



    // =====================================================================

    // GESTION BIBLIOTHÈQUE DE PLATS RÉUTILISABLES & 4 REPAS

    // =====================================================================

    let currentSavedMealsCache = [];

    let currentSavedMealsFilter = null;

    let currentSavedMealPhotoBase64 = null;



    function openSavedMealsLibraryModal(filterType = null) {

      currentSavedMealsFilter = filterType;

      const modal = document.getElementById('modal-saved-meals');

      if (modal) modal.classList.remove('hidden');

      updateSavedMealFilterButtonsUI();

      loadAndRenderSavedMeals();

    }



    function closeSavedMealsLibraryModal() {

      const modal = document.getElementById('modal-saved-meals');

      if (modal) modal.classList.add('hidden');

    }



    function filterSavedMealsLibrary(mealType) {

      currentSavedMealsFilter = mealType;

      updateSavedMealFilterButtonsUI();

      loadAndRenderSavedMeals();

    }



    function updateSavedMealFilterButtonsUI() {

      const types = ['all', 'breakfast', 'lunch', 'snack', 'dinner'];

      types.forEach(t => {

        const btn = document.getElementById(`filter-saved-${t}`);

        if (!btn) return;

        const isActive = (t === 'all' && !currentSavedMealsFilter) || (currentSavedMealsFilter === t);

        if (isActive) {

          btn.className = "saved-meal-filter-btn flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white transition-colors flex items-center justify-center space-x-1";

        } else {

          btn.className = "saved-meal-filter-btn flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-white transition-colors flex items-center justify-center space-x-1";

        }

      });

    }



    async function loadAndRenderSavedMeals() {

      const container = document.getElementById('saved-meals-cards-container');

      if (!container) return;

      container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-slate-400"><span class="animate-spin inline-block mr-2">⏳</span> Chargement des plats réutilisables...</div>';



      try {

        let url = '/api/meals/saved';

        if (currentSavedMealsFilter) {

          url += `?meal_type=${currentSavedMealsFilter}`;

        }

        const res = await apiFetch(url);

        if (res.ok) {

          currentSavedMealsCache = await res.json();

          renderSavedMealsCards(currentSavedMealsCache);

        } else {

          container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-rose-400">Impossible de charger les plats sauvegardés.</div>';

        }

      } catch (err) {

        container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-rose-400">Erreur réseau lors de la récupération des plats.</div>';

      }

    }



    function renderSavedMealsCards(meals) {

      const container = document.getElementById('saved-meals-cards-container');

      if (!container) return;



      if (!meals || meals.length === 0) {

        container.innerHTML = `

          <div class="col-span-full py-8 text-center space-y-3 bg-[#0B0F17]/50 border border-dashed border-[#1F2A3C] rounded-xl p-4">

            <span class="text-3xl block">🍽️</span>

            <p class="text-xs text-slate-400">Aucun plat réutilisable enregistré pour ce repas.</p>

            <button onclick="openCreateSavedMealModal(currentSavedMealsFilter)" class="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold inline-flex items-center space-x-1">

              <i data-lucide="plus" class="w-3.5 h-3.5"></i>

              <span>Créer un premier plat</span>

            </button>

          </div>

        `;

        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch(e){} }

        return;

      }



      const mealLabels = {

        breakfast: { label: "Petit-déjeuner 🥐", color: "text-amber-400 bg-amber-400/10 border-amber-400/20" },

        lunch: { label: "Déjeuner 🥗", color: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20" },

        snack: { label: "Goûter 🍎", color: "text-pink-400 bg-pink-400/10 border-pink-400/20" },

        dinner: { label: "Dîner 🍲", color: "text-indigo-400 bg-indigo-400/10 border-indigo-400/20" }

      };



      container.innerHTML = meals.map(m => {

        const typeInfo = mealLabels[m.meal_type] || { label: m.meal_type, color: "text-slate-400" };

        const safeName = escapeHtml(m.name || '');

        const safeServing = escapeHtml(m.serving_size || '1 portion');

        const photoUrl = sanitizeUrl(m.photo_url);

        const mId = parseInt(m.id, 10) || 0;

        const mType = escapeHtml(m.meal_type || '');



        return `

          <div class="bg-[#0B0F17] border border-[#1F2A3C] hover:border-indigo-500/30 rounded-xl p-3 flex flex-col justify-between space-y-2 transition-all">

            <div class="space-y-1.5">

              <div class="flex items-start justify-between gap-1">

                <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border ${typeInfo.color}">

                  ${escapeHtml(typeInfo.label)}

                </span>

                <div class="flex items-center space-x-1">

                  ${m.is_favorite ? '<span class="text-xs text-amber-400">⭐</span>' : ''}

                  <button onclick="deleteSavedMeal(${mId})" title="Supprimer ce plat" class="p-1 text-slate-500 hover:text-rose-400 rounded transition-colors">

                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>

                  </button>

                </div>

              </div>



              ${photoUrl ? `

                <div class="rounded-lg overflow-hidden border border-[#1F2A3C] h-24 w-full">

                  <img src="${photoUrl}" alt="${safeName}" class="w-full h-full object-cover">

                </div>

              ` : ''}



              <div>

                <h4 class="font-bold text-white text-xs leading-tight line-clamp-1">${safeName}</h4>

                <div class="text-[10px] text-slate-400 mt-0.5">${safeServing} ${m.quantity_grams ? '(' + Math.round(m.quantity_grams) + 'g)' : ''}</div>

              </div>



              <!-- Macros -->

              <div class="flex items-center justify-between text-[10px] pt-1 border-t border-[#1F2A3C]/70">

                <span class="font-bold text-white">${Math.round(m.calories)} kcal</span>

                <span class="text-brand-400">P:${Math.round(m.protein_g)}g</span>

                <span class="text-sky-400">G:${Math.round(m.carbs_g)}g</span>

                <span class="text-amber-400">L:${Math.round(m.fat_g)}g</span>

              </div>

            </div>



            <!-- Bouton Ajouter au Journal 1-clic -->

            <div class="pt-2">

              <button onclick="logSavedMealDirectly(${mId}, '${mType}')" class="w-full py-1.5 px-2 rounded-lg bg-brand-600/20 hover:bg-brand-600 text-brand-300 hover:text-white border border-brand-500/30 text-[11px] font-bold flex items-center justify-center space-x-1.5 transition-all active:scale-95">

                <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i>

                <span>+ Ajouter au Journal</span>

              </button>

            </div>

          </div>

        `;

      }).join('');



      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch(e){} }

    }



    async function logSavedMealDirectly(savedMealId, mealType) {

      const activeDate = (typeof window.getActiveMealDate === 'function')

        ? window.getActiveMealDate()

        : new Date().toISOString().split('T')[0];

      try {

        if (typeof showToast === 'function') showToast("Ajout au journal alimentaire...", "info");

        const res = await apiFetch(`/api/meals/saved/${savedMealId}/log`, {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({

            date: activeDate,

            meal_type: mealType,

            portion_factor: 1.0

          })

        });



        if (res.ok) {

          const label = (typeof window.formatJournalDateLabel === 'function')

            ? window.formatJournalDateLabel(activeDate)

            : activeDate;

          if (typeof showToast === 'function') showToast("Plat ajouté au journal " + label + " avec succès ! 🥐🥗🍎🍲", "success");

          closeSavedMealsLibraryModal();

          await loadDashboardData();

          switchTab('nutrition');

        } else {

          if (typeof showToast === 'function') showToast("Erreur lors de l'ajout du plat au journal.", "error");

        }

      } catch (err) {

        if (typeof showToast === 'function') showToast("Erreur réseau lors de l'ajout du plat.", "error");

      }

    }



    async function deleteSavedMeal(mealId) {

      if (!confirm("Voulez-vous vraiment supprimer ce plat de votre bibliothèque ?")) return;

      try {

        const res = await apiFetch(`/api/meals/saved/${mealId}`, { method: 'DELETE' });

        if (res.ok) {

          if (typeof showToast === 'function') showToast("Plat supprimé de la bibliothèque.", "info");

          loadAndRenderSavedMeals();

        } else {

          alert("Erreur lors de la suppression du plat.");

        }

      } catch (err) {

        alert("Erreur réseau lors de la suppression.");

      }

    }



    function openCreateSavedMealModal(prefillType = null) {

      const modal = document.getElementById('modal-create-saved-meal');

      if (!modal) return;

      const form = document.getElementById('form-create-saved-meal');

      if (form) form.reset();

      document.getElementById('saved-meal-edit-id').value = '';

      currentSavedMealPhotoBase64 = null;

      if (prefillType) {

        document.getElementById('saved-meal-type').value = prefillType;

      }

      modal.classList.remove('hidden');

    }



    function closeCreateSavedMealModal() {

      const modal = document.getElementById('modal-create-saved-meal');

      if (modal) modal.classList.add('hidden');

    }



    function handleSavedMealPhotoFile(event) {

      const file = event.target.files[0];

      if (!file) return;

      const reader = new FileReader();

      reader.onload = (e) => {

        currentSavedMealPhotoBase64 = e.target.result;

        document.getElementById('saved-meal-photo-url').value = currentSavedMealPhotoBase64;

      };

      reader.readAsDataURL(file);

    }



    async function handleSavedMealFormSubmit(event) {

      event.preventDefault();

      const btn = document.getElementById('btn-submit-saved-meal');

      btn.disabled = true;



      const payload = {

        name: document.getElementById('saved-meal-name').value.trim(),

        meal_type: document.getElementById('saved-meal-type').value,

        serving_size: document.getElementById('saved-meal-serving').value.trim() || "1 portion",

        calories: parseFloat(document.getElementById('saved-meal-calories').value) || 0,

        protein_g: parseFloat(document.getElementById('saved-meal-protein').value) || 0,

        carbs_g: parseFloat(document.getElementById('saved-meal-carbs').value) || 0,

        fat_g: parseFloat(document.getElementById('saved-meal-fat').value) || 0,

        ingredients: document.getElementById('saved-meal-ingredients').value.trim() || null,

        photo_url: document.getElementById('saved-meal-photo-url').value.trim() || currentSavedMealPhotoBase64 || null,

        is_favorite: document.getElementById('saved-meal-favorite').checked

      };



      try {

        const res = await apiFetch('/api/meals/saved', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });



        if (res.ok) {

          if (typeof showToast === 'function') showToast("Plat réutilisable enregistré !", "success");

          closeCreateSavedMealModal();

          openSavedMealsLibraryModal(payload.meal_type);

        } else {

          alert("Erreur lors de l'enregistrement du plat.");

        }

      } catch (err) {

        alert("Erreur réseau lors de l'enregistrement.");

      } finally {

        btn.disabled = false;

      }

    }



    async function saveEstimatedMealAsTemplate() {

      if (!currentEstimatedMeal) {

        alert("Veuillez d'abord estimer le repas avant de l'enregistrer comme plat type.");

        return;

      }



      const mealType = document.getElementById('meal-type-select').value;

      const desc = document.getElementById('meal-desc-input').value.trim();

      const defaultName = desc || (mealType === 'breakfast' ? "Mon Petit-déjeuner Type" : (mealType === 'lunch' ? "Mon Déjeuner Type" : (mealType === 'snack' ? "Mon Goûter Type" : "Mon Dîner Type")));

      const mealName = prompt("Nom du plat type à enregistrer :", defaultName);

      if (!mealName) return;



      const payload = {

        name: mealName.trim(),

        meal_type: mealType,

        serving_size: "1 portion",

        calories: Math.round(currentEstimatedMeal.total_calories_kcal || 0),

        protein_g: Math.round(currentEstimatedMeal.total_protein_g || 0),

        carbs_g: Math.round(currentEstimatedMeal.total_carbs_g || 0),

        fat_g: Math.round(currentEstimatedMeal.total_fat_g || 0),

        fiber_g: Math.round(currentEstimatedMeal.total_fiber_g || 0),

        ingredients: (currentEstimatedMeal.items || []).map(i => `${i.name} (${Math.round(i.portion_g || 100)}g)`).join(', '),

        items: currentEstimatedMeal.items || [],

        photo_url: currentUploadedPhotoUrl || null,

        is_favorite: true

      };



      try {

        const res = await apiFetch('/api/meals/saved', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });



        if (res.ok) {

          if (typeof showToast === 'function') showToast(`⭐ '${payload.name}' enregistré dans vos plats réutilisables !`, "success");

        } else {

          alert("Erreur lors de l'enregistrement du plat type.");

        }

      } catch (err) {

        alert("Erreur réseau.");

      }

    }



    async function saveLoggedMealAsTemplate(mealIndex) {

      const meals = currentData.recent_meals || [];

      const m = meals[mealIndex];

      if (!m) return;



      const mealType = m.meal_type || 'lunch';

      const itemsDesc = (m.items || []).map(i => i.name).join(', ');

      const defaultName = itemsDesc ? `Plat ${itemsDesc.slice(0, 30)}` : `Plat ${mealType}`;

      const mealName = prompt("Nom du plat à sauvegarder dans votre bibliothèque :", defaultName);

      if (!mealName) return;



      const payload = {

        name: mealName.trim(),

        meal_type: mealType,

        serving_size: "1 portion",

        calories: Math.round(m.total_calories_kcal || 0),

        protein_g: Math.round(m.protein_g || 0),

        carbs_g: Math.round(m.carbs_g || 0),

        fat_g: Math.round(m.fat_g || 0),

        fiber_g: Math.round(m.fiber_g || 0),

        ingredients: (m.items || []).map(i => `${i.name} (${Math.round(i.portion_g || 100)}g)`).join(', '),

        items: m.items || [],

        photo_url: m.photo_data_url || null,

        is_favorite: true

      };



      try {

        const res = await apiFetch('/api/meals/saved', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });



        if (res.ok) {

          if (typeof showToast === 'function') showToast(`⭐ '${payload.name}' sauvegardé dans votre bibliothèque !`, "success");

        } else {

          alert("Erreur lors de la sauvegarde du plat.");

        }

      } catch (err) {

        alert("Erreur réseau.");

      }

    }



    // =====================================================================

    // LOGIQUE SAISIE POIDS & ACTIVITÉ

    // =====================================================================

    function openWeightModal() {

      document.getElementById('modal-weight').classList.remove('hidden');

    }

    function closeWeightModal() {

      document.getElementById('modal-weight').classList.add('hidden');

    }



    async function submitWeightEntry() {

      const d = document.getElementById('input-weight-date').value;

      const w = parseFloat(document.getElementById('input-weight-val').value);

      const fat = parseFloat(document.getElementById('input-body-fat').value) || null;

      const muscle = parseFloat(document.getElementById('input-muscle-mass').value) || null;



      if (!w || isNaN(w)) {

        alert("Veuillez saisir un poids valide en kg.");

        return;

      }



      try {

        await apiFetch('/api/weights', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({

            date: d,

            weight_kg: w,

            body_fat_pct: fat,

            muscle_mass_kg: muscle,

            source: "manual"

          })

        });

      } catch (e) {}



      closeWeightModal();

      loadDashboardData();

      switchTab('weight');

    }



    function openActivityModal() {

      document.getElementById('modal-activity').classList.remove('hidden');

    }

    function closeActivityModal() {

      document.getElementById('modal-activity').classList.add('hidden');

    }



    async function submitActivityEntry() {

      const d = document.getElementById('input-act-date').value;

      const steps = parseInt(document.getElementById('input-act-steps').value) || 0;

      const cals = parseFloat(document.getElementById('input-act-cals').value) || 0;

      const mins = parseInt(document.getElementById('input-act-minutes').value) || 0;



      try {

        await apiFetch('/api/activities', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({

            date: d,

            steps: steps,

            active_calories_kcal: cals,

            workout_minutes: mins,

            source: "health_connect"

          })

        });

      } catch (e) {}



      closeActivityModal();

      loadDashboardData();

      switchTab('activity');

    }



    // =====================================================================

    // LOGIQUE PROFIL UTILISATEUR & ASSISTANT DE CONNEXION D'APPAREILS

    // =====================================================================

    let currentSelectedWizardDevice = 'ringconn';



    function openProfileModal() {

      try {

        // Fermer les autres modales ou menus déroulants pouvant se superposer

        const drop = document.getElementById('header-user-dropdown');

        if (drop) { drop.classList.add('hidden'); }



        ['modal-meal', 'modal-weight', 'modal-activity', 'modal-connect-wizard', 'modal-auth', 'modal-saved-meals', 'modal-create-saved-meal'].forEach(id => {

          const el = document.getElementById(id);

          if (el) { el.classList.add('hidden'); el.classList.remove('flex'); }

        });



        // Pré-remplir les champs avec les données actuelles

        const p = (currentData && currentData.profile) ? currentData.profile : {};

        const setVal = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined && val !== null) el.value = val; };

        setVal('prof-name', p.name);

        setVal('prof-gender', p.gender);

        setVal('prof-age', p.age);

        setVal('prof-height', p.height_cm);

        setVal('prof-target-weight', p.target_weight_kg);

        setVal('prof-target-steps', p.target_steps);

        setVal('prof-target-cals', p.target_calories_intake);

        setVal('prof-target-prot', p.protein_target_per_kg);



        const modal = document.getElementById('modal-profile');

        if (modal) {

          modal.classList.remove('hidden');

          modal.classList.add('flex');

        }

        if (window.lucide && lucide.createIcons) {

          try { lucide.createIcons(); } catch (e) {}

        }

      } catch (err) {

        console.error("Erreur openProfileModal:", err);

      }

    }



    function closeProfileModal() {

      const modal = document.getElementById('modal-profile');

      if (modal) {

        modal.classList.add('hidden');

        modal.classList.remove('flex');

      }

    }



    async function saveUserProfile() {

      const payload = {

        name: (document.getElementById('prof-name') && document.getElementById('prof-name').value) || 'Sébastien',

        gender: (document.getElementById('prof-gender') && document.getElementById('prof-gender').value) || 'male',

        age: parseInt(document.getElementById('prof-age') && document.getElementById('prof-age').value) || 35,

        height_cm: parseFloat(document.getElementById('prof-height') && document.getElementById('prof-height').value) || 178.0,

        target_weight_kg: parseFloat(document.getElementById('prof-target-weight') && document.getElementById('prof-target-weight').value) || 77.0,

        target_steps: parseInt(document.getElementById('prof-target-steps') && document.getElementById('prof-target-steps').value) || 10000,

        target_calories_intake: parseFloat(document.getElementById('prof-target-cals') && document.getElementById('prof-target-cals').value) || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0,

        protein_target_per_kg: parseFloat(document.getElementById('prof-target-prot') && document.getElementById('prof-target-prot').value) || 1.8

      };



      try {

        const res = await apiFetch('/api/profile', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        });

        if (res.ok) {

          closeProfileModal();

          await loadDashboardData();

          if (typeof showToast === 'function') showToast("✓ Profil mis à jour avec succès ! Les métriques métaboliques ont été recalculées.", "success");

          else alert("Profil mis à jour avec succès !");

        }

      } catch (e) {

        closeProfileModal();

      }

    }



    async function exportDataBackup() {

      try {

        const res = await apiFetch('/api/backup/export');

        if (!res.ok) throw new Error("Erreur export");

        const data = await res.json();

        

        // Sauvegarde miroir dans localStorage

        localStorage.setItem('vitaltrack_backup_cache', JSON.stringify(data));



        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });

        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');

        a.href = url;

        a.download = `vitaltrack-sauvegarde-${new Date().toISOString().slice(0, 10)}.json`;

        document.body.appendChild(a);

        a.click();

        document.body.removeChild(a);

        URL.revokeObjectURL(url);

        alert("✓ Sauvegarde complète exportée avec succès ! (Profil + Poids + Repas + Activités)");

      } catch (e) {

        alert("Erreur lors de l'export des données.");

      }

    }



    async function importDataBackup(event) {

      const file = event.target.files[0];

      if (!file) return;



      const reader = new FileReader();

      reader.onload = async (e) => {

        try {

          const parsed = JSON.parse(e.target.result);

          const res = await apiFetch('/api/backup/import', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ data: parsed, overwrite: true })

          });

          const resData = await res.json();

          if (res.ok) {

            localStorage.setItem('vitaltrack_backup_cache', JSON.stringify(parsed));

            alert(resData.message || "✓ Sauvegarde restaurée avec succès !");

            closeProfileModal();

            loadDashboardData();

          } else {

            alert("Erreur de restauration du fichier JSON.");

          }

        } catch (err) {

          alert("Fichier JSON invalide.");

        }

      };

      reader.readAsText(file);

    }



    async function clearPersonalHistory() {

      if (!confirm("Voulez-vous vider les données de démonstration pour démarrer votre suivi réel personnel ? Votre profil morphologique sera conservé.")) {

        return;

      }

      try {

        const res = await apiFetch('/api/profile/clear-history', { method: 'POST' });

        if (res.ok) {

          localStorage.removeItem('vitaltrack_backup_cache');

          alert("Historique réinitialisé ! Vous pouvez enregistrer votre première pesée réelle.");

          closeProfileModal();

          loadDashboardData();

        }

      } catch (e) {

        alert("Erreur lors de l'effacement de l'historique");

      }

    }



    async function resetDemoData() {

      if (!confirm("Recharger les données de démonstration 30 jours (poids, repas, activités) ?")) {

        return;

      }

      try {

        const res = await apiFetch('/api/profile/reset-demo', { method: 'POST' });

        if (res.ok) {

          alert("Jeu de données réaliste 30 jours rechargé avec succès !");

          closeProfileModal();

          loadDashboardData();

        }

      } catch (e) {

        alert("Erreur lors du rechargement de la démo");

      }

    }



    // Auto-sync miroir dans localStorage à chaque chargement réussi

    window.addEventListener('beforeunload', () => {

      if (currentData && currentData.profile) {

        try {

          localStorage.setItem('vitaltrack_last_known_profile', JSON.stringify(currentData.profile));

        } catch (e) {}

      }

    });



    function showToast(message, type = 'info', duration = 3500) {

      const container = document.getElementById('pwa-toast-container');

      if (!container) {

        console.log(`[Toast ${type}]`, message);

        return;

      }

      const toast = document.createElement('div');

      toast.className = `pointer-events-auto p-3.5 rounded-xl border shadow-xl flex items-center space-x-3 text-xs transition-all duration-300 transform translate-y-2 opacity-0 ${

        type === 'success' ? 'bg-[#0e2a1d] border-emerald-500/50 text-emerald-200 shadow-emerald-950/50' :

        type === 'error' ? 'bg-[#2d1215] border-red-500/50 text-red-200 shadow-red-950/50' :

        'bg-[#151D2A] border-[#1F2A3C] text-slate-200 shadow-black/60'

      }`;

      const iconName = type === 'success' ? 'check-circle' : (type === 'error' ? 'alert-triangle' : 'info');

      toast.innerHTML = `

        <i data-lucide="${iconName}" class="w-4 h-4 shrink-0 ${type === 'success' ? 'text-emerald-400' : (type === 'error' ? 'text-red-400' : 'text-blue-400')}"></i>

        <div class="flex-1 leading-snug">${escapeHtml(message)}</div>

      `;

      container.appendChild(toast);

      if (window.lucide && lucide.createIcons) {

        try { lucide.createIcons(); } catch (e) {}

      }

      requestAnimationFrame(() => {

        toast.classList.remove('translate-y-2', 'opacity-0');

      });

      setTimeout(() => {

        toast.classList.add('opacity-0', 'translate-y-2');

        setTimeout(() => toast.remove(), 300);

      }, duration);

    }



    function openAuthModal() {

      // Fermer les autres modales pour éviter toute superposition opaque

      const wizardModal = document.getElementById('modal-connect-wizard');

      if (wizardModal && !wizardModal.classList.contains('hidden')) {

        wizardModal.classList.add('hidden');

      }

      const profModal = document.getElementById('modal-profile');

      if (profModal && !profModal.classList.contains('hidden')) {

        profModal.classList.add('hidden');

      }

      const modal = document.getElementById('modal-auth');

      if (modal) {

        modal.classList.remove('hidden');

        modal.classList.add('flex');

      }

      if (currentGoogleConfig && currentGoogleConfig.google_client_id) {

        initGoogleIdentityServices();

      }

      if (window.lucide && lucide.createIcons) {

        try { lucide.createIcons(); } catch (e) {}

      }

    }



    function closeAuthModal() {

      const modal = document.getElementById('modal-auth');

      if (modal) {

        modal.classList.add('hidden');

        modal.classList.remove('flex');

      }

    }



    // Alias de compatibilité

    function openGoogleAuthModal() {

      openAuthModal();

    }

    function closeGoogleAuthModal() {

      closeAuthModal();

    }



    function switchAuthTab(tab) {

      const panelGoogle = document.getElementById('auth-panel-google');

      const panelEmail = document.getElementById('auth-panel-email');

      const tabGoogle = document.getElementById('tab-auth-google');

      const tabEmail = document.getElementById('tab-auth-email');



      if (tab === 'google') {

        if (panelGoogle) panelGoogle.classList.remove('hidden');

        if (panelEmail) panelEmail.classList.add('hidden');

        if (tabGoogle) {

          tabGoogle.className = "py-2 rounded-lg bg-brand-500/20 text-brand-300 border border-brand-500/30 flex items-center justify-center space-x-1.5 transition-all";

        }

        if (tabEmail) {

          tabEmail.className = "py-2 rounded-lg text-slate-400 hover:text-white flex items-center justify-center space-x-1.5 transition-all";

        }

      } else {

        if (panelGoogle) panelGoogle.classList.add('hidden');

        if (panelEmail) panelEmail.classList.remove('hidden');

        if (tabEmail) {

          tabEmail.className = "py-2 rounded-lg bg-brand-500/20 text-brand-300 border border-brand-500/30 flex items-center justify-center space-x-1.5 transition-all";

        }

        if (tabGoogle) {

          tabGoogle.className = "py-2 rounded-lg text-slate-400 hover:text-white flex items-center justify-center space-x-1.5 transition-all";

        }

      }

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

    }



    function setAuthEmailMode(mode) {

      currentAuthEmailMode = mode;

      const btnLogin = document.getElementById('btn-mode-login');

      const btnRegister = document.getElementById('btn-mode-register');

      const nameField = document.getElementById('email-field-name');

      const submitLabel = document.getElementById('btn-submit-email-label');

      const passHint = document.getElementById('password-hint');

      const errBox = document.getElementById('auth-email-error');

      if (errBox) errBox.classList.add('hidden');



      if (mode === 'register') {

        if (nameField) nameField.classList.remove('hidden');

        if (passHint) passHint.classList.remove('hidden');

        if (submitLabel) submitLabel.innerText = "Créer mon compte VitalTrack";

        if (btnRegister) {

          btnRegister.className = "font-bold text-brand-400 pb-1 border-b-2 border-brand-400 transition-all";

        }

        if (btnLogin) {

          btnLogin.className = "text-slate-400 hover:text-slate-200 pb-1 border-b-2 border-transparent transition-all";

        }

      } else {

        if (nameField) nameField.classList.add('hidden');

        if (passHint) passHint.classList.add('hidden');

        if (submitLabel) submitLabel.innerText = "Se connecter";

        if (btnLogin) {

          btnLogin.className = "font-bold text-brand-400 pb-1 border-b-2 border-brand-400 transition-all";

        }

        if (btnRegister) {

          btnRegister.className = "text-slate-400 hover:text-slate-200 pb-1 border-b-2 border-transparent transition-all";

        }

      }

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

    }



    function togglePasswordVisibility() {

      const passInp = document.getElementById('auth-password-input');

      const icon = document.getElementById('icon-toggle-password');

      if (!passInp) return;

      if (passInp.type === 'password') {

        passInp.type = 'text';

        if (icon) icon.setAttribute('data-lucide', 'eye-off');

      } else {

        passInp.type = 'password';

        if (icon) icon.setAttribute('data-lucide', 'eye');

      }

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

    }



    function showEmailAuthError(msg) {

      const errBox = document.getElementById('auth-email-error');

      const errText = document.getElementById('auth-email-error-text');

      if (errBox && errText) {

        errText.innerText = msg;

        errBox.classList.remove('hidden');

      }

    }



    async function handleEmailAuthSubmit() {

      const emailInp = document.getElementById('auth-email-input');

      const passInp = document.getElementById('auth-password-input');

      const nameInp = document.getElementById('auth-email-name');

      const btn = document.getElementById('btn-submit-email-auth');



      const email = emailInp ? emailInp.value.trim() : '';

      const password = passInp ? passInp.value : '';

      const name = (nameInp && nameInp.value.trim()) ? nameInp.value.trim() : 'Utilisateur VitalTrack';



      if (!email || !email.includes('@')) {

        showEmailAuthError("Veuillez renseigner une adresse email valide.");

        return;

      }

      if (!password || password.length < 6) {

        showEmailAuthError("Le mot de passe doit comporter au moins 6 caractères.");

        return;

      }



      if (btn) btn.disabled = true;



      try {

        const endpoint = currentAuthEmailMode === 'register' ? '/api/auth/register' : '/api/auth/login';

        const bodyPayload = currentAuthEmailMode === 'register'

          ? { email, password, name }

          : { email, password };



        const res = await fetch(endpoint, {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(bodyPayload)

        });



        const data = await res.json();



        if (res.ok) {

          // Stocker le token JWT dans localStorage

          if (data.access_token) {

            localStorage.setItem(JWT_STORAGE_KEY, data.access_token);

          }

          currentUnifiedSession = data.session || {

            is_authenticated: true,

            email: data.user ? data.user.email : email,

            name: data.user ? data.user.name : name,

            auth_method: 'email_password'

          };

          localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(currentUnifiedSession));

          renderUnifiedAuthState(currentUnifiedSession, data.profile);

          closeAuthModal();

          await loadDashboardData();

          showToast(`✓ ${data.message || 'Authentification réussie !'}`, "success");

        } else {

          showEmailAuthError(data.detail || "Erreur lors de l'authentification.");

        }

      } catch (e) {

        showEmailAuthError("Impossible de joindre le serveur VitalTrack.");

      } finally {

        if (btn) btn.disabled = false;

      }

    }



    function continueAsGuest() {

      closeAuthModal();

      alert("Mode Invité / Démo activé. Vous pouvez explorer toutes les fonctionnalités de VitalTrack.");

    }



    function toggleUserDropdown() {

      const menu = document.getElementById('header-user-dropdown');

      if (menu) {

        menu.classList.toggle('hidden');

      }

    }



    // Fermer le dropdown au clic en dehors

    document.addEventListener('click', (e) => {

      const container = document.getElementById('header-auth-container');

      const menu = document.getElementById('header-user-dropdown');

      if (container && menu && !container.contains(e.target)) {

        menu.classList.add('hidden');

      }

    });



    async function loadUnifiedAuthState() {

      // 1. Détection SSO direct depuis AppHub (?google_user=...)

      try {

        const urlParams = new URLSearchParams(window.location.search);

        const ssoEmail = urlParams.get('google_user');

        if (ssoEmail) {

          const ssoName = (ssoEmail.toLowerCase() === 'sebastienlamoliate@gmail.com') ? 'Sébastien LAMOLIATE' : ssoEmail.split('@')[0];

          await selectGoogleAccount(ssoEmail, ssoName, 'https://lh3.googleusercontent.com/a/default-user=s96-c');

          try {

            window.history.replaceState({}, document.title, window.location.pathname);

          } catch (e) {}

          return;

        }

      } catch (e) {}



      // 2. Lecture immédiate du cache local

      try {

        const cached = localStorage.getItem(GOOGLE_SESSION_KEY);

        if (cached) {

          const parsed = JSON.parse(cached);

          if (parsed && parsed.is_authenticated) {

            currentUnifiedSession = parsed;

            renderUnifiedAuthState(parsed, currentData ? currentData.profile : null);

          }

        }

      } catch (e) {}



      // 3. Appel backend pour synchronisation avec transmission automatique du Bearer Token

      try {

        const [confRes, meRes] = await Promise.all([

          apiFetch('/api/auth/config'),

          apiFetch('/api/auth/me')

        ]);



        if (confRes && confRes.ok) {

          currentGoogleConfig = await confRes.json();

          initGoogleIdentityServices();

        }



        if (meRes && meRes.ok) {

          const data = await meRes.json();

          if (data.session && data.session.is_authenticated) {

            currentUnifiedSession = data.session;

            localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(data.session));

            renderUnifiedAuthState(currentUnifiedSession, data.profile);

          } else if (!localStorage.getItem(GOOGLE_SESSION_KEY)) {

            currentUnifiedSession = { is_authenticated: false };

            renderUnifiedAuthState(currentUnifiedSession, data.profile);

          }

        }

      } catch (e) {

        console.warn("Erreur chargement session (mode local résilient) :", e);

      }



      // 4. L'application démarre directement sur les dashboards sans bloquer l'utilisateur par une modale

    }



    function initGoogleIdentityServices() {

      if (!currentGoogleConfig.google_client_id || typeof google === 'undefined' || !google.accounts || !google.accounts.id) {

        return;

      }

      try {

        google.accounts.id.initialize({

          client_id: currentGoogleConfig.google_client_id,

          callback: handleGoogleCredentialResponse,

          auto_select: false

        });



        const btnContainer = document.getElementById('gsi-button-container');

        if (btnContainer) {

          btnContainer.innerHTML = '';

          google.accounts.id.renderButton(btnContainer, {

            theme: "filled_blue",

            size: "large",

            shape: "pill",

            text: "signin_with",

            locale: "fr"

          });

        }

      } catch (e) {

        console.warn("Erreur init Google GIS :", e);

      }

    }



    async function handleGoogleCredentialResponse(response) {

      if (!response.credential) return;

      try {

        const res = await fetch('/api/auth/google', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ credential: response.credential })

        });

        if (res.ok) {

          const data = await res.json();

          if (data.access_token) {

            localStorage.setItem(JWT_STORAGE_KEY, data.access_token);

          }

          currentUnifiedSession = data.session;

          localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(data.session));

          renderUnifiedAuthState(data.session, data.profile);

          syncGoogleAccountStorage(data.session.email);

          closeAuthModal();

          await loadDashboardData();

          alert(`Bienvenue ${data.session.name} ! Votre compte Google et vos données sont synchronisés.`);

        }

      } catch (e) {

        alert("Erreur lors de l'authentification Google.");

      }

    }



    async function selectGoogleAccount(email, name, picture) {

      const accountEmail = email || 'sebastienlamoliate@gmail.com';

      const accountName = name || 'Sébastien LAMOLIATE';

      const accountPicture = picture || 'https://lh3.googleusercontent.com/a/default-user=s96-c';



      const instantSession = {

        is_authenticated: true,

        email: accountEmail,

        name: accountName,

        picture: accountPicture,

        auth_method: 'google_account_chooser',

        last_login: new Date().toISOString()

      };

      currentUnifiedSession = instantSession;

      localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(instantSession));

      if (currentData && currentData.profile) {

        currentData.profile.google_email = accountEmail;

        currentData.profile.google_name = accountName;

        currentData.profile.google_picture = accountPicture;

      }

      renderUnifiedAuthState(instantSession, currentData ? currentData.profile : null);

      syncGoogleAccountStorage(accountEmail);

      closeAuthModal();



      try {

        const res = await fetch('/api/auth/google', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({

            email: accountEmail,

            name: accountName,

            picture: accountPicture

          })

        });



        if (res.ok) {

          const data = await res.json();

          if (data.access_token) {

            localStorage.setItem(JWT_STORAGE_KEY, data.access_token);

          }

          currentUnifiedSession = data.session || instantSession;

          localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(currentUnifiedSession));

          renderUnifiedAuthState(currentUnifiedSession, data.profile);

        }

      } catch (err) {

        console.warn("Backend API en cold start, session maintenue via cache local :", err);

      }



      await loadDashboardData();

      showToast("✓ Connecté avec succès en tant que " + accountName + " (" + accountEmail + ") !", "success");

    }



    function showOtherGoogleAccountForm() {

      const chooserList = document.getElementById('google-chooser-list');

      const otherForm = document.getElementById('google-other-account-form');

      if (chooserList) chooserList.classList.add('hidden');

      if (otherForm) otherForm.classList.remove('hidden');

    }



    function hideOtherGoogleAccountForm() {

      const chooserList = document.getElementById('google-chooser-list');

      const otherForm = document.getElementById('google-other-account-form');

      if (otherForm) otherForm.classList.add('hidden');

      if (chooserList) chooserList.classList.remove('hidden');

    }



    function submitOtherGoogleAccount() {

      const emailInput = document.getElementById('google-custom-email');

      const nameInput = document.getElementById('google-custom-name');

      const email = emailInput ? emailInput.value.trim() : '';

      const name = nameInput && nameInput.value.trim() ? nameInput.value.trim() : (email.split('@')[0] || 'Utilisateur Google');



      if (!email || !email.includes('@')) {

        alert("Veuillez renseigner une adresse email Google valide.");

        return;

      }



      selectGoogleAccount(email, name, 'https://lh3.googleusercontent.com/a/default-user=s96-c');

    }



    async function logoutSession() {

      try {

        localStorage.removeItem(JWT_STORAGE_KEY);

        localStorage.removeItem(GOOGLE_SESSION_KEY);

        await apiFetch('/api/auth/logout', { method: 'POST' });

      } catch (e) {

        console.warn("Déconnexion backend différée :", e);

      } finally {

        currentUnifiedSession = { is_authenticated: false };

        renderUnifiedAuthState(currentUnifiedSession, null);

        closeAuthModal();

        await loadDashboardData();

        alert("Déconnexion réussie.");

      }

    }



    // Alias pour compatibilité

    async function logoutGoogle() {

      await logoutSession();

    }



    async function saveGoogleClientId() {

      const inp = document.getElementById('google-input-client-id');

      const val = inp ? inp.value.trim() : '';

      if (!val) {

        alert("Veuillez saisir un Client ID valide.");

        return;

      }

      try {

        const res = await apiFetch('/api/auth/config', {

          method: 'PUT',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ google_client_id: val })

        });

        if (res.ok) {

          const data = await res.json();

          currentGoogleConfig = data.config;

          initGoogleIdentityServices();

          alert("✓ Google Client ID enregistré avec succès !");

        }

      } catch (e) {

        alert("Erreur lors de l'enregistrement du Client ID.");

      }

    }



    function renderUnifiedAuthState(session, profile) {

      const headerContainer = document.getElementById('header-auth-container');

      const profEmail = document.getElementById('prof-google-email');

      const profAvatar = document.getElementById('prof-google-avatar');

      const profActionBtn = document.getElementById('btn-prof-google-action');



      const connView = document.getElementById('auth-connected-view');

      const loginView = document.getElementById('auth-login-view');

      const uAvatar = document.getElementById('auth-user-avatar');

      const uInitials = document.getElementById('auth-user-initials');

      const uName = document.getElementById('auth-user-name');

      const uEmail = document.getElementById('auth-user-email');

      const uBadge = document.getElementById('auth-provider-badge');



      if (session && session.is_authenticated) {

        const rawEmail = session.email || '';

        const rawName = session.name || (rawEmail ? rawEmail.split('@')[0] : '') || 'Utilisateur';

        const email = escapeHtml(rawEmail);

        const name = escapeHtml(rawName);

        const picture = sanitizeUrl(session.picture || '');

        const initials = escapeHtml(rawName.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'VT');

        const firstName = escapeHtml(rawName.split(' ')[0] || '');

        const isGoogle = (session.auth_method && session.auth_method.includes('google'));



        // Header : Avatar utilisateur connecté avec menu déroulant

        if (headerContainer) {

          headerContainer.innerHTML = `

            <button type="button" onclick="toggleUserDropdown()" id="btn-header-avatar" class="flex items-center space-x-1.5 p-1 rounded-xl bg-[#151D2A] hover:bg-[#1F2A3C] border border-brand-500/40 text-white text-xs font-medium transition-all active:scale-95 shadow-sm" title="${name} (${email})">

              <div class="w-7 h-7 rounded-lg overflow-hidden flex items-center justify-center bg-gradient-to-tr from-brand-600 to-electric-cyan text-white font-bold text-xs shrink-0">

                ${picture ? `<img src="${picture}" class="w-full h-full object-cover" alt="Avatar">` : `<span>${initials}</span>`}

              </div>

              <span class="hidden sm:inline font-semibold px-1 text-brand-300">${firstName}</span>

              <span class="w-2 h-2 rounded-full bg-brand-400 mr-1"></span>

              <i data-lucide="chevron-down" class="w-3.5 h-3.5 text-slate-400 hidden sm:inline"></i>

            </button>



            <!-- Menu Déroulant Profil -->

            <div id="header-user-dropdown" class="absolute right-0 top-full mt-2 w-56 rounded-2xl bg-[#151D2A] border border-[#1F2A3C] shadow-2xl p-2 space-y-1 z-50 hidden">

              <div class="px-3 py-2 border-b border-[#1F2A3C] mb-1">

                <div class="text-xs font-bold text-white truncate">${name}</div>

                <div class="text-[10px] text-brand-400 truncate">${email}</div>

                <span class="inline-block mt-1 text-[9px] px-1.5 py-0.2 rounded-full bg-brand-500/20 text-brand-300 border border-brand-500/30">${isGoogle ? 'Compte Google' : 'Compte Email'}</span>

              </div>

              <button onclick="toggleUserDropdown(); openProfileModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">

                <i data-lucide="user" class="w-4 h-4 text-brand-400"></i>

                <span>Mon Profil</span>

              </button>

              <button onclick="toggleUserDropdown(); openFriendsModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">

                <i data-lucide="users" class="w-4 h-4 text-brand-400"></i>

                <span>Amis & Partage</span>

              </button>

              <button onclick="toggleUserDropdown(); openConnectWizardModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">

                <i data-lucide="link-2" class="w-4 h-4 text-indigo-400"></i>

                <span>Appareils Connectés</span>

              </button>

              <button onclick="toggleUserDropdown(); openAuthModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">

                <i data-lucide="shield" class="w-4 h-4 text-sky-400"></i>

                <span>Sécurité & Sessions</span>

              </button>

              <div class="border-t border-[#1F2A3C] pt-1">

                <button onclick="toggleUserDropdown(); logoutSession()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-red-300 hover:bg-red-950/40 flex items-center space-x-2 transition-colors">

                  <i data-lucide="log-out" class="w-4 h-4 text-red-400"></i>

                  <span>Déconnexion</span>

                </button>

              </div>

            </div>

          `;

        }



        // Modale Profil

        if (profEmail) profEmail.innerText = `${rawEmail} (${isGoogle ? 'Google' : 'Email'})`;

        if (profAvatar) {

          profAvatar.innerHTML = picture

            ? `<img src="${picture}" class="w-full h-full object-cover">`

            : `<div class="w-full h-full bg-brand-600 flex items-center justify-center text-white font-bold text-xs">${initials}</div>`;

        }

        if (profActionBtn) {

          profActionBtn.innerText = "Gérer Compte";

          profActionBtn.className = "px-2.5 py-1.5 rounded-lg bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/40 text-brand-300 text-[11px] font-semibold transition-all";

        }



        // Modale Auth

        if (connView) connView.classList.remove('hidden');

        if (loginView) loginView.classList.add('hidden');

        if (uAvatar) {

          if (picture) {

            uAvatar.src = picture;

            uAvatar.classList.remove('hidden');

            if (uInitials) uInitials.classList.add('hidden');

          } else {

            uAvatar.classList.add('hidden');

            if (uInitials) {

              uInitials.innerText = initials;

              uInitials.classList.remove('hidden');

            }

          }

        }

        if (uName) uName.innerText = rawName;

        if (uEmail) uEmail.innerText = rawEmail;

        if (uBadge) uBadge.innerText = isGoogle ? "Google" : "Email & Mot de passe";



      } else {

        // Déconnecté

        if (headerContainer) {

          headerContainer.innerHTML = `

            <button type="button" onclick="openAuthModal()" id="btn-header-auth" class="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 border border-white/20 text-white text-xs font-medium transition-all active:scale-95 shadow-sm" title="Se connecter / S'inscrire">

              <i data-lucide="user" class="w-4 h-4 text-brand-400"></i>

              <span class="hidden sm:inline">Connexion</span>

            </button>

          `;

        }



        if (profEmail) profEmail.innerText = "Non connecté";

        if (profAvatar) {

          profAvatar.innerHTML = `

            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">

              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>

            </svg>

          `;

        }

        if (profActionBtn) {

          profActionBtn.innerText = "Se connecter";

          profActionBtn.className = "px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 border border-white/20 text-white text-[11px] font-semibold transition-all";

        }



        if (connView) connView.classList.add('hidden');

        if (loginView) loginView.classList.remove('hidden');

      }

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

    }



    // Alias pour compatibilité

    function renderGoogleAuthState(session, profile) {

      renderUnifiedAuthState(session, profile);

    }



    // Exposition globale explicite des handlers d'interface

    window.openProfileModal = openProfileModal;

    window.closeProfileModal = closeProfileModal;

    window.saveUserProfile = saveUserProfile;

    window.openConnectWizardModal = openConnectWizardModal;

    window.closeConnectWizardModal = closeConnectWizardModal;

    window.selectWizardDevice = selectWizardDevice;

    window.submitDeviceConnection = submitDeviceConnection;

    window.openAuthModal = openAuthModal;

    window.closeAuthModal = closeAuthModal;

    window.switchTab = switchTab;

    window.generateDeviceToken = generateDeviceToken;

    window.toggleTokenVisibility = toggleTokenVisibility;

    window.copyTokenToClipboard = copyTokenToClipboard;

    window.fetchOrInitDeviceToken = fetchOrInitDeviceToken;

    window.testHealthConnectIngestion = testHealthConnectIngestion;

    window.formatRelativeTime = formatRelativeTime;

    window.renderLiveSyncBanner = renderLiveSyncBanner;

    window.triggerSyncFromBanner = triggerSyncFromBanner;



    function syncGoogleAccountStorage(email) {

      if (!email) return;

      const key = `vitaltrack_backup_${email}`;

      const existing = localStorage.getItem(key);

      if (existing) {

        try {

          const parsed = JSON.parse(existing);

          apiFetch('/api/backup/import', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ data: parsed, overwrite: false })

          });

        } catch (e) {}

      } else if (currentData) {

        localStorage.setItem(key, JSON.stringify(currentData));

      }

    }

  



