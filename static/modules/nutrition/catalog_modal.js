// static/modules/nutrition/catalog_modal.js - Modale création/édition aliment & composition plat

// ============================================================================
// GESTION DE LA COMPOSITION D'INGRÉDIENTS DU PLAT & PRÉCALCUL (STAGE 14)
// ============================================================================

function toggleDishCompositionSection(isDish) {
  const sec = document.getElementById('dish-composition-section');
  if (sec) {
    if (isDish) {
      sec.classList.remove('hidden');
      populateDishIngredientSelect();
    } else {
      sec.classList.add('hidden');
    }
  }
}

function handleCatItemTypeChange(event) {
  const isDish = event.target.value === 'dish';
  toggleDishCompositionSection(isDish);
  const unitSelect = document.getElementById('cat-item-unit');
  const qtyInput = document.getElementById('cat-item-qty');
  const catSelect = document.getElementById('cat-item-category');
  if (isDish) {
    if (unitSelect) unitSelect.value = 'portion';
    if (qtyInput) qtyInput.value = '1';
    if (catSelect && catSelect.value === 'autre') catSelect.value = 'plats_composes';
  } else {
    if (unitSelect) unitSelect.value = 'g';
    if (qtyInput) qtyInput.value = '100';
    if (catSelect && catSelect.value === 'plats_composes') catSelect.value = 'autre';
  }
}

function populateDishIngredientSelect() {
  const sel = document.getElementById('dish-ingredient-select');
  if (!sel) return;

  let html = '<option value="">-- Choisir un aliment existant à ajouter --</option>';

  const catalogFoods = currentCatalogItems.filter(it => it.item_type === 'food');
  if (catalogFoods.length > 0) {
    html += '<optgroup label="📋 Aliments de mon catalogue">';
    catalogFoods.forEach(f => {
      html += `<option value="cat_${escapeHtml(f.id)}">${escapeHtml(f.name)} (${escapeHtml(f.default_quantity)}${escapeHtml(f.default_unit)} = ${Math.round(f.calories_per_unit)} kcal)</option>`;
    });
    html += '</optgroup>';
  }

  html += '<optgroup label="🥖 Ingrédients essentiels recommandés">';
  RECOMMENDED_STAPLE_INGREDIENTS.forEach((s, idx) => {
    html += `<option value="staple_${idx}">${s.emoji || '🥗'} ${s.label}</option>`;
  });
  html += '</optgroup>';

  sel.innerHTML = html;
  handleDishIngredientSelectChange();
}

function handleDishIngredientSelectChange() {
  const sel = document.getElementById('dish-ingredient-select');
  const qtyInput = document.getElementById('dish-ingredient-add-qty');
  const unitLabel = document.getElementById('dish-ingredient-add-unit');
  if (!sel || !qtyInput) return;

  const val = sel.value;
  if (!val) {
    qtyInput.value = '100';
    if (unitLabel) unitLabel.textContent = 'g';
    return;
  }

  if (val.startsWith('cat_')) {
    const id = parseInt(val.replace('cat_', ''), 10);
    const item = currentCatalogItems.find(it => it.id === id);
    if (item) {
      qtyInput.value = item.default_quantity || 100;
      if (unitLabel) unitLabel.textContent = item.default_unit || 'g';
    }
  } else if (val.startsWith('staple_')) {
    const idx = parseInt(val.replace('staple_', ''), 10);
    const s = RECOMMENDED_STAPLE_INGREDIENTS[idx];
    if (s) {
      qtyInput.value = s.default_quantity || 100;
      if (unitLabel) unitLabel.textContent = s.default_unit || 'g';
    }
  }
}

