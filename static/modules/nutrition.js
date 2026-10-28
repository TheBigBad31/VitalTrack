// static/modules/nutrition.js - Module Desktop Web & PWA pour Catalogue Aliments & Plats et Journal Quotidien

// static/app.js - Module Desktop Web & PWA pour Catalogue Aliments & Plats et Journal Quotidien des Repas (Stage 12)

let currentCatalogItems = [];
let currentCatalogFilter = 'all'; // 'all', 'food', 'dish'
let currentCatalogSourceFilter = 'all'; // 'all', 'mine', 'public', 'friends' (Stage 15 / BALI-85)
let currentCatalogBenefitFilter = ''; // Filtre par bienfait (Stage 13)
let currentFriendSubscriptions = []; // Liste des abonnements aux catalogues d'amis
let currentExplorerFriend = null; // Ami en cours d'exploration
let currentExplorerFriendItems = []; // Aliments de l'ami
let currentCatalogSearch = '';
let currentJournalDate = new Date().toISOString().split('T')[0];
let currentJournalData = null;
let currentActiveMealSlot = 'lunch';
let catalogItemPhotoBase64 = null;
let currentNutritionLayoutMode = 'split'; // 'split' (desktop côte à côte), 'journal', 'catalog'

// Bienfaits actifs dans la modale d'édition/création de plat (Stage 13)
let modalSelectedBenefits = [];

// Composition d'ingrédients pour la création/édition de plat (Stage 14 / BALI-35)
let modalDishIngredients = [];

const RECOMMENDED_STAPLE_INGREDIENTS = [
  { name: "Pain complet", default_unit: "g", default_quantity: 40.0, calories_per_unit: 99.0, protein_per_unit_g: 3.6, carbs_per_unit_g: 18.0, fat_per_unit_g: 0.8, fiber_per_unit_g: 2.8, emoji: "🍞", label: "Pain complet (1 tranche = 40g)" },
  { name: "Pain blanc / Baguette", default_unit: "g", default_quantity: 40.0, calories_per_unit: 110.0, protein_per_unit_g: 3.4, carbs_per_unit_g: 22.0, fat_per_unit_g: 0.8, fiber_per_unit_g: 1.2, emoji: "🥖", label: "Pain blanc / Baguette (40g)" },
  { name: "Beurre doux", default_unit: "g", default_quantity: 10.0, calories_per_unit: 72.0, protein_per_unit_g: 0.1, carbs_per_unit_g: 0.1, fat_per_unit_g: 8.2, fiber_per_unit_g: 0.0, emoji: "🧈", label: "Beurre doux (1 cuillère = 10g)" },
  { name: "Beurre demi-sel", default_unit: "g", default_quantity: 10.0, calories_per_unit: 72.0, protein_per_unit_g: 0.1, carbs_per_unit_g: 0.1, fat_per_unit_g: 8.2, fiber_per_unit_g: 0.0, emoji: "🧈", label: "Beurre demi-sel (1 cuillère = 10g)" },
  { name: "Huile d'olive vierge", default_unit: "g", default_quantity: 10.0, calories_per_unit: 88.0, protein_per_unit_g: 0.0, carbs_per_unit_g: 0.0, fat_per_unit_g: 10.0, fiber_per_unit_g: 0.0, emoji: "🫒", label: "Huile d'olive (1 cuillère à soupe = 10g)" },
  { name: "Œuf entier plein air", default_unit: "pièce", default_quantity: 1.0, calories_per_unit: 78.0, protein_per_unit_g: 6.9, carbs_per_unit_g: 0.4, fat_per_unit_g: 5.2, fiber_per_unit_g: 0.0, emoji: "🥚", label: "Œuf entier (1 pièce ~ 55g)" },
  { name: "Avocat frais", default_unit: "g", default_quantity: 75.0, calories_per_unit: 120.0, protein_per_unit_g: 1.5, carbs_per_unit_g: 6.8, fat_per_unit_g: 11.3, fiber_per_unit_g: 5.2, emoji: "🥑", label: "Avocat (1/2 pièce = 75g)" },
  { name: "Jambon blanc découenné", default_unit: "g", default_quantity: 40.0, calories_per_unit: 44.0, protein_per_unit_g: 8.4, carbs_per_unit_g: 0.4, fat_per_unit_g: 1.0, fiber_per_unit_g: 0.0, emoji: "🍖", label: "Jambon blanc (1 tranche = 40g)" },
  { name: "Fromage emmental râpé", default_unit: "g", default_quantity: 30.0, calories_per_unit: 115.0, protein_per_unit_g: 8.2, carbs_per_unit_g: 0.1, fat_per_unit_g: 9.3, fiber_per_unit_g: 0.0, emoji: "🧀", label: "Fromage emmental (30g)" },
  { name: "Tomate fraîche", default_unit: "g", default_quantity: 100.0, calories_per_unit: 18.0, protein_per_unit_g: 0.9, carbs_per_unit_g: 3.9, fat_per_unit_g: 0.2, fiber_per_unit_g: 1.2, emoji: "🍅", label: "Tomate fraîche (100g)" },
  { name: "Riz blanc ou basmati cuit", default_unit: "g", default_quantity: 150.0, calories_per_unit: 195.0, protein_per_unit_g: 4.0, carbs_per_unit_g: 42.0, fat_per_unit_g: 0.5, fiber_per_unit_g: 1.5, emoji: "🍚", label: "Riz cuit (150g)" },
  { name: "Pâtes complètes cuites", default_unit: "g", default_quantity: 150.0, calories_per_unit: 210.0, protein_per_unit_g: 8.2, carbs_per_unit_g: 40.5, fat_per_unit_g: 1.2, fiber_per_unit_g: 5.2, emoji: "🍝", label: "Pâtes complètes cuites (150g)" },
  { name: "Flocons d'avoine", default_unit: "g", default_quantity: 50.0, calories_per_unit: 185.0, protein_per_unit_g: 6.8, carbs_per_unit_g: 30.0, fat_per_unit_g: 3.5, fiber_per_unit_g: 5.0, emoji: "🥣", label: "Flocons d'avoine (50g)" },
  { name: "Miel d'acacia", default_unit: "g", default_quantity: 15.0, calories_per_unit: 46.0, protein_per_unit_g: 0.0, carbs_per_unit_g: 12.3, fat_per_unit_g: 0.0, fiber_per_unit_g: 0.0, emoji: "🍯", label: "Miel (1 cuillère à soupe = 15g)" }
]; // Array of { benefit_id, source, explanation, icon, title }

// Variables Drag & Drop Desktop
let draggedCatalogItem = null;
let pendingDropItem = null;
let pendingDropSlot = null;

// ============================================================================
// Initialisation & Bascule de Layout Desktop Multi-Colonnes
// ============================================================================

