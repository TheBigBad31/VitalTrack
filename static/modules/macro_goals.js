// static/modules/macro_goals.js - Suivi quotidien des objectifs nutritionnels (Protéines, Calories, Glucides, Lipides)

(function () {
  const NUTRIENT_CONFIG = {
    protein: {
      key: 'protein',
      field: 'protein_g',
      targetKey: 'protein_g',
      label: 'Protéines',
      shortLabel: 'Prot.',
      emoji: '💪',
      unit: 'g',
      priority: true,
      accentHex: '#7C3AED',
      accentBg: 'rgba(124, 58, 237, 0.78)',
      accentBorder: '#A78BFA',
      tabBg: '#7C3AED',
      tabBorder: '#A78BFA',
      ruleHint: 'Objectif plancher prioritaire (≥ 95 % atteint)',
    },
    calories: {
      key: 'calories',
      field: 'calories_kcal',
      targetKey: 'calories',
      label: 'Calories',
      shortLabel: 'Kcal',
      emoji: '🔥',
      unit: 'kcal',
      priority: false,
      accentHex: '#F59E0B',
      accentBg: 'rgba(245, 158, 11, 0.78)',
      accentBorder: '#FBBF24',
      tabBg: '#D97706',
      tabBorder: '#FBBF24',
      ruleHint: 'Fourchette optimale : 90 % à 108 % de la cible',
    },
    carbs: {
      key: 'carbs',
      field: 'carbs_g',
      targetKey: 'carbs_g',
      label: 'Glucides',
      shortLabel: 'Gluc.',
      emoji: '⚡',
      unit: 'g',
      priority: false,
      accentHex: '#22D3EE',
      accentBg: 'rgba(34, 211, 238, 0.75)',
      accentBorder: '#67E8F9',
      tabBg: '#0284C7',
      tabBorder: '#38BDF8',
      ruleHint: 'Fourchette équilibrée : 85 % à 115 % de la cible',
    },
    fat: {
      key: 'fat',
      field: 'fat_g',
      targetKey: 'fat_g',
      label: 'Lipides',
      shortLabel: 'Lip.',
      emoji: '🥑',
      unit: 'g',
      priority: false,
      accentHex: '#C026D3',
      accentBg: 'rgba(192, 38, 211, 0.75)',
      accentBorder: '#E879F9',
      tabBg: '#A21CAF',
      tabBorder: '#E879F9',
      ruleHint: 'Fourchette santé : 80 % à 110 % de la cible',
    },
  };

  const NUTRIENT_ORDER = ['protein', 'calories', 'carbs', 'fat'];

  const panelState = {
    summary: { nutrient: 'protein', days: 7, chart: null },
    nutrition: { nutrient: 'protein', days: 14, chart: null },
  };

  function evaluateNutrientStatus(nutrient, value, target, rule) {
    const val = Math.round(Math.max(0, Number(value) || 0) * 10) / 10;
    const ruleTarget = rule && rule.target !== undefined && rule.target !== null ? Number(rule.target) : Number(target);
    const tgt = Math.round(Math.max(0, ruleTarget || 0) * 10) / 10;
    let diff = Math.round((val - tgt) * 10) / 10;

    if (rule && ['min', 'max', 'range'].includes(rule.mode)) {
      const mode = rule.mode;
      const minV = rule.min !== undefined && rule.min !== null ? Number(rule.min) : null;
      const maxV = rule.max !== undefined && rule.max !== null ? Number(rule.max) : null;
      let refVal = tgt;
      if (mode === 'min' && minV !== null) {
        refVal = minV;
        diff = Math.round((val - minV) * 10) / 10;
      } else if (mode === 'max' && maxV !== null) {
        refVal = maxV;
        diff = Math.round((val - maxV) * 10) / 10;
      }

      if (val <= 0) return { pct: 0, diff, state: 'empty', mode, min: minV, max: maxV };
      const pct = refVal > 0 ? Math.round((val / refVal) * 1000) / 10 : 0;

      let state = 'below';
      if (mode === 'min') {
        const floor = minV !== null ? minV : tgt;
        if (val >= floor) state = 'reached';
        else if (val >= floor * 0.85) state = 'close';
        else state = 'below';
      } else if (mode === 'max') {
        const ceilV = maxV !== null ? maxV : tgt;
        if (val <= ceilV) state = 'reached';
        else if (val <= ceilV * 1.1) state = 'close';
        else state = 'over';
      } else {
        let lo = minV !== null ? minV : Math.round(tgt * 0.9 * 10) / 10;
        let hi = maxV !== null ? maxV : Math.round(tgt * 1.1 * 10) / 10;
        if (lo > hi) { const tmp = lo; lo = hi; hi = tmp; }
        if (val >= lo && val <= hi) state = 'reached';
        else if ((val >= lo * 0.85 && val < lo) || (val > hi && val <= hi * 1.1)) state = 'close';
        else if (val > hi * 1.1) state = 'over';
        else state = 'below';
      }
      return { pct, diff, state, mode, min: minV, max: maxV };
    }

    if (val <= 0) return { pct: 0, diff, state: 'empty' };
    const pct = tgt > 0 ? Math.round((val / tgt) * 1000) / 10 : 0;

    let state = 'below';
    if (nutrient === 'protein') {
      if (pct >= 95) state = 'reached';
      else if (pct >= 80) state = 'close';
      else state = 'below';
    } else if (nutrient === 'calories') {
      if (pct >= 90 && pct <= 108) state = 'reached';
      else if ((pct >= 75 && pct < 90) || (pct > 108 && pct <= 115)) state = 'close';
      else if (pct > 115) state = 'over';
      else state = 'below';
    } else if (nutrient === 'carbs') {
      if (pct >= 85 && pct <= 115) state = 'reached';
      else if ((pct >= 70 && pct < 85) || (pct > 115 && pct <= 125)) state = 'close';
      else if (pct > 125) state = 'over';
      else state = 'below';
    } else {
      if (pct >= 80 && pct <= 110) state = 'reached';
      else if ((pct >= 65 && pct < 80) || (pct > 110 && pct <= 120)) state = 'close';
      else if (pct > 120) state = 'over';
      else state = 'below';
    }
    return { pct, diff, state };
  }

  function resolveTargets() {
    const data = (typeof currentData !== 'undefined' && currentData) || {};
    const s = data.summary || {};
    const profile = data.profile || {};
    const t = s.targets || (data.daily_goals_history && data.daily_goals_history.targets) || {};
    const existingRules = (s.targets && s.targets.rules) || (data.daily_goals_history && data.daily_goals_history.rules) || null;

    const weight =
      Number(t.weight_kg) ||
      Number(s.current_weight_kg) ||
      Number(profile.current_weight_kg) ||
      Number(profile.target_weight_kg) ||
      0;

    if (existingRules && Number(t.protein_g) > 0 && Number(t.calories) > 0) {
      return {
        protein_g: Math.round(Number(t.protein_g) * 10) / 10,
        calories: Math.round(Number(t.calories) * 10) / 10,
        carbs_g: Math.round(Number(t.carbs_g || (t.calories * 0.45) / 4) * 10) / 10,
        fat_g: Math.round(Number(t.fat_g || (t.calories * 0.30) / 9) * 10) / 10,
        weight_kg: weight > 0 ? Math.round(weight * 10) / 10 : null,
        rules: existingRules,
      };
    }

    if (typeof resolveNutritionTargetsFromConfig === 'function') {
      const computed = resolveNutritionTargetsFromConfig(null, { profile, summary: s });
      return {
        protein_g: computed.protein_g,
        calories: computed.calories,
        carbs_g: computed.carbs_g,
        fat_g: computed.fat_g,
        weight_kg: computed.weight_kg,
        rules: computed.rules,
      };
    }

    const targetCals =
      Number(t.calories) ||
      Number(s.target_calories_intake) ||
      Number(profile.target_calories_intake) ||
      2000;
    // Priorité à protein_target_per_kg * poids (jamais écrasé par daily_protein_target_g résiduel)
    const targetProt =
      Number(t.protein_g) ||
      (profile.protein_target_per_kg && weight
        ? Math.round(Number(profile.protein_target_per_kg) * weight)
        : Number(profile.daily_protein_target_g) || Math.round((targetCals * 0.25) / 4));
    const targetCarbs =
      Number(t.carbs_g) ||
      Number(profile.daily_carbs_target_g) ||
      Math.round((targetCals * 0.45) / 4);
    const targetFat =
      Number(t.fat_g) ||
      Number(profile.daily_fat_target_g) ||
      Math.round((targetCals * 0.30) / 9);

    return {
      protein_g: Math.round(targetProt * 10) / 10,
      calories: Math.round(targetCals * 10) / 10,
      carbs_g: Math.round(targetCarbs * 10) / 10,
      fat_g: Math.round(targetFat * 10) / 10,
      weight_kg: weight > 0 ? Math.round(weight * 10) / 10 : null,
      rules: existingRules,
    };
  }

  function formatRuleLabelShort(rule, fallbackTarget, unit) {
    const fmt = (v) => Math.round(Number(v) || 0).toLocaleString('fr-FR');
    if (rule && rule.mode === 'min') return `≥ ${fmt(rule.min !== null ? rule.min : fallbackTarget)} ${unit}`;
    if (rule && rule.mode === 'max') return `≤ ${fmt(rule.max !== null ? rule.max : fallbackTarget)} ${unit}`;
    if (rule && rule.mode === 'range' && rule.min !== null && rule.max !== null) {
      return `${fmt(rule.min)}–${fmt(rule.max)} ${unit}`;
    }
    return `/ ${fmt(fallbackTarget)} ${unit}`;
  }

  function formatRuleHintText(cfg, target, rule, targetPerKg) {
    const fmt = (v) => Math.round(Number(v) || 0).toLocaleString('fr-FR');
    const perKgStr = targetPerKg ? ` (${targetPerKg} g/kg)` : '';
    if (rule && rule.mode === 'min') {
      const floor = rule.min !== null ? rule.min : target;
      return `${cfg.emoji} ${cfg.label} • Seuil plancher ≥ ${fmt(floor)} ${cfg.unit}/j${perKgStr}`;
    }
    if (rule && rule.mode === 'max') {
      const ceilV = rule.max !== null ? rule.max : target;
      return `${cfg.emoji} ${cfg.label} • Plafond à ne pas dépasser ≤ ${fmt(ceilV)} ${cfg.unit}/j${perKgStr}`;
    }
    if (rule && rule.mode === 'range' && rule.min !== null && rule.max !== null) {
      return `${cfg.emoji} ${cfg.label} • Fourchette cible ${fmt(rule.min)} – ${fmt(rule.max)} ${cfg.unit}/j${perKgStr}`;
    }
    return `${cfg.emoji} ${cfg.label} • Cible ${fmt(target)} ${cfg.unit}/j${perKgStr} — ${cfg.ruleHint}`;
  }

  function getGoalsHistoryDataset() {
    const data = (typeof currentData !== 'undefined' && currentData) || {};
    const targets = resolveTargets();
    const rules = targets.rules || {};

    if (
      data.daily_goals_history &&
      Array.isArray(data.daily_goals_history.daily) &&
      data.daily_goals_history.daily.length > 0
    ) {
      // Recalculer les statuts avec les cibles & règles courantes
      const daily = data.daily_goals_history.daily.map((row) => ({
        ...row,
        status: {
          protein: evaluateNutrientStatus('protein', row.protein_g, targets.protein_g, rules.protein),
          calories: evaluateNutrientStatus('calories', row.calories_kcal, targets.calories, rules.calories),
          carbs: evaluateNutrientStatus('carbs', row.carbs_g, targets.carbs_g, rules.carbs),
          fat: evaluateNutrientStatus('fat', row.fat_g, targets.fat_g, rules.fat),
        },
      }));
      return { targets, rules, weight_kg: targets.weight_kg || data.daily_goals_history.weight_kg, daily };
    }

    // Fallback local à partir de recent_meals
    const meals = Array.isArray(data.recent_meals) ? data.recent_meals : [];
    const byDate = new Map();
    meals.forEach((m) => {
      const d = String(m.date || '').slice(0, 10);
      if (!d) return;
      const cur = byDate.get(d) || { calories_kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 };
      cur.calories_kcal += Number(m.total_calories_kcal) || 0;
      cur.protein_g += Number(m.protein_g) || 0;
      cur.carbs_g += Number(m.carbs_g) || 0;
      cur.fat_g += Number(m.fat_g) || 0;
      cur.fiber_g += Number(m.fiber_g) || 0;
      byDate.set(d, cur);
    });

    const daily = [];
    for (let i = 29; i >= 0; i -= 1) {
      const dt = new Date();
      dt.setDate(dt.getDate() - i);
      const iso = dt.toISOString().split('T')[0];
      const b = byDate.get(iso) || { calories_kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 };
      const cals = Math.round(b.calories_kcal * 10) / 10;
      const prot = Math.round(b.protein_g * 10) / 10;
      const carbs = Math.round(b.carbs_g * 10) / 10;
      const fat = Math.round(b.fat_g * 10) / 10;
      daily.push({
        date: iso,
        calories_kcal: cals,
        protein_g: prot,
        carbs_g: carbs,
        fat_g: fat,
        fiber_g: Math.round(b.fiber_g * 10) / 10,
        protein_per_kg: targets.weight_kg && prot > 0 ? Math.round((prot / targets.weight_kg) * 100) / 100 : null,
        status: {
          protein: evaluateNutrientStatus('protein', prot, targets.protein_g, rules.protein),
          calories: evaluateNutrientStatus('calories', cals, targets.calories, rules.calories),
          carbs: evaluateNutrientStatus('carbs', carbs, targets.carbs_g, rules.carbs),
          fat: evaluateNutrientStatus('fat', fat, targets.fat_g, rules.fat),
        },
      });
    }

    return { targets, rules, weight_kg: targets.weight_kg, daily };
  }

  function computePeriodMetrics(dailySlice, nutrient, target, weightKg) {
    const cfg = NUTRIENT_CONFIG[nutrient];
    const todayRow = dailySlice[dailySlice.length - 1] || null;
    const todayVal = todayRow ? Number(todayRow[cfg.field]) || 0 : 0;
    const todayStatus = todayRow ? todayRow.status[nutrient] : evaluateNutrientStatus(nutrient, 0, target);

    const logged = dailySlice.filter((r) => (Number(r[cfg.field]) || 0) > 0);
    const reached = logged.filter((r) => r.status[nutrient].state === 'reached');
    const loggedDays = logged.length;
    const daysReached = reached.length;
    const avgLogged =
      loggedDays > 0
        ? Math.round((logged.reduce((acc, r) => acc + (Number(r[cfg.field]) || 0), 0) / loggedDays) * 10) / 10
        : 0;
    const adherencePct = loggedDays > 0 ? Math.round((daysReached / loggedDays) * 100) : 0;

    let streak = 0;
    let idx = dailySlice.length - 1;
    if (idx >= 0 && dailySlice[idx].status[nutrient].state !== 'reached') {
      idx -= 1;
    }
    while (idx >= 0 && dailySlice[idx].status[nutrient].state === 'reached') {
      streak += 1;
      idx -= 1;
    }

    return {
      target,
      today: todayVal,
      todayPct: Math.round(todayStatus.pct),
      todayRemaining: Math.round(Math.max(0, target - todayVal)),
      todayDiff: Math.round(todayStatus.diff),
      todayState: todayStatus.state,
      avgLogged,
      loggedDays,
      daysReached,
      adherencePct,
      streak,
      todayPerKg: nutrient === 'protein' && weightKg && todayVal > 0 ? (todayVal / weightKg).toFixed(2) : null,
      targetPerKg: nutrient === 'protein' && weightKg && target > 0 ? (target / weightKg).toFixed(1) : null,
    };
  }

  function stateDisplay(state, nutrient) {
    if (state === 'reached') {
      return {
        label: 'Objectif atteint',
        short: '✓',
        barBg: 'rgba(16, 185, 129, 0.82)',
        barBorder: '#34D399',
        pillClass: 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300',
        dotClass: 'bg-emerald-400',
      };
    }
    if (state === 'close') {
      return {
        label: 'Proche de la cible',
        short: '~',
        barBg: 'rgba(245, 158, 11, 0.78)',
        barBorder: '#FBBF24',
        pillClass: 'bg-amber-500/15 border-amber-500/40 text-amber-300',
        dotClass: 'bg-amber-400',
      };
    }
    if (state === 'over') {
      return {
        label: 'Au-dessus de la cible',
        short: '↑',
        barBg: 'rgba(244, 63, 94, 0.78)',
        barBorder: '#FB7185',
        pillClass: 'bg-rose-500/15 border-rose-500/40 text-rose-300',
        dotClass: 'bg-rose-400',
      };
    }
    if (state === 'below') {
      const cfg = NUTRIENT_CONFIG[nutrient];
      return {
        label: 'Sous la cible',
        short: '↓',
        barBg: nutrient === 'protein' ? 'rgba(244, 63, 94, 0.72)' : cfg.accentBg,
        barBorder: nutrient === 'protein' ? '#FB7185' : cfg.accentBorder,
        pillClass:
          nutrient === 'protein'
            ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
            : 'bg-slate-800/80 border-slate-600/50 text-slate-300',
        dotClass: nutrient === 'protein' ? 'bg-rose-400' : 'bg-slate-400',
      };
    }
    return {
      label: 'Non saisi',
      short: '·',
      barBg: 'rgba(71, 85, 105, 0.35)',
      barBorder: 'rgba(100, 116, 139, 0.5)',
      pillClass: 'bg-[#0B0F17] border-[#25254A] text-slate-500',
      dotClass: 'bg-slate-600',
    };
  }

  function formatShortWeekday(isoDate) {
    try {
      const d = new Date(`${isoDate}T12:00:00`);
      const names = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
      return `${names[d.getDay()]} ${isoDate.slice(8, 10)}`;
    } catch (_e) {
      return isoDate.slice(5);
    }
  }

  function openJournalForDate(isoDate) {
    if (!isoDate) return;
    if (typeof switchTab === 'function') {
      switchTab('nutrition');
    }
    if (typeof currentJournalDate !== 'undefined') {
      window.currentJournalDate = isoDate;
      currentJournalDate = isoDate;
    }
    const input = document.getElementById('journal-date-input');
    if (input) input.value = isoDate;
    if (typeof loadMealsJournal === 'function') {
      loadMealsJournal(isoDate);
    }
  }

  function renderOverviewStrip(prefix, dataset, activeNutrient) {
    const container = document.getElementById(`${prefix}-macro-goals-overview`);
    if (!container) return;
    container.textContent = '';

    const todayRow = dataset.daily[dataset.daily.length - 1] || null;
    const rules = dataset.rules || {};
    NUTRIENT_ORDER.forEach((key) => {
      const cfg = NUTRIENT_CONFIG[key];
      const tgt = dataset.targets[cfg.targetKey];
      const rule = rules[key] || null;
      const val = todayRow ? Math.round(Number(todayRow[cfg.field]) || 0) : 0;
      const st = todayRow ? todayRow.status[key] : evaluateNutrientStatus(key, val, tgt, rule);
      const pct = Math.min(100, Math.round(st.pct));
      const isSelected = key === activeNutrient;
      const disp = stateDisplay(st.state, key);

      const card = document.createElement('button');
      card.type = 'button';
      card.className = `text-left p-3 rounded-xl border transition-all cursor-pointer ${
        isSelected
          ? 'bg-[#25254A]/70 border-brand-500 shadow-md'
          : 'bg-[#0B0F17] border-[#25254A] hover:border-slate-600'
      }`;
      if (isSelected) {
        card.style.borderColor = cfg.accentBorder;
      }
      card.addEventListener('click', () => selectMacroGoalNutrient(prefix, key));

      const topRow = document.createElement('div');
      topRow.className = 'flex items-center justify-between gap-1 mb-1.5';

      const titleWrap = document.createElement('span');
      titleWrap.className = 'text-xs font-bold text-white flex items-center gap-1';
      titleWrap.textContent = `${cfg.emoji} ${cfg.label}`;
      if (cfg.priority) {
        const prio = document.createElement('span');
        prio.className = 'text-[9px] px-1.5 py-0.5 rounded-full bg-brand-500/25 text-brand-300 border border-brand-500/40 font-bold';
        prio.textContent = 'Priorité';
        titleWrap.appendChild(prio);
      }

      const pctBadge = document.createElement('span');
      pctBadge.className = `text-[10px] font-bold px-1.5 py-0.5 rounded-md border ${disp.pillClass}`;
      pctBadge.textContent = `${Math.round(st.pct)}%`;

      topRow.appendChild(titleWrap);
      topRow.appendChild(pctBadge);

      const valRow = document.createElement('div');
      valRow.className = 'text-sm font-extrabold text-white';
      valRow.textContent = `${val.toLocaleString('fr-FR')} `;
      const tgtSpan = document.createElement('span');
      tgtSpan.className = 'text-[11px] font-normal text-slate-400';
      tgtSpan.textContent = rule ? `(${formatRuleLabelShort(rule, tgt, cfg.unit)})` : `/ ${Math.round(tgt).toLocaleString('fr-FR')} ${cfg.unit}`;
      valRow.appendChild(tgtSpan);

      const barTrack = document.createElement('div');
      barTrack.className = 'w-full bg-slate-800/90 rounded-full h-1.5 mt-2 overflow-hidden';
      const barFill = document.createElement('div');
      barFill.className = 'h-full rounded-full transition-all duration-300';
      barFill.style.width = `${pct}%`;
      barFill.style.backgroundColor = st.state === 'reached' ? '#10B981' : cfg.accentHex;
      barTrack.appendChild(barFill);

      const subRow = document.createElement('div');
      subRow.className = 'text-[10px] text-slate-400 mt-1 flex items-center justify-between';
      const rem = Math.round(tgt - val);
      const remSpan = document.createElement('span');
      if (st.state === 'reached') {
        remSpan.className = 'text-emerald-400 font-semibold';
        remSpan.textContent = '✓ Objectif atteint';
      } else if (rem > 0) {
        remSpan.textContent = `Reste ${rem.toLocaleString('fr-FR')} ${cfg.unit}`;
      } else {
        remSpan.className = 'text-amber-400 font-semibold';
        remSpan.textContent = `+${Math.abs(rem).toLocaleString('fr-FR')} ${cfg.unit}`;
      }
      subRow.appendChild(remSpan);

      if (key === 'protein' && dataset.weight_kg && val > 0) {
        const pkg = document.createElement('span');
        pkg.className = 'text-brand-300 font-mono';
        pkg.textContent = `${(val / dataset.weight_kg).toFixed(1)} g/kg`;
        subRow.appendChild(pkg);
      }

      card.appendChild(topRow);
      card.appendChild(valRow);
      card.appendChild(barTrack);
      card.appendChild(subRow);
      container.appendChild(card);
    });
  }

  function renderDayIndicatorsStrip(prefix, dailySlice, nutrient) {
    const strip = document.getElementById(`${prefix}-macro-goals-days-strip`);
    if (!strip) return;
    strip.textContent = '';

    const cfg = NUTRIENT_CONFIG[nutrient];
    const todayIso = new Date().toISOString().split('T')[0];
    // Afficher les 14 derniers jours au maximum dans la frise pour garder une lecture fluide
    const visibleDays = dailySlice.length > 14 ? dailySlice.slice(-14) : dailySlice;

    visibleDays.forEach((row) => {
      const val = Math.round(Number(row[cfg.field]) || 0);
      const st = row.status[nutrient];
      const disp = stateDisplay(st.state, nutrient);
      const isToday = row.date === todayIso;

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.title = `${row.date} — ${cfg.label}: ${val} ${cfg.unit} (${Math.round(st.pct)}%) • ${disp.label}. Cliquer pour ouvrir le journal.`;
      btn.className = `flex flex-col items-center justify-center px-2 py-1.5 rounded-xl border text-center transition-all cursor-pointer ${disp.pillClass} ${
        isToday ? 'border-white' : ''
      }`;
      btn.style.minWidth = '54px';
      btn.addEventListener('click', () => openJournalForDate(row.date));

      const dayLbl = document.createElement('span');
      dayLbl.className = 'text-[10px] font-semibold opacity-90 whitespace-nowrap';
      dayLbl.textContent = isToday ? "Auj." : formatShortWeekday(row.date);

      const iconLbl = document.createElement('span');
      iconLbl.className = 'text-xs font-extrabold leading-tight my-0.5';
      iconLbl.textContent = disp.short;

      const valLbl = document.createElement('span');
      valLbl.className = 'text-[10px] font-mono opacity-90';
      valLbl.textContent = val > 0 ? `${val}${cfg.unit === 'kcal' ? '' : 'g'}` : '—';

      btn.appendChild(dayLbl);
      btn.appendChild(iconLbl);
      btn.appendChild(valLbl);
      strip.appendChild(btn);
    });
  }

  function renderMacroGoalsPanel(prefix) {
    const state = panelState[prefix];
    if (!state) return;

    const canvas = document.getElementById(`chart-${prefix}-macro-goals`);
    if (!canvas) return;

    const dataset = getGoalsHistoryDataset();
    const nutrient = state.nutrient || 'protein';
    const cfg = NUTRIENT_CONFIG[nutrient];
    const target = dataset.targets[cfg.targetKey];
    const rule = (dataset.rules && dataset.rules[nutrient]) || null;
    const sliceDays = Math.max(1, Math.min(state.days || 7, dataset.daily.length));
    const dailySlice = dataset.daily.slice(-sliceDays);
    const metrics = computePeriodMetrics(dailySlice, nutrient, target, dataset.weight_kg);

    // 1. Mise à jour des onglets nutriments
    NUTRIENT_ORDER.forEach((key) => {
      const btn = document.getElementById(`${prefix}-macro-tab-${key}`);
      if (!btn) return;
      const nCfg = NUTRIENT_CONFIG[key];
      if (key === nutrient) {
        btn.className = 'px-3 py-1.5 rounded-xl text-xs font-bold border text-white shadow-md transition-all flex items-center gap-1.5 cursor-pointer';
        btn.style.backgroundColor = nCfg.tabBg;
        btn.style.borderColor = nCfg.tabBorder;
        btn.setAttribute('aria-pressed', 'true');
      } else {
        btn.className =
          'px-3 py-1.5 rounded-xl text-xs font-semibold border border-[#25254A] bg-[#0B0F17] text-slate-300 hover:text-white hover:border-slate-600 transition-all flex items-center gap-1.5 cursor-pointer';
        btn.style.backgroundColor = '';
        btn.style.borderColor = '';
        btn.setAttribute('aria-pressed', 'false');
      }
    });

    // 2. Mise à jour des boutons de période (7j / 14j / 30j)
    [7, 14, 30].forEach((d) => {
      const btn = document.getElementById(`${prefix}-macro-days-${d}`);
      if (!btn) return;
      if (d === state.days) {
        btn.className = 'px-2.5 py-1 rounded-lg text-[11px] font-bold bg-brand-600 text-white transition-colors cursor-pointer';
      } else {
        btn.className = 'px-2.5 py-1 rounded-lg text-[11px] font-semibold text-slate-400 hover:text-white transition-colors cursor-pointer';
      }
    });

    // 3. Sous-titre / règle du nutriment
    const hintEl = document.getElementById(`${prefix}-macro-goals-hint`);
    if (hintEl) {
      hintEl.textContent = formatRuleHintText(cfg, target, rule, metrics.targetPerKg);
    }

    // 4. Mini-KPIs
    const elToday = document.getElementById(`${prefix}-macro-kpi-today`);
    const elTodaySub = document.getElementById(`${prefix}-macro-kpi-today-sub`);
    if (elToday) {
      elToday.textContent = `${Math.round(metrics.today).toLocaleString('fr-FR')} / ${Math.round(target).toLocaleString('fr-FR')} ${cfg.unit}`;
    }
    if (elTodaySub) {
      if (metrics.todayState === 'reached') {
        elTodaySub.textContent = `✓ ${metrics.todayPct}% atteint${metrics.todayPerKg ? ` • ${metrics.todayPerKg} g/kg` : ''}`;
        elTodaySub.className = 'text-[11px] font-semibold text-emerald-400';
      } else if (metrics.today > 0) {
        const diffTxt =
          metrics.todayDiff < 0
            ? `Reste ${Math.abs(metrics.todayDiff).toLocaleString('fr-FR')} ${cfg.unit}`
            : `+${metrics.todayDiff.toLocaleString('fr-FR')} ${cfg.unit}`;
        elTodaySub.textContent = `${metrics.todayPct}% • ${diffTxt}${metrics.todayPerKg ? ` (${metrics.todayPerKg} g/kg)` : ''}`;
        elTodaySub.className = 'text-[11px] font-semibold text-amber-400';
      } else {
        elTodaySub.textContent = 'Aucun repas saisi aujourd’hui';
        elTodaySub.className = 'text-[11px] text-slate-400';
      }
    }

    const elReached = document.getElementById(`${prefix}-macro-kpi-reached`);
    const elReachedSub = document.getElementById(`${prefix}-macro-kpi-reached-sub`);
    if (elReached) {
      elReached.textContent = `${metrics.daysReached} / ${metrics.loggedDays || sliceDays} j`;
    }
    if (elReachedSub) {
      elReachedSub.textContent =
        metrics.loggedDays > 0
          ? `${metrics.adherencePct}% des jours saisis`
          : `Sur les ${sliceDays} derniers jours`;
    }

    const elStreak = document.getElementById(`${prefix}-macro-kpi-streak`);
    const elStreakSub = document.getElementById(`${prefix}-macro-kpi-streak-sub`);
    if (elStreak) {
      elStreak.textContent = `${metrics.streak} j`;
    }
    if (elStreakSub) {
      elStreakSub.textContent = metrics.streak >= 3 ? '🔥 Excellente régularité' : 'Jours consécutifs atteints';
    }

    const elAvg = document.getElementById(`${prefix}-macro-kpi-avg`);
    const elAvgSub = document.getElementById(`${prefix}-macro-kpi-avg-sub`);
    if (elAvg) {
      elAvg.textContent = `${Math.round(metrics.avgLogged).toLocaleString('fr-FR')} ${cfg.unit}`;
    }
    if (elAvgSub) {
      const deltaAvg = Math.round(metrics.avgLogged - target);
      elAvgSub.textContent =
        metrics.loggedDays > 0
          ? `${deltaAvg >= 0 ? '+' : ''}${deltaAvg} ${cfg.unit} vs cible`
          : 'Moyenne sur jours saisis';
    }

    // 5. Bandeau des 4 nutriments d'aujourd'hui
    renderOverviewStrip(prefix, dataset, nutrient);

    // 6. Frise d'indicateurs par jour
    renderDayIndicatorsStrip(prefix, dailySlice, nutrient);

    // 7. Graphique Chart.js (Barres colorées par statut + Ligne objectif cible)
    if (typeof Chart === 'undefined') return;
    if (state.chart) {
      try {
        state.chart.destroy();
      } catch (_e) {
        /* ignore */
      }
      state.chart = null;
    }

    const labels = dailySlice.map((r) => (sliceDays <= 14 ? formatShortWeekday(r.date) : r.date.slice(5)));
    const values = dailySlice.map((r) => Math.round(Number(r[cfg.field]) || 0));
    const barColors = dailySlice.map((r) => stateDisplay(r.status[nutrient].state, nutrient).barBg);
    const barBorders = dailySlice.map((r) => stateDisplay(r.status[nutrient].state, nutrient).barBorder);

    const chartDatasets = [
      {
        type: 'bar',
        label: `${cfg.label} (${cfg.unit})`,
        data: values,
        backgroundColor: barColors,
        borderColor: barBorders,
        borderWidth: 1.5,
        borderRadius: 6,
        maxBarThickness: 34,
        order: 2,
      },
    ];

    let maxBound = target;
    if (rule && rule.mode === 'range' && rule.min !== null && rule.max !== null) {
      const minVal = Math.round(Number(rule.min));
      const maxVal = Math.round(Number(rule.max));
      maxBound = Math.max(target, maxVal);
      chartDatasets.push(
        {
          type: 'line',
          label: `Seuil min (${minVal} ${cfg.unit})`,
          data: dailySlice.map(() => minVal),
          borderColor: '#10B981',
          borderDash: [5, 4],
          borderWidth: 1.8,
          pointRadius: 0,
          fill: false,
          order: 1,
        },
        {
          type: 'line',
          label: `Plafond max (${maxVal} ${cfg.unit})`,
          data: dailySlice.map(() => maxVal),
          borderColor: '#F59E0B',
          borderDash: [5, 4],
          borderWidth: 1.8,
          pointRadius: 0,
          backgroundColor: 'rgba(16, 185, 129, 0.08)',
          fill: '-1',
          order: 0,
        }
      );
    } else if (rule && rule.mode === 'min') {
      const floorVal = Math.round(Number(rule.min !== null ? rule.min : target));
      maxBound = Math.max(target, floorVal);
      chartDatasets.push({
        type: 'line',
        label: `Seuil plancher (≥ ${floorVal} ${cfg.unit})`,
        data: dailySlice.map(() => floorVal),
        borderColor: '#10B981',
        borderDash: [6, 4],
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        order: 0,
      });
    } else if (rule && rule.mode === 'max') {
      const ceilVal = Math.round(Number(rule.max !== null ? rule.max : target));
      maxBound = Math.max(target, ceilVal);
      chartDatasets.push({
        type: 'line',
        label: `Plafond max (≤ ${ceilVal} ${cfg.unit})`,
        data: dailySlice.map(() => ceilVal),
        borderColor: '#F43F5E',
        borderDash: [6, 4],
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        order: 0,
      });
    } else {
      chartDatasets.push({
        type: 'line',
        label: `Objectif (${Math.round(target)} ${cfg.unit})`,
        data: dailySlice.map(() => Math.round(target)),
        borderColor: '#F59E0B',
        borderDash: [6, 4],
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        order: 0,
      });
    }

    try {
      state.chart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: chartDatasets,
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: {
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { color: '#94a3b8', font: { size: 11 } },
            },
            y: {
              beginAtZero: true,
              suggestedMax: Math.round(Math.max(maxBound * 1.2, ...values, 10)),
              grid: { color: 'rgba(255,255,255,0.05)' },
              ticks: {
                color: '#94a3b8',
                font: { size: 11 },
                callback: (v) => `${v}${cfg.unit === 'kcal' ? '' : 'g'}`,
              },
            },
          },
          plugins: {
            legend: {
              position: 'top',
              labels: { color: '#cbd5e1', boxWidth: 12, font: { size: 11 } },
            },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  if (ctx.datasetIndex > 0) {
                    return ` ${ctx.dataset.label}`;
                  }
                  const row = dailySlice[ctx.dataIndex];
                  const st = row.status[nutrient];
                  const disp = stateDisplay(st.state, nutrient);
                  const diffSign = st.diff >= 0 ? `+${Math.round(st.diff)}` : `${Math.round(st.diff)}`;
                  return ` ${cfg.label} : ${Math.round(ctx.raw).toLocaleString('fr-FR')} ${cfg.unit} (${Math.round(st.pct)}% • ${diffSign} ${cfg.unit}) — ${disp.label}`;
                },
              },
            },
          },
        },
      });
    } catch (err) {
      console.warn(`[MacroGoals] Erreur rendu graphique (${prefix}):`, err);
      state.chart = null;
    }
  }

  function selectMacroGoalNutrient(prefix, nutrient) {
    if (!panelState[prefix] || !NUTRIENT_CONFIG[nutrient]) return;
    panelState[prefix].nutrient = nutrient;
    renderMacroGoalsPanel(prefix);
  }

  function selectMacroGoalDays(prefix, days) {
    if (!panelState[prefix]) return;
    const parsed = parseInt(days, 10);
    if (![7, 14, 30].includes(parsed)) return;
    panelState[prefix].days = parsed;
    renderMacroGoalsPanel(prefix);
  }

  function renderAllMacroGoalsPanels() {
    renderMacroGoalsPanel('summary');
    renderMacroGoalsPanel('nutrition');
  }

  /**
   * Met à jour en mémoire la journée d'aujourd'hui dans currentData.daily_goals_history
   * après une modification optimiste du Journal des Repas.
   */
  function syncTodayIntoMacroGoalsHistory(daySummary) {
    if (!daySummary || typeof currentData === 'undefined' || !currentData) return;
    const todayIso = new Date().toISOString().split('T')[0];
    const targets = resolveTargets();

    const cals = Math.round((Number(daySummary.total_calories) || 0) * 10) / 10;
    const prot = Math.round((Number(daySummary.total_protein_g) || 0) * 10) / 10;
    const carbs = Math.round((Number(daySummary.total_carbs_g) || 0) * 10) / 10;
    const fat = Math.round((Number(daySummary.total_fat_g) || 0) * 10) / 10;
    const fiber = Math.round((Number(daySummary.total_fiber_g) || 0) * 10) / 10;

    const rules = targets.rules || {};
    if (
      currentData.daily_goals_history &&
      Array.isArray(currentData.daily_goals_history.daily)
    ) {
      const rows = currentData.daily_goals_history.daily;
      const idx = rows.findIndex((r) => r.date === todayIso);
      const updatedRow = {
        date: todayIso,
        calories_kcal: cals,
        protein_g: prot,
        carbs_g: carbs,
        fat_g: fat,
        fiber_g: fiber,
        protein_per_kg:
          targets.weight_kg && prot > 0 ? Math.round((prot / targets.weight_kg) * 100) / 100 : null,
        status: {
          protein: evaluateNutrientStatus('protein', prot, targets.protein_g, rules.protein),
          calories: evaluateNutrientStatus('calories', cals, targets.calories, rules.calories),
          carbs: evaluateNutrientStatus('carbs', carbs, targets.carbs_g, rules.carbs),
          fat: evaluateNutrientStatus('fat', fat, targets.fat_g, rules.fat),
        },
      };
      if (idx >= 0) {
        rows[idx] = updatedRow;
      } else {
        rows.push(updatedRow);
      }
    }

    if (typeof currentActiveTab === 'undefined' || currentActiveTab === 'summary') {
      renderMacroGoalsPanel('summary');
    }
    if (typeof currentActiveTab !== 'undefined' && currentActiveTab === 'nutrition') {
      renderMacroGoalsPanel('nutrition');
    }
  }

  /**
   * Rend les 4 jauges d'objectifs (Protéines en avant, Calories, Glucides, Lipides)
   * dans l'en-tête du Journal Quotidien pour la date sélectionnée.
   */
  function renderJournalDayMacroBars(daySummary) {
    const container = document.getElementById('journal-day-macro-goals-grid');
    if (!container) return;
    container.textContent = '';

    const sum = daySummary || {};
    const targets = resolveTargets();
    const rules = targets.rules || {};
    const valuesMap = {
      protein: Math.round(Number(sum.total_protein_g) || 0),
      calories: Math.round(Number(sum.total_calories) || 0),
      carbs: Math.round(Number(sum.total_carbs_g) || 0),
      fat: Math.round(Number(sum.total_fat_g) || 0),
    };

    NUTRIENT_ORDER.forEach((key) => {
      const cfg = NUTRIENT_CONFIG[key];
      const val = valuesMap[key];
      const tgt = targets[cfg.targetKey];
      const rule = rules[key] || null;
      const st = evaluateNutrientStatus(key, val, tgt, rule);
      const disp = stateDisplay(st.state, key);
      const pctBar = Math.min(100, Math.round(st.pct));

      const card = document.createElement('div');
      card.className = `p-2.5 rounded-xl border ${
        cfg.priority
          ? 'bg-brand-500/10 border-brand-500/40'
          : 'bg-[#0B0F17] border-[#25254A]'
      }`;

      const top = document.createElement('div');
      top.className = 'flex items-center justify-between gap-1 text-[11px] mb-1';
      const lbl = document.createElement('span');
      lbl.className = 'font-bold text-white flex items-center gap-1';
      lbl.textContent = `${cfg.emoji} ${cfg.label}`;
      const badge = document.createElement('span');
      badge.className = `text-[10px] font-bold px-1.5 py-0.5 rounded border ${disp.pillClass}`;
      badge.textContent = `${Math.round(st.pct)}%`;
      top.appendChild(lbl);
      top.appendChild(badge);

      const numbers = document.createElement('div');
      numbers.className = 'flex items-baseline justify-between text-xs';
      const mainVal = document.createElement('span');
      mainVal.className = 'font-extrabold text-white';
      mainVal.textContent = `${val.toLocaleString('fr-FR')} `;
      const tgtVal = document.createElement('span');
      tgtVal.className = 'text-[10px] font-normal text-slate-400';
      tgtVal.textContent = rule ? `(${formatRuleLabelShort(rule, tgt, cfg.unit)})` : `/ ${Math.round(tgt).toLocaleString('fr-FR')} ${cfg.unit}`;
      mainVal.appendChild(tgtVal);

      const remEl = document.createElement('span');
      const rem = Math.round(tgt - val);
      remEl.className = `text-[10px] font-semibold ${
        st.state === 'reached' ? 'text-emerald-400' : rem < 0 ? 'text-amber-400' : 'text-slate-400'
      }`;
      remEl.textContent =
        st.state === 'reached'
          ? '✓ Atteint'
          : rem >= 0
            ? `-${rem}${cfg.unit === 'kcal' ? '' : 'g'}`
            : `+${Math.abs(rem)}${cfg.unit === 'kcal' ? '' : 'g'}`;

      numbers.appendChild(mainVal);
      numbers.appendChild(remEl);

      const track = document.createElement('div');
      track.className = 'w-full bg-slate-800/90 rounded-full h-1.5 mt-1.5 overflow-hidden';
      const fill = document.createElement('div');
      fill.className = 'h-full rounded-full transition-all duration-300';
      fill.style.width = `${pctBar}%`;
      fill.style.backgroundColor = st.state === 'reached' ? '#10B981' : cfg.accentHex;
      track.appendChild(fill);

      card.appendChild(top);
      card.appendChild(numbers);
      card.appendChild(track);
      container.appendChild(card);
    });
  }

  window.renderMacroGoalsPanel = renderMacroGoalsPanel;
  window.renderAllMacroGoalsPanels = renderAllMacroGoalsPanels;
  window.selectMacroGoalNutrient = selectMacroGoalNutrient;
  window.selectMacroGoalDays = selectMacroGoalDays;
  window.syncTodayIntoMacroGoalsHistory = syncTodayIntoMacroGoalsHistory;
  window.renderJournalDayMacroBars = renderJournalDayMacroBars;
  window.evaluateNutrientStatus = evaluateNutrientStatus;
})();
