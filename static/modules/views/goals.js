// static/modules/views/goals.js - Vue Objectifs, Seuils/Fourchettes Configurables & Source Unique de Vérité (BALI-303)

const PRESET_GOAL_RULES = {
  weight_loss: {
    protein: { mode: 'min', unit: 'per_kg', min: 1.8, max: null },
    calories: { mode: 'range', source: 'dynamic', tolerance_low_pct: 10, tolerance_high_pct: 8 },
    carbs: { mode: 'range', source: 'auto', tolerance_low_pct: 15, tolerance_high_pct: 15 },
    fat: { mode: 'range', source: 'auto', tolerance_low_pct: 20, tolerance_high_pct: 10 },
  },
  maintenance: {
    protein: { mode: 'min', unit: 'per_kg', min: 1.4, max: null },
    calories: { mode: 'range', source: 'dynamic', tolerance_low_pct: 10, tolerance_high_pct: 8 },
    carbs: { mode: 'range', source: 'auto', tolerance_low_pct: 15, tolerance_high_pct: 15 },
    fat: { mode: 'range', source: 'auto', tolerance_low_pct: 20, tolerance_high_pct: 10 },
  },
  recomposition: {
    protein: { mode: 'min', unit: 'per_kg', min: 2.2, max: null },
    calories: { mode: 'range', source: 'dynamic', tolerance_low_pct: 10, tolerance_high_pct: 8 },
    carbs: { mode: 'range', source: 'auto', tolerance_low_pct: 15, tolerance_high_pct: 15 },
    fat: { mode: 'range', source: 'auto', tolerance_low_pct: 20, tolerance_high_pct: 10 },
  },
  muscle_gain: {
    protein: { mode: 'min', unit: 'per_kg', min: 2.0, max: null },
    calories: { mode: 'range', source: 'dynamic', tolerance_low_pct: 5, tolerance_high_pct: 12 },
    carbs: { mode: 'min', source: 'auto', tolerance_low_pct: 10, tolerance_high_pct: 20 },
    fat: { mode: 'range', source: 'auto', tolerance_low_pct: 15, tolerance_high_pct: 15 },
  },
};