function addIngredientToDish() {
  const sel = document.getElementById('dish-ingredient-select');
  const qtyInput = document.getElementById('dish-ingredient-add-qty');
  if (!sel || !qtyInput) return;

  const val = sel.value;
  if (!val) {
    alert("Veuillez sélectionner un aliment dans la liste.");
    return;
  }

  const qty = parseFloat(qtyInput.value);
  if (isNaN(qty) || qty <= 0) {
    alert("Veuillez saisir une quantité valide supérieure à 0.");
    return;
  }

  let ingredientData = null;
  if (val.startsWith('cat_')) {
    const id = parseInt(val.replace('cat_', ''), 10);
    const item = currentCatalogItems.find(it => it.id === id);
    if (item) {
      ingredientData = {
        food_item_id: item.id,
        name: item.name,
        quantity: qty,
        unit: item.default_unit || 'g',
        default_quantity: item.default_quantity || 100.0,
        calories_per_unit: item.calories_per_unit || 0.0,
        protein_per_unit_g: item.protein_per_unit_g || 0.0,
        carbs_per_unit_g: item.carbs_per_unit_g || 0.0,
        fat_per_unit_g: item.fat_per_unit_g || 0.0,
        fiber_per_unit_g: item.fiber_per_unit_g || 0.0
      };
    }
  } else if (val.startsWith('staple_')) {
    const idx = parseInt(val.replace('staple_', ''), 10);
    const s = RECOMMENDED_STAPLE_INGREDIENTS[idx];
    if (s) {
      ingredientData = {
        food_item_id: null,
        name: s.name,
        quantity: qty,
        unit: s.default_unit || 'g',
        default_quantity: s.default_quantity || 100.0,
        calories_per_unit: s.calories_per_unit || 0.0,
        protein_per_unit_g: s.protein_per_unit_g || 0.0,
        carbs_per_unit_g: s.carbs_per_unit_g || 0.0,
        fat_per_unit_g: s.fat_per_unit_g || 0.0,
        fiber_per_unit_g: s.fiber_per_unit_g || 0.0
      };
    }
  }

  if (ingredientData) {
    modalDishIngredients.push(ingredientData);
    renderDishIngredientsList();
    recalculateDishFromIngredients();
    if (typeof showToast === 'function') {
      showToast(`'${ingredientData.name}' (${qty}${ingredientData.unit}) ajouté au plat !`, 'info');
    }
  }
}

function removeDishIngredient(index) {
  if (index >= 0 && index < modalDishIngredients.length) {
    modalDishIngredients.splice(index, 1);
    renderDishIngredientsList();
    recalculateDishFromIngredients();
  }
}

function updateDishIngredientQuantity(index, newQtyStr) {
  const newQty = parseFloat(newQtyStr);
  if (isNaN(newQty) || newQty <= 0) return;
  if (modalDishIngredients[index]) {
    modalDishIngredients[index].quantity = newQty;
    recalculateDishFromIngredients();
  }
}

