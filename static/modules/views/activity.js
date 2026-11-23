// static/modules/views/activity.js - Vue Activité & Santé (sommeil, HRV, séances, tendances)

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


window.renderActivityView = renderActivityView;