const GOAL_NUTRIENT_META = [
  { key: 'protein', label: 'Protéines', emoji: '💪', unit: 'g', accent: 'border-brand-500/40', badge: 'bg-brand-500/15 text-brand-300 border-brand-500/30', isProtein: true },
  { key: 'calories', label: 'Calories', emoji: '🔥', unit: 'kcal', accent: 'border-amber-500/30', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30', isCalories: true },
  { key: 'carbs', label: 'Glucides', emoji: '⚡', unit: 'g', accent: 'border-cyan-500/30', badge: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
  { key: 'fat', label: 'Lipides', emoji: '🥑', unit: 'g', accent: 'border-fuchsia-500/30', badge: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30' },
];

let goalsDraftConfig = null;

function cloneObj(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function getEffectiveWeightKg() {
  const data = (typeof currentData !== 'undefined' && currentData) || {};
  const s = data.summary || {};
  const p = data.profile || {};
  const w = Number(s.current_weight_kg) || Number(p.current_weight_kg) || Number(p.target_weight_kg) || 0;
  return w > 0 ? Math.round(w * 10) / 10 : null;
}

function getDynamicCaloriesBase(profileId) {
  const data = (typeof currentData !== 'undefined' && currentData) || {};
  const s = data.summary || {};
  const prof = data.profile || {};
  const p = (typeof GOAL_PROFILES !== 'undefined' && GOAL_PROFILES[profileId]) || { delta: -500, steps: 10000 };
  if (s.dynamic_tdee && Number(s.dynamic_tdee.dynamic_tdee) > 0) {
    return Math.max(1200, Math.round(Number(s.dynamic_tdee.dynamic_tdee) + p.delta));
  }
  const weight = getEffectiveWeightKg() || Number(prof.current_weight_kg) || Number(prof.target_weight_kg) || 80;
  const height = Number(prof.height_cm) || 178;
  const age = Number(prof.age) || 35;
  const gender = String(prof.gender || 'male').toLowerCase();
  const bmr = gender === 'female'
    ? (10 * weight + 6.25 * height - 5 * age - 161)
    : (10 * weight + 6.25 * height - 5 * age + 5);
  const neatFactors = {
    sedentary: 0.10,
    lightly_active: 0.15,
    light: 0.15,
    moderately_active: 0.20,
    moderate: 0.20,
    very_active: 0.25,
    active: 0.25,
    extra_active: 0.30,
  };
  const actKey = String(prof.activity_level || 'moderately_active').trim().toLowerCase();
  const baseNeat = bmr * (neatFactors[actKey] ?? 0.20);
  const targetSteps = Number(prof.target_steps) || Number(p.steps) || 10000;
  const todaySteps = Number(s.steps) || 0;
  const effectiveSteps = Math.max(todaySteps, targetSteps);
  const neatSteps = effectiveSteps * 0.0005 * weight;
  const workoutCals = Number(s.workout_calories_kcal) || 0;
  return Math.max(1200, Math.round(bmr + baseNeat + neatSteps + workoutCals + p.delta));
}

function parseProfileGoalsConfig(raw) {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_e) {
      return {};
    }
  }
  return {};
}

function getPresetDefaultGoalsConfig(profileId) {
  const key = PRESET_GOAL_RULES[profileId] ? profileId : 'weight_loss';
  return cloneObj(PRESET_GOAL_RULES[key]);
}

/**
 * Résout les cibles effectives (target, min, max, mode, unit) à partir d'une config
 * en miroir exact du backend `resolve_nutrition_goals`.
 */
function resolveNutritionTargetsFromConfig(cfgIn, opts = {}) {
  const data = (typeof currentData !== 'undefined' && currentData) || {};
  const profile = opts.profile || data.profile || {};
  const summary = opts.summary || data.summary || {};
  const goalId = opts.goalProfileId || profile.goal_profile_id || (typeof activeGoalProfileId !== 'undefined' ? activeGoalProfileId : 'weight_loss');
  const presetRules = getPresetDefaultGoalsConfig(goalId);
  const cfg = cfgIn || parseProfileGoalsConfig(profile.nutrition_goals_config);
  const weight = opts.weightKg !== undefined ? opts.weightKg : getEffectiveWeightKg();

  // 1. Calories
  const calCfg = Object.assign({}, presetRules.calories, cfg.calories || {});
  const calMode = ['min', 'max', 'range'].includes(calCfg.mode) ? calCfg.mode : 'range';
  const calSource = calCfg.source === 'fixed' ? 'fixed' : 'dynamic';
  const calTolLo = Number.isFinite(Number(calCfg.tolerance_low_pct)) ? Number(calCfg.tolerance_low_pct) : 10;
  const calTolHi = Number.isFinite(Number(calCfg.tolerance_high_pct)) ? Number(calCfg.tolerance_high_pct) : 8;
  const dynCal = opts.dynamicCalories !== undefined
    ? Number(opts.dynamicCalories)
    : getDynamicCaloriesBase(goalId);
  const profCal = Number(profile.target_calories_intake) || dynCal || 2000;

  let calTarget, calMin = null, calMax = null;
  if (calSource === 'fixed') {
    const cMin = Number(calCfg.min);
    const cMax = Number(calCfg.max);
    const cTgt = Number(calCfg.target);
    if (calMode === 'min') {
      calMin = Math.round((cMin > 0 ? cMin : (cTgt > 0 ? cTgt : profCal)) * 10) / 10;
      calTarget = calMin;
    } else if (calMode === 'max') {
      calMax = Math.round((cMax > 0 ? cMax : (cTgt > 0 ? cTgt : profCal)) * 10) / 10;
      calTarget = calMax;
    } else {
      calMin = Math.round((cMin > 0 ? cMin : (cTgt || profCal) * (1 - calTolLo / 100)) * 10) / 10;
      calMax = Math.round((cMax > 0 ? cMax : (cTgt || profCal) * (1 + calTolHi / 100)) * 10) / 10;
      if (calMin > calMax) { const tmp = calMin; calMin = calMax; calMax = tmp; }
      calTarget = Math.round((cTgt > 0 ? cTgt : (calMin + calMax) / 2) * 10) / 10;
    }
  } else {
    calTarget = Math.round(dynCal * 10) / 10;
    if (calMode === 'min') {
      calMin = calTarget;
    } else if (calMode === 'max') {
      calMax = calTarget;
    } else {
      calMin = Math.round(calTarget * (1 - calTolLo / 100) * 10) / 10;
      calMax = Math.round(calTarget * (1 + calTolHi / 100) * 10) / 10;
    }
  }

  // 2. Protéines (priorité à per_kg * poids sauf si unit === 'g')
  const protCfg = Object.assign({}, presetRules.protein, cfg.protein || {});
  const protMode = ['min', 'max', 'range'].includes(protCfg.mode) ? protCfg.mode : 'min';
  const protUnit = protCfg.unit === 'g' ? 'g' : 'per_kg';
  const profPerKg = Number(profile.protein_target_per_kg) || presetRules.protein.min || 1.8;

  let protTarget, protMin = null, protMax = null, protPerKg = null, protMinPerKg = null, protMaxPerKg = null;
  if (protUnit === 'g') {
    const pMin = Number(protCfg.min);
    const pMax = Number(protCfg.max);
    const pTgt = Number(protCfg.target || protCfg.value);
    const fallbackG = Number(profile.daily_protein_target_g) || (weight ? Math.round(profPerKg * weight) : Math.round((calTarget * 0.25) / 4));
    if (protMode === 'min') {
      protMin = Math.round((pMin > 0 ? pMin : (pTgt > 0 ? pTgt : fallbackG)) * 10) / 10;
      protTarget = protMin;
    } else if (protMode === 'max') {
      protMax = Math.round((pMax > 0 ? pMax : (pTgt > 0 ? pTgt : fallbackG)) * 10) / 10;
      protTarget = protMax;
    } else {
      protMin = Math.round((pMin > 0 ? pMin : (pTgt || fallbackG) * 0.9) * 10) / 10;
      protMax = Math.round((pMax > 0 ? pMax : (pTgt || fallbackG) * 1.15) * 10) / 10;
      if (protMin > protMax) { const tmp = protMin; protMin = protMax; protMax = tmp; }
      protTarget = Math.round((pTgt > 0 ? pTgt : (protMin + protMax) / 2) * 10) / 10;
    }
    if (weight) {
      protPerKg = Math.round((protTarget / weight) * 100) / 100;
      protMinPerKg = protMin !== null ? Math.round((protMin / weight) * 100) / 100 : null;
      protMaxPerKg = protMax !== null ? Math.round((protMax / weight) * 100) / 100 : null;
    }
  } else if (weight) {
    const basePerKg = Number(protCfg.value || protCfg.target || protCfg.min) || profPerKg;
    if (protMode === 'min') {
      protMinPerKg = Math.round((Number(protCfg.min) > 0 ? Number(protCfg.min) : basePerKg) * 100) / 100;
      protMin = Math.round(protMinPerKg * weight * 10) / 10;
      protTarget = protMin;
      protPerKg = protMinPerKg;
    } else if (protMode === 'max') {
      protMaxPerKg = Math.round((Number(protCfg.max) > 0 ? Number(protCfg.max) : basePerKg) * 100) / 100;
      protMax = Math.round(protMaxPerKg * weight * 10) / 10;
      protTarget = protMax;
      protPerKg = protMaxPerKg;
    } else {
      protMinPerKg = Math.round((Number(protCfg.min) > 0 ? Number(protCfg.min) : basePerKg) * 100) / 100;
      protMaxPerKg = Math.round((Number(protCfg.max) > 0 ? Number(protCfg.max) : protMinPerKg + 0.4) * 100) / 100;
      if (protMinPerKg > protMaxPerKg) { const tmp = protMinPerKg; protMinPerKg = protMaxPerKg; protMaxPerKg = tmp; }
      protMin = Math.round(protMinPerKg * weight * 10) / 10;
      protMax = Math.round(protMaxPerKg * weight * 10) / 10;
      protTarget = Math.round(((protMin + protMax) / 2) * 10) / 10;
      protPerKg = Math.round(((protMinPerKg + protMaxPerKg) / 2) * 100) / 100;
    }
  } else {
    protTarget = Math.round((Number(profile.daily_protein_target_g) || (calTarget * 0.25) / 4) * 10) / 10;
    if (protMode === 'min') protMin = protTarget;
    else if (protMode === 'max') protMax = protTarget;
    else { protMin = Math.round(protTarget * 0.9 * 10) / 10; protMax = Math.round(protTarget * 1.15 * 10) / 10; }
  }

  // 3. Glucides
  const carbsCfg = Object.assign({}, presetRules.carbs, cfg.carbs || {});
  const carbsMode = ['min', 'max', 'range'].includes(carbsCfg.mode) ? carbsCfg.mode : 'range';
  const carbsSource = carbsCfg.source === 'fixed' ? 'fixed' : 'auto';
  const carbsTolLo = Number.isFinite(Number(carbsCfg.tolerance_low_pct)) ? Number(carbsCfg.tolerance_low_pct) : 15;
  const carbsTolHi = Number.isFinite(Number(carbsCfg.tolerance_high_pct)) ? Number(carbsCfg.tolerance_high_pct) : 15;
  const autoCarbs = Math.round(((calTarget * 0.45) / 4) * 10) / 10;

  let carbsTarget, carbsMin = null, carbsMax = null;
  if (carbsSource === 'fixed') {
    const cMin = Number(carbsCfg.min);
    const cMax = Number(carbsCfg.max);
    const cTgt = Number(carbsCfg.target);
    if (carbsMode === 'min') {
      carbsMin = Math.round((cMin > 0 ? cMin : (cTgt > 0 ? cTgt : autoCarbs)) * 10) / 10;
      carbsTarget = carbsMin;
    } else if (carbsMode === 'max') {
      carbsMax = Math.round((cMax > 0 ? cMax : (cTgt > 0 ? cTgt : autoCarbs)) * 10) / 10;
      carbsTarget = carbsMax;
    } else {
      carbsMin = Math.round((cMin > 0 ? cMin : (cTgt || autoCarbs) * (1 - carbsTolLo / 100)) * 10) / 10;
      carbsMax = Math.round((cMax > 0 ? cMax : (cTgt || autoCarbs) * (1 + carbsTolHi / 100)) * 10) / 10;
      if (carbsMin > carbsMax) { const tmp = carbsMin; carbsMin = carbsMax; carbsMax = tmp; }
      carbsTarget = Math.round((cTgt > 0 ? cTgt : (carbsMin + carbsMax) / 2) * 10) / 10;
    }
  } else {
    carbsTarget = autoCarbs;
    if (carbsMode === 'min') carbsMin = carbsTarget;
    else if (carbsMode === 'max') carbsMax = carbsTarget;
    else {
      carbsMin = Math.round(carbsTarget * (1 - carbsTolLo / 100) * 10) / 10;
      carbsMax = Math.round(carbsTarget * (1 + carbsTolHi / 100) * 10) / 10;
    }
  }

  // 4. Lipides
  const fatCfg = Object.assign({}, presetRules.fat, cfg.fat || {});
  const fatMode = ['min', 'max', 'range'].includes(fatCfg.mode) ? fatCfg.mode : 'range';
  const fatSource = fatCfg.source === 'fixed' ? 'fixed' : 'auto';
  const fatTolLo = Number.isFinite(Number(fatCfg.tolerance_low_pct)) ? Number(fatCfg.tolerance_low_pct) : 20;
  const fatTolHi = Number.isFinite(Number(fatCfg.tolerance_high_pct)) ? Number(fatCfg.tolerance_high_pct) : 10;
  const autoFat = Math.round(((calTarget * 0.30) / 9) * 10) / 10;

  let fatTarget, fatMin = null, fatMax = null;
  if (fatSource === 'fixed') {
    const fMin = Number(fatCfg.min);
    const fMax = Number(fatCfg.max);
    const fTgt = Number(fatCfg.target);
    if (fatMode === 'min') {
      fatMin = Math.round((fMin > 0 ? fMin : (fTgt > 0 ? fTgt : autoFat)) * 10) / 10;
      fatTarget = fatMin;
    } else if (fatMode === 'max') {
      fatMax = Math.round((fMax > 0 ? fMax : (fTgt > 0 ? fTgt : autoFat)) * 10) / 10;
      fatTarget = fatMax;
    } else {
      fatMin = Math.round((fMin > 0 ? fMin : (fTgt || autoFat) * (1 - fatTolLo / 100)) * 10) / 10;
      fatMax = Math.round((fMax > 0 ? fMax : (fTgt || autoFat) * (1 + fatTolHi / 100)) * 10) / 10;
      if (fatMin > fatMax) { const tmp = fatMin; fatMin = fatMax; fatMax = tmp; }
      fatTarget = Math.round((fTgt > 0 ? fTgt : (fatMin + fatMax) / 2) * 10) / 10;
    }
  } else {
    fatTarget = autoFat;
    if (fatMode === 'min') fatMin = fatTarget;
    else if (fatMode === 'max') fatMax = fatTarget;
    else {
      fatMin = Math.round(fatTarget * (1 - fatTolLo / 100) * 10) / 10;
      fatMax = Math.round(fatTarget * (1 + fatTolHi / 100) * 10) / 10;
    }
  }

  return {
    calories: calTarget,
    protein_g: protTarget,
    carbs_g: carbsTarget,
    fat_g: fatTarget,
    fiber_g: 25.0,
    protein_per_kg: protPerKg,
    weight_kg: weight,
    rules: {
      protein: { mode: protMode, target: protTarget, min: protMin, max: protMax, unit: 'g', input_unit: protUnit, per_kg: protPerKg, min_per_kg: protMinPerKg, max_per_kg: protMaxPerKg },
      calories: { mode: calMode, target: calTarget, min: calMin, max: calMax, unit: 'kcal', source: calSource, tolerance_low_pct: calTolLo, tolerance_high_pct: calTolHi },
      carbs: { mode: carbsMode, target: carbsTarget, min: carbsMin, max: carbsMax, unit: 'g', source: carbsSource, tolerance_low_pct: carbsTolLo, tolerance_high_pct: carbsTolHi },
      fat: { mode: fatMode, target: fatTarget, min: fatMin, max: fatMax, unit: 'g', source: fatSource, tolerance_low_pct: fatTolLo, tolerance_high_pct: fatTolHi },
    },
  };
}

function formatRulePreview(key, rule) {
  if (!rule) return '';
  const unit = rule.unit || (key === 'calories' ? 'kcal' : 'g');
  const fmt = (v) => Math.round(Number(v) || 0).toLocaleString('fr-FR');
  let base = '';
  if (rule.mode === 'min') {
    base = `≥ ${fmt(rule.min !== null ? rule.min : rule.target)} ${unit}/j`;
  } else if (rule.mode === 'max') {
    base = `≤ ${fmt(rule.max !== null ? rule.max : rule.target)} ${unit}/j`;
  } else {
    base = `${fmt(rule.min)} – ${fmt(rule.max)} ${unit}/j`;
  }
  if (key === 'protein' && rule.per_kg) {
    if (rule.mode === 'range' && rule.min_per_kg && rule.max_per_kg) {
      base += ` (${rule.min_per_kg}–${rule.max_per_kg} g/kg)`;
    } else {
      base += ` (${rule.per_kg} g/kg)`;
    }
  }
  return base;
}

function buildInitialDraftFromProfile() {
  const data = (typeof currentData !== 'undefined' && currentData) || {};
  const profile = data.profile || {};
  const goalId = profile.goal_profile_id || (typeof activeGoalProfileId !== 'undefined' ? activeGoalProfileId : 'weight_loss');
  const defaults = getPresetDefaultGoalsConfig(goalId);
  const saved = parseProfileGoalsConfig(profile.nutrition_goals_config);

  const merged = {
    protein: Object.assign({}, defaults.protein, saved.protein || {}),
    calories: Object.assign({}, defaults.calories, saved.calories || {}),
    carbs: Object.assign({}, defaults.carbs, saved.carbs || {}),
    fat: Object.assign({}, defaults.fat, saved.fat || {}),
  };

  // Si aucune config JSON sauvegardée mais protein_target_per_kg personnalisé en profil
  if (!saved.protein && profile.protein_target_per_kg) {
    merged.protein.min = Number(profile.protein_target_per_kg);
  }
  return merged;
}

function renderNutrientConfigCards() {
  const grid = document.getElementById('goals-nutrients-config-grid');
  if (!grid) return;
  if (!goalsDraftConfig) {
    goalsDraftConfig = buildInitialDraftFromProfile();
  }

  const weight = getEffectiveWeightKg();
  const refBadge = document.getElementById('goals-ref-weight-badge');
  if (refBadge) {
    refBadge.textContent = weight ? `Poids de référence : ${weight.toFixed(1)} kg` : 'Poids de référence : non renseigné';
  }

  const resolved = resolveNutritionTargetsFromConfig(goalsDraftConfig);
  grid.textContent = '';

  GOAL_NUTRIENT_META.forEach((meta) => {
    const key = meta.key;
    const nCfg = goalsDraftConfig[key];
    const resolvedRule = resolved.rules[key];

    const card = document.createElement('div');
    card.className = `p-4 rounded-2xl bg-[#0B0F17] border ${meta.accent} space-y-3`;

    // Header
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between gap-2';
    const title = document.createElement('div');
    title.className = 'font-bold text-sm text-white flex items-center gap-1.5';
    title.textContent = `${meta.emoji} ${meta.label}`;
    const preview = document.createElement('span');
    preview.id = `goal-preview-${key}`;
    preview.className = `text-[11px] font-bold px-2.5 py-0.5 rounded-full border ${meta.badge}`;
    preview.textContent = formatRulePreview(key, resolvedRule);
    header.appendChild(title);
    header.appendChild(preview);
    card.appendChild(header);

    if (key === 'calories' && resolvedRule.source !== 'fixed') {
      const dataObj = (typeof currentData !== 'undefined' && currentData) || {};
      const dyn = (dataObj.summary && dataObj.summary.dynamic_tdee) || null;
      if (dyn && Number(dyn.bmr_kcal) > 0) {
        const formulaBox = document.createElement('div');
        formulaBox.id = 'goal-calories-formula-breakdown';
        formulaBox.className = 'text-[11px] text-slate-300 bg-[#13132B]/70 border border-[#25254A] rounded-xl px-3 py-2 leading-relaxed';
        const bmrVal = Math.round(Number(dyn.bmr_kcal) || 0);
        const baseNeatVal = Math.round(Number(dyn.base_neat_kcal) || 0);
        const stepsVal = Math.round(Number(dyn.neat_steps_kcal) || 0);
        const effSteps = Number(dyn.effective_steps) || 0;
        const workoutVal = Math.round(Number(dyn.workout_calories_kcal) || 0);
        const profObj = (typeof GOAL_PROFILES !== 'undefined' && GOAL_PROFILES[resolved.goal_profile_id]) || { delta: Number(dyn.goal_delta) || 0 };
        const deltaVal = Math.round(Number(profObj.delta ?? dyn.goal_delta) || 0);
        const deltaStr = deltaVal >= 0 ? `+${deltaVal}` : `${deltaVal}`;
        const targetVal = Math.round(Number(resolvedRule.target) || 0);
        formulaBox.textContent = `Formule : BMR ${bmrVal} + Activité ${baseNeatVal} + Marche ${stepsVal} (${effSteps.toLocaleString('fr-FR')} pas) + Séances ${workoutVal} ${deltaStr} kcal = ${targetVal} kcal`;
        card.appendChild(formulaBox);
      }
    }

    // Row 1 : Mode (Plancher / Plafond / Fourchette) + Source/Unité
    const controlsRow = document.createElement('div');
    controlsRow.className = 'grid grid-cols-1 sm:grid-cols-2 gap-2.5';

    // Mode select
    const modeWrap = document.createElement('div');
    const modeLbl = document.createElement('label');
    modeLbl.className = 'block text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1';
    modeLbl.textContent = 'Type de règle';
    const modeSel = document.createElement('select');
    modeSel.id = `goal-mode-${key}`;
    modeSel.className = 'w-full bg-[#13132B] border border-[#25254A] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500';
    [
      { value: 'min', label: 'Seuil plancher (≥ min)' },
      { value: 'max', label: 'Plafond (≤ max)' },
      { value: 'range', label: 'Fourchette ([min – max])' },
    ].forEach((opt) => {
      const o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      if (nCfg.mode === opt.value) o.selected = true;
      modeSel.appendChild(o);
    });
    modeSel.addEventListener('change', () => {
      const prevMode = nCfg.mode;
      nCfg.mode = modeSel.value;
      // Pré-remplir intelligemment les bornes lors du changement de mode
      if (key === 'protein') {
        const curVal = Number(nCfg.min || nCfg.max || (nCfg.unit === 'g' ? resolvedRule.target : (resolvedRule.per_kg || 1.8)));
        if (nCfg.mode === 'min') { nCfg.min = curVal; nCfg.max = null; }
        else if (nCfg.mode === 'max') { nCfg.max = curVal; nCfg.min = null; }
        else {
          nCfg.min = Number(nCfg.min || curVal);
          nCfg.max = Number(nCfg.max || (nCfg.unit === 'g' ? Math.round(nCfg.min * 1.2) : Math.round((nCfg.min + 0.4) * 10) / 10));
        }
      } else if (nCfg.source === 'fixed') {
        const refTgt = Math.round(resolvedRule.target || 0);
        if (nCfg.mode === 'min') { nCfg.min = nCfg.min || refTgt; nCfg.max = null; }
        else if (nCfg.mode === 'max') { nCfg.max = nCfg.max || refTgt; nCfg.min = null; }
        else if (prevMode !== 'range') {
          nCfg.min = nCfg.min || Math.round(refTgt * 0.9);
          nCfg.max = nCfg.max || Math.round(refTgt * 1.1);
        }
      }
      renderNutrientConfigCards();
    });
    modeWrap.appendChild(modeLbl);
    modeWrap.appendChild(modeSel);
    controlsRow.appendChild(modeWrap);

    // Source / Unité select
    const srcWrap = document.createElement('div');
    const srcLbl = document.createElement('label');
    srcLbl.className = 'block text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1';
    srcLbl.textContent = meta.isProtein ? 'Unité de calcul' : 'Mode de calcul';
    const srcSel = document.createElement('select');
    srcSel.id = `goal-source-${key}`;
    srcSel.className = 'w-full bg-[#13132B] border border-[#25254A] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500';
    const srcOptions = meta.isProtein
      ? [
          { value: 'per_kg', label: 'Proportionnel au poids (g/kg)' },
          { value: 'g', label: 'Valeur fixe (g/jour)' },
        ]
      : meta.isCalories
        ? [
            { value: 'dynamic', label: 'Dynamique (TDEE + profil)' },
            { value: 'fixed', label: 'Valeur fixe (kcal/jour)' },
          ]
        : [
            { value: 'auto', label: 'Auto (% des calories)' },
            { value: 'fixed', label: 'Valeur fixe (g/jour)' },
          ];
    const currentSrc = meta.isProtein ? (nCfg.unit || 'per_kg') : (nCfg.source || (meta.isCalories ? 'dynamic' : 'auto'));
    srcOptions.forEach((opt) => {
      const o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      if (currentSrc === opt.value) o.selected = true;
      srcSel.appendChild(o);
    });
    srcSel.addEventListener('change', () => {
      if (meta.isProtein) {
        const newUnit = srcSel.value;
        if (newUnit === 'g' && nCfg.unit !== 'g') {
          nCfg.unit = 'g';
          nCfg.min = resolvedRule.min !== null ? Math.round(resolvedRule.min) : Math.round(resolvedRule.target);
          nCfg.max = resolvedRule.max !== null ? Math.round(resolvedRule.max) : (nCfg.mode === 'range' ? Math.round(resolvedRule.target * 1.15) : null);
        } else if (newUnit === 'per_kg' && nCfg.unit !== 'per_kg') {
          nCfg.unit = 'per_kg';
          const w = weight || 80;
          nCfg.min = resolvedRule.min !== null ? Math.round((resolvedRule.min / w) * 10) / 10 : 1.8;
          nCfg.max = resolvedRule.max !== null ? Math.round((resolvedRule.max / w) * 10) / 10 : (nCfg.mode === 'range' ? Math.round((nCfg.min + 0.4) * 10) / 10 : null);
        }
      } else {
        nCfg.source = srcSel.value;
        if (nCfg.source === 'fixed') {
          nCfg.target = Math.round(resolvedRule.target);
          if (nCfg.mode === 'min') { nCfg.min = Math.round(resolvedRule.min || resolvedRule.target); nCfg.max = null; }
          else if (nCfg.mode === 'max') { nCfg.max = Math.round(resolvedRule.max || resolvedRule.target); nCfg.min = null; }
          else {
            nCfg.min = Math.round(resolvedRule.min || resolvedRule.target * 0.9);
            nCfg.max = Math.round(resolvedRule.max || resolvedRule.target * 1.1);
          }
        }
      }
      renderNutrientConfigCards();
    });
    srcWrap.appendChild(srcLbl);
    srcWrap.appendChild(srcSel);
    controlsRow.appendChild(srcWrap);
    card.appendChild(controlsRow);

    // Row 2 : Valeurs précises (bornes min/max ou tolérances %)
    const valuesRow = document.createElement('div');
    valuesRow.className = 'grid grid-cols-1 sm:grid-cols-2 gap-2.5';

    const makeNumberField = (id, label, value, step, minAttr, maxAttr, onChange) => {
      const wrap = document.createElement('div');
      const lbl = document.createElement('label');
      lbl.className = 'block text-[10px] font-semibold text-slate-400 mb-1';
      lbl.textContent = label;
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.id = id;
      inp.step = String(step);
      inp.min = String(minAttr);
      inp.max = String(maxAttr);
      inp.value = value !== null && value !== undefined ? String(value) : '';
      inp.className = 'w-full bg-[#13132B] border border-[#25254A] rounded-lg px-2.5 py-1.5 text-sm font-bold text-white focus:outline-none focus:border-brand-500';
      inp.addEventListener('input', () => {
        const num = parseFloat(inp.value);
        if (Number.isFinite(num)) {
          onChange(num);
          const nextResolved = resolveNutritionTargetsFromConfig(goalsDraftConfig);
          const pEl = document.getElementById(`goal-preview-${key}`);
          if (pEl) pEl.textContent = formatRulePreview(key, nextResolved.rules[key]);
        }
      });
      wrap.appendChild(lbl);
      wrap.appendChild(inp);
      return wrap;
    };

    if (meta.isProtein) {
      const isPerKg = (nCfg.unit || 'per_kg') === 'per_kg';
      const uLbl = isPerKg ? 'g/kg' : 'g/j';
      const step = isPerKg ? 0.1 : 5;
      const minA = isPerKg ? 0.5 : 20;
      const maxA = isPerKg ? 4.0 : 500;
      if (nCfg.mode === 'min' || nCfg.mode === 'range') {
        const curMin = nCfg.min !== null && nCfg.min !== undefined ? nCfg.min : (isPerKg ? 1.8 : Math.round(resolvedRule.target));
        valuesRow.appendChild(makeNumberField(`goal-min-${key}`, `Seuil minimum (${uLbl})`, curMin, step, minA, maxA, (v) => { nCfg.min = v; }));
      }
      if (nCfg.mode === 'max' || nCfg.mode === 'range') {
        const curMax = nCfg.max !== null && nCfg.max !== undefined ? nCfg.max : (isPerKg ? 2.2 : Math.round(resolvedRule.target));
        valuesRow.appendChild(makeNumberField(`goal-max-${key}`, `Plafond maximum (${uLbl})`, curMax, step, minA, maxA, (v) => { nCfg.max = v; }));
      }
    } else if (nCfg.source === 'fixed') {
      const uLbl = meta.unit;
      const step = meta.isCalories ? 25 : 5;
      const minA = meta.isCalories ? 800 : 10;
      const maxA = meta.isCalories ? 6000 : 1000;
      if (nCfg.mode === 'min' || nCfg.mode === 'range') {
        const curMin = nCfg.min !== null && nCfg.min !== undefined ? nCfg.min : Math.round(resolvedRule.min || resolvedRule.target);
        valuesRow.appendChild(makeNumberField(`goal-min-${key}`, `Seuil minimum (${uLbl})`, curMin, step, minA, maxA, (v) => { nCfg.min = v; }));
      }
      if (nCfg.mode === 'max' || nCfg.mode === 'range') {
        const curMax = nCfg.max !== null && nCfg.max !== undefined ? nCfg.max : Math.round(resolvedRule.max || resolvedRule.target);
        valuesRow.appendChild(makeNumberField(`goal-max-${key}`, `Plafond maximum (${uLbl})`, curMax, step, minA, maxA, (v) => { nCfg.max = v; }));
      }
    } else {
      // Dynamic / Auto mode
      if (nCfg.mode === 'range') {
        valuesRow.appendChild(makeNumberField(
          `goal-tol-lo-${key}`,
          'Tolérance basse (-%)',
          nCfg.tolerance_low_pct !== undefined ? nCfg.tolerance_low_pct : 10,
          1, 0, 50,
          (v) => { nCfg.tolerance_low_pct = v; }
        ));
        valuesRow.appendChild(makeNumberField(
          `goal-tol-hi-${key}`,
          'Tolérance haute (+%)',
          nCfg.tolerance_high_pct !== undefined ? nCfg.tolerance_high_pct : 10,
          1, 0, 50,
          (v) => { nCfg.tolerance_high_pct = v; }
        ));
      } else {
        const info = document.createElement('div');
        info.className = 'sm:col-span-2 text-[11px] text-slate-400 bg-[#13132B] border border-[#25254A] rounded-lg px-3 py-2';
        info.textContent = nCfg.mode === 'min'
          ? `Calculé automatiquement : atteindre au moins ${Math.round(resolvedRule.target).toLocaleString('fr-FR')} ${meta.unit}/j.`
          : `Calculé automatiquement : ne pas dépasser ${Math.round(resolvedRule.target).toLocaleString('fr-FR')} ${meta.unit}/j.`;
        valuesRow.appendChild(info);
      }
    }

    card.appendChild(valuesRow);
    grid.appendChild(card);
  });
}

function applyResolvedTargetsAcrossApp(resolved, profileUpdates = {}) {
  if (typeof currentData === 'undefined' || !currentData) return;
  if (!currentData.profile) currentData.profile = {};
  Object.assign(currentData.profile, profileUpdates);

  if (!currentData.summary) currentData.summary = {};
  currentData.summary.target_calories_intake = resolved.calories;
  currentData.summary.targets = resolved;
  if (profileUpdates.target_steps) currentData.summary.steps_target = profileUpdates.target_steps;
  if (profileUpdates.target_weight_kg) currentData.summary.target_weight_kg = profileUpdates.target_weight_kg;

  if (currentData.daily_goals_history) {
    currentData.daily_goals_history.targets = {
      protein_g: resolved.protein_g,
      calories: resolved.calories,
      carbs_g: resolved.carbs_g,
      fat_g: resolved.fat_g,
    };
    currentData.daily_goals_history.rules = resolved.rules;
  }

  if (typeof currentJournalData !== 'undefined' && currentJournalData) {
    currentJournalData.targets = resolved;
  }

  if (typeof renderSummaryView === 'function') renderSummaryView();
  if (typeof renderAllMacroGoalsPanels === 'function') renderAllMacroGoalsPanels();
  if (typeof renderNutritionView === 'function') renderNutritionView();
  if (typeof renderMealsJournal === 'function' && typeof currentJournalData !== 'undefined' && currentJournalData) {
    renderMealsJournal();
  }
  if (typeof renderWeightSummaryChart === 'function') renderWeightSummaryChart();
  if (typeof renderWeightView === 'function') renderWeightView();
}

function selectGoalProfile(profileId, persist = true) {
  if (typeof GOAL_PROFILES === 'undefined' || !GOAL_PROFILES[profileId]) return;
  activeGoalProfileId = profileId;
  const p = GOAL_PROFILES[profileId];

  const titleEl = document.getElementById('active-goal-title');
  const descEl = document.getElementById('active-goal-desc');
  if (titleEl) titleEl.innerText = p.title;
  if (descEl) descEl.innerText = p.desc;

  ['weight_loss', 'maintenance', 'recomposition', 'muscle_gain'].forEach((id) => {
    const btn = document.getElementById(`btn-goal-${id}`);
    if (!btn) return;
    const statusSpan = btn.querySelector('.text-brand-400, .text-emerald-400, .text-slate-500, .text-slate-400:last-child');
    if (id === profileId) {
      btn.className = 'goal-btn text-left p-3.5 rounded-xl border-2 border-brand-500 bg-brand-500/10 transition-all flex flex-col justify-between space-y-2';
      if (statusSpan) {
        statusSpan.className = 'text-emerald-400 font-medium';
        statusSpan.innerText = 'Actif ✓';
      }
    } else {
      btn.className = 'goal-btn text-left p-3.5 rounded-xl border border-[#25254A] bg-[#0B0F17] hover:border-slate-600 transition-all flex flex-col justify-between space-y-2';
      if (statusSpan) {
        statusSpan.className = 'text-slate-400';
        statusSpan.innerText = 'Choisir';
      }
    }
  });

  if (persist) {
    // Lors d'un clic utilisateur sur un préréglage : réinitialiser les règles au préréglage choisi
    goalsDraftConfig = getPresetDefaultGoalsConfig(profileId);
    const newTargetCalories = getDynamicCaloriesBase(profileId);
    const stepsInp = document.getElementById('goal-target-steps-input');
    const stepsVal = document.getElementById('goal-target-steps-value');
    if (stepsInp) stepsInp.value = String(p.steps);
    if (stepsVal) stepsVal.textContent = `${p.steps.toLocaleString('fr-FR')} pas`;

    const resolved = resolveNutritionTargetsFromConfig(goalsDraftConfig, {
      goalProfileId: profileId,
      dynamicCalories: newTargetCalories,
    });

    if (typeof currentData !== 'undefined' && currentData && currentData.summary) {
      currentData.summary.recommendation = p.recommendation;
    }

    const profileUpdates = {
      goal_profile_id: profileId,
      target_calories_intake: newTargetCalories,
      target_steps: p.steps,
      protein_target_per_kg: p.protein_per_kg,
      daily_protein_target_g: null,
      daily_carbs_target_g: null,
      daily_fat_target_g: null,
      nutrition_goals_config: cloneObj(goalsDraftConfig),
    };

    applyResolvedTargetsAcrossApp(resolved, profileUpdates);
    renderNutrientConfigCards();

    const isReadOnly = Boolean(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active);
    if (!isReadOnly && typeof apiFetch === 'function') {
      apiFetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profileUpdates),
      }).then((res) => {
        if (res && res.ok) {
          if (typeof invalidateJournalCache === 'function') invalidateJournalCache();
          if (typeof showToast === 'function') showToast(`Profil objectif « ${p.title} » enregistré`, 'success');
        }
      }).catch((err) => console.warn('[Goals] Persistance profil objectif échouée:', err));
    }
  } else {
    renderNutrientConfigCards();
  }
}

