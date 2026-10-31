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

    function selectGoalProfile(profileId) {
      if (!GOAL_PROFILES[profileId]) return;
      activeGoalProfileId = profileId;
      const p = GOAL_PROFILES[profileId];

      // Mise à jour de l'affichage du header d'objectif
      const titleEl = document.getElementById('active-goal-title');
      const descEl = document.getElementById('active-goal-desc');
      if (titleEl) titleEl.innerText = p.title;
      if (descEl) descEl.innerText = p.desc;

      // Mise à jour des boutons
      ['weight_loss', 'maintenance', 'recomposition'].forEach(id => {
        const btn = document.getElementById(`btn-goal-${id}`);
        if (!btn) return;
        if (id === profileId) {
          btn.className = "goal-btn text-left p-3.5 rounded-xl border-2 border-brand-500 bg-brand-500/10 transition-all flex flex-col justify-between space-y-2";
          const statusSpan = btn.querySelector('.text-brand-400, .text-slate-500');
          if (statusSpan) {
            statusSpan.className = "text-brand-400 font-medium";
            statusSpan.innerText = "Actif ✓";
          }
        } else {
          btn.className = "goal-btn text-left p-3.5 rounded-xl border border-[#1F2A3C] bg-[#0B0F17] hover:border-slate-600 transition-all flex flex-col justify-between space-y-2";
          const statusSpan = btn.querySelector('.text-brand-400, .text-slate-500');
          if (statusSpan) {
            statusSpan.className = "text-slate-500";
            statusSpan.innerText = "Choisir";
          }
        }
      });

      // Recalcul de la cible calorique et des jauges
      if (currentData && currentData.summary) {
        const burned = currentData.summary.calories_burned_kcal || 2280;
        currentData.summary.target_calories_intake = Math.max(1200, Math.round(burned + p.delta));
        currentData.summary.steps_target = p.steps;
        currentData.summary.recommendation = p.recommendation;
        renderSummaryView();
      }
    }

    // Initialisation au chargement de la page
    document.addEventListener("DOMContentLoaded", () => {
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
      initDates();
      loadDashboardData();
      loadUnifiedAuthState();
      if (typeof loadFriendsData === 'function') {
        loadFriendsData();
      }
    });

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
        const res = await apiFetch(`/api/dashboard${readOnlyParam}`);
        if (res.ok) {
          currentData = await res.json();
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
      // Actualisation manuelle : on invalide tous les caches (onglets + journal)
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
    function renderSummaryView() {
      const s = currentData.summary || {};
      
      // Jauges
      document.getElementById('val-weight').innerHTML = `${s.current_weight_kg || '--'} <span class="text-xs font-normal text-slate-400">kg</span>`;
      document.getElementById('val-weight-trend').innerHTML = `<span class="text-brand-400">Tendance 7j: ${s.weight_trend_7d_kg || '--'} kg</span>`;
      const diff = s.weight_7d_variation_kg;
      const diffTxt = diff !== undefined ? (diff > 0 ? `+${diff} kg (7j)` : `${diff} kg (7j)`) : '--';
      document.getElementById('val-weight-diff').innerText = `Variation 7j: ${diffTxt}`;

      // Compteurs énergétiques, anneaux et macros (fonction réutilisable pour
      // les mises à jour ciblées du journal, sans reconstruire les graphiques)
      renderSummaryCounters();

      document.getElementById('val-steps').innerHTML = `${(s.steps || 0).toLocaleString()} <span class="text-xs font-normal text-slate-400">/ 10k</span>`;
      const stepsPct = Math.min(100, Math.round(((s.steps || 0) / (s.steps_target || 10000)) * 100));
      document.getElementById('val-steps-pct').innerText = `Progression: ${stepsPct}%`;
      document.getElementById('bar-steps').style.width = `${stepsPct}%`;

      document.getElementById('summary-recommendation').innerText = s.recommendation || "Poursuivez sur cette trajectoire régulière pour atteindre votre objectif de composition corporelle.";

      // Actualiser le bandeau dynamique de synchronisation Santé Connect / Objets
      renderLiveSyncBanner();

      renderWeightSummaryChart();
    }

    /**
     * Rafraîchit uniquement les compteurs énergétiques et macros de la Synthèse
     * (kcal ingérées / dépensées / bilan net, anneaux d'objectifs, donut macros).
     * Utilisé après une modification optimiste du journal (Lot 2 - BALI-90) :
     * coût constant, aucun graphique poids ni table recalculée.
     */
    function renderSummaryCounters() {
      const s = (currentData && currentData.summary) || {};

      const elCalsIn = document.getElementById('val-cals-in');
      if (elCalsIn) elCalsIn.innerHTML = `${Math.round(s.calories_intake_kcal || 0)} <span class="text-xs font-normal text-slate-400">kcal</span>`;
      const barCalsIn = document.getElementById('bar-cals-in');
      if (barCalsIn) {
        const inPct = Math.min(100, Math.round(((s.calories_intake_kcal || 0) / (s.target_calories_intake || 2000)) * 100));
        barCalsIn.style.width = `${inPct}%`;
      }

      const elCalsOut = document.getElementById('val-cals-out');
      if (elCalsOut) elCalsOut.innerHTML = `${Math.round(s.calories_burned_kcal || 0)} <span class="text-xs font-normal text-slate-400">kcal</span>`;

      // Mise à jour des Anneaux d'objectifs (Palier 3)
      renderSummaryRings();
      const elBmr = document.getElementById('val-bmr');
      if (elBmr) elBmr.innerText = `${Math.round(s.bmr_kcal || 1780)} kcal`;

      const net = Math.round(s.net_energy_balance_kcal || 0);
      const netEl = document.getElementById('val-net-balance');
      if (netEl) {
        netEl.innerHTML = `${net > 0 ? '+' : ''}${net} <span class="text-xs font-normal text-slate-400">kcal</span>`;
        netEl.className = `text-2xl sm:text-3xl font-extrabold ${net <= -250 ? 'text-emerald-400' : (net >= 250 ? 'text-amber-400' : 'text-blue-400')}`;
      }

      const stEl = document.getElementById('val-net-status');
      if (stEl) {
        stEl.innerText = `Statut: ${s.energy_status === 'deficit' ? 'Déficit optimal' : (s.energy_status === 'surplus' ? 'Surplus calorique' : 'Maintien')}`;
        stEl.className = `text-[11px] font-medium ${net <= -250 ? 'text-emerald-400' : (net >= 250 ? 'text-amber-400' : 'text-blue-400')}`;
      }

      const projChange = s.weekly_projected_weight_change_kg || ((net * 7) / 7700).toFixed(2);
      const elProj = document.getElementById('val-projected-loss');
      if (elProj) elProj.innerText = `Impact 7j: ~${projChange} kg`;

      // Donut Macros
      const m = s.macros || {};
      const elProt = document.getElementById('macro-prot-txt');
      const elCarbs = document.getElementById('macro-carbs-txt');
      const elFat = document.getElementById('macro-fat-txt');
      if (elProt) elProt.innerText = `${m.protein_g || 0}g (${m.protein_pct || 0}%)`;
      if (elCarbs) elCarbs.innerText = `${m.carbs_g || 0}g (${m.carbs_pct || 0}%)`;
      if (elFat) elFat.innerText = `${m.fat_g || 0}g (${m.fat_pct || 0}%)`;

      renderMacrosDonut(m);
    }

    /**
     * Applique en mémoire le `day_summary` du journal (aujourd'hui) au résumé du
     * tableau de bord, puis ne rafraîchit que les compteurs concernés.
     * Aucun appel /api/dashboard, aucune reconstruction de la page.
     * @param {{total_calories?:number,total_protein_g?:number,total_carbs_g?:number,total_fat_g?:number,macros_pct?:object}} daySummary
     */
    function applyJournalDaySummaryToDashboard(daySummary) {
      if (!daySummary) return;
      if (typeof currentData === 'undefined' || !currentData) return;
      if (!currentData.summary) currentData.summary = {};

      const s = currentData.summary;
      const intake = Number(daySummary.total_calories) || 0;
      const prot = Number(daySummary.total_protein_g) || 0;
      const carbs = Number(daySummary.total_carbs_g) || 0;
      const fat = Number(daySummary.total_fat_g) || 0;
      const macrosPct = daySummary.macros_pct || {};

      const macroCal = prot * 4 + carbs * 4 + fat * 9;
      const pctOf = (value, pct) => {
        if (pct !== undefined && pct !== null) return Math.round(Number(pct) * 10) / 10;
        return macroCal > 0 ? Math.round((value / macroCal) * 1000) / 10 : 0;
      };

      s.calories_intake_kcal = intake;
      s.macros = {
        protein_g: prot,
        carbs_g: carbs,
        fat_g: fat,
        protein_pct: pctOf(prot * 4, macrosPct.protein_pct),
        carbs_pct: pctOf(carbs * 4, macrosPct.carbs_pct),
        fat_pct: pctOf(fat * 9, macrosPct.fat_pct)
      };

      const burned = Number(s.calories_burned_kcal) || 0;
      const net = Math.round((intake - burned) * 10) / 10;
      s.net_energy_balance_kcal = net;
      s.energy_status = net <= -250 ? 'deficit' : (net >= 250 ? 'surplus' : 'maintenance');
      s.weekly_projected_weight_change_kg = Math.round(((net * 7.0) / 7700.0) * 1000) / 1000;

      // Rafraîchissement ciblé : compteurs si la Synthèse est visible, sinon
      // la vue sera rendue (dirty) à sa prochaine ouverture.
      if (currentActiveTab === 'summary' && typeof renderSummaryCounters === 'function') {
        dirtyTabs.delete('summary');
        renderSummaryCounters();
      } else {
        dirtyTabs.add('summary');
      }
    }

    function renderMacrosDonut(m) {
      const ctx = document.getElementById('chart-macros-donut');
      if (!ctx) return;
      if (chartMacrosDonut) chartMacrosDonut.destroy();

      const pCal = (m.protein_g || 0) * 4;
      const cCal = (m.carbs_g || 0) * 4;
      const fCal = (m.fat_g || 0) * 9;

      chartMacrosDonut = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: ['Protéines', 'Glucides', 'Lipides'],
          datasets: [{
            data: [pCal, cCal, fCal],
            backgroundColor: ['#7C3AED', '#22D3EE', '#C026D3'],
            borderWidth: 0,
            hoverOffset: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '72%',
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => ` ${ctx.label}: ${Math.round(ctx.raw)} kcal`
              }
            }
          }
        }
      });
    }

    function renderWeightSummaryChart() {
      const ctx = document.getElementById('chart-weight-summary');
      if (!ctx) return;
      if (chartWeightSummary) chartWeightSummary.destroy();

      const history = currentData.weights_history || [];
      const labels = history.map(w => w.date.slice(5)); // MM-DD
      const weights = history.map(w => w.weight_kg);
      const trends = history.map(w => w.trend_7d_kg);

      chartWeightSummary = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'Pesée (kg)',
              data: weights,
              borderColor: 'rgba(148, 163, 184, 0.5)',
              backgroundColor: '#94a3b8',
              borderWidth: 1.5,
              pointRadius: 2.5,
              pointHoverRadius: 5,
              tension: 0.1
            },
            {
              label: 'Tendance glissante 7j',
              data: trends,
              borderColor: '#7C3AED',
              backgroundColor: 'rgba(124, 58, 237, 0.15)',
              borderWidth: 3,
              fill: true,
              pointRadius: 0,
              tension: 0.3
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', maxTicksLimit: 8 } },
            y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } }
          },
          plugins: {
            legend: { position: 'top', labels: { color: '#cbd5e1', boxWidth: 12 } }
          }
        }
      });
    }

    // 2. Rendu Vue Poids & Composition
    function renderWeightView() {
      const s = currentData.summary || {};
      document.getElementById('val-body-fat').innerHTML = `${s.body_fat_pct || '--'} <span class="text-xs font-normal text-slate-400">%</span>`;
      document.getElementById('val-muscle-mass').innerHTML = `${s.muscle_mass_kg || '--'} <span class="text-xs font-normal text-slate-400">kg</span>`;
      document.getElementById('val-water-pct').innerHTML = `${s.water_pct || '--'} <span class="text-xs font-normal text-slate-400">%</span>`;
      document.getElementById('val-bmi').innerText = s.bmi || '--';

      // Graphique détaillé
      const ctx = document.getElementById('chart-weight-detail');
      if (ctx) {
        if (chartWeightDetail) chartWeightDetail.destroy();
        const history = currentData.weights_history || [];
        const labels = history.map(w => w.date);
        const weights = history.map(w => w.weight_kg);
        const trends = history.map(w => w.trend_7d_kg);
        const targets = history.map(() => s.target_weight_kg || 77.0);

        chartWeightDetail = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [
              {
                label: 'Pesée Réelle (kg)',
                data: weights,
                borderColor: '#94a3b8',
                backgroundColor: '#cbd5e1',
                borderWidth: 1.5,
                pointRadius: 3.5,
                tension: 0.1
              },
              {
                label: 'Tendance Lissée 7j',
                data: trends,
                borderColor: '#7C3AED',
                borderWidth: 3,
                pointRadius: 0,
                tension: 0.35
              },
              {
                label: 'Objectif Cible (77 kg)',
                data: targets,
                borderColor: '#f59e0b',
                borderDash: [5, 5],
                borderWidth: 2,
                pointRadius: 0
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } },
              y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } }
            },
            plugins: {
              legend: { position: 'top', labels: { color: '#cbd5e1' } }
            }
          }
        });
      }

      // Tableau des pesées
      const tbody = document.getElementById('table-weights-body');
      if (tbody) {
        const history = [...(currentData.weights_history || [])].reverse();
        tbody.innerHTML = history.slice(0, 10).map(w => `
          <tr class="hover:bg-[#1F2A3C]/40 transition-colors">
            <td class="py-2.5 px-3 font-medium text-white">${w.date}</td>
            <td class="py-2.5 px-3 font-bold text-white">${w.weight_kg} kg</td>
            <td class="py-2.5 px-3 text-slate-300">${w.trend_7d_kg ? w.trend_7d_kg + ' kg' : '--'}</td>
            <td class="py-2.5 px-3 text-slate-400">${w.body_fat_pct ? w.body_fat_pct + '%' : '--'}</td>
            <td class="py-2.5 px-3 text-slate-400">${w.muscle_mass_kg ? w.muscle_mass_kg + ' kg' : '--'}</td>
            <td class="py-2.5 px-3">
              <span class="px-2 py-0.5 rounded text-[10px] ${w.source === 'withings' ? 'bg-sky-500/10 text-sky-400 border border-sky-500/20' : 'bg-slate-800 text-slate-400'}">
                ${w.source}
              </span>
            </td>
          </tr>
        `).join('');
      }
    }

    // 3. Rendu Vue Nutrition & Calories Repas
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
                label: 'Cible (2000 kcal)',
                data: days.map(() => 2000),
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

          const target = 2000;
          const pct = Math.min(Math.round((total / target) * 100), 100);
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

        if (todayBadge) {
          todayBadge.textContent = `Aujourd'hui : ${todayTotal} kcal / 2 000 kcal`;
          if (todayTotal > 2000) {
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

        container.innerHTML = meals.map(m => {
          const typeInfo = mealTypeLabels[m.meal_type] || { label: m.meal_type, color: "text-slate-400" };
          const itemsStr = (m.items || []).map(i => `${i.name} (${Math.round(i.portion_g || 100)}g)`).join(', ');
          
          return `
            <div class="bg-[#0B0F17] border border-[#1F2A3C] rounded-xl p-4 flex flex-col justify-between space-y-3">
              <div class="flex items-start justify-between">
                <div>
                  <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border ${typeInfo.color}">
                    ${typeInfo.label}
                  </span>
                  <div class="text-xs text-slate-400 mt-1">${m.date}</div>
                </div>
                <div class="text-right">
                  <span class="text-base font-extrabold text-white">${Math.round(m.total_calories_kcal)}</span>
                  <span class="text-xs text-slate-400">kcal</span>
                </div>
              </div>

              <!-- Photo éventuelle -->
              ${m.photo_data_url ? `
                <div class="rounded-lg overflow-hidden border border-[#1F2A3C] max-h-32">
                  <img src="${m.photo_data_url}" alt="Photo repas" class="w-full h-full object-cover">
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

              <!-- Action Sauvegarde Plat Type -->
              <div class="pt-1 flex items-center justify-end">
                <button onclick="saveLoggedMealAsTemplate(${meals.indexOf(m)})" class="text-[10px] text-amber-400 hover:text-amber-300 flex items-center space-x-1 py-1 px-2 rounded-lg bg-amber-400/10 hover:bg-amber-400/20 border border-amber-400/20 transition-colors">
                  <i data-lucide="star" class="w-3 h-3"></i>
                  <span>⭐ Enregistrer comme plat type</span>
                </button>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    // 4. Rendu Vue Activité & Biomécanique Avancée (Palier 3)
    async function loadMetricsData(days = 30) {
      try {
        const resp = await API.get(`/api/metrics?days=${days}`);
        if (resp.ok) {
          currentMetricsData = await resp.json();
          return currentMetricsData;
        }
      } catch (err) {
        console.warn("[Metrics] Impossible de charger /api/metrics:", err);
      }
      return null;
    }

    function renderSummaryRings() {
      // Si nous avons déjà les métriques ou les données du dashboard
      const rings = (currentMetricsData && currentMetricsData.rings) || null;
      const s = (currentData && currentData.summary) || {};

      let stepsCur = 0;
      let stepsTgt = 10000;
      let stepsPct = 0;
      let calsCur = 0;
      let calsTgt = 500;
      let calsPct = 0;
      let recScore = s.sleep_score || null;

      if (rings) {
        stepsCur = rings.steps.current || 0;
        stepsTgt = rings.steps.target || 10000;
        stepsPct = rings.steps.pct || 0;
        calsCur = rings.active_calories.current || 0;
        calsTgt = rings.active_calories.target || 500;
        calsPct = rings.active_calories.pct || 0;
        recScore = rings.sleep_recovery.recovery_score || (rings.sleep_recovery.current_sleep_hours ? Math.round(rings.sleep_recovery.pct) : null);
      } else {
        stepsCur = s.steps || 0;
        stepsTgt = s.steps_target || 10000;
        stepsPct = Math.min(100, Math.round((stepsCur / stepsTgt) * 100));
        calsCur = Math.max(0, (s.calories_burned_kcal || 1780) - (s.bmr_kcal || 1780));
        calsPct = Math.min(100, Math.round((calsCur / 500) * 100));
      }

      // Anneau 1 : Pas
      const elStepsVal = document.getElementById('ring-steps-val');
      const elStepsPct = document.getElementById('ring-steps-pct');
      const elStepsSvg = document.getElementById('ring-svg-steps');
      if (elStepsVal) elStepsVal.innerHTML = `${stepsCur.toLocaleString()} <span class="text-xs font-normal text-slate-400">/ ${stepsTgt >= 1000 ? Math.round(stepsTgt/1000)+'k' : stepsTgt}</span>`;
      if (elStepsPct) elStepsPct.innerText = `Progression: ${stepsPct}%`;
      if (elStepsSvg) elStepsSvg.setAttribute('stroke-dasharray', `${Math.min(100, stepsPct)}, 100`);

      // Anneau 2 : Calories
      const elCalsVal = document.getElementById('ring-cals-val');
      const elCalsPct = document.getElementById('ring-cals-pct');
      const elCalsSvg = document.getElementById('ring-svg-cals');
      if (elCalsVal) elCalsVal.innerHTML = `${Math.round(calsCur)} <span class="text-xs font-normal text-slate-400">/ ${Math.round(calsTgt)} kcal</span>`;
      if (elCalsPct) elCalsPct.innerText = `Progression: ${calsPct}%`;
      if (elCalsSvg) elCalsSvg.setAttribute('stroke-dasharray', `${Math.min(100, calsPct)}, 100`);

      // Anneau 3 : Récupération
      const elRecVal = document.getElementById('ring-recovery-val');
      const elRecStat = document.getElementById('ring-recovery-status');
      const elRecSvg = document.getElementById('ring-svg-recovery');
      const recPct = recScore !== null ? Math.min(100, Math.max(0, recScore)) : 0;
      if (elRecVal) elRecVal.innerHTML = `${recScore !== null ? Math.round(recScore) : '--'} <span class="text-xs font-normal text-slate-400">/ 100</span>`;
      if (elRecStat) {
        if (recScore === null) {
          elRecStat.innerText = "En attente de nuit";
        } else if (recScore >= 80) {
          elRecStat.innerText = "Excellente récupération";
        } else if (recScore >= 60) {
          elRecStat.innerText = "Bonne récupération";
        } else {
          elRecStat.innerText = "Récupération à surveiller";
        }
      }
      if (elRecSvg) elRecSvg.setAttribute('stroke-dasharray', `${recPct}, 100`);
    }

    async function renderActivityView() {
      // Charger les données biométriques complètes sur /api/metrics à la demande
      if (!currentMetricsData) {
        await loadMetricsData(currentTrendsDays);
      }
      
      const metrics = currentMetricsData || {};
      const hasRealData = Boolean(metrics.has_real_data);

      const emptyEl = document.getElementById('activity-empty-state');
      const activeEl = document.getElementById('activity-content-active');

      if (!hasRealData) {
        if (emptyEl) emptyEl.classList.remove('hidden');
        if (activeEl) activeEl.classList.add('hidden');
        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch(e){} }
        return;
      }

      if (emptyEl) emptyEl.classList.add('hidden');
      if (activeEl) activeEl.classList.remove('hidden');

      // 1. Score de Récupération
      const rec = metrics.recovery || {};
      const recValEl = document.getElementById('val-recovery-score');
      const recBadgeEl = document.getElementById('badge-recovery-cat');
      const recInsightEl = document.getElementById('recovery-insight-text');

      if (recValEl) recValEl.innerText = rec.score !== undefined && rec.score !== null ? Math.round(rec.score) : '--';
      if (recBadgeEl) {
        const cat = rec.category || 'optimal';
        const catLabels = {
          optimal: { label: 'Optimal', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' },
          good: { label: 'Bon', cls: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30' },
          moderate: { label: 'Modéré', cls: 'bg-amber-500/10 text-amber-300 border-amber-500/30' },
          low: { label: 'Attention', cls: 'bg-rose-500/10 text-rose-300 border-rose-500/30' }
        };
        const cInfo = catLabels[cat] || catLabels.good;
        recBadgeEl.innerText = cInfo.label;
        recBadgeEl.className = `text-[10px] px-2 py-0.5 rounded-full border font-semibold ${cInfo.cls}`;
      }
      if (recInsightEl) {
        recInsightEl.innerText = rec.factors_summary || "Biomarqueurs stables dans leurs couloirs habituels.";
      }

      // Bande de normalité HRV
      const corridors = metrics.corridors || {};
      const hrvCorr = corridors.hrv_rmssd_ms;
      if (hrvCorr) {
        const rangeEl = document.getElementById('corridor-hrv-range');
        const minEl = document.getElementById('corridor-hrv-min');
        const maxEl = document.getElementById('corridor-hrv-max');
        const stEl = document.getElementById('corridor-hrv-status');
        const markerEl = document.getElementById('corridor-hrv-marker');

        if (rangeEl) rangeEl.innerText = `${Math.round(hrvCorr.lower_bound)} - ${Math.round(hrvCorr.upper_bound)} ms`;
        if (minEl) minEl.innerText = `${Math.round(hrvCorr.p15 || hrvCorr.lower_bound)} ms`;
        if (maxEl) maxEl.innerText = `${Math.round(hrvCorr.p85 || hrvCorr.upper_bound)} ms`;
        if (stEl) {
          stEl.innerText = hrvCorr.is_in_corridor ? "Dans la normale" : (hrvCorr.current_value < hrvCorr.lower_bound ? "En-dessous" : "Au-dessus");
          stEl.className = hrvCorr.is_in_corridor ? "text-cyan-400 font-medium" : "text-amber-400 font-medium";
        }
        if (markerEl && hrvCorr.current_value && hrvCorr.upper_bound > hrvCorr.lower_bound) {
          const ratio = Math.max(0, Math.min(1, (hrvCorr.current_value - hrvCorr.lower_bound * 0.8) / (hrvCorr.upper_bound * 1.2 - hrvCorr.lower_bound * 0.8)));
          markerEl.style.left = `${Math.round(ratio * 100)}%`;
        }
      }

      // 2. Hypnogramme & Dette de Sommeil (RingConn Gen 3)
      const sleep = metrics.sleep || {};
      const sSession = sleep.latest_session;
      if (sSession) {
        const durHours = (sSession.duration_minutes || 0) / 60;
        const durEl = document.getElementById('sleep-total-duration');
        const effEl = document.getElementById('sleep-efficiency-pct');
        if (durEl) durEl.innerText = `${Math.floor(durHours)}h ${Math.round((durHours % 1) * 60)}m`;
        if (effEl) effEl.innerText = `${Math.round(sSession.efficiency_pct || 85)}%`;

        renderHypnogram(sSession);
      } else {
        const timeline = document.getElementById('hypnogram-timeline');
        if (timeline) {
          timeline.innerHTML = `<div class="w-full flex items-center justify-center text-xs text-slate-500">Aucune phase de sommeil enregistrée cette nuit.</div>`;
        }
      }

      const sDebt = sleep.debt;
      if (sDebt) {
        const debtEl = document.getElementById('val-sleep-debt');
        const debtDescEl = document.getElementById('val-sleep-debt-desc');
        const barDebt = document.getElementById('bar-sleep-debt');
        if (debtEl) debtEl.innerText = `${sDebt.cumulative_debt_hours > 0 ? '+' : ''}${sDebt.cumulative_debt_hours} h`;
        if (debtDescEl) debtDescEl.innerText = sDebt.description || "Dette calculée sur fenêtre 7j.";
        if (barDebt) {
          const pct = Math.min(100, Math.max(5, (sDebt.cumulative_debt_hours / 10.0) * 100));
          barDebt.style.width = `${pct}%`;
        }
      }

      // 3. Graphiques : FC Intraday, Tendances Long Terme & Corrélations
      renderIntradayHRChart(metrics.intraday_hr || []);
      renderTrendsChart(metrics.trends || []);
      renderWorkoutsList(metrics.workouts || []);
      renderCrossCorrelationsChart();
      renderCalendarHeatmap(metrics.heatmap || []);

      if (window.lucide && lucide.createIcons) {
        try { lucide.createIcons(); } catch(e){}
      }
    }

    // Hypnogramme : Rendu visuel des phases de sommeil en barres de couleur
    function renderHypnogram(session) {
      const container = document.getElementById('hypnogram-timeline');
      if (!container) return;

      const stages = session.stages || [];
      const totalSec = stages.reduce((acc, st) => acc + (st.duration_seconds || 0), 0) || (session.duration_minutes * 60);

      const stageColors = {
        deep: 'bg-violet-600 hover:brightness-125',
        rem: 'bg-cyan-400 hover:brightness-125',
        light: 'bg-blue-500 hover:brightness-125',
        awake: 'bg-rose-500 hover:brightness-125'
      };

      const stageLabels = {
        deep: 'Profond',
        rem: 'Paradoxal (REM)',
        light: 'Léger',
        awake: 'Éveil'
      };

      let deepSec = session.deep_minutes ? session.deep_minutes * 60 : 0;
      let remSec = session.rem_minutes ? session.rem_minutes * 60 : 0;
      let lightSec = session.light_minutes ? session.light_minutes * 60 : 0;
      let awakeSec = session.awake_minutes ? session.awake_minutes * 60 : 0;

      if (stages.length > 0) {
        deepSec = stages.filter(s => s.stage === 'deep').reduce((a, b) => a + b.duration_seconds, 0);
        remSec = stages.filter(s => s.stage === 'rem').reduce((a, b) => a + b.duration_seconds, 0);
        lightSec = stages.filter(s => s.stage === 'light').reduce((a, b) => a + b.duration_seconds, 0);
        awakeSec = stages.filter(s => s.stage === 'awake').reduce((a, b) => a + b.duration_seconds, 0);

        container.innerHTML = stages.map(st => {
          const widthPct = Math.max(0.5, ((st.duration_seconds || 60) / totalSec) * 100);
          const colorCls = stageColors[st.stage] || 'bg-slate-600';
          const mins = Math.round(st.duration_seconds / 60);
          return `
            <div class="${colorCls} h-full transition-all cursor-pointer rounded-sm"
                 style="width: ${widthPct}%;"
                 title="${stageLabels[st.stage] || st.stage}: ${mins} min (${st.start_time ? st.start_time.slice(11,16) : ''} - ${st.end_time ? st.end_time.slice(11,16) : ''})">
            </div>
          `;
        }).join('');
      } else {
        container.innerHTML = `
          <div class="w-full flex items-center justify-center text-xs text-slate-400">
            Session globale de ${Math.round(session.duration_minutes)} min enregistrée (détail des phases non partitionné).
          </div>
        `;
      }

      // Pourcentages dans la légende
      const pctDeepEl = document.getElementById('pct-deep');
      const pctRemEl = document.getElementById('pct-rem');
      const pctLightEl = document.getElementById('pct-light');
      const pctAwakeEl = document.getElementById('pct-awake');
      if (pctDeepEl && totalSec > 0) pctDeepEl.innerText = `${Math.round((deepSec / totalSec) * 100)}%`;
      if (pctRemEl && totalSec > 0) pctRemEl.innerText = `${Math.round((remSec / totalSec) * 100)}%`;
      if (pctLightEl && totalSec > 0) pctLightEl.innerText = `${Math.round((lightSec / totalSec) * 100)}%`;
      if (pctAwakeEl && totalSec > 0) pctAwakeEl.innerText = `${Math.round((awakeSec / totalSec) * 100)}%`;
    }

    // Graphique FC Intraday sur 24 heures
    function renderIntradayHRChart(samples) {
      const ctx = document.getElementById('chart-hr-intraday');
      if (!ctx) return;
      if (chartHRIntraday) chartHRIntraday.destroy();

      const labels = samples.map(s => s.timestamp ? s.timestamp.slice(11, 16) : '');
      const data = samples.map(s => s.value);

      // Calcul FC repos estimée
      if (data.length > 0) {
        const sorted = [...data].sort((a,b) => a - b);
        const rhrPill = document.getElementById('stat-resting-hr-pill');
        if (rhrPill) rhrPill.innerText = `Min: ${sorted[0]} | Repos: ${sorted[Math.floor(sorted.length * 0.1)]} bpm`;
      }

      chartHRIntraday = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: 'Fréquence Cardiaque (bpm)',
            data: data,
            borderColor: '#F43F5E',
            backgroundColor: 'rgba(244, 63, 94, 0.12)',
            fill: true,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: data.length > 100 ? 0 : 2,
            pointHoverRadius: 5
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#14142B',
              borderColor: '#25254A',
              borderWidth: 1,
              titleColor: '#F8FAFC',
              bodyColor: '#F43F5E'
            }
          },
          scales: {
            x: {
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { color: '#64748B', maxTicksLimit: 12 }
            },
            y: {
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { color: '#94A3B8' },
              suggestedMin: 45,
              suggestedMax: 150
            }
          }
        }
      });
    }

    // Graphique Tendances Long Terme (HRV & RHR 30 à 90 jours avec Couloirs de Normalité)
    function renderTrendsChart(trends) {
      const ctx = document.getElementById('chart-biometrics-trends');
      if (!ctx) return;
      if (chartBiometricsTrends) chartBiometricsTrends.destroy();

      const labels = trends.map(t => t.date ? t.date.slice(5) : '');
      const hrvData = trends.map(t => t.hrv_rmssd_ms);
      const rhrData = trends.map(t => t.resting_hr_bpm);

      // Calcul des baselines pour couloir
      const validHrv = hrvData.filter(v => v !== null && v !== undefined);
      const avgHrv = validHrv.length > 0 ? (validHrv.reduce((a,b)=>a+b,0) / validHrv.length) : 55;
      const hrvUpper = avgHrv * 1.15;
      const hrvLower = avgHrv * 0.85;

      chartBiometricsTrends = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'HRV (RMSSD ms)',
              data: hrvData,
              borderColor: '#22D3EE',
              backgroundColor: '#22D3EE',
              borderWidth: 2,
              pointRadius: 2.5,
              tension: 0.25,
              yAxisID: 'yHrv'
            },
            {
              label: 'Couloir HRV Max',
              data: labels.map(() => hrvUpper),
              borderColor: 'rgba(34, 211, 238, 0.3)',
              borderDash: [4, 4],
              borderWidth: 1,
              pointRadius: 0,
              fill: false,
              yAxisID: 'yHrv'
            },
            {
              label: 'Couloir HRV Min',
              data: labels.map(() => hrvLower),
              borderColor: 'rgba(34, 211, 238, 0.3)',
              borderDash: [4, 4],
              borderWidth: 1,
              pointRadius: 0,
              fill: false,
              yAxisID: 'yHrv'
            },
            {
              label: 'FC de Repos (bpm)',
              data: rhrData,
              borderColor: '#A855F7',
              backgroundColor: '#A855F7',
              borderWidth: 2,
              pointRadius: 2.5,
              tension: 0.25,
              yAxisID: 'yRhr'
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              labels: {
                color: '#CBD5E1',
                filter: item => !item.text.includes('Couloir')
              }
            }
          },
          scales: {
            x: {
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { color: '#64748B' }
            },
            yHrv: {
              type: 'linear',
              position: 'left',
              title: { display: true, text: 'HRV (ms)', color: '#22D3EE' },
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { color: '#22D3EE' }
            },
            yRhr: {
              type: 'linear',
              position: 'right',
              title: { display: true, text: 'FC Repos (bpm)', color: '#A855F7' },
              grid: { drawOnChartArea: false },
              ticks: { color: '#A855F7' }
            }
          }
        }
      });
    }

    async function changeTrendsRange(days) {
      currentTrendsDays = days;
      [30, 60, 90].forEach(d => {
        const btn = document.getElementById(`btn-range-${d}`);
        if (!btn) return;
        if (d === days) {
          btn.className = "px-2.5 py-1 rounded-lg text-[10px] font-bold bg-violet-600 text-white";
        } else {
          btn.className = "px-2.5 py-1 rounded-lg text-[10px] font-medium text-slate-400 hover:text-white";
        }
      });
      await loadMetricsData(days);
      if (currentMetricsData && currentMetricsData.trends) {
        renderTrendsChart(currentMetricsData.trends);
        renderCalendarHeatmap(currentMetricsData.heatmap || []);
      }
    }

    // Journal des Séances d'Entraînement (`workouts`)
    function renderWorkoutsList(workouts) {
      const container = document.getElementById('workouts-list-container');
      const badge = document.getElementById('workouts-count-badge');
      if (!container) return;

      if (badge) badge.innerText = `${workouts.length} séance${workouts.length > 1 ? 's' : ''}`;

      if (workouts.length === 0) {
        container.innerHTML = `
          <div class="p-4 rounded-xl bg-[#0B0B1A]/60 border border-[#25254A] text-center text-xs text-slate-500">
            Aucun entraînement synchronisé récemment.
          </div>
        `;
        return;
      }

      const workoutIcons = {
        running: 'footprints',
        cycling: 'bike',
        swimming: 'waves',
        walking: 'navigation',
        strength: 'dumbbell'
      };

      container.innerHTML = workouts.slice(0, 10).map(w => {
        const iconName = workoutIcons[w.workout_type] || 'activity';
        const startFormatted = w.start_time ? w.start_time.replace('T', ' ').slice(0, 16) : '';
        return `
          <div class="p-3 rounded-xl bg-[#0B0B1A]/90 border border-[#25254A] hover:border-violet-500/40 transition-colors flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <div class="w-8 h-8 rounded-lg bg-violet-600/10 border border-violet-500/20 flex items-center justify-center text-violet-400 shrink-0">
                <i data-lucide="${iconName}" class="w-4 h-4"></i>
              </div>
              <div>
                <div class="text-xs font-bold text-white capitalize">${w.workout_type || 'Séance'}</div>
                <div class="text-[10px] text-slate-400">${startFormatted} • ${w.duration_minutes || 0} min</div>
              </div>
            </div>
            <div class="text-right">
              <div class="text-xs font-black text-orange-400">${Math.round(w.calories_kcal || 0)} kcal</div>
              <div class="text-[10px] text-rose-400">${w.avg_hr_bpm ? w.avg_hr_bpm + ' bpm avg' : (w.distance_meters ? (w.distance_meters/1000).toFixed(1) + ' km' : '')}</div>
            </div>
          </div>
        `;
      }).join('');
    }

    // Corrélations Croisées (Poids vs Calories / Sommeil vs HRV)
    function switchCorrelationMode(mode) {
      currentCorrelationMode = mode;
      const btnW = document.getElementById('btn-corr-weight');
      const btnS = document.getElementById('btn-corr-sleep');
      if (btnW && btnS) {
        if (mode === 'weight_cals') {
          btnW.className = "px-2.5 py-1 rounded-lg text-[10px] font-bold bg-violet-600 text-white";
          btnS.className = "px-2.5 py-1 rounded-lg text-[10px] font-medium text-slate-400 hover:text-white";
        } else {
          btnS.className = "px-2.5 py-1 rounded-lg text-[10px] font-bold bg-violet-600 text-white";
          btnW.className = "px-2.5 py-1 rounded-lg text-[10px] font-medium text-slate-400 hover:text-white";
        }
      }
      renderCrossCorrelationsChart();
    }

    function renderCrossCorrelationsChart() {
      const ctx = document.getElementById('chart-cross-correlations');
      if (!ctx || !currentMetricsData) return;
      if (chartCrossCorrelations) chartCrossCorrelations.destroy();

      const corrs = currentMetricsData.correlations || {};

      if (currentCorrelationMode === 'weight_cals') {
        const list = corrs.weight_vs_calories || [];
        const labels = list.map(item => item.date.slice(5));
        const weights = list.map(item => item.weight_kg);
        const cals = list.map(item => item.active_calories);

        chartCrossCorrelations = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: labels,
            datasets: [
              {
                type: 'bar',
                label: 'Calories Actives Dépensées (kcal)',
                data: cals,
                backgroundColor: 'rgba(249, 115, 22, 0.35)',
                borderColor: '#F97316',
                borderWidth: 1.5,
                yAxisID: 'yCals'
              },
              {
                type: 'line',
                label: 'Poids (kg)',
                data: weights,
                borderColor: '#34D399',
                backgroundColor: '#34D399',
                borderWidth: 2,
                pointRadius: 3,
                tension: 0.2,
                yAxisID: 'yWeight'
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { labels: { color: '#CBD5E1' } }
            },
            scales: {
              x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748B' } },
              yCals: {
                type: 'linear',
                position: 'left',
                title: { display: true, text: 'Calories (kcal)', color: '#F97316' },
                grid: { color: 'rgba(255,255,255,0.04)' },
                ticks: { color: '#F97316' }
              },
              yWeight: {
                type: 'linear',
                position: 'right',
                title: { display: true, text: 'Poids (kg)', color: '#34D399' },
                grid: { drawOnChartArea: false },
                ticks: { color: '#34D399' }
              }
            }
          }
        });
      } else {
        const list = corrs.sleep_vs_hrv || [];
        const labels = list.map(item => item.date.slice(5));
        const sleepScores = list.map(item => item.sleep_score);
        const hrv = list.map(item => item.hrv_rmssd_ms);

        chartCrossCorrelations = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [
              {
                label: 'Score de Sommeil (/100)',
                data: sleepScores,
                borderColor: '#818CF8',
                backgroundColor: '#818CF8',
                borderWidth: 2,
                pointRadius: 2.5,
                tension: 0.2,
                yAxisID: 'ySleep'
              },
              {
                label: 'HRV (ms)',
                data: hrv,
                borderColor: '#22D3EE',
                backgroundColor: '#22D3EE',
                borderWidth: 2,
                pointRadius: 2.5,
                tension: 0.2,
                yAxisID: 'yHrv'
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { labels: { color: '#CBD5E1' } }
            },
            scales: {
              x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748B' } },
              ySleep: {
                type: 'linear',
                position: 'left',
                title: { display: true, text: 'Sommeil (/100)', color: '#818CF8' },
                grid: { color: 'rgba(255,255,255,0.04)' },
                ticks: { color: '#818CF8' }
              },
              yHrv: {
                type: 'linear',
                position: 'right',
                title: { display: true, text: 'HRV (ms)', color: '#22D3EE' },
                grid: { drawOnChartArea: false },
                ticks: { color: '#22D3EE' }
              }
            }
          }
        });
      }
    }

    // Heatmap Calendaire d'Assiduité (90 jours)
    function renderCalendarHeatmap(heatmapDays) {
      const container = document.getElementById('calendar-heatmap-container');
      if (!container) return;

      if (heatmapDays.length === 0) {
        container.innerHTML = `<div class="text-xs text-slate-500 py-3">Aucune donnée calendaire d'assiduité.</div>`;
        return;
      }

      const intensityColors = {
        0: 'bg-[#151D2A] border border-[#25254A]',
        1: 'bg-violet-950/80 border border-violet-800/60',
        2: 'bg-violet-600',
        3: 'bg-cyan-400'
      };

      container.innerHTML = `
        <div class="flex flex-wrap gap-1.5 pt-1">
          ${heatmapDays.map(d => {
            const cls = intensityColors[d.intensity] || intensityColors[0];
            const workoutBadge = d.has_workout ? '• Entraînement' : '';
            return `
              <div class="w-3.5 h-3.5 sm:w-4 sm:h-4 rounded cursor-pointer transition-transform hover:scale-125 ${cls}"
                   title="${d.date}: ${d.steps} pas ${workoutBadge}">
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    window.changeTrendsRange = changeTrendsRange;
    window.switchCorrelationMode = switchCorrelationMode;
    window.renderSummaryRings = renderSummaryRings;

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

        function renderLiveSyncBanner() {
      const banner = document.getElementById('banner-health-connect-live');
      if (!banner) return;

      const titleEl = document.getElementById('live-hc-title');
      const badgeEl = document.getElementById('live-hc-status-badge');
      const statusTextEl = document.getElementById('live-hc-status-text');
      const iconEl = document.getElementById('live-hc-icon');
      const iconContainerEl = document.getElementById('live-hc-icon-container');
      const stepsEl = document.getElementById('live-hc-steps');
      const calsEl = document.getElementById('live-hc-cals');
      const hrEl = document.getElementById('live-hc-hr');
      const hrvEl = document.getElementById('live-hc-hrv');
      const sleepEl = document.getElementById('live-hc-sleep');
      const syncBtn = document.getElementById('live-hc-sync-btn');
      const syncTxt = document.getElementById('live-hc-sync-txt');

      const s = currentData.summary || {};
      const allDevices = currentData.devices || [];
      const connectedDevices = allDevices.filter(d => Boolean(d.connected || d.status === 'connected'));

      // Trouver l'appareil prioritaire (Health Connect > RingConn > Oura > premier connecté)
      let activeDevice = connectedDevices.find(d => (d.id || d.device_id) === 'health_connect')
        || connectedDevices.find(d => ['ringconn', 'oura'].includes(d.id || d.device_id))
        || connectedDevices[0]
        || null;

      const latestAct = (currentData.activities_history && currentData.activities_history.length > 0)
        ? currentData.activities_history[currentData.activities_history.length - 1]
        : null;

      const stepsVal = latestAct ? (latestAct.steps || s.steps) : s.steps;
      const calsVal = latestAct ? (latestAct.active_calories_kcal || 0) : null;
      const hrVal = latestAct ? (latestAct.resting_hr_bpm || s.resting_hr_bpm) : s.resting_hr_bpm;
      const hrvVal = latestAct ? (latestAct.hrv_ms || s.hrv_ms) : s.hrv_ms;
      const sleepVal = latestAct ? (latestAct.sleep_score || s.sleep_score) : s.sleep_score;

      if (stepsEl) stepsEl.innerText = stepsVal !== null && stepsVal !== undefined ? `${stepsVal.toLocaleString()} pas` : '-- pas';
      if (calsEl) calsEl.innerText = calsVal !== null && calsVal !== undefined ? `${calsVal} kcal` : '-- kcal';
      if (hrEl) hrEl.innerText = hrVal ? `${hrVal} BPM` : '--';
      if (hrvEl) hrvEl.innerText = hrvVal ? `${hrvVal} ms` : '--';
      if (sleepEl) sleepEl.innerText = sleepVal ? `${sleepVal} / 100` : '--';

      // 1. Cas : Aucun appareil connecté
      if (!activeDevice && connectedDevices.length === 0) {
        if (titleEl) titleEl.innerText = "Synchronisation appareils : Aucune passerelle connectée";
        if (badgeEl) {
          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 font-semibold flex items-center gap-1";
          badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-slate-500"></span><span id="live-hc-status-text">Non connecté</span>';
        }
        if (iconEl) iconEl.setAttribute('data-lucide', 'link-2');
        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-slate-800/60 border border-slate-700 flex items-center justify-center text-slate-400 shrink-0";
        if (syncTxt) syncTxt.innerText = "Connecter";
        if (syncBtn) {
          syncBtn.onclick = () => openConnectWizardModal('health_connect');
          syncBtn.title = "Ouvrir l'assistant de connexion d'appareils";
        }
        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-slate-900/60 via-[#151D2A] to-[#151D2A] border border-slate-700/50 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";
        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
        return;
      }

      // 2. Cas : Appareil connecté
      const devId = activeDevice.id || activeDevice.device_id;
      const devName = activeDevice.name || (devId === 'health_connect' ? 'Google Santé Connect (Android)' : (devId === 'withings' ? 'Withings' : devId));
      if (titleEl) titleEl.innerText = `Données en direct : ${devName}`;

      let iconName = 'smartphone';
      if (activeDevice.device_type === 'ring' || devId === 'ringconn' || devId === 'oura') iconName = 'circle-dot';
      else if (activeDevice.device_type === 'scale' || devId === 'withings') iconName = 'scale';
      if (iconEl) iconEl.setAttribute('data-lucide', iconName);

      if (syncBtn) {
        syncBtn.onclick = () => triggerSyncFromBanner(devId);
        syncBtn.title = `Lancer la synchronisation immédiate de ${devName}`;
      }
      if (syncTxt) syncTxt.innerText = "Synchroniser";

      const lastSyncRaw = activeDevice.last_sync_at || activeDevice.last_sync;
      const syncStatus = (activeDevice.sync_status || activeDevice.status || 'connected').toLowerCase();
      const relativeTime = formatRelativeTime(lastSyncRaw);

      if (syncStatus === 'error' || syncStatus === 'failed') {
        if (badgeEl) {
          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/30 font-semibold flex items-center gap-1";
          badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span><span id="live-hc-status-text">Erreur de synchronisation ⚠</span>';
        }
        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0";
        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-rose-950/30 via-[#151D2A] to-[#151D2A] border border-rose-500/30 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";
      } else if (!lastSyncRaw || syncStatus === 'waiting_first_sync') {
        if (badgeEl) {
          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 font-semibold flex items-center gap-1";
          badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span><span id="live-hc-status-text">En attente du 1er envoi depuis votre téléphone</span>';
        }
        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0";
        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-amber-950/30 via-[#151D2A] to-[#151D2A] border border-amber-500/30 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";
      } else {
        const syncLabel = relativeTime ? `Synchronisé ${relativeTime.toLowerCase()} ✓` : 'Synchronisé ✓';
        if (badgeEl) {
          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold flex items-center gap-1";
          badgeEl.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span><span id="live-hc-status-text">${syncLabel}</span>`;
        }
        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0";
        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-emerald-950/40 via-[#151D2A] to-[#151D2A] border border-emerald-500/30 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";
      }

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    async function triggerSyncFromBanner(deviceId) {
      const syncIcon = document.getElementById('live-hc-sync-icon');
      const syncTxt = document.getElementById('live-hc-sync-txt');
      if (syncIcon) syncIcon.classList.add('animate-spin');
      if (syncTxt) syncTxt.innerText = "Synchronisation...";

      const targetId = deviceId || 'health_connect';
      try {
        await triggerDeviceSync(targetId);
      } finally {
        if (syncIcon) syncIcon.classList.remove('animate-spin');
        if (syncTxt) syncTxt.innerText = "Synchroniser";
      }
    }

    function renderDevicesView() {
      const grid = document.getElementById('devices-grid');
      if (!grid) return;

      const allDevices = currentData.devices || [];
      // Filtrer STRICTEMENT : seuls les appareils ajoutés / connectés sont affichés
      const connectedDevices = allDevices.filter(d => Boolean(d.connected || d.status === 'connected'));

      if (connectedDevices.length === 0) {
        grid.innerHTML = `
          <div class="col-span-full bg-[#0B0F17] border border-dashed border-[#1F2A3C] rounded-2xl p-8 text-center space-y-3">
            <div class="w-12 h-12 mx-auto rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
              <i data-lucide="link-2" class="w-6 h-6"></i>
            </div>
            <h4 class="text-sm font-bold text-white">Aucun objet connecté dans votre profil pour le moment</h4>
            <p class="text-xs text-slate-400 max-w-md mx-auto">
              Ajoutez votre bague connectée RingConn, Google Santé Connect (Android), ou votre balance Withings pour lancer la synchronisation automatique.
            </p>
            <button type="button" onclick="openConnectWizardModal()" class="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-md shadow-indigo-600/20 inline-flex items-center space-x-2 transition-transform active:scale-95">
              <i data-lucide="plus" class="w-4 h-4"></i>
              <span>Ajouter mon premier appareil</span>
            </button>
          </div>
        `;
        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
        return;
      }

      // Rendu des cartes pour chaque appareil connecté
      const cardsHtml = connectedDevices.map(d => {
        const devId = d.id || d.device_id;
        const lastSyncVal = d.last_sync_at || d.last_sync;
        const wizTarget = (devId === 'ringconn' || devId === 'withings' || devId === 'oura' || devId === 'health_connect') ? devId : 'health_connect';

        // Métriques contextuelles selon l'appareil
        let metricsSnippet = '';
        if (devId === 'health_connect') {
          const act = (currentData.activities_history && currentData.activities_history.length > 0)
            ? currentData.activities_history[currentData.activities_history.length - 1]
            : null;
          if (act) {
            metricsSnippet = `
              <div class="p-2.5 rounded-xl bg-emerald-950/20 border border-emerald-500/30 text-[11px] text-slate-300 space-y-1">
                <span class="text-emerald-400 font-semibold block flex items-center space-x-1">
                  <i data-lucide="check-circle" class="w-3 h-3 text-emerald-400"></i>
                  <span>Dernier flux reçu :</span>
                </span>
                <div class="text-white font-medium">
                  <strong>${(act.steps || 0).toLocaleString()} pas</strong> • <strong>${act.active_calories_kcal || 0} kcal</strong> • FC ${act.resting_hr_bpm || 57} BPM • Sommeil ${act.sleep_score || 85}/100
                </div>
              </div>
            `;
          }
        } else if (devId === 'withings') {
          const w = (currentData.weights_history && currentData.weights_history.length > 0)
            ? currentData.weights_history[currentData.weights_history.length - 1]
            : null;
          if (w) {
            metricsSnippet = `
              <div class="p-2.5 rounded-xl bg-sky-950/20 border border-sky-500/30 text-[11px] text-slate-300 space-y-1">
                <span class="text-sky-400 font-semibold block flex items-center space-x-1">
                  <i data-lucide="check-circle" class="w-3 h-3 text-sky-400"></i>
                  <span>Dernière pesée reçue :</span>
                </span>
                <div class="text-white font-medium">
                  <strong>${w.weight_kg} kg</strong> ${w.body_fat_pct ? `• ${w.body_fat_pct}% MG` : ''} ${w.muscle_mass_kg ? `• ${w.muscle_mass_kg} kg Muscle` : ''}
                </div>
              </div>
            `;
          }
        }

        // Détermination fine du badge et statut de synchronisation
        const isWaitingFirstSync = (devId === 'health_connect' && (!lastSyncVal || d.sync_status === 'waiting_first_sync'));
        const syncBadgeHtml = isWaitingFirstSync
          ? `<span class="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1"><span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span><span>En attente du 1er envoi</span></span>`
          : `<span class="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1"><span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span><span>Synchronisé ✓</span></span>`;

        const syncStatusDesc = isWaitingFirstSync
          ? `<span class="text-amber-400 font-medium">En attente du 1er envoi depuis votre téléphone</span>`
          : `<span class="text-emerald-400 font-medium">Flux actif dans votre profil</span>`;

        const lastSyncLabel = lastSyncVal
          ? (typeof formatRelativeTime === 'function' && formatRelativeTime(lastSyncVal) ? formatRelativeTime(lastSyncVal) : lastSyncVal.slice(0, 16).replace('T', ' '))
          : (isWaitingFirstSync ? 'Aucune donnée reçue' : 'Enregistré');

        return `
          <div class="bg-[#0B0F17] hover:bg-[#111826] border border-[#1F2A3C] hover:border-brand-500/50 rounded-2xl p-4 flex flex-col justify-between space-y-4 transition-all group">
            <div class="flex items-start justify-between">
              <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-xl bg-brand-500/10 text-brand-400 border border-brand-500/20 flex items-center justify-center">
                  <i data-lucide="${d.device_type === 'ring' ? 'circle-dot' : (d.device_type === 'scale' ? 'scale' : 'smartphone')}" class="w-5 h-5"></i>
                </div>
                <div>
                  <h4 class="font-bold text-white text-sm">${d.name}</h4>
                  <span class="text-[10px] text-brand-400 font-medium">${devId === 'health_connect' ? 'Passerelle Android Santé Connect' : (devId === 'withings' ? 'Balance Wi-Fi & Impédancemètre' : d.device_type)}</span>
                </div>
              </div>
              ${syncBadgeHtml}
            </div>

            ${metricsSnippet}

            <div class="text-xs text-slate-300">
              <div class="flex justify-between py-1 border-b border-[#1F2A3C]/50">
                <span class="text-slate-400">Dernière synchronisation :</span>
                <span class="text-slate-200 font-medium">${lastSyncLabel}</span>
              </div>
              <div class="flex justify-between py-1">
                <span class="text-slate-400">Statut liaison :</span>
                ${syncStatusDesc}
              </div>
            </div>

            <div class="flex items-center space-x-2">
              <button type="button" onclick="openConnectWizardModal('${wizTarget}')" class="flex-1 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-all">
                <i data-lucide="settings" class="w-3.5 h-3.5"></i>
                <span>Configurer</span>
              </button>
              <button type="button" onclick="triggerDeviceSync('${devId}')" class="flex-1 py-2 rounded-xl bg-[#1F2A3C] hover:bg-[#2A374D] text-slate-200 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">
                <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-brand-400"></i>
                <span>Synchroniser</span>
              </button>
              <button type="button" onclick="disconnectDevice('${devId}')" title="Déconnecter et retirer du profil" class="p-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 transition-colors">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
              </button>
            </div>
          </div>
        `;
      }).join('');

      // Carte d'ajout pour connecter un autre objet
      const addCardHtml = `
        <div onclick="openConnectWizardModal()" class="border-2 border-dashed border-[#1F2A3C] hover:border-indigo-500/60 rounded-2xl p-6 flex flex-col items-center justify-center text-center space-y-2.5 cursor-pointer transition-colors group min-h-[180px]">
          <div class="w-11 h-11 rounded-xl bg-[#151D2A] group-hover:bg-indigo-600/20 text-slate-400 group-hover:text-indigo-400 border border-[#1F2A3C] group-hover:border-indigo-500/30 flex items-center justify-center transition-all">
            <i data-lucide="plus" class="w-5 h-5"></i>
          </div>
          <div>
            <h5 class="text-xs font-bold text-slate-200 group-hover:text-white transition-colors">Ajouter un autre appareil</h5>
            <p class="text-[10px] text-slate-500 mt-0.5">RingConn Gen 3, Google Santé Connect, Withings...</p>
          </div>
        </div>
      `;

      grid.innerHTML = cardsHtml + addCardHtml;
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    async function triggerDeviceSync(deviceId) {
      try {
        if (typeof showToast === 'function') showToast(`Synchronisation de ${deviceId} en cours...`, 'info');
        const res = await apiFetch(`/api/devices/${deviceId}/sync`, {
          method: 'POST'
        });
        if (res.ok) {
          const data = await res.json();
          if (typeof showToast === 'function') showToast(`Synchronisation de ${data.name || deviceId} réussie ! Données biométriques mises à jour.`, 'success');
          else alert(`Synchronisation de ${data.name || deviceId} réussie ! Données mises à jour.`);
          await loadDashboardData();
        } else {
          // Fallback legacy
          await apiFetch('/api/devices/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId })
          });
          if (typeof showToast === 'function') showToast(`Synchronisation de ${deviceId} effectuée.`, 'info');
          await loadDashboardData();
        }
      } catch (err) {
        if (typeof showToast === 'function') showToast(`Synchronisation déclenchée.`, 'info');
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
    // LOGIQUE MODAL PHOTO REPAS & CURSEUR
    // =====================================================================
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
            <span class="font-bold text-white text-xs">${item.name}</span>
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
        return `
          <div class="bg-[#0B0F17] border border-[#1F2A3C] hover:border-indigo-500/30 rounded-xl p-3 flex flex-col justify-between space-y-2 transition-all">
            <div class="space-y-1.5">
              <div class="flex items-start justify-between gap-1">
                <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border ${typeInfo.color}">
                  ${typeInfo.label}
                </span>
                <div class="flex items-center space-x-1">
                  ${m.is_favorite ? '<span class="text-xs text-amber-400">⭐</span>' : ''}
                  <button onclick="deleteSavedMeal(${m.id})" title="Supprimer ce plat" class="p-1 text-slate-500 hover:text-rose-400 rounded transition-colors">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                  </button>
                </div>
              </div>

              ${m.photo_url ? `
                <div class="rounded-lg overflow-hidden border border-[#1F2A3C] h-24 w-full">
                  <img src="${m.photo_url}" alt="${m.name}" class="w-full h-full object-cover">
                </div>
              ` : ''}

              <div>
                <h4 class="font-bold text-white text-xs leading-tight line-clamp-1">${m.name}</h4>
                <div class="text-[10px] text-slate-400 mt-0.5">${m.serving_size || '1 portion'} ${m.quantity_grams ? '(' + Math.round(m.quantity_grams) + 'g)' : ''}</div>
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
              <button onclick="logSavedMealDirectly(${m.id}, '${m.meal_type}')" class="w-full py-1.5 px-2 rounded-lg bg-brand-600/20 hover:bg-brand-600 text-brand-300 hover:text-white border border-brand-500/30 text-[11px] font-bold flex items-center justify-center space-x-1.5 transition-all active:scale-95">
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
        target_calories_intake: parseFloat(document.getElementById('prof-target-cals') && document.getElementById('prof-target-cals').value) || 2000.0,
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

    function openConnectWizardModal(deviceId) {
      try {
        // Fermer les autres modales ou menus déroulants pouvant se superposer
        const drop = document.getElementById('header-user-dropdown');
        if (drop) { drop.classList.add('hidden'); }

        ['modal-meal', 'modal-weight', 'modal-activity', 'modal-profile', 'modal-auth', 'modal-saved-meals', 'modal-create-saved-meal'].forEach(id => {
          const el = document.getElementById(id);
          if (el) { el.classList.add('hidden'); el.classList.remove('flex'); }
        });

        const targetDev = (typeof deviceId === 'string' && deviceId) ? deviceId : (currentSelectedWizardDevice || 'ringconn');
        selectWizardDevice(targetDev);
        const modal = document.getElementById('modal-connect-wizard');
        if (modal) {
          modal.classList.remove('hidden');
          modal.classList.add('flex');
        }
        if (window.lucide && lucide.createIcons) {
          try { lucide.createIcons(); } catch (e) {}
        }
      } catch (err) {
        console.error("Erreur openConnectWizardModal:", err);
      }
    }

    function closeConnectWizardModal() {
      const modal = document.getElementById('modal-connect-wizard');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function selectWizardDevice(deviceId) {
      currentSelectedWizardDevice = deviceId;
      document.querySelectorAll('.wizard-device-card').forEach(c => {
        c.classList.remove('border-2', 'border-brand-500', 'bg-brand-500/10');
        c.classList.add('border', 'border-[#1F2A3C]', 'bg-[#0B0F17]');
      });

      const selCard = document.getElementById(`wiz-opt-${deviceId}`);
      if (selCard) {
        selCard.classList.remove('border-[#1F2A3C]', 'bg-[#0B0F17]');
        selCard.classList.add('border-2', 'border-brand-500', 'bg-brand-500/10');
      }

      const container = document.getElementById('wizard-config-container');
      const actionText = document.getElementById('wizard-action-text');

      if (deviceId === 'ringconn') {
        actionText.innerText = "Connecter ma bague RingConn Gen 3";
        container.innerHTML = `
          <div class="space-y-2.5">
            <div class="flex items-center space-x-2 text-brand-400 font-bold text-xs">
              <i data-lucide="sparkles" class="w-4 h-4"></i>
              <span>Connexion Optimale : Bague RingConn Gen 3</span>
            </div>
            <p class="text-xs text-slate-300">
              Votre bague <strong>RingConn Gen 3</strong> mesure en temps réel le sommeil (durée, score réparateur), l'HRV nocturne en ms, la fréquence cardiaque et les calories actives.
            </p>
            <div class="bg-[#151D2A] p-2.5 rounded-lg border border-[#1F2A3C] text-[11px] space-y-2">
              <span class="text-slate-400 block font-semibold">Modes d'interconnexion au choix :</span>
              <div class="text-slate-200">
                <span class="text-brand-400 font-bold">1. Passerelle Google Health Connect (Android)</span> : Synchronisation automatique native.
              </div>
              <div class="text-slate-200">
                <span class="text-brand-400 font-bold">2. Webhook RingConn / MacroDroid</span> :
                <div class="mt-1 p-1.5 rounded bg-[#0B0F17] font-mono text-[10px] text-brand-400 flex items-center justify-between">
                  <span>POST /api/webhooks/ringconn</span>
                  <button type="button" onclick="navigator.clipboard.writeText(window.location.origin + '/api/webhooks/ringconn'); alert('URL Webhook copiée !');" class="text-slate-400 hover:text-white ml-2 text-[10px] underline">Copier</button>
                </div>
              </div>
              <div class="text-slate-200">
                <span class="text-brand-400 font-bold">3. OpenAPI Cloud Directe</span> : Token d'accès OpenAPI RingConn.
              </div>
            </div>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Clé API / Token RingConn (Facultatif si synchronisé via Google Health) :</label>
              <input type="text" id="wiz-input-ringconn-key" placeholder="rc_live_... ou laisser vide pour passerelle Google Health" class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500">
            </div>
            <div class="pt-2">
              <button type="button" onclick="testRingConnIngestion()" class="w-full py-2 rounded-lg bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/40 text-brand-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">
                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                <span>Tester la réception / Synchroniser métriques RingConn</span>
              </button>
            </div>
          </div>
        `;
      } else if (deviceId === 'health_connect') {
        actionText.innerText = "Activer la passerelle Google Health Connect";
        container.innerHTML = `
          <div class="space-y-3.5">
            <div class="flex items-center space-x-2 text-sky-400 font-bold text-xs">
              <i data-lucide="smartphone" class="w-4 h-4"></i>
              <span>Passerelle Universelle Android Google Health Connect</span>
            </div>
            <p class="text-xs text-slate-300">
              Centralise toutes vos applications de santé sur smartphone (RingConn, balances connectées, trackers) et les pousse vers le webhook VitalTrack.
            </p>

            <!-- Téléchargements directs : APK & Profil MacroDroid -->
            <div class="p-3 rounded-xl bg-gradient-to-r from-indigo-950/40 to-[#151D2A] border border-indigo-500/30 space-y-2">
              <span class="text-[11px] font-bold text-indigo-300 flex items-center space-x-1.5">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span>Applications & Profils Android à installer :</span>
              </span>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-0.5">
                <a href="/static/downloads/vitaltrack-health-bridge.apk" download="vitaltrack-health-bridge.apk" class="py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center justify-center space-x-2 shadow-md shadow-indigo-600/25 transition-transform active:scale-95 text-center cursor-pointer">
                  <i data-lucide="smartphone" class="w-4 h-4"></i>
                  <span>Télécharger l'APK Android</span>
                </a>
                <a href="/static/downloads/macrodroid_health_connect_profile.json" download="macrodroid_health_connect_profile.json" class="py-2 px-3 rounded-xl bg-[#1F2A3C] hover:bg-[#2A374D] border border-slate-600 text-slate-200 font-semibold text-xs flex items-center justify-center space-x-2 transition-colors text-center cursor-pointer">
                  <i data-lucide="file-json" class="w-4 h-4 text-amber-400"></i>
                  <span>Profil MacroDroid (.json)</span>
                </a>
              </div>
            </div>

            <!-- Configuration Webhook & Jeton Secret -->
            <div class="p-3 rounded-xl bg-[#151D2A] border border-[#1F2A3C] text-[11px] text-slate-300 space-y-2.5">
              <!-- Endpoint Webhook -->
              <div class="space-y-1">
                <div class="flex justify-between items-center text-slate-400">
                  <span class="font-medium">URL du Webhook :</span>
                  <button type="button" onclick="navigator.clipboard.writeText(window.location.origin + '/api/webhooks/health-connect'); if (typeof showToast === 'function') showToast('URL Webhook copiée !', 'success'); else alert('URL Webhook copiée !');" class="text-brand-400 hover:text-brand-300 flex items-center space-x-1 text-[11px] font-semibold underline cursor-pointer">
                    <i data-lucide="copy" class="w-3 h-3"></i>
                    <span>Copier l'URL</span>
                  </button>
                </div>
                <div class="p-2 rounded-lg bg-[#0B0F17] font-mono text-[10px] text-brand-400 break-all border border-[#1F2A3C]/70 select-all">
                  ${window.location.origin}/api/webhooks/health-connect
                </div>
              </div>

              <!-- Jeton Secret X-Webhook-Token -->
              <div class="space-y-1 pt-1.5 border-t border-[#1F2A3C]/60">
                <div class="flex justify-between items-center text-slate-400">
                  <span class="font-medium">Jeton Secret (<code>X-Webhook-Token</code>) :</span>
                  <div class="flex items-center space-x-2">
                    <button type="button" onclick="generateDeviceToken('health_connect')" class="text-indigo-400 hover:text-indigo-300 font-semibold text-[11px] underline cursor-pointer" title="Régénérer un nouveau jeton d'appareil">
                      Régénérer
                    </button>
                    <button type="button" onclick="toggleTokenVisibility('health_connect')" id="wiz-token-toggle-health_connect" class="text-slate-400 hover:text-white flex items-center space-x-1 text-[11px] cursor-pointer">
                      <i data-lucide="eye" id="wiz-token-eye-icon-health_connect" class="w-3 h-3"></i>
                      <span id="wiz-token-eye-text-health_connect">Révéler</span>
                    </button>
                    <button type="button" onclick="copyTokenToClipboard('health_connect')" class="text-brand-400 hover:text-brand-300 flex items-center space-x-1 text-[11px] font-semibold underline cursor-pointer">
                      <i data-lucide="copy" class="w-3 h-3"></i>
                      <span>Copier mon Token</span>
                    </button>
                  </div>
                </div>
                <div class="p-2 rounded-lg bg-[#0B0F17] font-mono text-[10px] text-emerald-400 break-all border border-[#1F2A3C]/70 flex items-center justify-between">
                  <span id="wiz-token-display-val-health_connect" class="tracking-wider">Chargement du jeton...</span>
                </div>
              </div>

              <!-- Statut réel de réception -->
              <div class="flex justify-between items-center pt-1.5 border-t border-[#1F2A3C]/60 text-xs">
                <span class="text-slate-400">Statut de synchronisation :</span>
                <span id="wiz-sync-badge-health_connect" class="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                  <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                  <span>En attente du 1er envoi depuis votre téléphone</span>
                </span>
              </div>
            </div>

            <!-- Guide Xiaomi HyperOS / MIUI -->
            <div class="p-2.5 rounded-lg bg-[#0B0F17] border border-amber-500/30 text-[11px] space-y-1.5">
              <div class="flex items-center space-x-1.5 text-amber-400 font-bold">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i>
                <span>Réglages Requis Xiaomi HyperOS / MIUI</span>
              </div>
              <ul class="text-[10px] text-slate-300 list-disc list-inside space-y-0.5">
                <li><strong>Démarrage auto</strong> : <em>Paramètres > Applications > Gérer les applications > VitalTrack Bridge (ou MacroDroid) > Démarrage automatique</em> : <strong>Activé</strong>.</li>
                <li><strong>Batterie</strong> : <em>Économiseur de batterie MIUI</em> : régler sur <strong>« Pas de restrictions »</strong>.</li>
                <li><strong>Santé Connect</strong> : <em>Paramètres > Sécurité & Confidentialité > Health Connect > Applications autorisées</em> : accorder l'accès en lecture.</li>
              </ul>
            </div>

            <div class="pt-1">
              <button type="button" onclick="testHealthConnectIngestion()" class="w-full py-2.5 rounded-xl bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 text-sky-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors cursor-pointer shadow-sm">
                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                <span>Envoyer test webhook</span>
              </button>
            </div>
          </div>
        `;
        fetchOrInitDeviceToken('health_connect');
      } else if (deviceId === 'withings') {
        actionText.innerText = "Connecter ma Balance Withings";
        container.innerHTML = `
          <div class="space-y-2.5">
            <div class="flex items-center space-x-2 text-brand-400 font-bold text-xs">
              <i data-lucide="scale" class="w-4 h-4"></i>
              <span>Balance Withings Body Smart / Comp (Wi-Fi Direct)</span>
            </div>
            <p class="text-xs text-slate-300">
              Synchronisation directe Cloud-to-Cloud via OAuth 2.0 officiel de Withings.
            </p>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Identifiant Compte Withings (Email) :</label>
              <input type="email" id="wiz-input-withings-email" placeholder="sebastienlamoliate@gmail.com" value="sebastienlamoliate@gmail.com" class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500">
            </div>
            <div class="pt-1">
              <button type="button" onclick="testScaleIngestion('withings')" class="w-full py-2 rounded-lg bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/40 text-brand-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">
                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                <span>Tester la réception d'une pesée Withings</span>
              </button>
            </div>
          </div>
        `;
      } else {
        actionText.innerText = "Connecter Oura Ring Gen 3";
        container.innerHTML = `
          <div class="space-y-2.5">
            <div class="flex items-center space-x-2 text-indigo-400 font-bold text-xs">
              <i data-lucide="circle-dot" class="w-4 h-4"></i>
              <span>Oura Ring Gen 3 Cloud API v2</span>
            </div>
            <p class="text-xs text-slate-300">
              Interconnexion par Bearer Token personnel via l'API v2 d'Oura.
            </p>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Personal Access Token Oura :</label>
              <input type="password" id="wiz-input-oura-token" placeholder="Bearer token Oura..." class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500">
            </div>
          </div>
        `;
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    async function testRingConnIngestion() {
      const todayStr = new Date().toISOString().split('T')[0];
      const payload = {
        date: todayStr,
        source: "ringconn_gen3",
        steps: 11450,
        active_calories_kcal: 490.0,
        resting_hr_bpm: 56,
        hrv_ms: 62.0,
        sleep_score: 88,
        workout_minutes: 40,
        workout_type: "Marche & Cardio (RingConn Gen 3)"
      };
      try {
        const res = await fetch('/api/webhooks/ringconn', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          alert("✓ Succès ! Métriques RingConn Gen 3 reçues (11 450 pas, HRV 62 ms, Score Sommeil 88).");
          loadDashboardData();
        }
      } catch (e) {
        alert("Erreur lors du test webhook RingConn");
      }
    }

    let currentDeviceTokens = {};
    let deviceTokensRevealed = {};

    async function fetchOrInitDeviceToken(deviceId) {
      const displayEl = document.getElementById(`wiz-token-display-val-${deviceId}`);
      const badgeEl = document.getElementById(`wiz-sync-badge-${deviceId}`);

      // Mettre à jour le badge selon le statut réel de l'appareil
      if (currentData && currentData.devices) {
        const d = currentData.devices.find(dev => (dev.id || dev.device_id) === deviceId);
        if (d && badgeEl) {
          const hasSync = Boolean(d.last_sync_at || d.last_sync);
          if (hasSync) {
            const relTime = formatRelativeTime(d.last_sync_at || d.last_sync) || 'Récemment';
            badgeEl.className = "text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1";
            badgeEl.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span><span>Synchronisé (${relTime})</span>`;
          } else {
            badgeEl.className = "text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1";
            badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span><span>En attente du 1er envoi depuis votre téléphone</span>';
          }
        }
      }

      try {
        const res = await apiFetch(`/api/devices/${deviceId}/token`, { method: 'GET' });
        if (res && res.ok) {
          const data = await res.json();
          if (data && data.token) {
            currentDeviceTokens[deviceId] = data.token;
            updateTokenDisplay(deviceId);
            return data.token;
          }
        }
      } catch (e) {
        // En cas d'erreur de récupération
      }

      // Si aucun jeton n'existe encore pour l'utilisateur, on le génère automatiquement
      try {
        const genRes = await apiFetch(`/api/devices/${deviceId}/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: deviceId === 'health_connect' ? 'Google Health Connect' : deviceId })
        });
        if (genRes && genRes.ok) {
          const data = await genRes.json();
          if (data && data.token) {
            currentDeviceTokens[deviceId] = data.token;
            updateTokenDisplay(deviceId);
            return data.token;
          }
        } else {
          console.error("Échec création token automatique:", genRes ? genRes.status : "inconnu");
          if (displayEl) displayEl.innerText = "Non configuré";
        }
      } catch (err) {
        console.error("Erreur récupération/génération token:", err);
        if (displayEl) displayEl.innerText = "Non configuré";
      }
    }

    function updateTokenDisplay(deviceId) {
      const displayEl = document.getElementById(`wiz-token-display-val-${deviceId}`);
      const eyeIcon = document.getElementById(`wiz-token-eye-icon-${deviceId}`);
      const eyeText = document.getElementById(`wiz-token-eye-text-${deviceId}`);
      if (!displayEl) return;

      const token = currentDeviceTokens[deviceId] || "";
      const isRevealed = Boolean(deviceTokensRevealed[deviceId]);

      if (!token) {
        displayEl.innerText = "Aucun jeton actif";
        return;
      }

      if (isRevealed) {
        displayEl.innerText = token;
        if (eyeText) eyeText.innerText = "Masquer";
        if (eyeIcon) eyeIcon.setAttribute('data-lucide', 'eye-off');
      } else {
        const prefix = token.slice(0, 10);
        displayEl.innerText = prefix + "••••••••••••••••••••••••";
        if (eyeText) eyeText.innerText = "Révéler";
        if (eyeIcon) eyeIcon.setAttribute('data-lucide', 'eye');
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    function toggleTokenVisibility(deviceId) {
      deviceTokensRevealed[deviceId] = !deviceTokensRevealed[deviceId];
      updateTokenDisplay(deviceId);
    }

    async function copyTokenToClipboard(deviceId) {
      let token = currentDeviceTokens[deviceId];
      if (!token) {
        token = await fetchOrInitDeviceToken(deviceId);
      }
      if (token) {
        navigator.clipboard.writeText(token);
        if (typeof showToast === 'function') showToast("✓ Jeton secret copié dans le presse-papier !", "success");
        else alert("✓ Jeton secret copié dans le presse-papier !");
      } else {
        if (typeof showToast === 'function') showToast("Jeton introuvable.", "error");
      }
    }

    async function generateDeviceToken(deviceId) {
      try {
        if (typeof showToast === 'function') showToast("Génération d'un nouveau jeton...", "info");
        const res = await apiFetch(`/api/devices/${deviceId}/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: deviceId === 'health_connect' ? 'Google Health Connect' : 'Smart Sensor' })
        });
        if (res && res.ok) {
          const data = await res.json();
          if (data && data.token) {
            currentDeviceTokens[deviceId] = data.token;
            deviceTokensRevealed[deviceId] = true; // Révélé dès la génération
            updateTokenDisplay(deviceId);
            navigator.clipboard.writeText(data.token);
            if (typeof showToast === 'function') {
              showToast("✓ Nouveau jeton généré et copié dans le presse-papier !", "success");
            } else {
              alert(`✓ Jeton généré et copié dans le presse-papier :\n${data.token}`);
            }
            await loadDashboardData();
          }
        } else {
          const errData = await res.json().catch(() => ({}));
          console.error("Erreur génération token HTTP status:", res.status, errData);
          if (typeof showToast === 'function') showToast("Erreur génération jeton: " + (errData.detail || res.statusText), "error");
          else alert("Erreur génération jeton: " + (errData.detail || res.statusText));
        }
      } catch (err) {
        console.error("Erreur génération token:", err);
        if (typeof showToast === 'function') showToast("Erreur lors de la génération du jeton.", "error");
        else alert("Erreur lors de la génération du jeton.");
      }
    }

    async function testHealthConnectIngestion() {
      const todayStr = new Date().toISOString().split('T')[0];
      let token = currentDeviceTokens['health_connect'];
      if (!token) {
        token = await fetchOrInitDeviceToken('health_connect');
      }

      const headers = { 'Content-Type': 'application/json' };
      if (token) {
        headers['X-Webhook-Token'] = token;
      }

      const payload = {
        date: todayStr,
        source: "health_connect",
        steps: 12100,
        active_calories_kcal: 530.0,
        resting_hr_bpm: 57,
        hrv_ms: 59.0,
        sleep_score: 85,
        token: token || undefined
      };

      try {
        if (typeof showToast === 'function') showToast("Envoi du test webhook avec X-Webhook-Token...", "info");
        const res = await fetch('/api/webhooks/health-connect', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          if (typeof showToast === 'function') {
            showToast("✓ Succès ! Payload ingéré et authentifié avec votre X-Webhook-Token.", "success");
          } else {
            alert("✓ Succès ! Passerelle Google Health Connect testée et validée avec votre X-Webhook-Token.");
          }
          await loadDashboardData();
          // Mettre à jour l'affichage du wizard
          await fetchOrInitDeviceToken('health_connect');
        } else {
          const errData = await res.json().catch(() => ({}));
          const msg = "Échec du test webhook : " + (errData.detail || res.statusText);
          if (typeof showToast === 'function') showToast(msg, "error");
          else alert(msg);
        }
      } catch (e) {
        if (typeof showToast === 'function') showToast("Erreur de communication lors du test webhook Google Health", "error");
        else alert("Erreur lors du test webhook Google Health");
      }
    }

    async function testScaleIngestion(sourceName) {
      const todayStr = new Date().toISOString().split('T')[0];
      const payload = {
        date: todayStr,
        source: sourceName,
        weight_kg: 79.4,
        body_fat_pct: 19.9,
        muscle_mass_kg: 38.3,
        water_pct: 56.8
      };
      try {
        const res = await fetch('/api/webhook/health', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          alert(`✓ Succès ! Pesée reçue via connecteur ${sourceName} : 79.4 kg, 19.9% masse grasse.`);
          loadDashboardData();
        }
      } catch (e) {
        alert("Erreur test balance");
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

    async function submitDeviceConnection() {
      const devId = currentSelectedWizardDevice;
      let apiKey = null;
      let email = null;
      let authType = 'connected';

      if (devId === 'ringconn') {
        const inp = document.getElementById('wiz-input-ringconn-key');
        apiKey = inp ? inp.value : null;
        authType = apiKey ? 'ringconn_openapi' : 'google_health_connect';
      } else if (devId === 'withings') {
        const inp = document.getElementById('wiz-input-withings-email');
        email = inp ? inp.value : 'sebastienlamoliate@gmail.com';
        authType = 'withings_oauth';
      } else if (devId === 'health_connect') {
        authType = 'google_health_connect';
      } else if (devId === 'oura') {
        const inp = document.getElementById('wiz-input-oura-token');
        apiKey = inp ? inp.value : null;
        authType = 'oura_bearer_token';
      }

      try {
        const res = await apiFetch('/api/devices/connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            device_id: devId,
            connected: true,
            auth_type: authType,
            api_key: apiKey,
            account_email: email
          })
        });

        if (res.ok) {
          closeConnectWizardModal();
          await loadDashboardData();
          switchTab('devices');
          showToast(`Félicitations ! L'appareil '${devId === 'ringconn' ? 'RingConn Gen 3' : (devId === 'health_connect' ? 'Google Health Connect' : devId)}' a été connecté avec succès à votre profil VitalTrack !`, 'success');
        }
      } catch (e) {
        closeConnectWizardModal();
      }
    }

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
        <div class="flex-1 leading-snug">${message}</div>
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
        const email = session.email || '';
        const name = session.name || (email.split('@')[0]) || 'Sébastien';
        const picture = session.picture || '';
        const initials = name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'VT';
        const isGoogle = (session.auth_method && session.auth_method.includes('google'));

        // Header : Avatar utilisateur connecté avec menu déroulant
        if (headerContainer) {
          headerContainer.innerHTML = `
            <button type="button" onclick="toggleUserDropdown()" id="btn-header-avatar" class="flex items-center space-x-1.5 p-1 rounded-xl bg-[#151D2A] hover:bg-[#1F2A3C] border border-brand-500/40 text-white text-xs font-medium transition-all active:scale-95 shadow-sm" title="${name} (${email})">
              <div class="w-7 h-7 rounded-lg overflow-hidden flex items-center justify-center bg-gradient-to-tr from-brand-600 to-electric-cyan text-white font-bold text-xs shrink-0">
                ${picture ? `<img src="${picture}" class="w-full h-full object-cover" alt="Avatar">` : `<span>${initials}</span>`}
              </div>
              <span class="hidden sm:inline font-semibold px-1 text-brand-300">${name.split(' ')[0]}</span>
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
        if (profEmail) profEmail.innerText = `${email} (${isGoogle ? 'Google' : 'Email'})`;
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
        if (uName) uName.innerText = name;
        if (uEmail) uEmail.innerText = email;
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
  

function renderGoalsView() {
  if (typeof activeGoalProfileId !== 'undefined') {
    selectGoalProfile(activeGoalProfileId);
  }
}
window.renderGoalsView = renderGoalsView;
