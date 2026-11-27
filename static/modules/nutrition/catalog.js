// static/modules/nutrition/catalog.js - Catalogue aliments/plats, filtres et Drag & Drop

// ============================================================================
// 1. CATALOGUE D'ALIMENTS & PLATS
// ============================================================================

/**
 * Charge le catalogue complet une seule fois puis le conserve en mémoire.
 * Tous les filtres (type, recherche, bienfait) sont ensuite appliqués localement
 * par renderCatalogItems() : aucune requête HTTP à la frappe (Lot 2 - BALI-90).
 * @param {boolean} [force=false] - Force un rechargement réseau (après création/suppression).
 */
async function loadCatalogItems(force = false) {
  const container = document.getElementById('catalog-items-grid');

  if (catalogLoaded && !force) {
    renderCatalogItems();
    return;
  }

  if (catalogLoadPromise && !force) {
    await catalogLoadPromise;
    return;
  }

  if (container && currentCatalogItems.length === 0) {
    container.innerHTML = '<div class="col-span-full py-12 text-center text-slate-500 text-sm">Chargement du catalogue...</div>';
  }

  let url = '/api/catalog/items';
  const params = [];
  if (currentCatalogSourceFilter && currentCatalogSourceFilter !== 'all') {
    params.push(`source=${encodeURIComponent(currentCatalogSourceFilter)}`);
  }
  if (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active && window.currentReadOnlyFriend.friend_id) {
    params.push(`user_id=${window.currentReadOnlyFriend.friend_id}`);
  }
  if (params.length > 0) {
    url += '?' + params.join('&');
  }

  catalogLoadPromise = (async () => {
    try {
      const res = await apiFetch(url);
      if (res.ok) {
        currentCatalogItems = await res.json();
        catalogLoaded = true;
        renderCatalogItems();
        if (document.getElementById("modal-catalog-picker-list")) {
          renderModalCatalogList();
        }
        return true;
      }
      console.warn("Échec requête catalogue:", res.status);
      renderCatalogLoadError(container, res.status);
      if (typeof showToast === 'function') {
        showToast(catalogErrorMessage(res.status), "error");
      }
    } catch (err) {
      console.error("Erreur réseau ou rendu catalogue:", err);
      renderCatalogLoadError(container, 0);
      if (typeof showToast === 'function') {
        showToast("Catalogue indisponible : erreur réseau. Vérifiez votre connexion puis réessayez.", "error");
      }
    }
    return false;
  })();

  try {
    await catalogLoadPromise;
  } finally {
    catalogLoadPromise = null;
  }
}

/** Invalide le cache catalogue (après création, édition ou suppression d'un élément). */
function invalidateCatalogCache() {
  catalogLoaded = false;
}

/** Message d'erreur lisible selon le code HTTP (BALI-99 / Lot A). */
function catalogErrorMessage(status) {
  if (status === 401) return "Session expirée. Veuillez vous reconnecter pour accéder au catalogue.";
  if (status === 404) return "Catalogue introuvable (404). Contactez le support si cela persiste.";
  if (status >= 500) return "Erreur serveur (5xx). L'équipe technique a été notifiée, réessayez dans quelques instants.";
  return "Erreur de chargement du catalogue (code " + status + "). Réessayez ou actualisez la page.";
}

/** Affiche une carte d'erreur explicite (avec relance) dans la grille du catalogue. */
function renderCatalogLoadError(container, status) {
  if (!container) return;
  container.innerHTML = `
    <div class="col-span-full bg-rose-500/10 border border-rose-500/30 rounded-2xl p-4 space-y-2 text-center">
      <p class="text-sm font-bold text-rose-300">Catalogue indisponible</p>
      <p class="text-xs text-slate-400">${catalogErrorMessage(status)}</p>
      <button type="button" onclick="loadCatalogItems(true)" class="px-3 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/30 text-rose-200 text-xs font-semibold transition-colors">
        Réessayer
      </button>
    </div>
  `;
  if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
}
window.renderCatalogLoadError = renderCatalogLoadError;
window.catalogErrorMessage = catalogErrorMessage;

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
  // Filtrage 100 % local : le catalogue est déjà en mémoire.
  if (catalogLoaded) {
    renderCatalogItems();
  } else {
    loadCatalogItems();
  }
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
  loadCatalogItems(true);
}

