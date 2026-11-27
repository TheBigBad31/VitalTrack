// static/modules/nutrition.js - Module Desktop Web & PWA pour Catalogue Aliments & Plats et Journal Quotidien

// static/app.js - Module Desktop Web & PWA pour Catalogue Aliments & Plats et Journal Quotidien des Repas (Stage 12)

let currentCatalogItems = [];
let currentCatalogFilter = 'all'; // 'all', 'food', 'dish'
let currentCatalogSourceFilter = 'all'; // 'all', 'mine', 'public', 'friends' (Stage 15 / BALI-85)
let currentCatalogBenefitFilter = ''; // Filtre par bienfait (Stage 13)
let currentCatalogCategoryFilter = ''; // Filtre par catégorie alimentaire (BALI-273)
let currentCatalogSort = 'name_asc'; // Tri du catalogue (BALI-273)
let currentFriendSubscriptions = []; // Liste des abonnements aux catalogues d'amis
let currentExplorerFriend = null; // Ami en cours d'exploration
let currentExplorerFriendItems = []; // Aliments de l'ami
let currentCatalogSearch = '';
let currentJournalDate = new Date().toISOString().split('T')[0];
let currentJournalData = null;
let currentActiveMealSlot = 'lunch';

// --- Lot 2 (BALI-90) : cache mémoire par date, requêtes dédupliquées & mutations optimistes ---
// journalCacheByDate[date] = { date, meals: [...], day_summary: {...} }
// Rejouer une date déjà consultée coûte 0 requête et 0 ms de rendu.
const journalCacheByDate = new Map();

// --- BALI-143 : États de chargement boutons & prévention double-clic ---
/** Déclencher l'état "chargement" sur un bouton (afficher micro-spinner + désactiver) */
function setButtonLoading(btn, state = true) {
  if (!btn) return;
  if (state) {
    btn.classList.add('btn-loading');
    const spinner = btn.querySelector('.spinner');
    if (!spinner) {
      const s = document.createElement('div');
      s.className = 'spinner';
      btn.appendChild(s);
    }
    btn.disabled = true;
    btn.title = 'En cours...';
  } else {
    btn.classList.remove('btn-loading');
    const spinner = btn.querySelector('.spinner');
    if (spinner) spinner.remove();
    btn.disabled = false;
    btn.title = '';
  }
}

