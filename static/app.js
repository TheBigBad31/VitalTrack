// static/app.js - Module PWA pour Catalogue Aliments & Plats et Journal Quotidien des Repas (Stage 12)

let currentCatalogItems = [];
let currentCatalogFilter = 'all'; // 'all', 'food', 'dish'
let currentCatalogSearch = '';
let currentJournalDate = new Date().toISOString().split('T')[0];
let currentJournalData = null;
let currentActiveMealSlot = 'lunch';
let catalogItemPhotoBase64 = null;

// ============================================================================
// Initialisation & Bascule de sous-sections
// ============================================================================

function switchNutritionSubSection(sub) {
  const secJournal = document.getElementById('nutrition-sec-journal');
  const secCatalog = document.getElementById('nutrition-sec-catalog');
  const btnJournal = document.getElementById('btn-subnav-journal');
  const btnCatalog = document.getElementById('btn-subnav-catalog');

  if (sub === 'journal') {
    if (secJournal) secJournal.classList.remove('hidden');
    if (secCatalog) secCatalog.classList.add('hidden');
    if (btnJournal) {
      btnJournal.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/20 flex items-center justify-center space-x-2 transition-all';
    }
    if (btnCatalog) {
      btnCatalog.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';
    }
    loadMealsJournal(currentJournalDate);
  } else {
    if (secJournal) secJournal.classList.add('hidden');
    if (secCatalog) secCatalog.classList.remove('hidden');
    if (btnCatalog) {
      btnCatalog.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/20 flex items-center justify-center space-x-2 transition-all';
    }
    if (btnJournal) {
      btnJournal.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';
    }
    loadCatalogItems();
  }
}

// ============================================================================
// 1. CATALOGUE D'ALIMENTS & PLATS
// ============================================================================

async function loadCatalogItems() {
  const container = document.getElementById('catalog-items-grid');
  if (container) {
    container.innerHTML = '<div class="col-span-full py-12 text-center text-slate-500 text-sm">Chargement du catalogue...</div>';
  }

  let url = '/api/catalog/items';
  const params = [];
  if (currentCatalogFilter && currentCatalogFilter !== 'all') {
    params.push(`type=${encodeURIComponent(currentCatalogFilter)}`);
  }
  if (currentCatalogSearch && currentCatalogSearch.trim()) {
    params.push(`q=${encodeURIComponent(currentCatalogSearch.trim())}`);
  }
  if (params.length > 0) {
    url += '?' + params.join('&');
  }

  try {
    const res = await (typeof apiFetch === 'function' ? apiFetch(url) : fetch(url));
    if (res.ok) {
      currentCatalogItems = await res.json();
      renderCatalogItems();
    } else {
      if (container) container.innerHTML = '<div class="col-span-full py-8 text-center text-rose-400 text-xs">Erreur de chargement du catalogue</div>';
    }
  } catch (err) {
    if (container) container.innerHTML = '<div class="col-span-full py-8 text-center text-rose-400 text-xs">Erreur réseau</div>';
  }
}

function filterCatalog(type) {
  currentCatalogFilter = type;
  ['all', 'food', 'dish'].forEach(t => {
    const btn = document.getElementById(`cat-filter-${t}`);
    if (btn) {
      if (t === type) {
        btn.className = 'px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-500 text-slate-950 transition-colors';
      } else {
        btn.className = 'px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-[#151D2A] transition-colors';
      }
    }
  });
  loadCatalogItems();
}

function handleCatalogSearch(e) {
  currentCatalogSearch = e.target.value;
  loadCatalogItems();
}