let catalogSearchDebounceTimer = null;

function handleCatalogSearch(e) {
  const val = e.target.value || '';
  if (catalogSearchDebounceTimer) {
    clearTimeout(catalogSearchDebounceTimer);
  }
  catalogSearchDebounceTimer = setTimeout(() => {
    currentCatalogSearch = val;
    // Aucune requête réseau : on filtre currentCatalogItems en mémoire et on rend immédiatement.
    if (catalogLoaded) {
      renderCatalogItems();
    } else {
      loadCatalogItems();
    }
  }, 250);
}

/** Normalise un texte pour la recherche : minuscules, sans accents, espaces compactés. */
function normalizeSearchText(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/œ/gi, 'oe')
    .replace(/æ/gi, 'ae')
    .toLowerCase()
    .trim();
}

const CATALOG_CATEGORIES = [
  { id: 'viandes', label: 'Viandes & Volailles', shortLabel: 'Viandes', emoji: '🥩', order: 1, badgeClass: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  { id: 'poissons_oeufs', label: 'Poissons & Œufs', shortLabel: 'Poissons & Œufs', emoji: '🐟', order: 2, badgeClass: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
  { id: 'legumes', label: 'Légumes & Crudités', shortLabel: 'Légumes', emoji: '🥦', order: 3, badgeClass: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  { id: 'fruits', label: 'Fruits', shortLabel: 'Fruits', emoji: '🍎', order: 4, badgeClass: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  { id: 'feculents', label: 'Féculents, Céréales & Pain', shortLabel: 'Féculents', emoji: '🍚', order: 5, badgeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  { id: 'laitages', label: 'Laitages & Fromages', shortLabel: 'Laitages', emoji: '🥛', order: 6, badgeClass: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  { id: 'legumineuses_oleagineux', label: 'Légumineuses & Oléagineux', shortLabel: 'Oléagineux', emoji: '🥜', order: 7, badgeClass: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30' },
  { id: 'matieres_grasses', label: 'Matières grasses & Huiles', shortLabel: 'Lipides', emoji: '🫒', order: 8, badgeClass: 'bg-lime-500/15 text-lime-300 border-lime-500/30' },
  { id: 'plats_composes', label: 'Plats cuisinés & Salades', shortLabel: 'Plats', emoji: '🍲', order: 9, badgeClass: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30' },
  { id: 'boissons', label: 'Boissons', shortLabel: 'Boissons', emoji: '🥤', order: 10, badgeClass: 'bg-teal-500/15 text-teal-300 border-teal-500/30' },
  { id: 'sucre_snacks', label: 'Produits sucrés & Collations', shortLabel: 'Snacks', emoji: '🍫', order: 11, badgeClass: 'bg-pink-500/15 text-pink-300 border-pink-500/30' },
  { id: 'autre', label: 'Autre', shortLabel: 'Autre', emoji: '🍽️', order: 12, badgeClass: 'bg-slate-500/15 text-slate-300 border-slate-500/30' }
];

const CATALOG_CATEGORY_BY_ID = Object.fromEntries(CATALOG_CATEGORIES.map(c => [c.id, c]));

const CATALOG_CATEGORY_KEYWORDS = [
  ['matieres_grasses', ['huile', 'beurre', 'margarine', 'creme fraiche', 'mayonnaise', 'vinaigrette', 'saindoux']],
  ['boissons', ["lait d'amande", "lait d'avoine", 'lait de soja', ' eau ', 'eau minerale', 'eau plate', 'eau gazeuse', 'cafe', ' the ', 'the vert', 'the noir', 'tisane', 'infusion', ' jus ', 'jus d', 'soda', 'smoothie', 'biere', ' vin ', 'boisson', 'kombucha', 'limonade']],
  ['sucre_snacks', ['chocolat', 'sucre', 'miel', 'confiture', 'biscuit', 'gateau', 'patisserie', 'bonbon', 'glace', 'chips', 'brioche', 'croissant', 'viennoiserie', 'compote']],
  ['viandes', ['poulet', 'dinde', 'boeuf', 'steak', 'veau', 'porc', 'jambon', 'agneau', 'canard', 'lardon', 'saucisse', 'viande', 'bacon', 'escalope', 'magret', 'bavette', 'entrecote']],
  ['poissons_oeufs', ['saumon', 'thon', 'cabillaud', 'truite', 'maquereau', 'sardine', 'crevette', 'moule', 'poisson', 'colin', 'merlu', 'dorade', 'oeuf', 'omelette']],
  ['laitages', ['yaourt', 'yogourt', 'fromage', ' lait ', 'skyr', 'petit suisse', 'mozzarella', 'emmental', ' comte ', 'parmesan', 'ricotta', 'cottage', 'kefir', 'faisselle']],
  ['legumineuses_oleagineux', ['amande', 'noix', 'noisette', 'cajou', 'pistache', 'cacahuete', 'lentille', 'pois chiche', 'haricot rouge', 'haricot blanc', 'soja', 'tofu', 'tempeh', 'edamame', 'graine', 'chia', ' lin ']],
  ['feculents', ['avoine', ' riz ', 'riz ', 'pates', 'spaghetti', 'tagliatelle', ' pain', 'baguette', 'tartine', 'quinoa', 'semoule', 'boulgour', 'patate', 'pomme de terre', 'farine', ' ble ', 'sarrasin', ' mais ', 'muesli', 'granola', 'biscotte', 'gnocchi']],
  ['fruits', ['banane', ' pomme ', 'pommes', ' poire ', 'poires', 'fraise', 'framboise', 'myrtille', 'orange', 'clementine', 'mandarine', 'kiwi', 'mangue', 'ananas', 'raisin', 'peche', 'abricot', 'melon', 'pasteque', 'cerise', 'citron', 'figue', ' datte', 'prune', 'fruit']],
  ['legumes', ['avocat', 'tomate', 'carotte', 'brocoli', 'haricot vert', 'courgette', 'aubergine', 'poivron', 'concombre', 'salade', 'laitue', 'epinard', 'chou', 'oignon', ' ail ', 'champignon', 'poireau', 'radis', 'betterave', 'celeri', 'asperge', 'petit pois', 'legume']],
  ['plats_composes', ['bowl', 'pizza', 'burger', 'sandwich', 'quiche', 'gratin', 'curry', 'wok', 'soupe', 'potage', 'lasagne', 'couscous', 'paella', 'wrap', 'poke']]
];

function resolveCatalogItemCategory(item) {
  if (!item) return 'autre';
  const raw = String(item.category || '').trim().toLowerCase();
  if (raw && CATALOG_CATEGORY_BY_ID[raw]) return raw;
  if (item.item_type === 'dish') return 'plats_composes';
  const normName = ` ${normalizeSearchText(item.name || '')} `;
  for (const [slug, keywords] of CATALOG_CATEGORY_KEYWORDS) {
    if (keywords.some(kw => normName.includes(kw))) {
      return slug;
    }
  }
  return 'autre';
}

function getCatalogCategoryMeta(categoryId) {
  return CATALOG_CATEGORY_BY_ID[categoryId] || CATALOG_CATEGORY_BY_ID.autre;
}

/** Vrai si l'élément correspond à la recherche libre (tous les mots saisis doivent être présents). */
function catalogItemMatchesSearch(item, normalizedQuery) {
  if (!normalizedQuery) return true;
  // L'index de recherche est calculé une seule fois par élément (et non à chaque frappe).
  if (item.__searchHaystack === undefined) {
    const catMeta = getCatalogCategoryMeta(resolveCatalogItemCategory(item));
    item.__searchHaystack = normalizeSearchText(`${item.name || ''} ${item.description || ''} ${catMeta.label} ${catMeta.shortLabel}`);
  }
  return normalizedQuery.split(/\s+/).filter(Boolean).every(token => item.__searchHaystack.includes(token));
}

/** Réinitialise recherche, type, catégorie, tri et bienfait du catalogue. */
function resetCatalogFilters() {
  currentCatalogSearch = '';
  currentCatalogBenefitFilter = '';
  currentCatalogCategoryFilter = '';
  currentCatalogSort = 'name_asc';
  currentCatalogFilter = 'all';

  const searchInput = document.getElementById('catalog-search-input');
  if (searchInput) searchInput.value = '';

  const benefitSelect = document.getElementById('cat-filter-benefit');
  if (benefitSelect) benefitSelect.value = '';

  const categorySelect = document.getElementById('cat-filter-category');
  if (categorySelect) categorySelect.value = '';

  const sortSelect = document.getElementById('cat-sort-select');
  if (sortSelect) sortSelect.value = 'name_asc';

  ['all', 'food', 'dish'].forEach(t => {
    const btn = document.getElementById(`cat-filter-${t}`);
    if (!btn) return;
    btn.className = t === 'all'
      ? 'flex-1 px-2 py-1.5 rounded-lg text-xs font-bold bg-brand-500 text-white transition-colors'
      : 'flex-1 px-2 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-[#151D2A] transition-colors';
  });

  renderCatalogItems();
}

function handleBenefitFilterChange(event) {
  currentCatalogBenefitFilter = event.target.value;
  renderCatalogItems();
}

function handleCategoryFilterChange(event) {
  currentCatalogCategoryFilter = event.target.value;
  renderCatalogItems();
}

function handleCatalogSortChange(event) {
  currentCatalogSort = event.target.value || 'name_asc';
  renderCatalogItems();
}

const CATALOG_MEAL_SLOT_ACTIONS = [
  { slot: 'breakfast', emoji: '🥐', label: 'Petit-déjeuner', classes: 'bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/30' },
  { slot: 'lunch', emoji: '🥗', label: 'Déjeuner', classes: 'bg-brand-500/10 hover:bg-brand-500/20 border-brand-500/30' },
  { slot: 'snack', emoji: '🍎', label: 'Goûter', classes: 'bg-pink-500/10 hover:bg-pink-500/20 border-pink-500/30' },
  { slot: 'dinner', emoji: '🍲', label: 'Dîner', classes: 'bg-indigo-500/10 hover:bg-indigo-500/20 border-indigo-500/30' }
];

function buildCatalogItemCardHtml(item) {
  const isDish = item.item_type === 'dish';
  const catMeta = getCatalogCategoryMeta(resolveCatalogItemCategory(item));
  const categoryIconBox = `<span class="inline-flex items-center justify-center w-8 h-8 rounded-xl border ${catMeta.badgeClass} text-base shadow-sm shrink-0" title="Catégorie : ${escapeHtml(catMeta.label)}">${catMeta.emoji}</span>`;

  const natureBadge = isDish
    ? `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 shrink-0" title="Plat composé / Recette">🍲 Plat composé</span>`
    : `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 shrink-0" title="Ingrédient brut">Ingrédient</span>`;

  let sourceBadge = '';
  const isPublic = Boolean(item.is_public || item.user_id === 0 || item.user_id === null || item.source === 'public');
  const isFriend = Boolean(item.owner_name || item.friend_name || (item.source === 'friend' || item.source === 'friends'));
  if (isPublic) {
    sourceBadge = `<span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/30 shrink-0" title="Catalogue public" aria-label="Catalogue public"><i data-lucide="globe" class="w-3 h-3"></i></span>`;
  } else if (isFriend) {
    const rawFriendLabel = item.owner_name || item.friend_name || "Ami";
    const friendLabel = escapeHtml(rawFriendLabel);
    sourceBadge = `<span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 shrink-0" title="Partagé par ${friendLabel}" aria-label="Partagé par ${friendLabel}"><i data-lucide="user-check" class="w-3 h-3"></i></span>`;
  } else {
    sourceBadge = `<span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30 shrink-0" title="Création personnelle" aria-label="Création personnelle"><i data-lucide="user" class="w-3 h-3"></i></span>`;
  }

  const unitLabel = escapeHtml(`${item.default_quantity}${item.default_unit || 'g'}`);
  const p = Math.round((item.protein_per_unit_g || 0) * 10) / 10;
  const g = Math.round((item.carbs_per_unit_g || 0) * 10) / 10;
  const l = Math.round((item.fat_per_unit_g || 0) * 10) / 10;
  const cal = Math.round(item.calories_per_unit);
  const itemName = escapeHtml(item.name || '');
  const itemId = escapeHtml(String(item.id));
  const photoUrl = sanitizeUrl(item.photo_url);
  const categoryBadge = `<span class="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold border ${catMeta.badgeClass} shrink-0" title="Catégorie : ${escapeHtml(catMeta.label)}">${escapeHtml(catMeta.shortLabel)}</span>`;
  const cardSurfaceClass = isDish
    ? 'bg-gradient-to-br from-[#0B0F17] to-indigo-950/25 border-indigo-500/35 hover:border-indigo-400/70 hover:shadow-indigo-500/10'
    : 'bg-[#0B0F17] border-[#1F2A3C] hover:border-brand-500/60 hover:shadow-brand-500/10';
  const cardSig = escapeHtml(`${item.updated_at || ''}|${item.item_type || 'food'}|${item.name || ''}|${catMeta.id}|${cal}|${p}|${g}|${l}`);

  const mealQuickButtonsHtml = CATALOG_MEAL_SLOT_ACTIONS.map(m => `
    <button
      type="button"
      onclick="promptAddToMeal('${itemId}', '${m.slot}')"
      title="Ajouter au ${m.label}"
      aria-label="Ajouter ${itemName} au ${m.label}"
      class="w-8 h-8 rounded-lg border ${m.classes} text-sm flex items-center justify-center transition-all active:scale-95"
    >${m.emoji}</button>
  `).join('');

  const benefitsList = item.benefits || [];
  const benefitsHtml = benefitsList.length > 0 ? `
    <div class="flex flex-wrap items-center gap-1 pt-0.5">
      ${benefitsList.map(b => {
        const bTitle = escapeHtml(b.title || b.benefit_id || '');
        const bExp = b.explanation ? ' : ' + escapeHtml(b.explanation) : '';
        const bIcon = escapeHtml(b.icon || '🛡️');
        return `
          <span 
            class="inline-flex items-center justify-center w-5 h-5 rounded-md bg-brand-500/15 border border-brand-500/30 text-xs cursor-help hover:scale-110 hover:bg-brand-500/25 transition-all shadow-sm"
            title="${bTitle}${bExp}"
          >
            ${bIcon}
          </span>
        `;
      }).join('')}
    </div>
  ` : '';

  const recipeHtml = (isDish && item.recipe_items && item.recipe_items.length > 0) ? `
    <div class="px-2 py-0.5 bg-[#151D2A]/80 rounded-lg border border-indigo-500/20 text-[10px] text-slate-400 truncate" title="${escapeHtml(item.recipe_items.map(ing => `${ing.name} (${ing.quantity}${ing.unit || 'g'})`).join(', '))}">
      <span class="text-indigo-300 font-bold">🥗 ${item.recipe_items.length} ingr. :</span>
      <span class="text-slate-300 font-medium">${escapeHtml(item.recipe_items.map(ing => ing.name).join(', '))}</span>
    </div>
  ` : '';

  return `
    <div 
      class="catalog-draggable-card ${cardSurfaceClass} border rounded-xl p-2.5 flex flex-col justify-between space-y-2 transition-all shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md select-none group"
      draggable="true"
      ondragstart="handleCatalogDragStart(event, '${itemId}')"
      ondragend="handleCatalogDragEnd(event)"
      data-item-id="${itemId}"
      data-item-sig="${cardSig}"
      title="Cliquer sur un repas ci-dessous ou glisser vers un repas"
      ondblclick="promptAddToMeal('${itemId}')"
    >
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-start space-x-2.5 min-w-0 flex-1">
          ${categoryIconBox}
          <div class="min-w-0 flex-1 space-y-1">
            <h4 class="font-bold text-xs sm:text-sm text-white leading-snug" style="overflow-wrap:break-word;" title="${itemName}">${itemName}</h4>
            <div class="flex flex-wrap items-center gap-1">
              ${natureBadge}
              ${categoryBadge}
              ${sourceBadge}
            </div>
          </div>
        </div>
        <div class="text-right shrink-0 pt-0.5">
          <span class="text-xs font-black text-amber-400">${cal}</span>
          <span class="text-[9px] text-slate-400">kcal</span>
        </div>
      </div>

      ${photoUrl ? `
        <div class="rounded-lg overflow-hidden border border-[#1F2A3C] h-14 bg-[#151D2A]">
          <img src="${photoUrl}" alt="${itemName}" class="w-full h-full object-cover pointer-events-none">
        </div>
      ` : ''}

      <div class="flex items-center justify-between gap-2 text-[10px] text-slate-400 font-mono px-2.5 py-1 bg-[#151D2A] rounded-lg">
        <span class="text-slate-300 font-semibold truncate">Réf: ${unitLabel}</span>
        <span class="shrink-0 space-x-1.5">
          <span class="text-brand-400 font-semibold">P:${p}g</span>
          <span class="text-sky-400 font-semibold">G:${g}g</span>
          <span class="text-amber-400 font-semibold">L:${l}g</span>
        </span>
      </div>

      ${recipeHtml}

      ${benefitsHtml}

      <div class="flex items-center justify-between gap-1.5 pt-1 border-t border-[#1F2A3C]/70 ${(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active) ? 'hidden' : ''}">
        <div class="flex items-center gap-1" role="group" aria-label="Ajouter directement à un repas">
          ${mealQuickButtonsHtml}
        </div>
        
        <div class="flex items-center gap-1">
          ${(!isPublic && !isFriend) ? `
            <button onclick="openEditCatalogItemModal('${itemId}')" title="Modifier" aria-label="Modifier cet aliment" class="p-1 rounded-md text-slate-400 hover:text-white hover:bg-[#151D2A] min-w-[36px] min-h-[36px] flex items-center justify-center">
              <i data-lucide="pencil" class="w-3 h-3"></i>
            </button>
            <button onclick="deleteCatalogItem('${itemId}')" title="Supprimer" aria-label="Supprimer cet aliment" class="p-1 rounded-md text-rose-400/70 hover:text-rose-400 hover:bg-rose-500/10 min-w-[36px] min-h-[36px] flex items-center justify-center">
              <i data-lucide="trash-2" class="w-3 h-3"></i>
            </button>
          ` : (isFriend ? `
            <button onclick="copyFriendItemToMyCatalog('${itemId}')" title="Importer dans mon catalogue" aria-label="Importer dans mon catalogue" class="px-1.5 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-300 text-[10px] font-semibold flex items-center space-x-1 min-h-[36px]">
              <i data-lucide="copy" class="w-2.5 h-2.5"></i>
              <span>Importer</span>
            </button>
          ` : '')}
        </div>
      </div>
    </div>
  `;
}

function renderCatalogItems() {
  const container = document.getElementById('catalog-items-grid');
  const countBadge = document.getElementById('catalog-items-count');

  let itemsToRender = Array.isArray(currentCatalogItems) ? currentCatalogItems : [];

  // 1. Filtre par type (aliments / plats) — appliqué en mémoire
  if (currentCatalogFilter && currentCatalogFilter !== 'all') {
    itemsToRender = itemsToRender.filter(it => it.item_type === currentCatalogFilter);
  }

  // 2. Recherche libre — appliquée en mémoire avec debounce (0 requête réseau)
  const normalizedQuery = normalizeSearchText(currentCatalogSearch);
  if (normalizedQuery) {
    itemsToRender = itemsToRender.filter(it => catalogItemMatchesSearch(it, normalizedQuery));
  }

  // 3. Filtre par bienfait santé
  if (currentCatalogBenefitFilter) {
    itemsToRender = itemsToRender.filter(it => {
      const bList = it.benefits || [];
      return bList.some(b => (b.benefit_id || b.id) === currentCatalogBenefitFilter);
    });
  }

  // 4. Filtre par catégorie alimentaire (BALI-273)
  if (currentCatalogCategoryFilter) {
    itemsToRender = itemsToRender.filter(it => resolveCatalogItemCategory(it) === currentCatalogCategoryFilter);
  }

  // 5. Tri du catalogue (BALI-273)
  itemsToRender = itemsToRender.slice().sort((a, b) => {
    if (currentCatalogSort === 'category') {
      const ca = getCatalogCategoryMeta(resolveCatalogItemCategory(a));
      const cb = getCatalogCategoryMeta(resolveCatalogItemCategory(b));
      if (ca.order !== cb.order) return ca.order - cb.order;
      return String(a.name || '').localeCompare(String(b.name || ''), 'fr');
    }
    if (currentCatalogSort === 'calories_asc') {
      return (Number(a.calories_per_unit) || 0) - (Number(b.calories_per_unit) || 0);
    }
    if (currentCatalogSort === 'calories_desc') {
      return (Number(b.calories_per_unit) || 0) - (Number(a.calories_per_unit) || 0);
    }
    if (currentCatalogSort === 'protein_desc') {
      return (Number(b.protein_per_unit_g) || 0) - (Number(a.protein_per_unit_g) || 0);
    }
    return String(a.name || '').localeCompare(String(b.name || ''), 'fr');
  });

  if (countBadge) {
    countBadge.textContent = `${itemsToRender.length} élément${itemsToRender.length > 1 ? 's' : ''}`;
  }

  if (!container) return;

  if (itemsToRender.length === 0) {
    const hasFilter = Boolean(normalizedQuery || currentCatalogBenefitFilter || currentCatalogCategoryFilter || (currentCatalogFilter && currentCatalogFilter !== 'all'));
    const safeSearch = escapeHtml((currentCatalogSearch || '').trim());
    container.innerHTML = `
      <div class="col-span-full py-10 text-center bg-[#0B0F17] border border-[#1F2A3C] rounded-2xl p-6 space-y-3">
        <i data-lucide="book-open" class="w-9 h-9 text-slate-600 mx-auto"></i>
        <h4 class="text-sm font-bold text-slate-300">Aucun ingrédient ou plat correspondant</h4>
        <p class="text-xs text-slate-400 max-w-sm mx-auto">${normalizedQuery ? `Aucun résultat pour « ${safeSearch} ».` : 'Aucun élément ne correspond à votre filtre.'}</p>
        <div class="flex flex-wrap items-center justify-center gap-2 pt-2">
          ${hasFilter ? `<button onclick="resetCatalogFilters()" class="px-3 py-1.5 rounded-xl bg-[#1F2A3C] text-slate-200 text-xs font-semibold hover:bg-[#2A3850] transition-colors">Réinitialiser les filtres</button>` : ''}
          <button onclick="openCreateCatalogItemModal('food')" class="px-3 py-1.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold">+ Nouvel ingrédient</button>
          <button onclick="openCreateCatalogItemModal('dish')" class="px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold">+ Nouveau plat</button>
        </div>
      </div>
    `;
    refreshIcons(container);
    return;
  }

  // Nettoyage de l'état vide s'il était affiché
  if (container.querySelector('.col-span-full')) {
    container.innerHTML = '';
  }

  // Rendu différentiel : réutilisation des cartes DOM existantes sans tout détruire
  const targetIds = itemsToRender.map(it => String(it.id));
  const targetIdsSet = new Set(targetIds);

  // 1. Supprimer les nœuds devenus obsolètes
  const currentCards = Array.from(container.children);
  const existingMap = new Map();
  for (const child of currentCards) {
    const id = child.getAttribute('data-item-id');
    if (!id || !targetIdsSet.has(id)) {
      child.remove();
    } else {
      existingMap.set(id, child);
    }
  }

  // 2. Mettre à jour, réordonner ou insérer les cartes nécessaires
  const newlyCreatedCards = [];
  const template = document.createElement('template');

  for (let i = 0; i < itemsToRender.length; i++) {
    const item = itemsToRender[i];
    const itemIdStr = String(item.id);
    let card = existingMap.get(itemIdStr);

    const expectedSig = `${item.updated_at || ''}|${item.item_type || 'food'}|${item.name || ''}|${resolveCatalogItemCategory(item)}|${Math.round(item.calories_per_unit)}|${Math.round((item.protein_per_unit_g || 0) * 10) / 10}|${Math.round((item.carbs_per_unit_g || 0) * 10) / 10}|${Math.round((item.fat_per_unit_g || 0) * 10) / 10}`;
    if (card && card.getAttribute('data-item-sig') === expectedSig) {
      if (container.children[i] !== card) {
        container.insertBefore(card, container.children[i] || null);
      }
    } else {
      template.innerHTML = buildCatalogItemCardHtml(item).trim();
      const newCard = template.content.firstElementChild;
      if (card) {
        container.replaceChild(newCard, card);
      } else {
        container.insertBefore(newCard, container.children[i] || null);
      }
      card = newCard;
      existingMap.set(itemIdStr, card);
      newlyCreatedCards.push(card);
    }
  }

  // Rafraîchir les icônes Lucide uniquement sur les éléments nouvellement insérés
  if (newlyCreatedCards.length > 0) {
    newlyCreatedCards.forEach(c => refreshIcons(c));
  }

  // 3. Synthèse des bienfaits du jour (Stage 13)
  if (typeof renderJournalDayBenefitsSummary === "function" && typeof currentJournalData !== "undefined" && currentJournalData && currentJournalData.meals) {
    renderJournalDayBenefitsSummary(currentJournalData.meals);
  }
}


// ============================================================================
// 2. GESTION DU GLISSER-DÉPOSER NATIF (HTML5 DRAG & DROP & POINTER EVENTS)
// ============================================================================

function handleCatalogDragStart(event, itemId) {
  if (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active) {
    event.preventDefault();
    return;
  }
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
      <div class="font-bold text-xs text-white">${escapeHtml(item.name)}</div>
      <div class="text-[10px] text-brand-300">${Math.round(item.calories_per_unit)} kcal &bull; ${escapeHtml(item.default_quantity)} ${escapeHtml(item.default_unit)}</div>
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

function confirmDropPortionModal() {
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

  const targetDate = currentJournalDate;
  const payload = {
    date: targetDate,
    food_item_id: item.id,
    quantity: qty,
    unit: item.default_unit || 'g'
  };

  // 1) Fermeture immédiate de la pop-in (le focus revient à la recherche du catalogue)
  closeDropPortionModal();

  // 2) Mise à jour optimiste en mémoire + rendu AVANT la fin de la requête réseau (< 16 ms)
  const optimisticItem = buildOptimisticJournalItem(item, qty);
  const snapshot = applyOptimisticItemAdded(targetDate, slot, optimisticItem);
  if (typeof showToast === 'function') {
    showToast(`'${item.name}' (${qty}${item.default_unit || 'g'}) ajouté !`, 'success');
  }

  // 3) Persistance réseau en arrière-plan puis consolidation sans rechargement global
  persistOptimisticAddition(payload, targetDate, slot, snapshot, item);
}