function switchNutritionLayout(mode) {
  currentNutritionLayoutMode = mode;
  const secJournal = document.getElementById('nutrition-sec-journal');
  const secCatalog = document.getElementById('nutrition-sec-catalog');
  const btnDesktopSplit = document.getElementById('btn-subnav-desktop-split');
  const btnJournal = document.getElementById('btn-subnav-journal');
  const btnCatalog = document.getElementById('btn-subnav-catalog');

  if (mode === 'split') {
    if (secJournal) {
      secJournal.classList.remove('hidden');
      secJournal.className = 'xl:col-span-7 space-y-4';
    }
    if (secCatalog) {
      secCatalog.classList.remove('hidden');
      secCatalog.className = 'xl:col-span-5 space-y-4';
    }
    if (btnDesktopSplit) {
      btnDesktopSplit.className = 'hidden xl:flex px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-brand-500 text-white shadow-md shadow-brand-500/20 items-center justify-center space-x-2 transition-all';
    }
    if (btnJournal) {
      btnJournal.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';
    }
    if (btnCatalog) {
      btnCatalog.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';
    }
    loadCatalogItems();
    loadMealsJournal(currentJournalDate);
  } else if (mode === 'journal') {
    if (secJournal) {
      secJournal.classList.remove('hidden');
      secJournal.className = 'col-span-12 space-y-4';
    }
    if (secCatalog) secCatalog.classList.add('hidden');
    if (btnDesktopSplit) {
      btnDesktopSplit.className = 'hidden xl:flex px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] items-center justify-center space-x-2 transition-all';
    }
    if (btnJournal) {
      btnJournal.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-brand-500 text-white shadow-md shadow-brand-500/20 flex items-center justify-center space-x-2 transition-all';
    }
    if (btnCatalog) {
      btnCatalog.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';
    }
    loadMealsJournal(currentJournalDate);
  } else if (mode === 'catalog') {
    if (secJournal) secJournal.classList.add('hidden');
    if (secCatalog) {
      secCatalog.classList.remove('hidden');
      secCatalog.className = 'col-span-12 space-y-4';
    }
    if (btnDesktopSplit) {
      btnDesktopSplit.className = 'hidden xl:flex px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] items-center justify-center space-x-2 transition-all';
    }
    if (btnCatalog) {
      btnCatalog.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-brand-500 text-white shadow-md shadow-brand-500/20 flex items-center justify-center space-x-2 transition-all';
    }
    if (btnJournal) {
      btnJournal.className = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';
    }
    loadCatalogItems();
  }
}

