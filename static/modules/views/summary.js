// static/modules/views/summary.js - Vue Aujourd'hui (anneaux d'énergie, jauges macros, résumé)

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
        const targetCals = s.target_calories_intake || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 0;
        const inPct = targetCals > 0 ? Math.min(100, Math.round(((s.calories_intake_kcal || 0) / targetCals) * 100)) : 0;
        barCalsIn.style.width = `${inPct}%`;
      }



      const elCalsOut = document.getElementById('val-cals-out');

      if (elCalsOut) elCalsOut.innerHTML = `${Math.round(s.calories_burned_kcal || 0)} <span class="text-xs font-normal text-slate-400">kcal</span>`;



      // Mise à jour des Anneaux d'objectifs (Palier 3)

      renderSummaryRings();

      const elBmr = document.getElementById('val-bmr');
      if (elBmr) elBmr.innerText = `${Math.round(s.bmr_kcal || (CONFIG.defaults && CONFIG.defaults.bmr_kcal) || 0)} kcal`;



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



      const kcalPerKg = CONFIG.kcal_per_kg || 0;
      const projChange = s.weekly_projected_weight_change_kg !== undefined ? s.weekly_projected_weight_change_kg : (kcalPerKg > 0 ? ((net * 7) / kcalPerKg).toFixed(2) : null);
      const elProj = document.getElementById('val-projected-loss');
      if (elProj) elProj.innerText = projChange !== null && projChange !== undefined ? `Impact 7j: ~${projChange} kg` : 'Impact 7j: -- kg';



      // Donut Macros & progression restante
      const m = s.macros || {};
      const targets = s.targets || {};
      const profile = (currentData && currentData.profile) || {};
      const targetCals = s.target_calories_intake || targets.calories || (CONFIG.defaults && CONFIG.defaults.target_calories_intake) || 2000;
      const intakeCals = Math.round(s.calories_intake_kcal || 0);

      // Calcul cibles de macronutriments (fallback propre si targets non renseigné)
      const protTarget = targets.protein_g || profile.daily_protein_target_g || (profile.protein_target_per_kg && (profile.current_weight_kg || profile.target_weight_kg) ? Math.round(profile.protein_target_per_kg * (profile.current_weight_kg || profile.target_weight_kg)) : Math.round((targetCals * 0.25) / 4));
      const carbsTarget = targets.carbs_g || profile.daily_carbs_target_g || Math.round((targetCals * 0.45) / 4);
      const fatTarget = targets.fat_g || profile.daily_fat_target_g || Math.round((targetCals * 0.30) / 9);

      // 1. Centre du donut
      const elRatio = document.getElementById('donut-cals-ratio');
      if (elRatio) elRatio.innerText = `${intakeCals.toLocaleString('fr-FR')} / ${Math.round(targetCals).toLocaleString('fr-FR')} kcal`;

      const elDonutRemaining = document.getElementById('donut-cals-remaining');
      if (elDonutRemaining) {
        const calDiff = Math.round(targetCals - intakeCals);
        if (calDiff >= 0) {
          elDonutRemaining.innerText = `Reste : ${calDiff.toLocaleString('fr-FR')} kcal`;
          elDonutRemaining.className = 'text-[11px] font-bold text-emerald-400 leading-tight';
        } else {
          elDonutRemaining.innerText = `+${Math.abs(calDiff).toLocaleString('fr-FR')} kcal`;
          elDonutRemaining.className = 'text-[11px] font-bold text-amber-400 leading-tight';
        }
      }

      // 2. Macronutriments consommés, cibles, reste et barres de progression
      const protConsumed = Math.round(Number(m.protein_g) || 0);
      const carbsConsumed = Math.round(Number(m.carbs_g) || 0);
      const fatConsumed = Math.round(Number(m.fat_g) || 0);

      const updateMacroRow = (txtId, remId, barId, consumed, pct, target) => {
        const elTxt = document.getElementById(txtId);
        if (elTxt) elTxt.innerText = `${consumed}g (${pct || 0}%) / ${Math.round(target)}g`;

        const elRem = document.getElementById(remId);
        if (elRem) {
          const rem = Math.round(target - consumed);
          if (rem >= 0) {
            elRem.innerText = `Reste : ${rem} g`;
            elRem.className = 'text-[11px] font-semibold text-emerald-400';
          } else {
            elRem.innerText = `+${Math.abs(rem)} g`;
            elRem.className = 'text-[11px] font-semibold text-amber-400';
          }
        }

        const elBar = document.getElementById(barId);
        if (elBar) {
          const progress = target > 0 ? Math.min(100, Math.round((consumed / target) * 100)) : 0;
          elBar.style.width = `${progress}%`;
        }
      };

      updateMacroRow('macro-prot-txt', 'macro-prot-remaining', 'macro-prot-bar', protConsumed, m.protein_pct, protTarget);
      updateMacroRow('macro-carbs-txt', 'macro-carbs-remaining', 'macro-carbs-bar', carbsConsumed, m.carbs_pct, carbsTarget);
      updateMacroRow('macro-fat-txt', 'macro-fat-remaining', 'macro-fat-bar', fatConsumed, m.fat_pct, fatTarget);

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

      const kcalPerKg = CONFIG.kcal_per_kg || 0;
      s.weekly_projected_weight_change_kg = kcalPerKg > 0 ? Math.round(((net * 7.0) / kcalPerKg) * 1000) / 1000 : null;



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

      const targetWeight = currentData.summary && currentData.summary.target_weight_kg

        ? currentData.summary.target_weight_kg

        : 77.0;



      // Calculer l'étendue Y pour inclure à la fois les pesées et la cible

      const allWeights = [...weights, targetWeight];

      const maxWeight = Math.max(...allWeights) * 1.1; // 10% de marge au-dessus

      const minWeight = Math.min(...allWeights) * 0.9; // 10% de marge en-dessous

      // S'assurer que les bornes sont raisonnables

      const safeMin = Math.max(20, minWeight);

      const safeMax = Math.min(300, maxWeight);



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

            },

            {

              label: 'Objectif Cible',

              data: labels.map(() => targetWeight),

              borderColor: '#f59e0b',

              borderDash: [5, 5],

              borderWidth: 2,

              pointRadius: 0,

              fill: false,

              yAxisID: 'yWeight'

            }

          ]

        },

        options: {

          responsive: true,

          maintainAspectRatio: false,

          interaction: { mode: 'index', intersect: false },

          scales: {

            x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', maxTicksLimit: 8 } },

            y: {

              grid: { color: 'rgba(255,255,255,0.05)' },

              ticks: { color: '#64748b' },

              suggestedMin: safeMin * 0.9,

              suggestedMax: safeMax * 1.1

            },

            'yWeight': {

              type: 'linear',

              position: 'right',

              grid: { color: 'rgba(255,255,255,0.05)' },

              ticks: { color: '#f59e0b' },

              suggestedMin: safeMin * 0.9,

              suggestedMax: safeMax * 1.1,

              // Afficher la ligne de cible avec un style distinct

              borderDash: [5, 5]

            }

          },

          plugins: {

            legend: { position: 'top', labels: { color: '#cbd5e1', boxWidth: 12 } }

          }

        }

      });

    }



    // 2. Rendu Vue Poids & Composition


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

        calsCur = Math.max(0, (s.calories_burned_kcal || 0) - (s.bmr_kcal || 0));

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




window.renderSummaryView = renderSummaryView;
window.renderSummaryRings = renderSummaryRings;