/** Empêcher les double-clics sur un bouton en le désactivant temporairement */
function preventDoubleClick(btn) {
  if (!btn) return;
  let clicked = false;
  btn.addEventListener('click', (e) => {
    if (clicked) {
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }
    clicked = true;
    setButtonLoading(btn, true);
    // Réactiver après 300ms (délai de double-clic + temps de chargement)
    setTimeout(() => {
      clicked = false;
      setButtonLoading(btn, false);
    }, 300);
  });
}
// Promesses de chargement en vol (déduplication : 1 seule requête par date).
const journalInflightByDate = new Map();
// Horodatage de la dernière lecture serveur par date (stale-while-revalidate).
const journalFetchedAtByDate = new Map();
const JOURNAL_REVALIDATE_MS = 30000;
// Nombre de mutations optimistes en cours par date (garde anti-écrasement par une revalidation).
const journalPendingMutations = new Map();
// Préchargement de J-1 effectué (une seule fois par session).
let journalPrefetchDone = false;
// Cache du catalogue : chargé une fois, filtré 100 % en mémoire ensuite.
let catalogLoaded = false;
let catalogLoadPromise = null;
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
  const layoutContainer = document.getElementById('nutrition-desktop-layout-container');
  const secJournal = document.getElementById('nutrition-sec-journal');
  const secCatalog = document.getElementById('nutrition-sec-catalog');
  const analyticsSec = document.getElementById('nutrition-journal-analytics');
  const catalogGrid = document.getElementById('catalog-items-grid');
  const btnMap = {
    split: document.getElementById('btn-subnav-desktop-split'),
    journal: document.getElementById('btn-subnav-journal'),
    catalog: document.getElementById('btn-subnav-catalog')
  };

  const activeBtnClass = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-brand-500 text-white shadow-md shadow-brand-500/20 flex items-center justify-center space-x-2 transition-all';
  const inactiveBtnClass = 'flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-400 hover:text-white hover:bg-[#151D2A] flex items-center justify-center space-x-2 transition-all';

  Object.entries(btnMap).forEach(([key, btn]) => {
    if (btn) btn.className = key === mode ? activeBtnClass : inactiveBtnClass;
  });

  if (mode === 'split') {
    if (layoutContainer) {
      layoutContainer.className = 'grid grid-cols-1 xl:grid-cols-12 gap-6 items-start';
    }
    if (secJournal) {
      secJournal.className = 'xl:col-span-7 space-y-4';
    }
    if (secCatalog) {
      secCatalog.className = 'xl:col-span-5 space-y-4';
    }
    if (catalogGrid) {
      catalogGrid.className = 'grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[750px] overflow-y-auto pr-1';
    }
    if (analyticsSec) {
      analyticsSec.classList.remove('hidden');
    }
    loadCatalogItems();
    loadMealsJournal(currentJournalDate);
  } else if (mode === 'journal') {
    if (layoutContainer) {
      layoutContainer.className = 'grid grid-cols-1 gap-6 items-start';
    }
    if (secJournal) {
      secJournal.className = 'space-y-4';
    }
    if (secCatalog) {
      secCatalog.classList.add('hidden');
    }
    if (analyticsSec) {
      analyticsSec.classList.remove('hidden');
    }
    loadMealsJournal(currentJournalDate);
  } else if (mode === 'catalog') {
    if (layoutContainer) {
      layoutContainer.className = 'grid grid-cols-1 gap-6 items-start';
    }
    if (secJournal) {
      secJournal.classList.add('hidden');
    }
    if (secCatalog) {
      secCatalog.className = 'space-y-4';
    }
    if (catalogGrid) {
      catalogGrid.className = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3';
    }
    if (analyticsSec) {
      analyticsSec.classList.add('hidden');
    }
    loadCatalogItems();
  }
}

function switchNutritionSubSection(sub) {
  if (typeof switchTab === 'function' && (typeof currentActiveTab === 'undefined' || currentActiveTab !== 'nutrition')) {
    switchTab('nutrition');
  }

  switchNutritionLayout(sub);

  if (sub === 'catalog') {
    const searchInput = document.getElementById('catalog-search-input');
    if (searchInput) {
      searchInput.focus({ preventScroll: true });
    }
  }
}

function initNutritionNavigation() {
  switchNutritionLayout(currentNutritionLayoutMode || 'split');
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


async function refreshNutritionWithMetricsSync() {
  const btn = document.getElementById('btn-sync-nutrition-metrics');
  const icon = btn ? btn.querySelector('i') : null;
  if (icon) icon.classList.add('animate-spin');

  try {
    if (typeof triggerDeviceSync === 'function') {
      await triggerDeviceSync('health_connect');
    }
    if (typeof loadMealsJournal === 'function') {
      await loadMealsJournal(currentJournalDate);
    }
    if (typeof showToast === 'function') {
      showToast('Conseils et métriques synchronisés !', 'success');
    }
  } catch (err) {
    console.warn('[nutrition] sync error:', err);
    if (typeof showToast === 'function') showToast('Synchronisation effectuée.', 'info');
  } finally {
    if (icon) icon.classList.remove('animate-spin');
  }
}

window.openBarcodeScannerModal = openBarcodeScannerModal;
window.closeBarcodeScannerModal = closeBarcodeScannerModal;
window.resetBarcodeScannerStep = resetBarcodeScannerStep;
window.startCameraBarcodeScanner = startCameraBarcodeScanner;
window.stopCameraBarcodeScanner = stopCameraBarcodeScanner;
window.lookupManualBarcode = lookupManualBarcode;
window.lookupBarcode = lookupBarcode;
window.updateBarcodeLivePortionMacros = updateBarcodeLivePortionMacros;
window.addScannedProductToCatalog = addScannedProductToCatalog;
window.addScannedProductToActiveMeal = addScannedProductToActiveMeal;
window.refreshNutritionWithMetricsSync = refreshNutritionWithMetricsSync;