function switchNutritionSubSection(sub) {
  // 1. S'assurer que l'onglet parent Nutrition & Repas est actif
  if (typeof switchTab === 'function') {
    switchTab('nutrition');
  }

  // 2. Basculer l'affichage vers la vue demandée
  switchNutritionLayout(sub);

  // 3. Déclenchement visuel immédiat & scroll fluide
  if (sub === 'journal') {
    const secJournal = document.getElementById('nutrition-sec-journal');
    if (secJournal) {
      secJournal.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    if (typeof showToast === 'function') {
      showToast("📅 Vue Journal des 4 Repas active", "info");
    }
  } else if (sub === 'catalog') {
    const secCatalog = document.getElementById('nutrition-sec-catalog');
    if (secCatalog) {
      secCatalog.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    setTimeout(() => {
      const searchInput = document.getElementById('catalog-search-input');
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }, 150);
    if (typeof showToast === 'function') {
      showToast("📖 Catalogue d'Aliments & Plats actif (Touche '/' pour chercher)", "info");
    }
  }
}

// Initialisation des écouteurs explicites addEventListener pour la navigation
function initNutritionNavigation() {
  const btnJournal = document.getElementById('btn-subnav-journal');
  if (btnJournal && !btnJournal.dataset.bound) {
    btnJournal.dataset.bound = "true";
    btnJournal.addEventListener('click', (e) => {
      e.preventDefault();
      switchNutritionSubSection('journal');
    });
  }

  const btnCatalog = document.getElementById('btn-subnav-catalog');
  if (btnCatalog && !btnCatalog.dataset.bound) {
    btnCatalog.dataset.bound = "true";
    btnCatalog.addEventListener('click', (e) => {
      e.preventDefault();
      switchNutritionSubSection('catalog');
    });
  }

  const btnDesktopSplit = document.getElementById('btn-subnav-desktop-split');
  if (btnDesktopSplit && !btnDesktopSplit.dataset.bound) {
    btnDesktopSplit.dataset.bound = "true";
    btnDesktopSplit.addEventListener('click', (e) => {
      e.preventDefault();
      if (typeof switchTab === 'function') switchTab('nutrition');
      switchNutritionLayout('split');
      if (typeof showToast === 'function') showToast("🖥️ Vue Bureau Multi-Colonnes active", "info");
    });
  }

  const btnQuickAdd = document.getElementById('btn-quick-add-to-meal');
  if (btnQuickAdd && !btnQuickAdd.dataset.bound) {
    btnQuickAdd.dataset.bound = "true";
    btnQuickAdd.addEventListener('click', (e) => {
      e.preventDefault();
      if (typeof openSelectFromCatalogModal === 'function') {
        openSelectFromCatalogModal(currentActiveMealSlot || 'lunch');
      }
    });
  }
}

// ============================================================================
// 1. CATALOGUE D'ALIMENTS & PLATS
// ============================================================================

async function loadCatalogItems() {
  const container = document.getElementById('catalog-items-grid');
  if (container && currentCatalogItems.length === 0) {
    container.innerHTML = '<div class="col-span-full py-12 text-center text-slate-500 text-sm">Chargement du catalogue...</div>';
  }

  let url = '/api/catalog/items';
  const params = [];
  if (currentCatalogFilter && currentCatalogFilter !== 'all') {
    params.push(`type=${encodeURIComponent(currentCatalogFilter)}`);
  }
  if (currentCatalogSourceFilter && currentCatalogSourceFilter !== 'all') {
    params.push(`source=${encodeURIComponent(currentCatalogSourceFilter)}`);
  }
  if (currentCatalogSearch && currentCatalogSearch.trim()) {
    params.push(`q=${encodeURIComponent(currentCatalogSearch.trim())}`);
  }
  if (params.length > 0) {
    url += '?' + params.join('&');
  }

  try {
    const res = await apiFetch(url);
    if (res.ok) {
      currentCatalogItems = await res.json();
      renderCatalogItems();
      if (document.getElementById("modal-catalog-picker-list")) {
        renderModalCatalogList();
      }
    } else {
      console.warn("Échec requête catalogue:", res.status);
      if (container) container.innerHTML = '<div class="col-span-full py-8 text-center text-rose-400 text-xs">Erreur de chargement du catalogue</div>';
    }
  } catch (err) {
    console.error("Erreur réseau ou rendu catalogue:", err);
    if (container) container.innerHTML = '<div class="col-span-full py-8 text-center text-rose-400 text-xs">Erreur de chargement du catalogue</div>';
  }
}

function filterCatalog(type) {
  currentCatalogFilter = type;
  ['all', 'food', 'dish'].forEach(t => {
    const btn = document.getElementById(`cat-filter-${t}`);
    if (btn) {
      if (t === type) {
        btn.className = 'flex-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-brand-500 text-white transition-colors';
      } else {
        btn.className = 'flex-1 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-[#151D2A] transition-colors';
      }
    }
  });
  loadCatalogItems();
}

function filterCatalogSource(source) {
  currentCatalogSourceFilter = source;
  ['all', 'mine', 'public', 'friends'].forEach(s => {
    const btn = document.getElementById(`cat-source-${s}`);
    if (btn) {
      if (s === source) {
        btn.className = 'px-2 py-1.5 rounded-lg text-xs font-bold bg-brand-500 text-white transition-all text-center truncate shadow-sm';
      } else {
        btn.className = 'px-2 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-[#151D2A] transition-all text-center truncate flex items-center justify-center space-x-1';
      }
    }
  });
  loadCatalogItems();
}

function handleCatalogSearch(e) {
  currentCatalogSearch = e.target.value;
  loadCatalogItems();
}

function handleBenefitFilterChange(event) {
  currentCatalogBenefitFilter = event.target.value;
  renderCatalogItems();
}

function renderCatalogItems() {
  const container = document.getElementById('catalog-items-grid');
  const countBadge = document.getElementById('catalog-items-count');

  let itemsToRender = currentCatalogItems;
  if (currentCatalogBenefitFilter) {
    itemsToRender = itemsToRender.filter(it => {
      const bList = it.benefits || [];
      return bList.some(b => (b.benefit_id || b.id) === currentCatalogBenefitFilter);
    });
  }

  if (countBadge) {
    countBadge.textContent = `${itemsToRender.length} élément${itemsToRender.length > 1 ? 's' : ''}`;
  }

  if (!container) return;

  if (itemsToRender.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-10 text-center bg-[#0B0F17] border border-[#1F2A3C] rounded-2xl p-6 space-y-3">
        <i data-lucide="book-open" class="w-9 h-9 text-slate-600 mx-auto"></i>
        <h4 class="text-sm font-bold text-slate-300">Aucun aliment correspondant</h4>
        <p class="text-xs text-slate-500 max-w-sm mx-auto">Aucun élément ne correspond à votre filtre de bienfait ou recherche.</p>
        <div class="flex items-center justify-center gap-2 pt-2">
          <button onclick="openCreateCatalogItemModal('food')" class="px-3 py-1.5 rounded-xl bg-brand-600 text-white text-xs font-semibold">+ Nouvel aliment</button>
          <button onclick="openCreateCatalogItemModal('dish')" class="px-3 py-1.5 rounded-xl bg-indigo-600 text-white text-xs font-semibold">+ Nouveau plat</button>
        </div>
      </div>
    `;
    if (window.lucide && lucide.createIcons) lucide.createIcons();
    return;
  }

  container.innerHTML = itemsToRender.map(item => {
    const isDish = item.item_type === 'dish';
    // Remplacement du texte par un code couleur + icône intuitive (assiette Plat / pomme Aliment)
    const typeBadge = isDish
      ? `<span class="inline-flex items-center justify-center w-6 h-6 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-xs shadow-sm shrink-0" title="Plat composé / Recette">🍽️</span>`
      : `<span class="inline-flex items-center justify-center w-6 h-6 rounded-lg bg-brand-500/20 text-brand-300 border border-brand-500/30 text-xs shadow-sm shrink-0" title="Aliment simple / Ingrédient brut">🍎</span>`;

    // Badge d'origine de l'aliment (BALI-85) : Public, Perso, ou Ami
    let sourceBadge = '';
    const isPublic = Boolean(item.is_public || item.user_id === 0 || item.user_id === null || item.source === 'public');
    const isFriend = Boolean(item.owner_name || item.friend_name || (item.source === 'friend' || item.source === 'friends'));
    if (isPublic) {
      sourceBadge = `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-sky-500/15 text-sky-300 border border-sky-500/30 shrink-0" title="Aliment du socle public"><i data-lucide="globe" class="w-2.5 h-2.5"></i><span>Public</span></span>`;
    } else if (isFriend) {
      const friendLabel = item.owner_name || item.friend_name || "Ami";
      sourceBadge = `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 shrink-0" title="Catalogue partagé par ${friendLabel}"><i data-lucide="user-check" class="w-2.5 h-2.5"></i><span>${friendLabel}</span></span>`;
    } else {
      sourceBadge = `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-purple-500/15 text-purple-300 border border-purple-500/30 shrink-0" title="Ma création personnelle"><i data-lucide="user" class="w-2.5 h-2.5"></i><span>Perso</span></span>`;
    }

    const unitLabel = `${item.default_quantity}${item.default_unit || 'g'}`;
    const p = Math.round((item.protein_per_unit_g || 0) * 10) / 10;
    const g = Math.round((item.carbs_per_unit_g || 0) * 10) / 10;
    const l = Math.round((item.fat_per_unit_g || 0) * 10) / 10;
    const cal = Math.round(item.calories_per_unit);

    // Badges de bienfaits santé : uniquement les icônes compactes avec tooltips
    const benefitsList = item.benefits || [];
    const benefitsHtml = benefitsList.length > 0 ? `
      <div class="flex flex-wrap items-center gap-1 pt-0.5">
        ${benefitsList.map(b => `
          <span 
            class="inline-flex items-center justify-center w-5 h-5 rounded-md bg-brand-500/15 border border-brand-500/30 text-xs cursor-help hover:scale-110 hover:bg-brand-500/25 transition-all shadow-sm"
            title="${b.title || b.benefit_id}${b.explanation ? ' : ' + b.explanation : ''}"
          >
            ${b.icon || '🛡️'}
          </span>
        `).join('')}
      </div>
    ` : '';

    return `
      <div 
        class="catalog-draggable-card bg-[#0B0F17] border border-[#1F2A3C] hover:border-brand-500/60 rounded-xl p-2.5 flex flex-col justify-between space-y-1.5 transition-all shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md hover:shadow-brand-500/10 select-none group"
        draggable="true"
        ondragstart="handleCatalogDragStart(event, '${item.id}')"
        ondragend="handleCatalogDragEnd(event)"
        data-item-id="${item.id}"
        title="Glisser vers un repas ou double-cliquer pour ajouter"
        ondblclick="promptAddToMeal('${item.id}')"
      >
        <div class="flex items-center justify-between gap-1.5">
          <div class="flex items-center space-x-1.5 min-w-0 flex-1">
            <div class="text-slate-500 group-hover:text-brand-400 shrink-0 cursor-grab active:cursor-grabbing">
              <i data-lucide="grip-vertical" class="w-3.5 h-3.5"></i>
            </div>
            ${typeBadge}
            <h4 class="font-bold text-xs text-white truncate" title="${item.name}">${item.name}</h4>
            ${sourceBadge}
          </div>
          <div class="text-right shrink-0">
            <span class="text-xs font-black text-amber-400">${cal}</span>
            <span class="text-[9px] text-slate-400">kcal</span>
          </div>
        </div>

        ${item.photo_url ? `
          <div class="rounded-lg overflow-hidden border border-[#1F2A3C] h-14 bg-[#151D2A]">
            <img src="${item.photo_url}" alt="${item.name}" class="w-full h-full object-cover pointer-events-none">
          </div>
        ` : ''}

        <div class="flex items-center justify-between text-[10px] text-slate-400 font-mono px-2 py-0.5 bg-[#151D2A] rounded-lg">
          <span class="text-slate-300 font-semibold truncate">Réf: ${unitLabel}</span>
          <span class="shrink-0 space-x-1.5">
            <span class="text-brand-400 font-semibold">P:${p}g</span>
            <span class="text-sky-400 font-semibold">G:${g}g</span>
            <span class="text-amber-400 font-semibold">L:${l}g</span>
          </span>
        </div>

        ${isDish && item.recipe_items && item.recipe_items.length > 0 ? `
          <div class="px-2 py-0.5 bg-[#151D2A]/80 rounded-lg border border-indigo-500/20 text-[10px] text-slate-400 truncate" title="${item.recipe_items.map(ing => `${ing.name} (${ing.quantity}${ing.unit || 'g'})`).join(', ')}">
            <span class="text-indigo-300 font-bold">🥗 ${item.recipe_items.length} ingr. :</span>
            <span class="text-slate-300 font-medium">${item.recipe_items.map(ing => ing.name).join(', ')}</span>
          </div>
        ` : ''}

        ${benefitsHtml}

        <div class="flex items-center justify-between pt-1 border-t border-[#1F2A3C]/70">
          <button 
            type="button"
            onclick="promptAddToMeal('${item.id}')" 
            title="Ajouter au repas sélectionné"
            class="text-[10px] font-bold text-brand-400 hover:text-brand-300 flex items-center space-x-1 py-0.5 px-2 rounded-lg bg-brand-500/10 hover:bg-brand-500/20 border border-brand-500/20 transition-colors"
          >
            <i data-lucide="plus" class="w-3 h-3"></i>
            <span>Ajouter</span>
          </button>
          
          <div class="flex items-center gap-1">
            ${(!isPublic && !isFriend) ? `
              <button onclick="openEditCatalogItemModal('${item.id}')" title="Modifier" class="p-1 rounded-md text-slate-400 hover:text-white hover:bg-[#151D2A]">
                <i data-lucide="pencil" class="w-3 h-3"></i>
              </button>
              <button onclick="deleteCatalogItem('${item.id}')" title="Supprimer" class="p-1 rounded-md text-rose-400/70 hover:text-rose-400 hover:bg-rose-500/10">
                <i data-lucide="trash-2" class="w-3 h-3"></i>
              </button>
            ` : (isFriend ? `
              <button onclick="copyFriendItemToMyCatalog('${item.id}')" title="Importer dans mon catalogue" class="px-1.5 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-300 text-[10px] font-semibold flex items-center space-x-1">
                <i data-lucide="copy" class="w-2.5 h-2.5"></i>
                <span>Importer</span>
              </button>
            ` : '')}
          </div>
        </div>
      </div>
    `;
  }).join('');

  if (window.lucide && lucide.createIcons) lucide.createIcons();

  // 3. Synthèse des bienfaits du jour (Stage 13)
  if (typeof renderJournalDayBenefitsSummary === "function" && typeof currentJournalData !== "undefined" && currentJournalData && currentJournalData.meals) {
    renderJournalDayBenefitsSummary(currentJournalData.meals);
  }
}


// ============================================================================
// 2. GESTION DU GLISSER-DÉPOSER NATIF (HTML5 DRAG & DROP & POINTER EVENTS)
// ============================================================================

function handleCatalogDragStart(event, itemId) {
  const item = currentCatalogItems.find(it => it.id == itemId);
  if (!item) return;

  draggedCatalogItem = item;
  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData('text/plain', JSON.stringify({
    id: item.id,
    name: item.name,
    default_quantity: item.default_quantity,
    default_unit: item.default_unit,
    calories_per_unit: item.calories_per_unit
  }));

  // Création d'un Ghost preview semi-transparent
  const ghost = document.createElement('div');
  ghost.id = 'drag-ghost-preview';
  ghost.className = 'fixed -top-96 -left-96 bg-[#151D2A] border-2 border-brand-400 text-white px-3 py-2 rounded-xl shadow-2xl flex items-center space-x-2.5 z-50 pointer-events-none opacity-90';
  ghost.innerHTML = `
    <span class="text-base">${item.item_type === 'dish' ? '🍲' : '🥗'}</span>
    <div>
      <div class="font-bold text-xs text-white">${item.name}</div>
      <div class="text-[10px] text-brand-300">${Math.round(item.calories_per_unit)} kcal &bull; ${item.default_quantity} ${item.default_unit}</div>
    </div>
  `;
  document.body.appendChild(ghost);
  event.dataTransfer.setDragImage(ghost, 20, 20);
  setTimeout(() => ghost.remove(), 0);

  // Mise en surbrillance réceptrice des 4 zones de repas
  const dropZones = document.querySelectorAll('.meal-drop-zone');
  dropZones.forEach(zone => {
    zone.classList.add('border-dashed', 'border-brand-500/60', 'bg-brand-500/[0.03]');
  });
}

function handleCatalogDragEnd(event) {
  draggedCatalogItem = null;
  const dropZones = document.querySelectorAll('.meal-drop-zone');
  dropZones.forEach(zone => {
    zone.classList.remove('border-dashed', 'border-brand-500/60', 'bg-brand-500/[0.03]', 'ring-2', 'ring-brand-400/50');
  });

  const placeholders = document.querySelectorAll('.drop-target-placeholder');
  placeholders.forEach(el => el.classList.add('hidden'));
}

function handleMealDragOver(event, slot) {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';

  const zone = document.getElementById(`meal-zone-${slot}`);
  if (zone) {
    zone.classList.add('ring-2', 'ring-brand-400', 'bg-brand-500/[0.07]');
  }

  const placeholder = document.getElementById(`drop-placeholder-${slot}`);
  if (placeholder) {
    placeholder.classList.remove('hidden');
  }
}

function handleMealDragLeave(event, slot) {
  const zone = document.getElementById(`meal-zone-${slot}`);
  if (zone) {
    zone.classList.remove('ring-2', 'ring-brand-400', 'bg-brand-500/[0.07]');
  }

  const placeholder = document.getElementById(`drop-placeholder-${slot}`);
  if (placeholder) {
    placeholder.classList.add('hidden');
  }
}

function handleMealDrop(event, slot) {
  event.preventDefault();
  handleMealDragLeave(event, slot);

  let item = draggedCatalogItem;
  if (!item) {
    try {
      const dataStr = event.dataTransfer.getData('text/plain');
      if (dataStr) {
        const parsed = JSON.parse(dataStr);
        item = currentCatalogItems.find(it => it.id == parsed.id) || parsed;
      }
    } catch (e) {
      console.warn("Drop data parsing error:", e);
    }
  }

  if (!item) return;

  // Déclencher immédiatement la pop-in inline de saisie de grammage
  openDropPortionModal(item, slot);
}

// ============================================================================
// 3. POP-IN INLINE RAPIDE AU DROP DE QUANTITÉ AVEC VALIDATION CLAVIER
// ============================================================================

function openDropPortionModal(item, slot) {
  pendingDropItem = item;
  pendingDropSlot = slot;

  const slotTitles = {
    breakfast: "Petit-déjeuner 🥐",
    lunch: "Déjeuner 🥗",
    snack: "Goûter 🍎",
    dinner: "Dîner 🍲"
  };

  const modal = document.getElementById('modal-drop-portion');
  const titleEl = document.getElementById('drop-modal-slot-title');
  const nameEl = document.getElementById('drop-modal-item-name');
  const refLabel = document.getElementById('drop-modal-ref-label');
  const qtyInput = document.getElementById('drop-modal-qty-input');
  const unitLabel = document.getElementById('drop-modal-unit-label');
  const photoContainer = document.getElementById('drop-modal-item-photo-container');
  const photoImg = document.getElementById('drop-modal-item-photo');

  if (titleEl) titleEl.textContent = slotTitles[slot] || slot;
  if (nameEl) nameEl.textContent = item.name;
  if (refLabel) {
    refLabel.textContent = `Référence : ${item.default_quantity} ${item.default_unit} = ${Math.round(item.calories_per_unit)} kcal`;
  }
  if (unitLabel) unitLabel.textContent = item.default_unit || 'g';

  if (item.photo_url && photoContainer && photoImg) {
    photoImg.src = item.photo_url;
    photoContainer.classList.remove('hidden');
  } else if (photoContainer) {
    photoContainer.classList.add('hidden');
  }

  // Quantité par défaut (100g ou 1 portion)
  const defaultQty = item.default_quantity || (item.item_type === 'dish' ? 1 : 100);
  if (qtyInput) {
    qtyInput.value = defaultQty;
    // Autofocus immédiat et pré-sélection totale du texte
    setTimeout(() => {
      qtyInput.focus();
      qtyInput.select();
    }, 50);
  }

  updateDropModalLiveMacros();

  if (modal) {
    modal.classList.remove('hidden');
  }

  // Écoute des touches Entrée et Échap sur la modal
  document.addEventListener('keydown', handleDropModalKeydown);
}

function closeDropPortionModal() {
  const modal = document.getElementById('modal-drop-portion');
  if (modal) modal.classList.add('hidden');
  pendingDropItem = null;
  pendingDropSlot = null;
  document.removeEventListener('keydown', handleDropModalKeydown);

  // Rétablissement immédiat du focus vers la barre de recherche du catalogue pour enchaîner
  const searchInput = document.getElementById('catalog-search-input');
  if (searchInput) searchInput.focus();
}

function handleDropModalKeydown(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    confirmDropPortionModal();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeDropPortionModal();
  }
}