function resetGoalsToActivePreset() {
  const pid = (typeof activeGoalProfileId !== 'undefined' && activeGoalProfileId) || 'weight_loss';
  selectGoalProfile(pid, true);
}

async function saveNutritionGoalsConfig() {
  const isReadOnly = Boolean(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active);
  if (isReadOnly) return;

  if (!goalsDraftConfig) {
    goalsDraftConfig = buildInitialDraftFromProfile();
  }

  const pid = (typeof activeGoalProfileId !== 'undefined' && activeGoalProfileId) || 'weight_loss';
  const weightInp = document.getElementById('goal-target-weight-input');
  const stepsInp = document.getElementById('goal-target-steps-input');
  const waterInp = document.getElementById('goal-target-water-input');

  const targetWeight = weightInp ? Math.min(300, Math.max(30, parseFloat(weightInp.value) || 77)) : undefined;
  const targetSteps = stepsInp ? Math.min(50000, Math.max(1000, parseInt(stepsInp.value, 10) || 10000)) : undefined;
  const targetWater = waterInp ? Math.min(10000, Math.max(500, parseFloat(waterInp.value) || 2000)) : undefined;

  const resolved = resolveNutritionTargetsFromConfig(goalsDraftConfig, { goalProfileId: pid });
  const protRule = resolved.rules.protein;
  const carbsRule = resolved.rules.carbs;
  const fatRule = resolved.rules.fat;

  const payload = {
    goal_profile_id: pid,
    target_calories_intake: resolved.calories,
    protein_target_per_kg: protRule.per_kg ? Math.min(3.5, Math.max(0.8, protRule.per_kg)) : 1.8,
    daily_protein_target_g: protRule.input_unit === 'g' ? protRule.target : null,
    daily_carbs_target_g: carbsRule.source === 'fixed' ? carbsRule.target : null,
    daily_fat_target_g: fatRule.source === 'fixed' ? fatRule.target : null,
    nutrition_goals_config: cloneObj(goalsDraftConfig),
  };
  if (targetWeight !== undefined) payload.target_weight_kg = targetWeight;
  if (targetSteps !== undefined) payload.target_steps = targetSteps;
  if (targetWater !== undefined) payload.daily_water_target_ml = targetWater;

  const btn = document.getElementById('btn-save-nutrition-goals');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Enregistrement...';
  }

  try {
    applyResolvedTargetsAcrossApp(resolved, payload);
    const res = await apiFetch('/api/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res && res.ok) {
      if (typeof invalidateJournalCache === 'function') invalidateJournalCache();
      if (typeof showToast === 'function') showToast('✓ Objectifs et règles enregistrés et synchronisés sur tous les onglets', 'success');
    } else if (typeof showToast === 'function') {
      showToast('Erreur lors de la sauvegarde des objectifs', 'error');
    }
  } catch (err) {
    console.warn('[Goals] Erreur sauvegarde objectifs:', err);
    if (typeof showToast === 'function') showToast('Erreur réseau lors de la sauvegarde', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Enregistrer les objectifs';
    }
  }
}