function recalculateDishFromIngredients() {
  const countEl = document.getElementById('dish-ingredients-count');
  if (countEl) countEl.textContent = modalDishIngredients.length;

  if (modalDishIngredients.length === 0) {
    updateDishPrecalcDisplay(0, 0, 0, 0, 0, 0);
    return;
  }

  let totalCals = 0;
  let totalProt = 0;
  let totalCarbs = 0;
  let totalFat = 0;
  let totalFiber = 0;
  let totalWeight = 0;

  modalDishIngredients.forEach(ing => {
    const ratio = (parseFloat(ing.quantity) || 0) / (parseFloat(ing.default_quantity) || 100.0);
    const cals = (parseFloat(ing.calories_per_unit) || 0) * ratio;
    const prot = (parseFloat(ing.protein_per_unit_g) || 0) * ratio;
    const carbs = (parseFloat(ing.carbs_per_unit_g) || 0) * ratio;
    const fat = (parseFloat(ing.fat_per_unit_g) || 0) * ratio;
    const fiber = (parseFloat(ing.fiber_per_unit_g) || 0) * ratio;

    ing.calories = Math.round(cals * 10) / 10;
    ing.protein_g = Math.round(prot * 10) / 10;
    ing.carbs_g = Math.round(carbs * 10) / 10;
    ing.fat_g = Math.round(fat * 10) / 10;
    ing.fiber_g = Math.round(fiber * 10) / 10;

    totalCals += cals;
    totalProt += prot;
    totalCarbs += carbs;
    totalFat += fat;
    totalFiber += fiber;
    if (ing.unit === 'g') totalWeight += parseFloat(ing.quantity) || 0;
  });

  const calsRounded = Math.round(totalCals);
  const protRounded = Math.round(totalProt * 10) / 10;
  const carbsRounded = Math.round(totalCarbs * 10) / 10;
  const fatRounded = Math.round(totalFat * 10) / 10;
  const fiberRounded = Math.round(totalFiber * 10) / 10;

  const calsInput = document.getElementById('cat-item-cals');
  const protInput = document.getElementById('cat-item-prot');
  const carbsInput = document.getElementById('cat-item-carbs');
  const fatInput = document.getElementById('cat-item-fat');
  const fiberInput = document.getElementById('cat-item-fiber');

  if (calsInput) calsInput.value = calsRounded;
  if (protInput) protInput.value = protRounded;
  if (carbsInput) carbsInput.value = carbsRounded;
  if (fatInput) fatInput.value = fatRounded;
  if (fiberInput) fiberInput.value = fiberRounded;

  updateDishPrecalcDisplay(calsRounded, protRounded, carbsRounded, fatRounded, fiberRounded, totalWeight);

  if (typeof triggerModalNutritionEvaluation === 'function') {
    triggerModalNutritionEvaluation();
  }
}

function updateDishPrecalcDisplay(cals, prot, carbs, fat, fiber, weight) {
  const elCals = document.getElementById('dish-precalc-total-cals');
  const elWeight = document.getElementById('dish-precalc-total-weight');
  const elProt = document.getElementById('dish-precalc-prot');
  const elCarbs = document.getElementById('dish-precalc-carbs');
  const elFat = document.getElementById('dish-precalc-fat');
  const elFiber = document.getElementById('dish-precalc-fiber');

  if (elCals) elCals.textContent = `${cals} kcal`;
  if (elWeight) elWeight.textContent = weight > 0 ? `Poids total: ${Math.round(weight)}g` : '';
  if (elProt) elProt.textContent = `P: ${prot}g`;
  if (elCarbs) elCarbs.textContent = `G: ${carbs}g`;
  if (elFat) elFat.textContent = `L: ${fat}g`;
  if (elFiber) elFiber.textContent = `Fibres: ${fiber}g`;
}