function renderCatalogItems() {
  const container = document.getElementById('catalog-items-grid');
  const countBadge = document.getElementById('catalog-items-count');
  if (countBadge) {
    countBadge.textContent = `${currentCatalogItems.length} élément${currentCatalogItems.length > 1 ? 's' : ''}`;
  }

  if (!container) return;

  if (currentCatalogItems.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-12 text-center bg-[#0B0F17] border border-[#1F2A3C] rounded-2xl p-8 space-y-3">
        <i data-lucide="book-open" class="w-10 h-10 text-slate-600 mx-auto"></i>
        <h4 class="text-sm font-bold text-slate-300">Votre catalogue est vide</h4>
        <p class="text-xs text-slate-500 max-w-sm mx-auto">Enregistrez vos aliments de base ou vos plats favoris pour composer vos repas en 1 clic.</p>
        <div class="flex items-center justify-center gap-2 pt-2">
          <button onclick="openCreateCatalogItemModal('food')" class="px-3 py-1.5 rounded-xl bg-emerald-600 text-white text-xs font-semibold">+ Nouvel aliment</button>
          <button onclick="openCreateCatalogItemModal('dish')" class="px-3 py-1.5 rounded-xl bg-indigo-600 text-white text-xs font-semibold">+ Nouveau plat</button>
        </div>
      </div>
    `;
    if (window.lucide && lucide.createIcons) lucide.createIcons();
    return;
  }

  container.innerHTML = currentCatalogItems.map(item => {
    const isDish = item.item_type === 'dish';
    const typeBadge = isDish
      ? '<span class="text-[10px] px-2 py-0.5 rounded-full font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">Plat / Recette</span>'
      : '<span class="text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Aliment simple</span>';

    const unitLabel = `${item.default_quantity} ${item.default_unit}`;

    return `
      <div class="bg-[#0B0F17] border border-[#1F2A3C] hover:border-slate-700 rounded-2xl p-4 flex flex-col justify-between space-y-3 transition-colors">
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              ${typeBadge}
              <span class="text-[11px] text-slate-400 font-medium">Réf: ${unitLabel}</span>
            </div>
            <h4 class="font-bold text-sm text-white line-clamp-1">${item.name}</h4>
          </div>
          <div class="text-right shrink-0">
            <span class="text-base font-extrabold text-white">${Math.round(item.calories_per_unit)}</span>
            <span class="text-xs text-slate-400">kcal</span>
          </div>
        </div>

        ${item.photo_url ? `
          <div class="rounded-xl overflow-hidden border border-[#1F2A3C] h-28 bg-[#151D2A]">
            <img src="${item.photo_url}" alt="${item.name}" class="w-full h-full object-cover">
          </div>
        ` : ''}

        <div class="grid grid-cols-4 gap-1.5 py-2 px-2.5 bg-[#151D2A] rounded-xl text-center text-[10px]">
          <div>
            <div class="text-slate-500 font-semibold">Prot.</div>
            <div class="text-emerald-400 font-bold">${item.protein_per_unit_g || 0}g</div>
          </div>
          <div>
            <div class="text-slate-500 font-semibold">Gluc.</div>
            <div class="text-sky-400 font-bold">${item.carbs_per_unit_g || 0}g</div>
          </div>
          <div>
            <div class="text-slate-500 font-semibold">Lip.</div>
            <div class="text-amber-400 font-bold">${item.fat_per_unit_g || 0}g</div>
          </div>
          <div>
            <div class="text-slate-500 font-semibold">Fibr.</div>
            <div class="text-slate-300 font-bold">${item.fiber_per_unit_g || 0}g</div>
          </div>
        </div>

        <div class="flex items-center justify-between pt-1 border-t border-[#1F2A3C]/70">
          <button onclick="promptAddToMeal('${item.id}')" class="text-xs font-semibold text-emerald-400 hover:text-emerald-300 flex items-center space-x-1 py-1 px-2.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 transition-colors">
            <i data-lucide="plus" class="w-3.5 h-3.5"></i>
            <span>+ Ajouter à un repas</span>
          </button>
          <div class="flex items-center gap-1">
            <button onclick="openEditCatalogItemModal('${item.id}')" title="Modifier" class="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#151D2A]">
              <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
            </button>
            <button onclick="deleteCatalogItem('${item.id}')" title="Supprimer" class="p-1.5 rounded-lg text-rose-400/70 hover:text-rose-400 hover:bg-rose-500/10">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

function openCreateCatalogItemModal(type = 'food') {
  catalogItemPhotoBase64 = null;
  document.getElementById('form-catalog-item').reset();
  document.getElementById('cat-item-id').value = '';
  document.getElementById('cat-item-type').value = type;
  document.getElementById('cat-modal-title').textContent = type === 'dish' ? 'Créer un nouveau Plat / Recette' : 'Créer un nouvel Aliment';
  
  if (type === 'dish') {
    document.getElementById('cat-item-unit').value = 'portion';
    document.getElementById('cat-item-qty').value = '1';
  } else {
    document.getElementById('cat-item-unit').value = 'g';
    document.getElementById('cat-item-qty').value = '100';
  }

  const modal = document.getElementById('modal-catalog-item');
  if (modal) modal.classList.remove('hidden');
}

function openEditCatalogItemModal(itemId) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  if (!item) return;

  catalogItemPhotoBase64 = item.photo_url || null;
  document.getElementById('cat-item-id').value = item.id;
  document.getElementById('cat-item-name').value = item.name;
  document.getElementById('cat-item-type').value = item.item_type;
  document.getElementById('cat-item-unit').value = item.default_unit || 'g';
  document.getElementById('cat-item-qty').value = item.default_quantity || 100;
  document.getElementById('cat-item-cals').value = item.calories_per_unit;
  document.getElementById('cat-item-prot').value = item.protein_per_unit_g || 0;
  document.getElementById('cat-item-carbs').value = item.carbs_per_unit_g || 0;
  document.getElementById('cat-item-fat').value = item.fat_per_unit_g || 0;
  document.getElementById('cat-item-fiber').value = item.fiber_per_unit_g || 0;
  document.getElementById('cat-item-photo-url').value = item.photo_url || '';

  document.getElementById('cat-modal-title').textContent = `Modifier ${item.item_type === 'dish' ? 'le Plat' : "l'Aliment"}`;

  const modal = document.getElementById('modal-catalog-item');
  if (modal) modal.classList.remove('hidden');
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

  const payload = {
    name: document.getElementById('cat-item-name').value.trim(),
    item_type: document.getElementById('cat-item-type').value,
    default_unit: document.getElementById('cat-item-unit').value.trim(),
    default_quantity: parseFloat(document.getElementById('cat-item-qty').value) || 100.0,
    calories_per_unit: parseFloat(document.getElementById('cat-item-cals').value) || 0.0,
    protein_per_unit_g: parseFloat(document.getElementById('cat-item-prot').value) || 0.0,
    carbs_per_unit_g: parseFloat(document.getElementById('cat-item-carbs').value) || 0.0,
    fat_per_unit_g: parseFloat(document.getElementById('cat-item-fat').value) || 0.0,
    fiber_per_unit_g: parseFloat(document.getElementById('cat-item-fiber').value) || 0.0,
    photo_url: photoUrl
  };

  try {
    const isEdit = Boolean(itemId);
    const url = isEdit ? `/api/catalog/items/${itemId}` : '/api/catalog/items';
    const method = isEdit ? 'PUT' : 'POST';

    const res = await (typeof apiFetch === 'function' ? apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }) : fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }));

    if (res.ok) {
      if (typeof showToast === 'function') showToast(`'${payload.name}' enregistré dans le catalogue !`, 'success');
      closeCatalogItemModal();
      loadCatalogItems();
    } else {
      alert("Erreur lors de l'enregistrement dans le catalogue.");
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
    const res = await (typeof apiFetch === 'function' ? apiFetch(`/api/catalog/items/${itemId}`, { method: 'DELETE' }) : fetch(`/api/catalog/items/${itemId}`, { method: 'DELETE' }));
    if (res.ok) {
      if (typeof showToast === 'function') showToast(`'${name}' supprimé du catalogue`, 'success');
      loadCatalogItems();
    } else {
      alert("Erreur lors de la suppression.");
    }
  } catch (err) {
    alert("Erreur réseau.");
  }
}

