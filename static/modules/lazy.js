// static/modules/lazy.js - Lazy loading and skeleton manager for VitalTrack 6-Tab Architecture

const TAB_MODULES = {
  summary: { loaded: false, loading: false },
  weight: { loaded: false, loading: false },
  nutrition: { loaded: false, loading: false },
  activity: { loaded: false, loading: false },
  goals: { loaded: false, loading: false },
  devices: { loaded: false, loading: false }
};

/**
 * Render skeleton UI into a view container while data is loading.
 * @param {string} tabId 
 */
function renderTabSkeleton(tabId) {
  const container = document.getElementById(`tab-${tabId}-skeleton`);
  if (!container) return;
  
  if (tabId === 'weight') {
    container.innerHTML = `
      <div class="space-y-4">
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div class="h-28 skeleton-shimmer rounded-2xl"></div>
          <div class="h-28 skeleton-shimmer rounded-2xl"></div>
          <div class="h-28 skeleton-shimmer rounded-2xl"></div>
          <div class="h-28 skeleton-shimmer rounded-2xl"></div>
        </div>
        <div class="h-80 skeleton-shimmer rounded-2xl"></div>
      </div>
    `;
  } else if (tabId === 'activity') {
    container.innerHTML = `
      <div class="space-y-4">
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div class="h-24 skeleton-shimmer rounded-2xl"></div>
          <div class="h-24 skeleton-shimmer rounded-2xl"></div>
          <div class="h-24 skeleton-shimmer rounded-2xl"></div>
        </div>
        <div class="h-72 skeleton-shimmer rounded-2xl"></div>
      </div>
    `;
  } else if (tabId === 'devices') {
    container.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="h-44 skeleton-shimmer rounded-2xl"></div>
        <div class="h-44 skeleton-shimmer rounded-2xl"></div>
      </div>
    `;
  } else if (tabId === 'nutrition') {
    container.innerHTML = `
      <div class="space-y-4">
        <div class="h-14 skeleton-shimmer rounded-2xl"></div>
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <div class="h-96 skeleton-shimmer rounded-2xl"></div>
          <div class="h-96 skeleton-shimmer rounded-2xl"></div>
        </div>
      </div>
    `;
  } else if (tabId === 'goals') {
    container.innerHTML = `
      <div class="space-y-4">
        <div class="h-28 skeleton-shimmer rounded-2xl"></div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="h-56 skeleton-shimmer rounded-2xl"></div>
          <div class="h-56 skeleton-shimmer rounded-2xl"></div>
          <div class="h-56 skeleton-shimmer rounded-2xl"></div>
        </div>
      </div>
    `;
  }
  container.classList.remove('hidden');
}

/**
 * Hide the skeleton UI for a tab once data is ready.
 * @param {string} tabId 
 */
function hideTabSkeleton(tabId) {
  const container = document.getElementById(`tab-${tabId}-skeleton`);
  if (container) {
    container.classList.add('hidden');
  }
}

/**
 * Lazy load specific tab data on demand.
 * @param {string} tabId 
 */
async function loadTabData(tabId) {
  const state = TAB_MODULES[tabId];
  if (!state || state.loaded || state.loading) return;

  state.loading = true;
  renderTabSkeleton(tabId);

  try {
    if (tabId === 'weight') {
      if (typeof renderWeightView === 'function') {
        renderWeightView();
      }
    } else if (tabId === 'nutrition') {
      if (typeof initNutritionNavigation === 'function') initNutritionNavigation();
      if (typeof loadCatalogItems === 'function') await loadCatalogItems();
      if (typeof loadMealsJournal === 'function') await loadMealsJournal();
      if (typeof renderNutritionView === 'function') renderNutritionView();
    } else if (tabId === 'activity') {
      if (typeof renderActivityView === 'function') {
        renderActivityView();
      }
    } else if (tabId === 'goals') {
      if (typeof renderGoalsView === 'function') {
        renderGoalsView();
      }
    } else if (tabId === 'devices') {
      if (typeof renderDevicesView === 'function') {
        renderDevicesView();
      }
    }
    state.loaded = true;
  } catch (err) {
    console.error(`[LazyLoad] Erreur lors du chargement de l'onglet ${tabId}:`, err);
  } finally {
    state.loading = false;
    hideTabSkeleton(tabId);
  }
}

/**
 * Enhanced switchTab supporting 6 tabs, lazy loading, and desktop/mobile active styles.
 * @param {string} tabId - summary, weight, nutrition, activity, goals, devices
 */
function switchTab(tabId) {
  // Hide all view contents
  document.querySelectorAll('.view-content').forEach(el => el.classList.add('hidden'));
  
  const activeView = document.getElementById(`view-${tabId}`);
  if (activeView) {
    activeView.classList.remove('hidden');
  }

  // Desktop tab button active classes (Electric Violet / Cyan accent)
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.remove('nav-tab-active', 'text-white', 'border-violet-500');
    btn.classList.add('text-slate-400', 'border-transparent');
  });
  const deskBtn = document.getElementById(`tab-${tabId}-desk`);
  if (deskBtn) {
    deskBtn.classList.remove('text-slate-400', 'border-transparent');
    deskBtn.classList.add('nav-tab-active', 'text-white', 'border-violet-500');
  }

  // Mobile bottom bar button active classes
  document.querySelectorAll('nav.md\\:hidden button[id^="tab-"]').forEach(btn => {
    btn.classList.remove('text-violet-400', 'text-white');
    btn.classList.add('text-slate-400');
  });
  const mobBtn = document.getElementById(`tab-${tabId}-mob`);
  if (mobBtn) {
    mobBtn.classList.remove('text-slate-400');
    mobBtn.classList.add('text-violet-400', 'text-white');
  }

  // Trigger lazy loading for on-demand tabs
  if (tabId !== 'summary') {
    loadTabData(tabId);
  }

  // Resize Chart.js instances gracefully
  setTimeout(() => {
    if (tabId === 'weight' && typeof chartWeightDetail !== 'undefined' && chartWeightDetail) chartWeightDetail.resize();
    if (tabId === 'nutrition' && typeof chartMealsStacked !== 'undefined' && chartMealsStacked) chartMealsStacked.resize();
    if (tabId === 'activity' && typeof chartActivity !== 'undefined' && chartActivity) chartActivity.resize();
    if (tabId === 'summary' && typeof chartWeightSummary !== 'undefined' && chartWeightSummary) chartWeightSummary.resize();
    if (tabId === 'summary' && typeof chartMacrosDonut !== 'undefined' && chartMacrosDonut) chartMacrosDonut.resize();
    if (window.lucide && lucide.createIcons) {
      try { lucide.createIcons(); } catch (e) {}
    }
  }, 60);
}

// Invalidate loaded state when user clicks Refresh
function invalidateTabCaches() {
  Object.keys(TAB_MODULES).forEach(key => {
    TAB_MODULES[key].loaded = false;
  });
}

window.TAB_MODULES = TAB_MODULES;
window.renderTabSkeleton = renderTabSkeleton;
window.hideTabSkeleton = hideTabSkeleton;
window.loadTabData = loadTabData;
window.switchTab = switchTab;
window.invalidateTabCaches = invalidateTabCaches;