function renderDishIngredientsList() {
  const container = document.getElementById('dish-ingredients-list');
  const countEl = document.getElementById('dish-ingredients-count');
  if (countEl) countEl.textContent = modalDishIngredients.length;
  if (!container) return;

  if (modalDishIngredients.length === 0) {
    container.innerHTML = `
      <div class="py-4 text-center text-xs text-slate-500 italic bg-[#151D2A]/50 rounded-xl border border-dashed border-[#1F2A3C] p-3">
        Aucun ingrédient ajouté pour l'instant. Choisissez un aliment ci-dessus pour composer votre plat.
      </div>
    `;
    return;
  }

  container.innerHTML = modalDishIngredients.map((ing, idx) => {
    const ratio = (parseFloat(ing.quantity) || 0) / (parseFloat(ing.default_quantity) || 100.0);
    const cals = Math.round((parseFloat(ing.calories_per_unit) || 0) * ratio);
    const p = Math.round((parseFloat(ing.protein_per_unit_g) || 0) * ratio * 10) / 10;
    const g = Math.round((parseFloat(ing.carbs_per_unit_g) || 0) * ratio * 10) / 10;
    const l = Math.round((parseFloat(ing.fat_per_unit_g) || 0) * ratio * 10) / 10;

    return `
      <div class="flex items-center justify-between gap-2 p-2 rounded-xl bg-[#151D2A] border border-[#1F2A3C] hover:border-indigo-500/40 transition-colors">
        <div class="flex-1 min-w-0">
          <div class="flex items-center space-x-1.5">
            <span class="text-xs font-bold text-white truncate">${escapeHtml(ing.name)}</span>
            <span class="text-[9px] px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-300 font-mono">Ingrédient</span>
          </div>
          <div class="text-[10px] text-slate-400">
            <strong class="text-brand-400 font-bold">${cals} kcal</strong>
            <span class="mx-1">&bull;</span>
            <span>P: ${p}g</span>
            <span class="mx-1">&bull;</span>
            <span>G: ${g}g</span>
            <span class="mx-1">&bull;</span>
            <span>L: ${l}g</span>
          </div>
        </div>

        <div class="flex items-center space-x-1.5 shrink-0">
          <div class="flex items-center space-x-1">
            <input 
              type="number" 
              step="any" 
              min="0.1" 
              value="${ing.quantity}" 
              oninput="updateDishIngredientQuantity(${idx}, this.value)"
              class="w-16 bg-[#0B0F17] border border-[#1F2A3C] rounded-lg px-2 py-1 text-xs font-bold text-white text-center focus:outline-none focus:border-indigo-500 shadow-inner"
              title="Ajuster la quantité de cet ingrédient"
            >
            <span class="text-[11px] font-bold text-slate-400">${escapeHtml(ing.unit || 'g')}</span>
          </div>
          <button 
            type="button" 
            onclick="removeDishIngredient(${idx})" 
            title="Retirer cet ingrédient" 
            class="p-1 rounded-lg hover:bg-rose-500/20 text-rose-400 hover:text-rose-300 transition-colors"
          >
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      </div>
    `;
  }).join('');

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}


function openCreateCatalogItemModal(type = 'food') {
  catalogItemPhotoBase64 = null;
  modalSelectedBenefits = [];
  modalDishIngredients = [];
  document.getElementById('form-catalog-item').reset();
  document.getElementById('cat-item-id').value = '';
  document.getElementById('cat-item-type').value = type;
  document.getElementById('cat-modal-title').textContent = type === 'dish' ? 'Créer un nouveau Plat composé' : 'Créer un nouvel Ingrédient';
  
  const catSelect = document.getElementById('cat-item-category');
  if (type === 'dish') {
    document.getElementById('cat-item-unit').value = 'portion';
    document.getElementById('cat-item-qty').value = '1';
    if (catSelect) catSelect.value = 'plats_composes';
  } else {
    document.getElementById('cat-item-unit').value = 'g';
    document.getElementById('cat-item-qty').value = '100';
    if (catSelect) catSelect.value = 'autre';
  }

  toggleDishCompositionSection(type === 'dish');
  renderDishIngredientsList();
  renderModalSelectedBenefits();
  renderModalAutoBenefits([]);

  const modal = document.getElementById('modal-catalog-item');
  if (modal) modal.classList.remove('hidden');
}