function updateDropModalLiveMacros() {
  if (!pendingDropItem) return;
  const item = pendingDropItem;
  const qtyInput = document.getElementById('drop-modal-qty-input');
  const qty = parseFloat(qtyInput ? qtyInput.value : 0) || 0;
  const baseQty = item.default_quantity || 100;
  const ratio = qty / baseQty;

  const cal = Math.round(item.calories_per_unit * ratio);
  const p = Math.round((item.protein_per_unit_g || 0) * ratio * 10) / 10;
  const g = Math.round((item.carbs_per_unit_g || 0) * ratio * 10) / 10;
  const l = Math.round((item.fat_per_unit_g || 0) * ratio * 10) / 10;

  const calEl = document.getElementById('drop-modal-live-cals');
  const protEl = document.getElementById('drop-modal-live-prot');
  const carbsEl = document.getElementById('drop-modal-live-carbs');
  const fatEl = document.getElementById('drop-modal-live-fat');

  if (calEl) calEl.textContent = `${cal} kcal`;
  if (protEl) protEl.textContent = `${p}g`;
  if (carbsEl) carbsEl.textContent = `${g}g`;
  if (fatEl) fatEl.textContent = `${l}g`;
}

async function confirmDropPortionModal() {
  if (!pendingDropItem || !pendingDropSlot) return;
  const item = pendingDropItem;
  const slot = pendingDropSlot;
  const qtyInput = document.getElementById('drop-modal-qty-input');
  const qty = parseFloat(qtyInput ? qtyInput.value : 0);

  if (!qty || qty <= 0) {
    if (typeof showToast === 'function') {
      showToast("Veuillez saisir une quantité supérieure à 0.", "error");
    } else {
      alert("Quantité invalide");
    }
    return;
  }

  const payload = {
    date: currentJournalDate,
    food_item_id: item.id,
    quantity: qty,
    unit: item.default_unit || 'g'
  };

  closeDropPortionModal();

  try {
    const res = await apiFetch(`/api/meals/journal/${slot}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      if (typeof showToast === 'function') {
        showToast(`'${item.name}' (${qty}${item.default_unit}) ajouté à votre ${slot} !`, 'success');
      }
      loadMealsJournal(currentJournalDate);
    } else {
      if (typeof showToast === 'function') showToast("Erreur lors de l'enregistrement", "error");
    }
  } catch (err) {
    if (typeof showToast === 'function') showToast("Erreur réseau", "error");
  }
}

// ============================================================================
// 4. GESTION DES MODALES DU CATALOGUE (CRÉATION / ÉDITION)
// ============================================================================


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
  if (isDish) {
    if (unitSelect) unitSelect.value = 'portion';
    if (qtyInput) qtyInput.value = '1';
  } else {
    if (unitSelect) unitSelect.value = 'g';
    if (qtyInput) qtyInput.value = '100';
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
      html += `<option value="cat_${f.id}">${f.name} (${f.default_quantity}${f.default_unit} = ${Math.round(f.calories_per_unit)} kcal)</option>`;
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
            <span class="text-xs font-bold text-white truncate">${ing.name}</span>
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
            <span class="text-[11px] font-bold text-slate-400">${ing.unit || 'g'}</span>
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
  document.getElementById('cat-modal-title').textContent = type === 'dish' ? 'Créer un nouveau Plat / Recette' : 'Créer un nouvel Aliment';
  
  if (type === 'dish') {
    document.getElementById('cat-item-unit').value = 'portion';
    document.getElementById('cat-item-qty').value = '1';
  } else {
    document.getElementById('cat-item-unit').value = 'g';
    document.getElementById('cat-item-qty').value = '100';
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
  document.getElementById('cat-item-unit').value = item.default_unit || 'g';
  document.getElementById('cat-item-qty').value = item.default_quantity || 100;
  document.getElementById('cat-item-cals').value = item.calories_per_unit;
  document.getElementById('cat-item-prot').value = item.protein_per_unit_g || 0;
  document.getElementById('cat-item-carbs').value = item.carbs_per_unit_g || 0;
  document.getElementById('cat-item-fat').value = item.fat_per_unit_g || 0;
  document.getElementById('cat-item-fiber').value = item.fiber_per_unit_g || 0;
  document.getElementById('cat-item-photo-url').value = item.photo_url || '';

  document.getElementById('cat-modal-title').textContent = `Modifier ${item.item_type === 'dish' ? 'le Plat' : "l'Aliment"}`;

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
      <span>${b.icon || '🛡️'}</span>
      <span>${b.title || b.benefit_id}</span>
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

  container.innerHTML = results.map(r => {
    const alreadySelected = modalSelectedBenefits.some(b => b.benefit_id === r.benefit_id);
    return `
      <button 
        type="button"
        onclick="applyAutoBenefitToModal('${r.benefit_id}', '${r.title.replace(/'/g, "\\'")}', '${r.icon}', '${r.explanation.replace(/'/g, "\\'")}')"
        class="inline-flex items-center space-x-1 text-[10px] px-2 py-0.5 rounded-md font-semibold transition-all ${
          alreadySelected 
            ? 'bg-brand-500 text-white font-bold' 
            : 'bg-brand-500/10 text-brand-300 border border-brand-500/30 hover:bg-brand-500/25'
        }"
        title="${r.explanation}"
      >
        <span>${r.icon}</span>
        <span>${r.title}</span>
        <span>${alreadySelected ? '✓' : '+'}</span>
      </button>
    `;
  }).join('');
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
    photo_url: photoUrl,
    recipe_items: modalDishIngredients
  };

  try {
    const isEdit = Boolean(itemId);
    const url = isEdit ? `/api/catalog/items/${itemId}` : '/api/catalog/items';
    const method = isEdit ? 'PUT' : 'POST';

    const res = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

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
    const res = await apiFetch(`/api/catalog/items/${itemId}`, { method: 'DELETE' });
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
// 5. JOURNAL DES REPAS DU QUOTIDIEN (4 DROP ZONES MODULAIRES)
// ============================================================================

async function loadMealsJournal(dateStr) {
  currentJournalDate = dateStr || currentJournalDate || new Date().toISOString().split('T')[0];
  const dateInput = document.getElementById('journal-date-input');
  if (dateInput) dateInput.value = currentJournalDate;

  try {
    const res = await apiFetch(`/api/meals/journal?date=${currentJournalDate}`);
    if (res.ok) {
      currentJournalData = await res.json();
      renderMealsJournal();
      if (typeof loadDashboardData === 'function') {
        loadDashboardData();
      }
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
  if (elProt) elProt.textContent = `${Math.round(sum.total_protein_g || 0)}g P`;
  if (elCarbs) elCarbs.textContent = `${Math.round(sum.total_carbs_g || 0)}g G`;
  if (elFat) elFat.textContent = `${Math.round(sum.total_fat_g || 0)}g L`;
  if (elFiber) elFiber.textContent = `${Math.round(sum.total_fiber_g || 0)}g F`;

  // 2. Les 4 repas
  const slotConfig = {
    breakfast: { name: "Petit-déjeuner", emoji: "🥐", border: "border-amber-500/30", color: "text-amber-400", bgBadge: "bg-amber-500/10" },
    lunch: { name: "Déjeuner", emoji: "🥗", border: "border-brand-500/30", color: "text-brand-400", bgBadge: "bg-brand-500/10" },
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
      <div 
        id="meal-zone-${slot}"
        class="meal-drop-zone bg-[#151D2A] border ${cfg.border} hover:border-brand-500/50 rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3.5 shadow-sm transition-all duration-150"
        ondragover="handleMealDragOver(event, '${slot}')"
        ondragleave="handleMealDragLeave(event, '${slot}')"
        ondrop="handleMealDrop(event, '${slot}')"
      >
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

        <!-- Indicateur dynamique au survol glissé (« Déposer ici ») -->
        <div id="drop-placeholder-${slot}" class="drop-target-placeholder hidden py-3 px-4 border-2 border-dashed border-brand-400 rounded-xl bg-brand-500/10 text-brand-300 text-xs font-bold text-center flex items-center justify-center space-x-2 animate-pulse">
          <i data-lucide="arrow-down-to-dot" class="w-4 h-4"></i>
          <span>Déposer ici pour ajouter à ce repas</span>
        </div>

        <!-- Liste des aliments consommés -->
        <div class="space-y-2 min-h-[50px]">
          ${items.length === 0 ? `
            <div class="py-4 text-center text-xs text-slate-500 border border-dashed border-[#1F2A3C] rounded-xl flex flex-col items-center justify-center space-y-1">
              <span>Aucun aliment composé pour ce repas.</span>
              <span class="text-[11px] text-slate-400 font-medium">Glissez un aliment depuis le catalogue de gauche 👈</span>
            </div>
          ` : items.map(it => `
            <div class="flex items-center justify-between p-2 rounded-xl bg-[#0B0F17] border border-[#1F2A3C] hover:border-slate-700 transition-colors">
              <div class="flex-1 pr-2">
                <div class="text-xs font-bold text-white line-clamp-1">${it.name}</div>
                <div class="text-[11px] text-slate-400">
                  <span class="font-semibold text-slate-300">${it.quantity} ${it.unit}</span> &bull; 
                  <span class="text-brand-400 font-bold">${Math.round(it.calories)} kcal</span> 
                  (P:${Math.round(it.protein_g || 0)}g G:${Math.round(it.carbs_g || 0)}g L:${Math.round(it.fat_g || 0)}g)
                </div>
              </div>
              <button onclick="removeMealLogItem('${it.id}')" title="Retirer l'aliment" class="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 shrink-0">
                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          `).join('')}
        </div>

        <!-- Boutons d'actions -->
        <div class="flex items-center gap-2 pt-2 border-t border-[#1F2A3C]/70">
          <button onclick="openSelectFromCatalogModal('${slot}')" class="flex-1 py-2 px-3 rounded-xl bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/30 text-brand-300 text-xs font-bold flex items-center justify-center space-x-1.5 transition-colors">
            <i data-lucide="plus" class="w-4 h-4"></i>
            <span>+ Ajouter un aliment</span>
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

  // 3. Synthèse des bienfaits du jour (Stage 13)
  renderJournalDayBenefitsSummary(meals);
}

function renderJournalDayBenefitsSummary(meals) {
  const container = document.getElementById('journal-day-benefits-tags');
  const countBadge = document.getElementById('journal-benefits-count-badge');
  if (!container) return;

  // Récupérer tous les food_item_id consommés au cours des repas de la journée
  const consumedFoodItemIds = new Set();
  const actualMeals = meals || (typeof currentJournalData !== "undefined" && currentJournalData && currentJournalData.meals) || [];
  actualMeals.forEach(m => {
    (m.items || []).forEach(it => {
      if (it.food_item_id) consumedFoodItemIds.add(it.food_item_id);
    });
  });

  const activeBenefitsMap = new Map();

  // Trouver les bienfaits via les items du catalogue
  if (Array.isArray(currentCatalogItems)) {
    currentCatalogItems.forEach(catItem => {
      if (consumedFoodItemIds.has(catItem.id)) {
        (catItem.benefits || []).forEach(b => {
          const bId = b.benefit_id || b.id;
          if (!activeBenefitsMap.has(bId)) {
            activeBenefitsMap.set(bId, {
              ...b,
              foodNames: [catItem.name]
            });
          } else {
            activeBenefitsMap.get(bId).foodNames.push(catItem.name);
          }
        });
      }
    });
  }
  // Calcul synthétique supplémentaire selon les macros totales du jour
  const sum = (typeof currentJournalData !== "undefined" && currentJournalData && currentJournalData.day_summary) || {};
  if ((sum.total_fiber_g || 0) >= 25) {
    if (!activeBenefitsMap.has('gut_transit')) {
      activeBenefitsMap.set('gut_transit', {
        title: "Transit et confort intestinal",
        icon: "🌿",
        explanation: `Objectif journalier EFSA atteint (${Math.round(sum.total_fiber_g)}g >= 25g de fibres)`,
        foodNames: ["Fibres totales"]
      });
    }
  }
  if ((sum.total_protein_g || 0) >= 80) {
    if (!activeBenefitsMap.has('muscle_function')) {
      activeBenefitsMap.set('muscle_function', {
        title: "Fonction musculaire et récupération",
        icon: "💪",
        explanation: `Apport protéique majeur (${Math.round(sum.total_protein_g)}g) soutenant la synthèse musculaire`,
        foodNames: ["Protéines totales"]
      });
    }
  }

  const benefitsList = Array.from(activeBenefitsMap.values());
  if (countBadge) {
    countBadge.textContent = `${benefitsList.length} bienfait${benefitsList.length > 1 ? 's' : ''} actif${benefitsList.length > 1 ? 's' : ''}`;
  }

  if (benefitsList.length === 0) {
    container.innerHTML = '<span class="text-xs text-slate-500 italic">Ajoutez des aliments à vos repas pour découvrir les bienfaits métaboliques et santé de votre journée.</span>';
    return;
  }

  container.innerHTML = benefitsList.map(b => `
    <div 
      class="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-brand-500/10 border border-brand-500/25 text-brand-300 text-xs shadow-sm cursor-help hover:bg-brand-500/20 hover:scale-105 transition-all"
      title="${b.title} : ${b.explanation ? b.explanation : ''} (Apporté par : ${(b.foodNames || []).join(', ')})"
    >
      <span class="text-base">${b.icon || '🛡️'}</span>
      <span class="text-[10px] font-bold text-brand-300 font-mono">${(b.foodNames || []).length}</span>
    </div>
  `).join('');
}

async function removeMealLogItem(itemId) {
  try {
    const res = await apiFetch(`/api/meals/journal/items/${itemId}`, { method: 'DELETE' });
    if (res.ok) {
      if (typeof showToast === 'function') showToast("Aliment retiré du repas", "success");
      loadMealsJournal(currentJournalDate);
    }
  } catch (err) {
    alert("Erreur lors de la suppression de l'aliment");
  }
}

// ============================================================================
// 6. MODALE ALTERNATIVE DE SÉLECTION CLIC / DOUBLE-CLIC
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
  // Déclenche la pop-in rapide directement sur le slot actif
  openDropPortionModal(item, currentActiveMealSlot || 'lunch');
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

  container.innerHTML = filtered.map(it => {
    const isPublic = Boolean(it.is_public || it.user_id === 0 || it.user_id === null || it.source === 'public');
    const isFriend = Boolean(it.owner_name || it.friend_name || (it.source === 'friend' || it.source === 'friends'));
    let badge = '';
    if (isPublic) {
      badge = '<span class="text-[9px] px-1.5 py-0.2 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30">Public</span>';
    } else if (isFriend) {
      badge = `<span class="text-[9px] px-1.5 py-0.2 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">${it.owner_name || it.friend_name || 'Ami'}</span>`;
    } else {
      badge = '<span class="text-[9px] px-1.5 py-0.2 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30">Perso</span>';
    }
    return `
      <div onclick="selectCatalogItemForPortion('${it.id}')" class="p-2.5 rounded-xl bg-[#0B0F17] hover:bg-[#1F2A3C] border border-[#1F2A3C] hover:border-brand-500/50 cursor-pointer flex items-center justify-between transition-colors">
        <div class="flex-1 pr-2">
          <div class="flex items-center space-x-1.5">
            <span class="text-xs font-bold text-white">${it.name}</span>
            ${badge}
          </div>
          <div class="text-[11px] text-slate-400">Réf: ${it.default_quantity} ${it.default_unit} &bull; ${Math.round(it.calories_per_unit)} kcal</div>
        </div>
        <button class="px-2 py-1 rounded-lg bg-brand-500/20 text-brand-300 text-xs font-semibold shrink-0">Choisir</button>
      </div>
    `;
  }).join('');
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
    const res = await apiFetch(`/api/meals/journal/${currentActiveMealSlot}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

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
    const res = await apiFetch(`/api/meals/journal/${slot}/save-as-dish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

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

// ============================================================================
// 7. RACCOURCIS CLAVIER GLOBAUX POUR NAVIGATEUR DESKTOP
// ============================================================================

document.addEventListener('keydown', (e) => {
  // Raccourci '/' ou 'Ctrl+K' pour focus rapide sur la recherche du catalogue
  if ((e.key === '/' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    e.preventDefault();
    const searchInput = document.getElementById('catalog-search-input');
    if (searchInput) {
      searchInput.focus();
      searchInput.select();
    }
  }

  // Raccourci 'Escape' pour fermer la modale d'amis
  if (e.key === 'Escape') {
    const friendsModal = document.getElementById('modal-friends-catalog');
    if (friendsModal && !friendsModal.classList.contains('hidden')) {
      closeFriendsCatalogModal();
    }
  }
});

// Initialisation globale au chargement
// Initialisation globale au chargement & binding des écouteurs
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initNutritionNavigation();
    loadCatalogItems();
    loadMealsJournal();
  });
} else {
  initNutritionNavigation();
  loadCatalogItems();
  loadMealsJournal();
}

window.handleCatItemTypeChange = handleCatItemTypeChange;
window.handleDishIngredientSelectChange = handleDishIngredientSelectChange;
window.addIngredientToDish = addIngredientToDish;
window.removeDishIngredient = removeDishIngredient;
window.updateDishIngredientQuantity = updateDishIngredientQuantity;



// ============================================================================
// 8. GESTION DES ABONNEMENTS AUX CATALOGUES D'AMIS (BALI-85)
// ============================================================================

function openFriendsCatalogModal() {
  const modal = document.getElementById('modal-friends-catalog');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }
  loadFriendSubscriptions();
}

function closeFriendsCatalogModal() {
  const modal = document.getElementById('modal-friends-catalog');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
  closeFriendCatalogExplorer();
}

async function loadFriendSubscriptions() {
  const container = document.getElementById('friends-subscriptions-list');
  const pill = document.getElementById('friends-count-pill');
  if (container) {
    container.innerHTML = '<div class="py-6 text-center text-xs text-slate-500"><span class="animate-spin inline-block mr-2">⏳</span> Chargement de vos amis abonnés...</div>';
  }

  try {
    const res = await apiFetch('/api/catalog/subscriptions');
    if (res.ok) {
      currentFriendSubscriptions = await res.json();
      renderFriendSubscriptionsList(currentFriendSubscriptions);
      if (pill) {
        pill.textContent = `${currentFriendSubscriptions.length} abonné${currentFriendSubscriptions.length > 1 ? 's' : ''}`;
      }
    } else {
      if (container) {
        container.innerHTML = '<div class="py-6 text-center text-xs text-rose-400">Impossible de charger la liste des abonnements.</div>';
      }
    }
  } catch (err) {
    console.error("Erreur récupération abonnements amis:", err);
    if (container) {
      container.innerHTML = '<div class="py-6 text-center text-xs text-rose-400">Erreur réseau lors de la récupération des abonnements.</div>';
    }
  }
}

function renderFriendSubscriptionsList(subs) {
  const container = document.getElementById('friends-subscriptions-list');
  if (!container) return;

  if (!subs || subs.length === 0) {
    container.innerHTML = `
      <div class="py-8 text-center bg-[#0B0F17] border border-dashed border-[#1F2A3C] rounded-xl p-4 space-y-2">
        <i data-lucide="user-plus" class="w-8 h-8 text-slate-600 mx-auto"></i>
        <p class="text-xs text-slate-400 font-medium">Vous n'êtes actuellement abonné à aucun catalogue d'ami.</p>
        <p class="text-[11px] text-slate-500">Saisissez l'email de votre ami ci-dessus pour accéder à ses recettes.</p>
      </div>
    `;
    if (window.lucide && lucide.createIcons) lucide.createIcons();
    return;
  }

  container.innerHTML = subs.map(sub => {
    const friendName = sub.friend_name || sub.name || sub.email || `Ami #${sub.target_user_id || sub.id}`;
    const friendEmail = sub.friend_email || sub.email || '';
    const itemsCount = sub.items_count !== undefined ? sub.items_count : (sub.total_items || '--');
    const targetId = sub.target_user_id || sub.id;

    return `
      <div class="bg-[#0B0F17] border border-[#1F2A3C] hover:border-brand-500/40 rounded-xl p-3 flex items-center justify-between gap-3 transition-all">
        <div class="flex items-center space-x-3 min-w-0 flex-1">
          <div class="w-9 h-9 rounded-xl bg-brand-500/20 border border-brand-500/30 text-brand-300 font-bold flex items-center justify-center shrink-0 text-xs">
            ${friendName.charAt(0).toUpperCase()}
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center space-x-2">
              <span class="font-bold text-xs text-white truncate">${friendName}</span>
              <span class="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>Synchronisé</span>
              </span>
            </div>
            <div class="text-[11px] text-slate-400 truncate">${friendEmail || 'Utilisateur partagé'} &bull; ${itemsCount} aliments partagés</div>
          </div>
        </div>

        <div class="flex items-center gap-1.5 shrink-0">
          <button 
            type="button" 
            onclick="exploreFriendCatalog('${targetId}', '${friendName}')" 
            class="px-2.5 py-1.5 rounded-lg bg-brand-500/15 hover:bg-brand-500/25 border border-brand-500/30 text-brand-300 text-xs font-semibold flex items-center space-x-1 transition-all"
            title="Explorer le catalogue de cet ami"
          >
            <i data-lucide="eye" class="w-3.5 h-3.5"></i>
            <span>Explorer</span>
          </button>
          <button 
            type="button" 
            onclick="removeFriendSubscription('${targetId}', '${friendName}')" 
            class="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
            title="Se désabonner de ce catalogue"
          >
            <i data-lucide="user-x" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    `;
  }).join('');

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