// Initialisation au chargement de la page
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (_e) {} }
  initDates();
  loadDashboardData();
  loadUnifiedAuthState();
  if (typeof loadFriendsData === 'function') {
    loadFriendsData();
  }
  initGoalWeightInput();
});

// Gestion des champs rapides (poids cible, pas, hydratation) dans l'onglet Objectifs
function initGoalWeightInput() {
  const targetWeightInput = document.getElementById('goal-target-weight-input');
  const targetWeightValue = document.getElementById('goal-target-weight-value');
  const targetStepsInput = document.getElementById('goal-target-steps-input');
  const targetStepsValue = document.getElementById('goal-target-steps-value');
  const targetWaterInput = document.getElementById('goal-target-water-input');
  const targetWaterValue = document.getElementById('goal-target-water-value');

  if (targetStepsInput && targetStepsValue) {
    targetStepsInput.addEventListener('input', () => {
      const val = parseInt(targetStepsInput.value, 10) || 10000;
      targetStepsValue.textContent = `${val.toLocaleString('fr-FR')} pas`;
    });
  }
  if (targetWaterInput && targetWaterValue) {
    targetWaterInput.addEventListener('input', () => {
      const val = parseInt(targetWaterInput.value, 10) || 2000;
      targetWaterValue.textContent = `${val.toLocaleString('fr-FR')} ml`;
    });
  }

  if (!targetWeightInput) return;

  let saving = false;
  const saveTargetWeight = async (weightKg) => {
    if (saving) return;
    saving = true;
    try {
      const res = await apiFetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_weight_kg: weightKg }),
      });
      if (res.ok) {
        const body = await res.json();
        const profile = body.profile || body;
        if (targetWeightValue && profile.target_weight_kg) {
          targetWeightValue.innerText = `${profile.target_weight_kg} kg`;
        }
        if (typeof currentData !== 'undefined' && currentData) {
          if (currentData.profile) currentData.profile.target_weight_kg = weightKg;
          if (currentData.summary) currentData.summary.target_weight_kg = weightKg;
        }
        if (typeof renderWeightSummaryChart === 'function') renderWeightSummaryChart();
        if (typeof renderWeightView === 'function') renderWeightView();
      }
    } catch (err) {
      console.warn('Erreur mise à jour poids cible :', err);
    } finally {
      saving = false;
    }
  };

  targetWeightInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const weight = parseFloat(targetWeightInput.value) || 77;
      if (weight >= 30 && weight <= 300) saveTargetWeight(weight);
    }
  });

  let focusLossTimeout = null;
  targetWeightInput.addEventListener('blur', () => {
    clearTimeout(focusLossTimeout);
    focusLossTimeout = setTimeout(() => {
      const weight = parseFloat(targetWeightInput.value) || 77;
      if (weight >= 30 && weight <= 300) saveTargetWeight(weight);
    }, 500);
  });

  targetWeightInput.addEventListener('input', () => {
    const weight = parseFloat(targetWeightInput.value) || 77;
    if (targetWeightValue) targetWeightValue.innerText = `${weight} kg`;
  });
}