function openEditCatalogItemModal(itemId) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  if (!item) return;

  catalogItemPhotoBase64 = item.photo_url || null;
  modalSelectedBenefits = (item.benefits || []).map(b => ({
    benefit_id: b.benefit_id || b.id,
    title: b.title,
    icon: b.icon || '🛡️',
    source: b.source || 'manual',
    explanation: b.explanation || ''
  }));

  document.getElementById('cat-item-id').value = item.id;
  document.getElementById('cat-item-name').value = item.name;
  document.getElementById('cat-item-type').value = item.item_type;
  const catSelect = document.getElementById('cat-item-category');
  if (catSelect) catSelect.value = resolveCatalogItemCategory(item);
  document.getElementById('cat-item-unit').value = item.default_unit || 'g';
  document.getElementById('cat-item-qty').value = item.default_quantity || 100;
  document.getElementById('cat-item-cals').value = item.calories_per_unit;
  document.getElementById('cat-item-prot').value = item.protein_per_unit_g || 0;
  document.getElementById('cat-item-carbs').value = item.carbs_per_unit_g || 0;
  document.getElementById('cat-item-fat').value = item.fat_per_unit_g || 0;
  document.getElementById('cat-item-fiber').value = item.fiber_per_unit_g || 0;
  document.getElementById('cat-item-photo-url').value = item.photo_url || '';

  document.getElementById('cat-modal-title').textContent = `Modifier ${item.item_type === 'dish' ? 'le Plat composé' : "l'Ingrédient"}`;

  modalDishIngredients = Array.isArray(item.recipe_items) ? JSON.parse(JSON.stringify(item.recipe_items)) : [];
  toggleDishCompositionSection(item.item_type === 'dish');
  renderDishIngredientsList();
  if (modalDishIngredients.length > 0) {
    recalculateDishFromIngredients();
  }

  renderModalSelectedBenefits();
  triggerModalNutritionEvaluation();

  const modal = document.getElementById('modal-catalog-item');
  if (modal) modal.classList.remove('hidden');
}

// ----------------------------------------------------------------------------
// Fonctions d'évaluation et de gestion des bienfaits dans la modale (Stage 13)
// ----------------------------------------------------------------------------

function renderModalSelectedBenefits() {
  const container = document.getElementById('modal-selected-benefits-tags');
  if (!container) return;

  if (modalSelectedBenefits.length === 0) {
    container.innerHTML = '<span class="text-[10px] text-slate-500 italic">Aucun bienfait manuellement associé pour l\'instant.</span>';
    return;
  }

  container.innerHTML = modalSelectedBenefits.map((b, idx) => `
    <span class="inline-flex items-center space-x-1.5 text-[11px] px-2.5 py-1 rounded-lg font-semibold bg-brand-500/20 text-brand-300 border border-brand-500/40">
      <span>${escapeHtml(b.icon || '🛡️')}</span>
      <span>${escapeHtml(b.title || b.benefit_id)}</span>
      <button type="button" onclick="removeBenefitFromModalSelection(${idx})" class="hover:text-rose-400 ml-1">
        &times;
      </button>
    </span>
  `).join('');
}

function removeBenefitFromModalSelection(index) {
  modalSelectedBenefits.splice(index, 1);
  renderModalSelectedBenefits();
}

function addBenefitToModalSelection(benefitId) {
  if (!benefitId) return;
  if (modalSelectedBenefits.some(b => b.benefit_id === benefitId)) return;

  const titleMap = {
    cardio_protection: { title: "Protection cardiovasculaire", icon: "❤️" },
    cholesterol_regulation: { title: "Régulation du cholestérol", icon: "🩸" },
    blood_pressure: { title: "Contrôle pression artérielle", icon: "🩺" },
    vascular_elasticity: { title: "Élastification vasculaire", icon: "🫀" },
    glycemic_regulation: { title: "Régulation glycémique", icon: "📉" },
    satiety_control: { title: "Satiété & appétit", icon: "⚡" },
    energy_metabolism: { title: "Métabolisme énergétique", icon: "🔥" },
    gut_transit: { title: "Transit intestinal", icon: "🌿" },
    gut_microbiota: { title: "Microbiote & prébiotique", icon: "🦠" },
    liver_support: { title: "Soutien hépatique", icon: "🍃" },
    bone_health: { title: "Santé osseuse", icon: "🦴" },
    muscle_function: { title: "Fonction musculaire & récupération", icon: "💪" },
    immune_support: { title: "Renforcement immunitaire", icon: "🛡️" },
    antioxidant: { title: "Protection antioxydante", icon: "🫐" },
    cellular_hydration: { title: "Hydratation cellulaire", icon: "💧" },
    electrolyte_balance: { title: "Équilibre électrolytique", icon: "⚡" },
    cognitive_function: { title: "Fonctions cognitives", icon: "🧠" },
    vision_health: { title: "Maintien de la vision", icon: "👁️" },
    skin_health: { title: "Santé cutanée", icon: "✨" },
    oral_health: { title: "Santé bucco-dentaire", icon: "🦷" }
  };

  const meta = titleMap[benefitId] || { title: benefitId, icon: "🛡️" };
  modalSelectedBenefits.push({
    benefit_id: benefitId,
    title: meta.title,
    icon: meta.icon,
    source: 'manual',
    explanation: 'Choix de qualification utilisateur'
  });
  renderModalSelectedBenefits();
}

