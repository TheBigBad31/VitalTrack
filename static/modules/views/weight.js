// static/modules/views/weight.js - Vue Corps & Poids (impédancemétrie, courbe poids/tendance)

    function renderWeightView() {

      const s = currentData.summary || {};

      document.getElementById('val-body-fat').innerHTML = `${s.body_fat_pct || '--'} <span class="text-xs font-normal text-slate-400">%</span>`;

      document.getElementById('val-muscle-mass').innerHTML = `${s.muscle_mass_kg || '--'} <span class="text-xs font-normal text-slate-400">kg</span>`;

      document.getElementById('val-water-pct').innerHTML = `${s.water_pct || '--'} <span class="text-xs font-normal text-slate-400">%</span>`;

      document.getElementById('val-bmi').innerText = s.bmi || '--';



      // Graphique détaillé (pas journalier complet, pills toggle & mode OHLC)
      renderWeightDetailChart();



      // Tableau des pesées

      const tbody = document.getElementById('table-weights-body');

      if (tbody) {

        const history = [...(currentData.weights_history || [])].reverse();

        const countBadge = document.getElementById('weights-table-count');
        if (countBadge) {
          countBadge.textContent = `${history.length} pesée${history.length > 1 ? 's' : ''}`;
        }

        tbody.innerHTML = history.map(w => `

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



    let weightChartMode = 'line'; // 'line' | 'ohlc'
    const weightChartSeriesMeta = [
      { key: 'weight', label: 'Pesée Réelle (kg)', color: '#94a3b8' },
      { key: 'trend', label: 'Tendance Lissée 7j', color: '#7C3AED' },
      { key: 'muscle', label: 'Masse Musculaire (kg)', color: '#ef4444' },
      { key: 'fat', label: 'Masse Grasse %', color: '#eab308' },
      { key: 'target', label: 'Objectif Cible', color: '#f59e0b' }
    ];
    let weightChartVisibility = [true, true, false, false, true];

    function buildDailyWeightSeries(history, targetWeight) {
      if (!history || history.length === 0) {
        return { labels: [], weights: [], trends: [], muscle: [], fat: [], targets: [], ohlc: [] };
      }

      const byDate = new Map();
      const sorted = [...history].sort((a, b) => String(a.date).localeCompare(String(b.date)));
      for (const item of sorted) {
        const d = String(item.date).slice(0, 10);
        if (!byDate.has(d)) byDate.set(d, []);
        byDate.get(d).push(item);
      }

      const minDate = new Date(sorted[0].date.slice(0, 10) + 'T00:00:00Z');
      const maxDate = new Date(sorted[sorted.length - 1].date.slice(0, 10) + 'T00:00:00Z');

      const labels = [];
      const weights = [];
      const trends = [];
      const muscle = [];
      const fat = [];
      const targets = [];
      const ohlc = [];

      let prevClose = null;
      for (let dt = new Date(minDate); dt <= maxDate; dt.setUTCDate(dt.getUTCDate() + 1)) {
        const iso = dt.toISOString().slice(0, 10);
        labels.push(iso);
        targets.push(targetWeight);

        const entries = byDate.get(iso);
        if (!entries || entries.length === 0) {
          weights.push(null);
          trends.push(null);
          muscle.push(null);
          fat.push(null);
          ohlc.push(null);
          continue;
        }

        const last = entries[entries.length - 1];
        const dayWeights = entries.map(e => Number(e.weight_kg)).filter(v => !Number.isNaN(v));
        const wLast = dayWeights.length ? dayWeights[dayWeights.length - 1] : null;

        weights.push(wLast);
        trends.push(last.trend_7d_kg != null ? Number(last.trend_7d_kg) : null);
        muscle.push(last.muscle_mass_kg != null ? Number(last.muscle_mass_kg) : null);
        fat.push(last.body_fat_pct != null ? Number(last.body_fat_pct) : null);

        if (dayWeights.length > 0) {
          const open = prevClose !== null ? prevClose : dayWeights[0];
          const close = wLast;
          const high = Math.max(open, ...dayWeights);
          const low = Math.min(open, ...dayWeights);
          ohlc.push({ o: open, h: high, l: low, c: close });
          prevClose = close;
        } else {
          ohlc.push(null);
        }
      }

      return { labels, weights, trends, muscle, fat, targets, ohlc };
    }

    function renderWeightChartPills() {
      const container = document.getElementById('weight-chart-pills');
      if (!container) return;

      if (weightChartMode === 'ohlc') {
        container.innerHTML = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>Hausse (C ≥ O)
          </span>
          <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-rose-500/30 bg-rose-500/10 text-rose-300">
            <span class="w-2 h-2 rounded-full bg-rose-400"></span>Baisse (C &lt; O)
          </span>
        `;
        return;
      }

      container.innerHTML = weightChartSeriesMeta.map((s, idx) => {
        const active = weightChartVisibility[idx];
        const style = active
          ? `border-color: ${s.color}66; background-color: ${s.color}1a; color: #f8fafc;`
          : `border-color: #1F2A3C; background-color: #0B0F17; color: #64748b;`;
        const dotStyle = active ? `background-color: ${s.color};` : `background-color: #475569;`;
        return `
          <button type="button" onclick="toggleWeightDataset(${idx})" aria-pressed="${active}"
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors hover:border-slate-500"
            style="${style}">
            <span class="w-2 h-2 rounded-full shrink-0" style="${dotStyle}"></span>
            <span>${s.label}</span>
          </button>
        `;
      }).join('');
    }

    function toggleWeightDataset(idx) {
      weightChartVisibility[idx] = !weightChartVisibility[idx];
      renderWeightChartPills();
      if (chartWeightDetail && weightChartMode === 'line') {
        chartWeightDetail.setDatasetVisibility(idx, weightChartVisibility[idx]);
        chartWeightDetail.update();
      }
    }

    function applyWeightChartPreset(preset) {
      if (weightChartMode !== 'line') {
        setWeightChartMode('line');
      }
      if (preset === 'essentiel') {
        weightChartVisibility = [true, true, false, false, true];
      } else if (preset === 'composition') {
        weightChartVisibility = [true, false, true, true, false];
      } else if (preset === 'tout') {
        weightChartVisibility = [true, true, true, true, true];
      }
      renderWeightChartPills();
      if (chartWeightDetail) {
        weightChartVisibility.forEach((vis, idx) => chartWeightDetail.setDatasetVisibility(idx, vis));
        chartWeightDetail.update();
      }
    }

    function setWeightChartMode(mode) {
      weightChartMode = mode === 'ohlc' ? 'ohlc' : 'line';
      const btnLine = document.getElementById('weight-chart-mode-line');
      const btnOhlc = document.getElementById('weight-chart-mode-ohlc');
      if (btnLine && btnOhlc) {
        if (weightChartMode === 'line') {
          btnLine.className = 'px-2.5 py-1 rounded-md text-xs font-semibold transition-colors bg-brand-600 text-white';
          btnOhlc.className = 'px-2.5 py-1 rounded-md text-xs font-semibold transition-colors text-slate-400 hover:text-white';
        } else {
          btnOhlc.className = 'px-2.5 py-1 rounded-md text-xs font-semibold transition-colors bg-brand-600 text-white';
          btnLine.className = 'px-2.5 py-1 rounded-md text-xs font-semibold transition-colors text-slate-400 hover:text-white';
        }
      }
      renderWeightDetailChart();
    }

    const candlestickWickPlugin = {
      id: 'candlestickWickPlugin',
      afterDatasetsDraw(chart) {
        const ohlcData = chart.config._ohlcData;
        if (!ohlcData) return;
        const meta = chart.getDatasetMeta(0);
        if (!meta || !meta.data) return;
        const { ctx, scales: { y } } = chart;
        ctx.save();
        meta.data.forEach((bar, i) => {
          const d = ohlcData[i];
          if (!d) return;
          const x = bar.x;
          const yHigh = y.getPixelForValue(d.h);
          const yLow = y.getPixelForValue(d.l);
          ctx.strokeStyle = d.c >= d.o ? '#10b981' : '#ef4444';
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(x, yHigh);
          ctx.lineTo(x, yLow);
          ctx.stroke();
        });
        ctx.restore();
      }
    };

    function renderWeightDetailChart() {
      const ctx = document.getElementById('chart-weight-detail');
      if (!ctx) return;

      if (chartWeightDetail) chartWeightDetail.destroy();
      const s = (currentData && currentData.summary) || {};
      const targetWeight = s.target_weight_kg || 77.0;
      const series = buildDailyWeightSeries((currentData && currentData.weights_history) || [], targetWeight);

      renderWeightChartPills();

      if (weightChartMode === 'ohlc') {
        const barData = series.ohlc.map(d => {
          if (!d) return null;
          if (d.o === d.c) return [d.o - 0.03, d.c + 0.03];
          return [Math.min(d.o, d.c), Math.max(d.o, d.c)];
        });
        const barColors = series.ohlc.map(d => (!d ? 'transparent' : d.c >= d.o ? '#10b981' : '#ef4444'));

        chartWeightDetail = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: series.labels,
            datasets: [
              {
                label: 'Poids OHLC (kg)',
                data: barData,
                backgroundColor: barColors,
                borderColor: barColors,
                borderWidth: 1,
                borderRadius: 2,
                barPercentage: 0.6,
                categoryPercentage: 0.85
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
              y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } }
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label(context) {
                    const d = series.ohlc[context.dataIndex];
                    if (!d) return 'Aucune pesée';
                    const diff = (d.c - d.o).toFixed(2);
                    const sign = d.c >= d.o ? '+' : '';
                    return [
                      `Ouverture: ${d.o.toFixed(2)} kg`,
                      `Max: ${d.h.toFixed(2)} kg · Min: ${d.l.toFixed(2)} kg`,
                      `Clôture: ${d.c.toFixed(2)} kg (${sign}${diff} kg)`
                    ];
                  }
                }
              }
            }
          },
          plugins: [candlestickWickPlugin]
        });
        chartWeightDetail.config._ohlcData = series.ohlc;
        chartWeightDetail.update();
        return;
      }

      chartWeightDetail = new Chart(ctx, {
        type: 'line',
        data: {
          labels: series.labels,
          datasets: [
            {
              label: 'Pesée Réelle (kg)',
              data: series.weights,
              borderColor: '#94a3b8',
              backgroundColor: '#cbd5e1',
              borderWidth: 1.5,
              pointRadius: 3.5,
              spanGaps: true,
              tension: 0.1,
              hidden: !weightChartVisibility[0]
            },
            {
              label: 'Tendance Lissée 7j',
              data: series.trends,
              borderColor: '#7C3AED',
              borderWidth: 3,
              pointRadius: 0,
              spanGaps: true,
              tension: 0.35,
              hidden: !weightChartVisibility[1]
            },
            {
              label: 'Masse Musculaire (kg)',
              data: series.muscle,
              borderColor: '#ef4444',
              backgroundColor: '#ef4444',
              borderWidth: 1.5,
              pointRadius: 3,
              spanGaps: true,
              tension: 0.1,
              yAxisID: 'yComp',
              hidden: !weightChartVisibility[2]
            },
            {
              label: 'Masse Grasse %',
              data: series.fat,
              borderColor: '#eab308',
              backgroundColor: '#eab308',
              borderWidth: 1.5,
              pointRadius: 3,
              spanGaps: true,
              tension: 0.1,
              yAxisID: 'yComp',
              hidden: !weightChartVisibility[3]
            },
            {
              label: `Objectif Cible (${targetWeight} kg)`,
              data: series.targets,
              borderColor: '#f59e0b',
              borderDash: [5, 5],
              borderWidth: 2,
              pointRadius: 0,
              hidden: !weightChartVisibility[4]
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
            y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } },
            yComp: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: '#64748b' } }
          },
          plugins: {
            legend: { display: false }
          }
        }
      });
    }

    window.setWeightChartMode = setWeightChartMode;
    window.toggleWeightDataset = toggleWeightDataset;
    window.applyWeightChartPreset = applyWeightChartPreset;

    // 3. Rendu Vue Nutrition & Calories Repas


window.renderWeightView = renderWeightView;