// ============================================================================
// 2. JOURNAL DES REPAS DU QUOTIDIEN
// ============================================================================

async function loadMealsJournal(dateStr) {
  currentJournalDate = dateStr || currentJournalDate || new Date().toISOString().split('T')[0];
  const dateInput = document.getElementById('journal-date-input');
  if (dateInput) dateInput.value = currentJournalDate;

  try {
    const res = await (typeof apiFetch === 'function' ? apiFetch(`/api/meals/journal?date=${currentJournalDate}`) : fetch(`/api/meals/journal?date=${currentJournalDate}`));
    if (res.ok) {
      currentJournalData = await res.json();
      renderMealsJournal();
    }
  } catch (err) {
    console.error("Erreur chargement journal repas:", err);
  }
}

function changeJournalDate(offset) {
  const d = new Date(currentJournalDate);
  d.setDate(d.getDate() + offset);
  currentJournalDate = d.toISOString().split('T')[0];
  loadMealsJournal(currentJournalDate);
}

function handleJournalDateChange(e) {
  currentJournalDate = e.target.value;
  loadMealsJournal(currentJournalDate);
}

function setJournalToToday() {
  currentJournalDate = new Date().toISOString().split('T')[0];
  loadMealsJournal(currentJournalDate);
}

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
  if (elProt) elProt.textContent = `${Math.round(sum.total_protein_g || 0)}g`;
  if (elCarbs) elCarbs.textContent = `${Math.round(sum.total_carbs_g || 0)}g`;
  if (elFat) elFat.textContent = `${Math.round(sum.total_fat_g || 0)}g`;
  if (elFiber) elFiber.textContent = `${Math.round(sum.total_fiber_g || 0)}g`;

  // 2. Les 4 repas
  const slotConfig = {
    breakfast: { name: "Petit-déjeuner", emoji: "🥐", border: "border-amber-500/30", color: "text-amber-400", bgBadge: "bg-amber-500/10" },
    lunch: { name: "Déjeuner", emoji: "🥗", border: "border-emerald-500/30", color: "text-emerald-400", bgBadge: "bg-emerald-500/10" },
    snack: { name: "Goûter", emoji: "🍎", border: "border-pink-500/30", color: "text-pink-400", bgBadge: "bg-pink-500/10" },
    dinner: { name: "Dîner", emoji: "🍲", border: "border-indigo-500/30", color: "text-indigo-400", bgBadge: "bg-indigo-500/10" }
  };

  const meals = currentJournalData.meals || [];
  const mealsByType = {};
  meals.forEach(m => { mealsByType[m.meal_type] = m; });

  const container = document.getElementById('journal-slots-container');
  if (!container) return;

  container.innerHTML = ['breakfast', 'lunch', 'snack', 'dinner'].map(slot => {
    const cfg = slotConfig[slot];
    const m = mealsByType[slot] || { total_calories: 0, total_protein_g: 0, total_carbs_g: 0, total_fat_g: 0, items: [] };
    const items = m.items || [];

    return `
      <div class="bg-[#151D2A] border ${cfg.border} rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-4 shadow-sm">
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

        <!-- Liste des aliments consommés -->
        <div class="space-y-2 min-h-[60px]">
          ${items.length === 0 ? `
            <div class="py-4 text-center text-xs text-slate-500 border border-dashed border-[#1F2A3C] rounded-xl">
              Aucun aliment composé pour ce repas.
            </div>
          ` : items.map(it => `
            <div class="flex items-center justify-between p-2 rounded-xl bg-[#0B0F17] border border-[#1F2A3C] hover:border-slate-700 transition-colors">
              <div class="flex-1 pr-2">
                <div class="text-xs font-bold text-white line-clamp-1">${it.name}</div>
                <div class="text-[11px] text-slate-400">${it.quantity} ${it.unit} &bull; <span class="text-emerald-400 font-medium">${Math.round(it.calories)} kcal</span> (P:${Math.round(it.protein_g || 0)}g G:${Math.round(it.carbs_g || 0)}g L:${Math.round(it.fat_g || 0)}g)</div>
              </div>
              <button onclick="removeMealLogItem('${it.id}')" title="Retirer l'aliment" class="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 shrink-0">
                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          `).join('')}
        </div>

        <!-- Boutons d'actions -->
        <div class="flex items-center gap-2 pt-2 border-t border-[#1F2A3C]/70">
          <button onclick="openSelectFromCatalogModal('${slot}')" class="flex-1 py-2 px-3 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 text-xs font-bold flex items-center justify-center space-x-1.5 transition-colors">
            <i data-lucide="plus" class="w-4 h-4"></i>
            <span>+ Ajouter un aliment / plat</span>
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

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

async function removeMealLogItem(itemId) {
  try {
    const res = await (typeof apiFetch === 'function' ? apiFetch(`/api/meals/journal/items/${itemId}`, { method: 'DELETE' }) : fetch(`/api/meals/journal/items/${itemId}`, { method: 'DELETE' }));
    if (res.ok) {
      if (typeof showToast === 'function') showToast("Aliment retiré du repas", "success");
      loadMealsJournal(currentJournalDate);
    }
  } catch (err) {
    alert("Erreur lors de la suppression de l'aliment");
  }
}

// ============================================================================
// 3. SÉLECTION D'UN ALIMENT DU CATALOGUE POUR L'AJOUTER AU REPAS
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

  // Charger le catalogue
  renderModalCatalogList();

  const modal = document.getElementById('modal-select-catalog-item');
  if (modal) modal.classList.remove('hidden');
}

function closeSelectFromCatalogModal() {
  const modal = document.getElementById('modal-select-catalog-item');
  if (modal) modal.classList.add('hidden');
}

function promptAddToMeal(itemId) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  if (!item) return;
  openSelectFromCatalogModal(currentActiveMealSlot || 'lunch');
  selectCatalogItemForPortion(item.id);
}

function renderModalCatalogList(searchQuery = '') {
  const container = document.getElementById('modal-catalog-picker-list');
  if (!container) return;

  const q = searchQuery.toLowerCase().trim();
  const filtered = currentCatalogItems.filter(it => !q || it.name.toLowerCase().includes(q));

  if (filtered.length === 0) {
    container.innerHTML = '<div class="py-8 text-center text-xs text-slate-500">Aucun aliment correspondant trouvé.</div>';
    return;
  }

  container.innerHTML = filtered.map(it => `
    <div onclick="selectCatalogItemForPortion('${it.id}')" class="p-2.5 rounded-xl bg-[#0B0F17] hover:bg-[#1F2A3C] border border-[#1F2A3C] hover:border-emerald-500/50 cursor-pointer flex items-center justify-between transition-colors">
      <div class="flex-1 pr-2">
        <div class="text-xs font-bold text-white">${it.name}</div>
        <div class="text-[11px] text-slate-400">Réf: ${it.default_quantity} ${it.default_unit} &bull; ${Math.round(it.calories_per_unit)} kcal</div>
      </div>
      <button class="px-2 py-1 rounded-lg bg-emerald-600/20 text-emerald-300 text-xs font-semibold shrink-0">Choisir</button>
    </div>
  `).join('');
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

async function confirmAddCatalogItemToMeal() {
  if (!currentSelectedCatalogItem) return;
  const item = currentSelectedCatalogItem;
  const qty = parseFloat(document.getElementById('picker-portion-qty').value);
  if (!qty || qty <= 0) {
    alert("Veuillez saisir une quantité valide.");
    return;
  }

  const payload = {
    date: currentJournalDate,
    food_item_id: item.id,
    quantity: qty,
    unit: item.default_unit || 'g'
  };

  try {
    const res = await (typeof apiFetch === 'function' ? apiFetch(`/api/meals/journal/${currentActiveMealSlot}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }) : fetch(`/api/meals/journal/${currentActiveMealSlot}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }));

    if (res.ok) {
      if (typeof showToast === 'function') showToast(`'${item.name}' ajouté au ${currentActiveMealSlot} !`, 'success');
      closeSelectFromCatalogModal();
      backToPickerList();
      loadMealsJournal(currentJournalDate);
    } else {
      alert("Erreur lors de l'ajout au repas.");
    }
  } catch (err) {
    alert("Erreur réseau.");
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
    const res = await (typeof apiFetch === 'function' ? apiFetch(`/api/meals/journal/${slot}/save-as-dish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }) : fetch(`/api/meals/journal/${slot}/save-as-dish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }));

    if (res.ok) {
      if (typeof showToast === 'function') showToast(`Plat '${payload.name}' créé dans votre catalogue !`, 'success');
      loadCatalogItems();
    } else {
      alert("Erreur lors de la création du plat.");
    }
  } catch (err) {
    alert("Erreur réseau.");
  }
}

// Initialisation globale au chargement
document.addEventListener('DOMContentLoaded', () => {
  loadCatalogItems();
  loadMealsJournal();
});
