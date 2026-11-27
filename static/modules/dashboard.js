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
      },
      muscle_gain: {
        id: "muscle_gain",
        title: "🏋️ Prise de Masse Maigre",
        badge: "+300 kcal & P+ 2.0g/kg",
        delta: 300,
        steps: 8500,
        protein_per_kg: 2.0,
        desc: "Surplus contrôlé +300 kcal/j, protéines 2,0g/kg, glucides soutenus",
        recommendation: "Surplus calorique maîtrisé (+300 kcal) pour soutenir l'anabolisme musculaire et la récupération."
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
      if (typeof renderMacroGoalsPanel === 'function') {
        renderMacroGoalsPanel('nutrition');
      }
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
      const protByDay = [];

      days.forEach(day => {
        const dayMeals = meals.filter(m => m.date === day);
        let b = 0, l = 0, d = 0, s = 0, pDay = 0;
        dayMeals.forEach(m => {
          if (m.meal_type === 'breakfast') b += m.total_calories_kcal;
          else if (m.meal_type === 'lunch') l += m.total_calories_kcal;
          else if (m.meal_type === 'dinner') d += m.total_calories_kcal;
          else if (m.meal_type === 'snack') s += m.total_calories_kcal;
          pDay += Number(m.protein_g || 0);
        });

        bfast.push(b); lunch.push(l); dinner.push(d); snack.push(s); protByDay.push(pDay);
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
          const p = Math.round(protByDay[idx] || 0);
          const targetsObj = (currentData && currentData.summary && currentData.summary.targets) || {};
          const rulesObj = targetsObj.rules || {};
          const protTarget = Math.round(targetsObj.protein_g || 140);
          const protStatus = typeof evaluateNutrientStatus === 'function'
            ? evaluateNutrientStatus('protein', p, protTarget, rulesObj.protein)
            : { state: p >= Math.round(protTarget * 0.95) ? 'reached' : 'below' };
          const total = Math.round(b + l + s + d);
          const isToday = day === todayStr;
          if (isToday) todayTotal = total;

          const target = Math.round(targetsObj.calories || (currentData && currentData.summary && currentData.summary.target_calories_intake) || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0);
          const pct = target > 0 ? Math.min(Math.round((total / target) * 100), 100) : 0;
          const diff = total - target;
          const calStatus = typeof evaluateNutrientStatus === 'function'
            ? evaluateNutrientStatus('calories', total, target, rulesObj.calories)
            : { state: total === 0 ? 'empty' : (total <= target ? 'reached' : 'over') };

          let statusBadge = '';
          if (total === 0 || calStatus.state === 'empty') {
            statusBadge = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-500 font-medium">Non renseigné</span>';
          } else if (calStatus.state === 'reached') {
            statusBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/20">🟢 Conforme (${diff >= 0 ? '+' : ''}${diff} kcal)</span>`;
          } else if (calStatus.state === 'close') {
            statusBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 font-bold border border-amber-500/20">🟡 Proche (${diff >= 0 ? '+' : ''}${diff} kcal)</span>`;
          } else if (calStatus.state === 'over') {
            statusBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 font-bold border border-rose-500/20">🔴 Dépassé (+${diff} kcal)</span>`;
          } else {
            statusBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-400 font-bold border border-sky-500/20">🔵 Sous cible (${diff} kcal)</span>`;
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
                <span class="font-bold ${protStatus.state === 'reached' ? 'text-emerald-400' : (p > 0 ? 'text-brand-300' : 'text-slate-600')}">${p > 0 ? p + ' g' : '-'}</span>
                ${p > 0 ? `<span class="text-[10px] text-slate-400"> / ${Math.round(protTarget)}g</span>` : ''}
              </td>
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

    // 5. Rendu Vue Hub Objets Connectés (Uniquement les appareils ajoutés/connectés par l'utilisateur)
        function formatRelativeTime(isoString) {
      if (!isoString) return null;
      try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return null;
        const now = new Date();
        const diffMs = now - d;
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 1) return "À l'instant";
        if (diffMins === 1) return "Il y a 1 minute";
        if (diffMins < 60) return `Il y a ${diffMins} minutes`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours === 1) return "Il y a 1 heure";
        if (diffHours < 24) return `Il y a ${diffHours} heures`;
        const diffDays = Math.floor(diffHours / 24);
        if (diffDays === 1) return "Hier";
        return `Il y a ${diffDays} jours`;
      } catch (e) {
        return null;
      }
    }

    async function triggerDeviceSync(deviceId, options) {
      options = options || {};
      const devName = (deviceId === 'health_connect' ? 'Passerelle Health Connect' : deviceId);
      try {
        const loadingMsg = options.start_date
          ? `Synchronisation de ${devName} depuis le ${options.start_date}...`
          : (options.since_last_sync ? `Synchronisation incrémentale de ${devName}...` : `Synchronisation de ${devName} en cours...`);
        if (typeof showToast === 'function') showToast(loadingMsg, 'info');
        const qParams = new URLSearchParams();
        if (options.start_date) qParams.append('start_date', options.start_date);
        if (options.since_last_sync) qParams.append('since_last_sync', 'true');
        const qs = qParams.toString() ? ('?' + qParams.toString()) : '';
        const payloadBody = {
          device_id: deviceId,
          start_date: options.start_date || null,
          since_last_sync: Boolean(options.since_last_sync)
        };
        const res = await apiFetch('/api/devices/' + deviceId + '/sync' + qs, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payloadBody)
        });
        if (res.ok) {
          const data = await res.json();
          const periodInfo = data.start_date ? ' (période: ' + data.start_date + ' -> ' + data.end_date + ')' : '';
          const okMsg = 'Synchronisation de ' + (data.name || deviceId) + ' réussie ! Données biométriques à jour' + periodInfo + '.';
          if (typeof showToast === 'function') showToast(okMsg, 'success');
          else alert(okMsg);
          await loadDashboardData();
          return data;
        } else {
          // Fallback legacy
          const legacyRes = await apiFetch('/api/devices/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payloadBody)
          });
          if (legacyRes.ok) {
            const legData = await legacyRes.json();
            if (typeof showToast === 'function') showToast('Synchronisation de ' + deviceId + ' effectuée.', 'success');
            await loadDashboardData();
            return legData;
          } else {
            const errJson = await legacyRes.json().catch(() => ({}));
            const errDetail = errJson.detail || 'Erreur serveur';
            if (typeof showToast === 'function') showToast('Échec de la synchronisation : ' + errDetail, 'error');
            else alert('Échec de la synchronisation : ' + errDetail);
          }
        }
      } catch (err) {
        if (typeof showToast === 'function') showToast('Erreur lors de la synchronisation : ' + (err.message || err), 'error');
      }
    }
    async function disconnectDevice(deviceId) {
      if (!confirm(`Êtes-vous sûr de vouloir déconnecter et révoquer l'appareil '${deviceId}' ?`)) return;
      try {
        const res = await apiFetch(`/api/devices/${deviceId}`, {
          method: 'DELETE'
        });
        if (res.ok) {
          if (typeof showToast === 'function') showToast(`Appareil '${deviceId}' déconnecté et identifiants révoqués.`, 'info');
          await loadDashboardData();
        } else {
          if (typeof showToast === 'function') showToast(`Erreur lors de la déconnexion.`, 'error');
        }
      } catch (err) {
        if (typeof showToast === 'function') showToast(`Erreur réseau lors de la déconnexion.`, 'error');
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
        protein_target_per_kg: parseFloat(document.getElementById('prof-target-prot') && document.getElementById('prof-target-prot').value) || 1.8,
        daily_protein_target_g: null
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


    // =====================================================================
    // LOGIQUE SAUVEGARDE & PERSISTANCE DURABLE (Anti-Perte Vercel)
    // =====================================================================
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


    // =====================================================================
    // LOGIQUE AUTHENTIFICATION UNIFIÉE (GOOGLE, EMAIL/MDP, SESSION & TOKEN BEARER)
    // =====================================================================
    let currentUnifiedSession = { is_authenticated: false };
    let currentGoogleConfig = { google_client_id: "", is_configured: false };
    let currentAuthEmailMode = 'login'; // 'login' ou 'register'

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

    // Exposition globale explicite des handlers définis dans dashboard.js
    window.openProfileModal = openProfileModal;
    window.closeProfileModal = closeProfileModal;
    window.saveUserProfile = saveUserProfile;
    window.formatRelativeTime = formatRelativeTime;
    window.triggerDeviceSync = triggerDeviceSync;