async function addFriendSubscription() {
  const input = document.getElementById('friend-sub-input');
  if (!input) return;
  const val = input.value.trim();
  if (!val) {
    if (typeof showToast === 'function') showToast("Veuillez saisir un email ou identifiant d'ami", "warning");
    input.focus();
    return;
  }

  const btn = document.getElementById('btn-add-friend-sub');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="animate-spin">⏳</span>';
  }

  try {
    const payload = val.includes('@') ? { email: val } : { target_user_id: parseInt(val, 10) || val };
    const res = await apiFetch('/api/catalog/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      input.value = '';
      if (typeof showToast === 'function') showToast("Abonnement au catalogue validé avec succès !", "success");
      await loadFriendSubscriptions();
      loadCatalogItems(); // Actualise le catalogue principal
    } else {
      const err = await res.json().catch(() => ({}));
      const msg = err.detail || "Impossible de trouver ou s'abonner à cet utilisateur.";
      if (typeof showToast === 'function') showToast(msg, "error");
      else alert(msg);
    }
  } catch (err) {
    console.error("Erreur abonnement ami:", err);
    if (typeof showToast === 'function') showToast("Erreur réseau lors de l'abonnement", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<i data-lucide="user-plus" class="w-3.5 h-3.5"></i><span>S'abonner</span>';
      if (window.lucide && lucide.createIcons) lucide.createIcons();
    }
  }
}