function renderGoalsView() {
  if (typeof currentData !== 'undefined' && currentData && currentData.profile) {
    const prof = currentData.profile;
    if (prof.goal_profile_id && typeof GOAL_PROFILES !== 'undefined' && GOAL_PROFILES[prof.goal_profile_id]) {
      activeGoalProfileId = prof.goal_profile_id;
    }
    if (prof.target_weight_kg) {
      const targetWeight = Number(prof.target_weight_kg);
      const inputEl = document.getElementById('goal-target-weight-input');
      const valEl = document.getElementById('goal-target-weight-value');
      if (inputEl) inputEl.value = targetWeight.toFixed(1);
      if (valEl) valEl.textContent = `${targetWeight.toFixed(1)} kg`;
    }
    if (prof.target_steps) {
      const steps = parseInt(prof.target_steps, 10);
      const inputEl = document.getElementById('goal-target-steps-input');
      const valEl = document.getElementById('goal-target-steps-value');
      if (inputEl) inputEl.value = String(steps);
      if (valEl) valEl.textContent = `${steps.toLocaleString('fr-FR')} pas`;
    }
    if (prof.daily_water_target_ml) {
      const water = Math.round(Number(prof.daily_water_target_ml));
      const inputEl = document.getElementById('goal-target-water-input');
      const valEl = document.getElementById('goal-target-water-value');
      if (inputEl) inputEl.value = String(water);
      if (valEl) valEl.textContent = `${water.toLocaleString('fr-FR')} ml`;
    }
  }
  goalsDraftConfig = buildInitialDraftFromProfile();
  if (typeof activeGoalProfileId !== 'undefined') {
    selectGoalProfile(activeGoalProfileId, false);
  }
}

window.renderGoalsView = renderGoalsView;
window.selectGoalProfile = selectGoalProfile;
window.initGoalWeightInput = initGoalWeightInput;
window.saveNutritionGoalsConfig = saveNutritionGoalsConfig;
window.resetGoalsToActivePreset = resetGoalsToActivePreset;
window.resolveNutritionTargetsFromConfig = resolveNutritionTargetsFromConfig;
window.formatRulePreview = formatRulePreview;
