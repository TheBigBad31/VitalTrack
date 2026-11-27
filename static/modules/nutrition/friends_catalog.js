// static/modules/nutrition/friends_catalog.js - Catalogue partagé des amis

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
  const container = document.getElementById('friends-subscriptions-list') || document.getElementById('friends-subscriptions-container');
  if (!container) return;

  if (!subs || subs.length === 0) {
    container.innerHTML = `
      <div class="py-8 text-center text-xs text-slate-500 border border-dashed border-[#1F2A3C] rounded-2xl p-4">
        <i data-lucide="users" class="w-8 h-8 text-slate-600 mx-auto mb-2"></i>
        Vous n'êtes abonné à aucun catalogue d'ami pour le moment.<br>
        Entrez l'email d'un ami ci-dessus pour vous abonner à ses aliments et plats composés.
      </div>
    `;
    refreshIcons(container);
    return;
  }

  container.innerHTML = subs.map(sub => {
    const rawTargetId = sub.friend_id || sub.target_user_id || sub.id;
    const targetId = parseInt(rawTargetId, 10) || 0;
    const rawEmail = sub.friend_email || sub.target_user_email || sub.email || '';
    const rawFriendName = sub.friend_name || sub.target_user_name || (rawEmail ? rawEmail.split('@')[0] : 'Ami');
    const friendName = escapeHtml(rawFriendName);
    const friendEmail = escapeHtml(rawEmail || 'Utilisateur partagé');
    const friendPicture = sanitizeUrl(sub.friend_picture || sub.picture);
    const initials = escapeHtml(rawFriendName.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'VT');
    const itemsCount = sub.shared_items_count !== undefined ? parseInt(sub.shared_items_count, 10) : (sub.items ? sub.items.length : 0);

    return `
      <div class="p-3 rounded-2xl bg-[#0B0F17] border border-[#1F2A3C] flex items-center justify-between gap-3 hover:border-brand-500/50 transition-all">
        <div class="flex items-center space-x-3 min-w-0">
          <div class="w-10 h-10 rounded-xl overflow-hidden flex items-center justify-center bg-gradient-to-tr from-brand-600 to-electric-cyan text-white font-bold text-xs shrink-0">
            ${friendPicture ? `<img src="${friendPicture}" class="w-full h-full object-cover">` : initials}
          </div>
          <div class="min-w-0">
            <div class="flex items-center space-x-1.5">
              <span class="font-bold text-xs text-white truncate">${friendName}</span>
              <span class="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>Synchronisé</span>
              </span>
            </div>
            <div class="text-[11px] text-slate-400 truncate">${friendEmail} &bull; ${itemsCount} aliments partagés</div>
          </div>
        </div>

        <div class="flex items-center gap-1.5 shrink-0">
          <button 
            type="button" 
            data-action="explore-friend-catalog"
            data-target-id="${targetId}"
            data-friend-name="${friendName}"
            class="btn-explore-friend-catalog px-2.5 py-1.5 rounded-lg bg-brand-500/15 hover:bg-brand-500/25 border border-brand-500/30 text-brand-300 text-xs font-semibold flex items-center space-x-1 transition-all"
            title="Explorer le catalogue de cet ami"
          >
            <i data-lucide="eye" class="w-3.5 h-3.5"></i>
            <span>Explorer</span>
          </button>
          <button 
            type="button" 
            data-action="remove-friend-sub"
            data-target-id="${targetId}"
            data-friend-name="${friendName}"
            class="btn-remove-friend-sub p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
            title="Se désabonner de ce catalogue"
          >
            <i data-lucide="user-x" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    `;
  }).join('');

  container.querySelectorAll('.btn-explore-friend-catalog').forEach(btn => {
    btn.addEventListener('click', () => {
      exploreFriendCatalog(parseInt(btn.dataset.targetId, 10), btn.dataset.friendName);
    });
  });

  container.querySelectorAll('.btn-remove-friend-sub').forEach(btn => {
    btn.addEventListener('click', () => {
      removeFriendSubscription(parseInt(btn.dataset.targetId, 10), btn.dataset.friendName);
    });
  });

  refreshIcons(container);
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
      loadCatalogItems(true); // Actualise le catalogue principal
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
      btn.innerHTML = `<i data-lucide="user-plus" class="w-3.5 h-3.5"></i><span>S'abonner</span>`;
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
      loadCatalogItems(true);
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
  listEl.innerHTML = `<div class="py-6 text-center text-xs text-slate-500"><span class="animate-spin inline-block mr-2">⏳</span> Récupération du catalogue de l'ami...</div>`;

  try {
    const res = await apiFetch(`/api/catalog/friends/${friendId}/items`);
    if (res.ok) {
      const payload = await res.json();
      currentExplorerFriendItems = Array.isArray(payload) ? payload : (payload.items || []);
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
  const listEl = document.getElementById('friend-explorer-items-list') || document.getElementById('friend-catalog-explorer-items');
  if (!listEl) return;

  if (!items || items.length === 0) {
    listEl.innerHTML = `<div class="py-4 text-center text-xs text-slate-500 italic">Cet ami n'a pas encore d'aliments dans son catalogue.</div>`;
    return;
  }

  listEl.innerHTML = items.map(it => {
    const isDish = it.item_type === 'dish';
    const cal = Math.round(it.calories_per_unit);
    const unit = escapeHtml(`${it.default_quantity}${it.default_unit || 'g'}`);
    const p = Math.round((it.protein_per_unit_g || 0) * 10) / 10;
    const g = Math.round((it.carbs_per_unit_g || 0) * 10) / 10;
    const l = Math.round((it.fat_per_unit_g || 0) * 10) / 10;
    const itName = escapeHtml(it.name || '');
    const itId = escapeHtml(String(it.id));

    return `
      <div class="bg-[#0B0F17] border border-[#1F2A3C] rounded-xl p-2.5 flex items-center justify-between gap-2 hover:border-brand-500/40 transition-colors">
        <div class="flex items-center space-x-2 min-w-0 flex-1">
          <span class="text-base shrink-0">${isDish ? '🍽️' : '🍎'}</span>
          <div class="min-w-0 flex-1">
            <h5 class="text-xs font-bold text-white truncate">${itName}</h5>
            <div class="text-[10px] text-slate-400 font-mono">
              ${unit} &bull; <span class="text-amber-400 font-bold">${cal} kcal</span> (P:${p}g G:${g}g L:${l}g)
            </div>
          </div>
        </div>

        <div class="flex items-center space-x-1.5 shrink-0">
          <button 
            type="button" 
            onclick="copyFriendItemToMyCatalog('${itId}')" 
            class="px-2 py-1 rounded-lg bg-brand-500/15 hover:bg-brand-500/25 border border-brand-500/30 text-brand-300 text-[11px] font-semibold flex items-center space-x-1 transition-all"
            title="Copier cet aliment dans mon catalogue personnel"
          >
            <i data-lucide="copy" class="w-3 h-3"></i>
            <span>Importer</span>
          </button>
          <button 
            type="button" 
            onclick="addFriendItemDirectlyToActiveMeal('${itId}')" 
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
    category: item.category || null,
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
      loadCatalogItems(true);
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

// Lot 2 (BALI-90) : cache journal, préchargement & filtrage local du catalogue
window.journalCacheByDate = journalCacheByDate;
window.loadMealsJournal = loadMealsJournal;
window.changeJournalDate = changeJournalDate;
window.handleJournalDateChange = handleJournalDateChange;
window.setJournalToToday = setJournalToToday;
window.prefetchAdjacentJournalDates = prefetchAdjacentJournalDates;
window.invalidateJournalCache = invalidateJournalCache;
window.invalidateCatalogCache = invalidateCatalogCache;
window.resetCatalogFilters = resetCatalogFilters;
window.handleCategoryFilterChange = handleCategoryFilterChange;
window.handleCatalogSortChange = handleCatalogSortChange;
window.resolveCatalogItemCategory = resolveCatalogItemCategory;
window.loadCatalogItems = loadCatalogItems;
window.renderCatalogItems = renderCatalogItems;