async function removeFriendSubscription(targetId, friendName) {
  if (!confirm(`Souhaitez-vous vous désabonner du catalogue de ${friendName || 'cet ami'} ?`)) {
    return;
  }

  try {
    const res = await apiFetch(`/api/catalog/subscriptions/${targetId}`, {
      method: 'DELETE'
    });

    if (res.ok) {
      if (typeof showToast === 'function') showToast(`Désabonné du catalogue de ${friendName}`, "info");
      if (currentExplorerFriend && currentExplorerFriend.id == targetId) {
        closeFriendCatalogExplorer();
      }
      await loadFriendSubscriptions();
      loadCatalogItems();
    } else {
      alert("Erreur lors du désabonnement.");
    }
  } catch (err) {
    console.error("Erreur désabonnement:", err);
    alert("Erreur réseau lors du désabonnement.");
  }
}

async function exploreFriendCatalog(friendId, friendName) {
  const explorerView = document.getElementById('friend-catalog-explorer-view');
  const nameEl = document.getElementById('explorer-friend-name');
  const countEl = document.getElementById('explorer-friend-items-count');
  const listEl = document.getElementById('friend-explorer-items-list');

  if (!explorerView || !listEl) return;

  currentExplorerFriend = { id: friendId, name: friendName };
  explorerView.classList.remove('hidden');
  if (nameEl) nameEl.textContent = friendName;
  if (countEl) countEl.textContent = "Chargement des aliments...";
  listEl.innerHTML = '<div class="py-6 text-center text-xs text-slate-500"><span class="animate-spin inline-block mr-2">⏳</span> Récupération du catalogue de l'ami...</div>';

  try {
    const res = await apiFetch(`/api/catalog/friends/${friendId}/items`);
    if (res.ok) {
      currentExplorerFriendItems = await res.json();
      if (countEl) countEl.textContent = `${currentExplorerFriendItems.length} aliment${currentExplorerFriendItems.length > 1 ? 's' : ''} et plat${currentExplorerFriendItems.length > 1 ? 's' : ''}`;
      renderFriendExplorerItems(currentExplorerFriendItems);
    } else {
      listEl.innerHTML = '<div class="py-4 text-center text-xs text-rose-400">Impossible de charger le catalogue de cet ami.</div>';
    }
  } catch (err) {
    console.error("Erreur exploration catalogue ami:", err);
    listEl.innerHTML = '<div class="py-4 text-center text-xs text-rose-400">Erreur réseau lors de la récupération des aliments.</div>';
  }
}