async function triggerModalNutritionEvaluation() {
  const container = document.getElementById('modal-auto-benefits-container');
  if (!container) return;

  const payload = {
    name: document.getElementById('cat-item-name')?.value || '',
    default_quantity: parseFloat(document.getElementById('cat-item-qty')?.value) || 100,
    calories_per_unit: parseFloat(document.getElementById('cat-item-cals')?.value) || 0,
    protein_per_unit_g: parseFloat(document.getElementById('cat-item-prot')?.value) || 0,
    carbs_per_unit_g: parseFloat(document.getElementById('cat-item-carbs')?.value) || 0,
    fat_per_unit_g: parseFloat(document.getElementById('cat-item-fat')?.value) || 0,
    fiber_per_unit_g: parseFloat(document.getElementById('cat-item-fiber')?.value) || 0,
  };

  try {
    const res = await apiFetch('/api/nutrition/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const data = await res.json();
      renderModalAutoBenefits(data.results || []);
    }
  } catch (e) {
    console.warn("Échec évaluation nutritionnelle", e);
  }
}

function renderModalAutoBenefits(results) {
  const container = document.getElementById('modal-auto-benefits-container');
  if (!container) return;

  if (results.length === 0) {
    container.innerHTML = '<span class="text-[10px] text-slate-500 italic">Aucun bienfait supplémentaire automatiquement détecté selon les seuils actuels.</span>';
    return;
  }

  container.innerHTML = results.map((r, idx) => {
    const alreadySelected = modalSelectedBenefits.some(b => b.benefit_id === r.benefit_id);
    const bIcon = escapeHtml(r.icon || '🛡️');
    const bTitle = escapeHtml(r.title || '');
    const bExp = escapeHtml(r.explanation || '');
    return `
      <button 
        type="button"
        data-action="apply-auto-benefit"
        data-auto-index="${idx}"
        class="btn-auto-benefit inline-flex items-center space-x-1 text-[10px] px-2 py-0.5 rounded-md font-semibold transition-all ${
          alreadySelected 
            ? 'bg-brand-500 text-white font-bold' 
            : 'bg-brand-500/10 text-brand-300 border border-brand-500/30 hover:bg-brand-500/25'
        }"
        title="${bExp}"
      >
        <span>${bIcon}</span>
        <span>${bTitle}</span>
        <span>${alreadySelected ? '✓' : '+'}</span>
      </button>
    `;
  }).join('');

  container.querySelectorAll('.btn-auto-benefit').forEach(btn => {
    btn.addEventListener('click', () => {
      const r = results[parseInt(btn.dataset.autoIndex, 10)];
      if (r) {
        applyAutoBenefitToModal(r.benefit_id, r.title, r.icon, r.explanation);
      }
    });
  });
}

function applyAutoBenefitToModal(id, title, icon, explanation) {
  if (modalSelectedBenefits.some(b => b.benefit_id === id)) return;
  modalSelectedBenefits.push({
    benefit_id: id,
    title,
    icon,
    source: 'auto_rule',
    explanation
  });
  renderModalSelectedBenefits();
  triggerModalNutritionEvaluation();
}

function closeCatalogItemModal() {
  const modal = document.getElementById('modal-catalog-item');
  if (modal) modal.classList.add('hidden');
}

function handleCatalogPhotoFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    catalogItemPhotoBase64 = e.target.result;
    document.getElementById('cat-item-photo-url').value = catalogItemPhotoBase64.slice(0, 30) + '... (Image locale encodée)';
  };
  reader.readAsDataURL(file);
}

async function handleCatalogItemFormSubmit(event) {
  event.preventDefault();
  const itemId = document.getElementById('cat-item-id').value;
  const photoInput = document.getElementById('cat-item-photo-url').value;
  const photoUrl = catalogItemPhotoBase64 || (photoInput.startsWith('data:') || photoInput.startsWith('http') ? photoInput : null);

  const catSelect = document.getElementById('cat-item-category');
  const payload = {
    name: document.getElementById('cat-item-name').value.trim(),
    item_type: document.getElementById('cat-item-type').value,
    category: catSelect ? catSelect.value : null,
    default_unit: document.getElementById('cat-item-unit').value.trim(),
    default_quantity: parseFloat(document.getElementById('cat-item-qty').value) || 100.0,
    calories_per_unit: parseFloat(document.getElementById('cat-item-cals').value) || 0.0,
    protein_per_unit_g: parseFloat(document.getElementById('cat-item-prot').value) || 0.0,
    carbs_per_unit_g: parseFloat(document.getElementById('cat-item-carbs').value) || 0.0,
    fat_per_unit_g: parseFloat(document.getElementById('cat-item-fat').value) || 0.0,
    fiber_per_unit_g: parseFloat(document.getElementById('cat-item-fiber').value) || 0.0,
    photo_url: photoUrl,
    recipe_items: modalDishIngredients
  };

  try {
    const isEdit = Boolean(itemId);
    const url = isEdit ? `/api/catalog/items/${itemId}` : '/api/catalog/items';
    const method = isEdit ? 'PUT' : 'POST';

    let res = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.status === 500 || res.status === 503) {
      await new Promise(r => setTimeout(r, 400));
      res = await apiFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }

    if (res.ok) {
      const createdOrUpdated = await res.json();
      const realItemId = createdOrUpdated.id || itemId;

      // Synchroniser les bienfaits associés (Stage 13)
      if (realItemId) {
        try {
          const bUrl = `/api/catalog/items/${realItemId}/benefits`;
          const bPayload = {
            benefits: modalSelectedBenefits.map(b => ({
              benefit_id: b.benefit_id,
              source: b.source || 'manual',
              explanation: b.explanation || ''
            }))
          };
          await apiFetch(bUrl, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bPayload) });
        } catch (bErr) {
          console.warn("Erreur mise à jour bienfaits:", bErr);
        }
      }

      if (typeof showToast === 'function') showToast(`'${payload.name}' enregistré dans le catalogue !`, 'success');
      closeCatalogItemModal();
      loadCatalogItems(true);
    } else {
      const errBody = await res.json().catch(() => ({}));
      const detail = errBody.detail || errBody.error || `HTTP ${res.status}`;
      const msg = `Erreur lors de l'enregistrement dans le catalogue (${detail}).`;
      if (typeof showToast === 'function') showToast(msg, 'error');
      else alert(msg);
    }
  } catch (err) {
    alert("Erreur réseau lors de l'enregistrement.");
  }
}

async function deleteCatalogItem(itemId) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  const name = item ? item.name : 'cet élément';
  if (!confirm(`Supprimer '${name}' de votre catalogue ?`)) return;

  try {
    const res = await apiFetch(`/api/catalog/items/${itemId}`, { method: 'DELETE' });
    if (res.ok) {
      if (typeof showToast === 'function') showToast(`'${name}' supprimé du catalogue`, 'success');
      loadCatalogItems(true);
    } else {
      alert("Erreur lors de la suppression.");
    }
  } catch (err) {
    alert("Erreur réseau.");
  }
}