function closeFriendCatalogExplorer() {
  const explorerView = document.getElementById('friend-catalog-explorer-view');
  if (explorerView) explorerView.classList.add('hidden');
  currentExplorerFriend = null;
  currentExplorerFriendItems = [];
}

function renderFriendExplorerItems(items) {
  const listEl = document.getElementById('friend-explorer-items-list');
  if (!listEl) return;

  if (!items || items.length === 0) {
    listEl.innerHTML = '<div class="py-4 text-center text-xs text-slate-500 italic">Cet ami n'a pas encore d'aliments dans son catalogue.</div>';
    return;
  }

  listEl.innerHTML = items.map(it => {
    const isDish = it.item_type === 'dish';
    const cal = Math.round(it.calories_per_unit);
    const unit = `${it.default_quantity}${it.default_unit || 'g'}`;
    const p = Math.round((it.protein_per_unit_g || 0) * 10) / 10;
    const g = Math.round((it.carbs_per_unit_g || 0) * 10) / 10;
    const l = Math.round((it.fat_per_unit_g || 0) * 10) / 10;

    return `
      <div class="bg-[#0B0F17] border border-[#1F2A3C] rounded-xl p-2.5 flex items-center justify-between gap-2 hover:border-brand-500/40 transition-colors">
        <div class="flex items-center space-x-2 min-w-0 flex-1">
          <span class="text-base shrink-0">${isDish ? '🍽️' : '🍎'}</span>
          <div class="min-w-0 flex-1">
            <h5 class="text-xs font-bold text-white truncate">${it.name}</h5>
            <div class="text-[10px] text-slate-400 font-mono">
              ${unit} &bull; <span class="text-amber-400 font-bold">${cal} kcal</span> (P:${p}g G:${g}g L:${l}g)
            </div>
          </div>
        </div>

        <div class="flex items-center space-x-1.5 shrink-0">
          <button 
            type="button" 
            onclick="copyFriendItemToMyCatalog('${it.id}')" 
            class="px-2 py-1 rounded-lg bg-brand-500/15 hover:bg-brand-500/25 border border-brand-500/30 text-brand-300 text-[11px] font-semibold flex items-center space-x-1 transition-all"
            title="Copier cet aliment dans mon catalogue personnel"
          >
            <i data-lucide="copy" class="w-3 h-3"></i>
            <span>Importer</span>
          </button>
          <button 
            type="button" 
            onclick="addFriendItemDirectlyToActiveMeal('${it.id}')" 
            class="px-2 py-1 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 text-[11px] font-semibold flex items-center space-x-1 transition-all"
            title="Consommer directement dans mon repas actuel"
          >
            <i data-lucide="plus" class="w-3 h-3"></i>
            <span>Consommer</span>
          </button>
        </div>
      </div>
    `;
  }).join('');

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

async function copyFriendItemToMyCatalog(itemId) {
  // Recherche l'item soit dans currentExplorerFriendItems, soit dans currentCatalogItems
  const item = (currentExplorerFriendItems || []).find(it => it.id == itemId) || (currentCatalogItems || []).find(it => it.id == itemId);
  if (!item) return;

  const payload = {
    name: item.name,
    item_type: item.item_type || 'food',
    default_unit: item.default_unit || 'g',
    default_quantity: item.default_quantity || 100.0,
    calories_per_unit: item.calories_per_unit,
    protein_per_unit_g: item.protein_per_unit_g || 0.0,
    carbs_per_unit_g: item.carbs_per_unit_g || 0.0,
    fat_per_unit_g: item.fat_per_unit_g || 0.0,
    fiber_per_unit_g: item.fiber_per_unit_g || 0.0,
    photo_url: item.photo_url || null,
    recipe_items: item.recipe_items || []
  };

  try {
    const res = await apiFetch('/api/catalog/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      if (typeof showToast === 'function') {
        showToast(`'${item.name}' a été importé dans votre catalogue personnel !`, 'success');
      }
      loadCatalogItems();
    } else {
      alert("Erreur lors de l'import de l'aliment dans votre catalogue.");
    }
  } catch (err) {
    console.error("Erreur import aliment:", err);
    alert("Erreur réseau lors de l'import.");
  }
}

function addFriendItemDirectlyToActiveMeal(itemId) {
  const item = (currentExplorerFriendItems || []).find(it => it.id == itemId) || (currentCatalogItems || []).find(it => it.id == itemId);
  if (!item) return;
  closeFriendsCatalogModal();
  openDropPortionModal(item, currentActiveMealSlot || 'lunch');
}

window.openFriendsCatalogModal = openFriendsCatalogModal;
window.closeFriendsCatalogModal = closeFriendsCatalogModal;
window.loadFriendSubscriptions = loadFriendSubscriptions;
window.addFriendSubscription = addFriendSubscription;
window.removeFriendSubscription = removeFriendSubscription;
window.exploreFriendCatalog = exploreFriendCatalog;
window.closeFriendCatalogExplorer = closeFriendCatalogExplorer;
window.copyFriendItemToMyCatalog = copyFriendItemToMyCatalog;
window.addFriendItemDirectlyToActiveMeal = addFriendItemDirectlyToActiveMeal;
window.filterCatalogSource = filterCatalogSource;
