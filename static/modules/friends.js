// static/modules/friends.js - Gestion du cercle d'amis, demandes de partage et mode consultation Read-Only
// VitalTrack Desktop & PWA Web

// ============================================================================
// ÉTAT GLOBAL DU MODULE AMIS & MODE CONSULTATION
// ============================================================================

window.currentFriendsData = {
  friends: [],
  incoming_requests: [],
  outgoing_requests: []
};

// État de consultation Read-Only
// { active: false, friend_id: null, friend_name: '', friend_email: '', friend_picture: '' }
window.currentReadOnlyFriend = null;

// Onglet actif dans la vue / modale Amis : 'friends', 'incoming', 'outgoing'
let currentFriendsActiveTab = 'friends';

// ============================================================================
// 1. API & CHARGEMENT DES DONNÉES D'AMITIÉ
// ============================================================================

/**
 * Charge la liste des amis et demandes depuis l'API /api/friends
 */
async function loadFriendsData() {
  try {
    const res = await apiFetch('/api/friends');
    if (res.ok) {
      const data = await res.json();
      window.currentFriendsData = {
        friends: data.friends || [],
        incoming_requests: data.incoming_requests || [],
        outgoing_requests: data.outgoing_requests || []
      };
      renderFriendsView();
      renderProfileSelector();
      updateFriendsBadges();
    } else {
      console.warn("Échec du chargement des amis:", res.status);
    }
  } catch (err) {
    console.error("Erreur réseau chargement amis:", err);
  }
}

/**
 * Met à jour les pastilles de notification (ex: demandes reçues en attente)
 */
function updateFriendsBadges() {
  const count = (window.currentFriendsData.incoming_requests || []).length;
  const badgeDesk = document.getElementById('badge-friends-incoming-desk');
  const badgeModal = document.getElementById('badge-friends-incoming-tab');

  [badgeDesk, badgeModal].forEach(b => {
    if (b) {
      if (count > 0) {
        b.textContent = count;
        b.classList.remove('hidden');
      } else {
        b.classList.add('hidden');
      }
    }
  });
}

// ============================================================================
// 2. ENVOI, ACCEPTATION, REFUS ET RÉVOCATION
// ============================================================================

/**
 * Envoie une invitation d'ami par email ou pseudonyme
 */
async function handleSendFriendRequest(e) {
  if (e) e.preventDefault();
  const input = document.getElementById('friend-invite-input');
  const feedback = document.getElementById('friend-invite-feedback');
  const btn = document.getElementById('btn-send-friend-invite');

  if (!input) return;
  const identifier = input.value.trim();
  if (!identifier) {
    if (feedback) {
      feedback.textContent = "Veuillez saisir une adresse email ou un pseudonyme VitalTrack.";
      feedback.className = "text-xs text-rose-400 mt-2 block";
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.classList.add('opacity-50', 'cursor-not-allowed');
  }

  try {
    const res = await apiFetch('/api/friends/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifier: identifier, permission: 'read_only' })
    });

    const data = await res.json();

    if (res.ok) {
      input.value = '';
      if (feedback) {
        feedback.textContent = data.message || "Demande d'ami transmise avec succès !";
        feedback.className = "text-xs text-emerald-400 mt-2 block";
      }
      await loadFriendsData();
      switchFriendsTab('outgoing');
    } else {
      if (feedback) {
        feedback.textContent = data.detail || "Erreur lors de l'envoi de la demande.";
        feedback.className = "text-xs text-rose-400 mt-2 block";
      }
    }
  } catch (err) {
    console.error("Erreur envoi demande d'ami:", err);
    if (feedback) {
      feedback.textContent = "Erreur de connexion au serveur.";
      feedback.className = "text-xs text-rose-400 mt-2 block";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('opacity-50', 'cursor-not-allowed');
    }
  }
}

/**
 * Accepte une demande d'ami reçue
 */
async function acceptFriendRequest(requestId) {
  try {
    const res = await apiFetch(`/api/friends/${requestId}/accept`, { method: 'POST' });
    if (res.ok) {
      await loadFriendsData();
    } else {
      const err = await res.json();
      alert(err.detail || "Erreur lors de l'acceptation de la demande.");
    }
  } catch (e) {
    console.error("Erreur acceptFriendRequest:", e);
  }
}

/**
 * Refuse une demande d'ami reçue
 */
async function rejectFriendRequest(requestId) {
  try {
    const res = await apiFetch(`/api/friends/${requestId}/reject`, { method: 'POST' });
    if (res.ok) {
      await loadFriendsData();
    } else {
      const err = await res.json();
      alert(err.detail || "Erreur lors du refus de la demande.");
    }
  } catch (e) {
    console.error("Erreur rejectFriendRequest:", e);
  }
}

/**
 * Révoque une relation d'amitié ou annule une demande envoyée
 */
async function revokeOrDeleteFriend(targetId, confirmMsg) {
  const msg = confirmMsg || "Êtes-vous sûr de vouloir révoquer ce partage ?";
  if (!confirm(msg)) return;

  try {
    const res = await apiFetch(`/api/friends/${targetId}`, { method: 'DELETE' });
    if (res.ok) {
      // Si on était en train de consulter cet ami, retour à son propre journal
      if (window.currentReadOnlyFriend && window.currentReadOnlyFriend.friend_id === targetId) {
        exitReadOnlyMode();
      }
      await loadFriendsData();
    } else {
      const err = await res.json();
      alert(err.detail || "Erreur lors de la suppression.");
    }
  } catch (e) {
    console.error("Erreur revokeOrDeleteFriend:", e);
  }
}

// ============================================================================
// 3. SÉLECTEUR DE PROFIL & BASCULE DU MODE READ-ONLY
// ============================================================================

/**
 * Entre en mode consultation Read-Only pour un ami
 */
function enterReadOnlyMode(friendId, friendName, friendEmail, friendPicture) {
  window.currentReadOnlyFriend = {
    active: true,
    friend_id: friendId,
    friend_name: friendName || 'Ami',
    friend_email: friendEmail || '',
    friend_picture: friendPicture || ''
  };

  // Fermer la modale d'amis si ouverte
  closeFriendsModal();

  // Appliquer le verrouillage visuel & bannière
  applyReadOnlyUIState();

  // Recharger le dashboard et le journal avec l'ID de l'ami
  reloadAllViewsForCurrentProfile();
}

/**
 * Quitte le mode consultation Read-Only et revient à son propre journal
 */
function exitReadOnlyMode() {
  window.currentReadOnlyFriend = null;
  applyReadOnlyUIState();
  reloadAllViewsForCurrentProfile();
}

/**
 * Applique l'état visuel Read-Only : bannière, sélecteur et désactivation des mutations
 */
function applyReadOnlyUIState() {
  const banner = document.getElementById('read-only-banner');
  const bannerFriendName = document.getElementById('read-only-friend-name');
  const isReadOnly = Boolean(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active);

  // Bannière en haut de page
  if (banner) {
    if (isReadOnly) {
      if (bannerFriendName) {
        bannerFriendName.textContent = window.currentReadOnlyFriend.friend_name || window.currentReadOnlyFriend.friend_email || 'votre ami';
      }
      banner.classList.remove('hidden');
    } else {
      banner.classList.add('hidden');
    }
  }

  // Désactivation ou masquage contextuel des actions d'édition
  document.querySelectorAll('.write-action-btn, [data-write-action="true"]').forEach(el => {
    if (isReadOnly) {
      el.classList.add('hidden');
    } else {
      el.classList.remove('hidden');
    }
  });

  // Mettre à jour l'apparence du sélecteur de profil
  renderProfileSelector();
}

/**
 * Recharge toutes les vues (Dashboard, Journal repas, Catalogue) selon le profil actif
 */
async function reloadAllViewsForCurrentProfile() {
  // Invalider les caches d'onglets, journal et catalogue (Lot 2)
  if (typeof invalidateTabCaches === 'function') {
    invalidateTabCaches();
  }
  if (typeof invalidateJournalCache === 'function') {
    invalidateJournalCache();
  }
  if (typeof invalidateCatalogCache === 'function') {
    invalidateCatalogCache();
  }

  // 1. Dashboard
  if (typeof loadDashboardData === 'function') {
    await loadDashboardData();
  }

  // 2. Journal Repas
  if (typeof loadMealsJournal === 'function') {
    await loadMealsJournal();
  }

  // 3. Catalogue Aliments & Plats
  if (typeof loadCatalogItems === 'function') {
    await loadCatalogItems(true);
  }

  // 4. Recréer les icônes lucide
  if (window.lucide && lucide.createIcons) {
    lucide.createIcons();
  }
}

/**
 * Rendu du sélecteur de profil dans l'en-tête (Desktop & Mobile)
 */
function renderProfileSelector() {
  const container = document.getElementById('header-profile-selector-container');
  if (!container) return;

  const friends = (window.currentFriendsData && window.currentFriendsData.friends) || [];
  const isReadOnly = Boolean(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active);
  const currentName = isReadOnly ? (window.currentReadOnlyFriend.friend_name || window.currentReadOnlyFriend.friend_email) : 'Mon Journal';

  container.innerHTML = `
    <div class="relative">
      <button 
        type="button" 
        onclick="toggleProfileDropdown()" 
        id="btn-profile-selector" 
        class="flex items-center space-x-2 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all active:scale-95 shadow-sm ${
          isReadOnly 
            ? 'bg-amber-500/15 border-amber-500/40 text-amber-300 hover:bg-amber-500/25' 
            : 'bg-[#151D2A] hover:bg-[#1F2A3C] border-[#1F2A3C] text-white'
        }"
        title="Changer de profil ou journal"
      >
        <div class="w-2.5 h-2.5 rounded-full ${isReadOnly ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'} shrink-0"></div>
        <div class="flex items-center space-x-1.5 max-w-[140px] sm:max-w-[180px] truncate">
          <i data-lucide="${isReadOnly ? 'eye' : 'book-open'}" class="w-3.5 h-3.5 ${isReadOnly ? 'text-amber-400' : 'text-brand-400'} shrink-0"></i>
          <span class="truncate">${currentName}</span>
        </div>
        <i data-lucide="chevron-down" class="w-3.5 h-3.5 text-slate-400 shrink-0"></i>
      </button>

      <!-- Menu déroulant des profils -->
      <div 
        id="dropdown-profile-selector" 
        class="hidden absolute left-0 sm:right-0 sm:left-auto top-full mt-2 w-64 rounded-2xl bg-[#151D2A] border border-[#1F2A3C] shadow-2xl p-2 space-y-1 z-50"
      >
        <div class="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-[#1F2A3C]">
          Choisir un profil
        </div>

        <!-- Mon journal -->
        <button 
          type="button"
          onclick="exitReadOnlyMode(); toggleProfileDropdown();" 
          class="w-full text-left px-3 py-2 rounded-xl text-xs flex items-center justify-between transition-colors ${
            !isReadOnly ? 'bg-brand-500/20 text-brand-300 font-bold border border-brand-500/30' : 'text-slate-200 hover:bg-[#1F2A3C]'
          }"
        >
          <div class="flex items-center space-x-2.5">
            <div class="w-7 h-7 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center font-bold text-xs">
              <i data-lucide="user" class="w-4 h-4"></i>
            </div>
            <div>
              <div class="font-bold">Mon journal</div>
              <div class="text-[10px] text-slate-400">Édition & Suivi complet</div>
            </div>
          </div>
          ${!isReadOnly ? '<i data-lucide="check" class="w-4 h-4 text-brand-400"></i>' : ''}
        </button>

        <!-- Liste des amis autorisés -->
        ${friends.length > 0 ? `
          <div class="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-t border-[#1F2A3C] mt-1">
            Amis partagés (Lecture seule)
          </div>
          <div class="max-h-48 overflow-y-auto space-y-0.5">
            ${friends.map(f => {
              const fid = f.friend_id;
              const fname = f.friend_name || f.friend_email.split('@')[0];
              const fpic = f.friend_picture;
              const initials = fname.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'VT';
              const isSelected = isReadOnly && window.currentReadOnlyFriend.friend_id === fid;

              return `
                <button 
                  type="button"
                  onclick="enterReadOnlyMode(${fid}, '${fname.replace(/'/g, "\\'")}', '${(f.friend_email || '').replace(/'/g, "\\'")}', '${fpic || ''}'); toggleProfileDropdown();" 
                  class="w-full text-left px-3 py-2 rounded-xl text-xs flex items-center justify-between transition-colors ${
                    isSelected ? 'bg-amber-500/20 text-amber-300 font-bold border border-amber-500/30' : 'text-slate-200 hover:bg-[#1F2A3C]'
                  }"
                >
                  <div class="flex items-center space-x-2.5 min-w-0">
                    <div class="w-7 h-7 rounded-lg overflow-hidden flex items-center justify-center bg-gradient-to-tr from-brand-600 to-electric-cyan text-white font-bold text-xs shrink-0">
                      ${fpic ? `<img src="${fpic}" class="w-full h-full object-cover">` : initials}
                    </div>
                    <div class="min-w-0">
                      <div class="font-semibold text-white truncate">${fname}</div>
                      <div class="text-[10px] text-amber-400/80 flex items-center space-x-1">
                        <i data-lucide="eye" class="w-2.5 h-2.5"></i>
                        <span>Lecture seule</span>
                      </div>
                    </div>
                  </div>
                  ${isSelected ? '<i data-lucide="check" class="w-4 h-4 text-amber-400 shrink-0"></i>' : ''}
                </button>
              `;
            }).join('')}
          </div>
        ` : ''}

        <!-- Lien vers gestion des amis -->
        <div class="border-t border-[#1F2A3C] pt-1 mt-1">
          <button 
            type="button"
            onclick="toggleProfileDropdown(); openFriendsModal();" 
            class="w-full text-left px-3 py-2 rounded-xl text-xs text-brand-300 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors font-semibold"
          >
            <i data-lucide="users" class="w-4 h-4 text-brand-400"></i>
            <span>Gérer mon cercle d'amis</span>
          </button>
        </div>
      </div>
    </div>
  `;

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

function toggleProfileDropdown() {
  const d = document.getElementById('dropdown-profile-selector');
  if (d) d.classList.toggle('hidden');
}

// Fermer le dropdown en cliquant à l'extérieur
document.addEventListener('click', (e) => {
  const btn = document.getElementById('btn-profile-selector');
  const d = document.getElementById('dropdown-profile-selector');
  if (d && !d.classList.contains('hidden') && btn && !btn.contains(e.target) && !d.contains(e.target)) {
    d.classList.add('hidden');
  }
});

// ============================================================================
// 4. RENDU DE LA SECTION & MODALE AMIS & PARTAGE
// ============================================================================

/**
 * Bascule d'onglet dans l'interface Amis (Mes Amis / Demandes reçues / Demandes envoyées)
 */
function switchFriendsTab(tabName) {
  currentFriendsActiveTab = tabName;
  ['friends', 'incoming', 'outgoing'].forEach(t => {
    const btn = document.getElementById(`friends-tab-btn-${t}`);
    const sec = document.getElementById(`friends-tab-sec-${t}`);
    if (btn) {
      if (t === tabName) {
        btn.classList.add('bg-brand-600', 'text-white', 'font-bold');
        btn.classList.remove('text-slate-400', 'hover:text-white');
      } else {
        btn.classList.remove('bg-brand-600', 'text-white', 'font-bold');
        btn.classList.add('text-slate-400', 'hover:text-white');
      }
    }
    if (sec) {
      if (t === tabName) {
        sec.classList.remove('hidden');
      } else {
        sec.classList.add('hidden');
      }
    }
  });

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

/**
 * Affiche la modale de gestion des amis
 */
function openFriendsModal() {
  const modal = document.getElementById('modal-friends');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    loadFriendsData();
    switchFriendsTab('friends');
  }
}

/**
 * Ferme la modale de gestion des amis
 */
function closeFriendsModal() {
  const modal = document.getElementById('modal-friends');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

/**
 * Rendu des cartes d'amis, demandes reçues et demandes envoyées
 */
function renderFriendsView() {
  const data = window.currentFriendsData || { friends: [], incoming_requests: [], outgoing_requests: [] };

  // 1. Liste des Amis Acceptés
  const containerFriends = document.getElementById('friends-list-container');
  if (containerFriends) {
    if (!data.friends || data.friends.length === 0) {
      containerFriends.innerHTML = `
        <div class="col-span-full py-10 text-center rounded-2xl border border-dashed border-[#1F2A3C] p-6 space-y-2">
          <div class="w-12 h-12 rounded-2xl bg-brand-500/10 text-brand-400 flex items-center justify-center mx-auto">
            <i data-lucide="user-plus" class="w-6 h-6"></i>
          </div>
          <div class="font-bold text-white text-sm">Aucun ami pour le moment</div>
          <p class="text-xs text-slate-400 max-w-sm mx-auto">Invitez un proche ou coach pour lui permettre de suivre votre progression et vos repas en lecture seule.</p>
        </div>
      `;
    } else {
      containerFriends.innerHTML = data.friends.map(f => {
        const fname = f.friend_name || f.friend_email.split('@')[0];
        const fpic = f.friend_picture;
        const initials = fname.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'VT';
        const dateStr = f.created_at ? new Date(f.created_at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
        const isCurrentView = window.currentReadOnlyFriend && window.currentReadOnlyFriend.active && window.currentReadOnlyFriend.friend_id === f.friend_id;

        return `
          <div class="bg-[#0B0B1A] border ${isCurrentView ? 'border-amber-500/60 ring-2 ring-amber-500/30' : 'border-[#25254A]'} rounded-2xl p-4 flex flex-col justify-between space-y-3.5 hover:border-slate-600 transition-all">
            <div class="flex items-center space-x-3">
              <div class="w-10 h-10 rounded-xl overflow-hidden flex items-center justify-center bg-gradient-to-tr from-brand-600 to-electric-cyan text-white font-bold text-sm shrink-0">
                ${fpic ? `<img src="${fpic}" class="w-full h-full object-cover">` : initials}
              </div>
              <div class="min-w-0 flex-1">
                <div class="font-bold text-white text-sm truncate">${fname}</div>
                <div class="text-[11px] text-slate-400 truncate">${f.friend_email}</div>
                <div class="text-[10px] text-brand-400/80 font-medium">Ami depuis le ${dateStr}</div>
              </div>
            </div>

            <div class="flex items-center gap-2 pt-2 border-t border-[#1F2A3C]">
              ${isCurrentView ? `
                <button 
                  type="button" 
                  onclick="exitReadOnlyMode()" 
                  class="flex-1 py-2 px-3 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 text-xs font-bold flex items-center justify-center space-x-1.5 transition-colors"
                >
                  <i data-lucide="check" class="w-3.5 h-3.5"></i>
                  <span>En consultation</span>
                </button>
              ` : `
                <button 
                  type="button" 
                  onclick="enterReadOnlyMode(${f.friend_id}, '${fname.replace(/'/g, "\\'")}', '${(f.friend_email || '').replace(/'/g, "\\'")}', '${fpic || ''}')" 
                  class="flex-1 py-2 px-3 rounded-xl bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/30 text-brand-300 text-xs font-bold flex items-center justify-center space-x-1.5 transition-colors"
                >
                  <i data-lucide="eye" class="w-3.5 h-3.5"></i>
                  <span>Consulter le journal</span>
                </button>
              `}
              <button 
                type="button" 
                onclick="revokeOrDeleteFriend(${f.friend_id}, 'Voulez-vous vraiment révoquer le partage avec ${fname.replace(/'/g, "\\'")} ?')" 
                title="Révoquer le partage" 
                class="p-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-400 text-xs font-semibold flex items-center justify-center transition-colors"
              >
                <i data-lucide="user-x" class="w-4 h-4"></i>
              </button>
            </div>
          </div>
        `;
      }).join('');
    }
  }

  // 2. Demandes Reçues en attente
  const containerIncoming = document.getElementById('friends-incoming-container');
  if (containerIncoming) {
    if (!data.incoming_requests || data.incoming_requests.length === 0) {
      containerIncoming.innerHTML = `
        <div class="col-span-full py-8 text-center text-slate-500 text-xs border border-dashed border-[#1F2A3C] rounded-2xl">
          Aucune demande reçue en attente.
        </div>
      `;
    } else {
      containerIncoming.innerHTML = data.incoming_requests.map(r => {
        const sname = r.sender_name || r.sender_email.split('@')[0];
        const initial = sname[0].toUpperCase();
        return `
          <div class="bg-[#0B0B1A] border border-[#25254A] rounded-2xl p-4 flex flex-col justify-between space-y-3">
            <div class="flex items-center space-x-3">
              <div class="w-10 h-10 rounded-xl bg-violet-600/30 border border-violet-500/40 text-violet-300 flex items-center justify-center font-bold text-sm shrink-0">
                ${r.sender_picture ? `<img src="${r.sender_picture}" class="w-full h-full object-cover rounded-xl">` : initial}
              </div>
              <div class="min-w-0 flex-1">
                <div class="font-bold text-white text-sm truncate">${sname}</div>
                <div class="text-[11px] text-slate-400 truncate">${r.sender_email}</div>
                <div class="text-[10px] text-indigo-400 font-medium">Souhaite partager ses données en lecture seule</div>
              </div>
            </div>

            <div class="flex items-center gap-2 pt-2 border-t border-[#1F2A3C]">
              <button 
                type="button" 
                onclick="acceptFriendRequest(${r.request_id})" 
                class="flex-1 py-1.5 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center justify-center space-x-1.5 transition-colors shadow-sm"
              >
                <i data-lucide="check" class="w-3.5 h-3.5"></i>
                <span>Accepter</span>
              </button>
              <button 
                type="button" 
                onclick="rejectFriendRequest(${r.request_id})" 
                class="flex-1 py-1.5 px-3 rounded-xl bg-[#151D2A] hover:bg-[#1F2A3C] border border-[#1F2A3C] text-slate-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors"
              >
                <i data-lucide="x" class="w-3.5 h-3.5"></i>
                <span>Refuser</span>
              </button>
            </div>
          </div>
        `;
      }).join('');
    }
  }

  // 3. Demandes Envoyées en attente
  const containerOutgoing = document.getElementById('friends-outgoing-container');
  if (containerOutgoing) {
    if (!data.outgoing_requests || data.outgoing_requests.length === 0) {
      containerOutgoing.innerHTML = `
        <div class="col-span-full py-8 text-center text-slate-500 text-xs border border-dashed border-[#1F2A3C] rounded-2xl">
          Aucune invitation en attente de réponse.
        </div>
      `;
    } else {
      containerOutgoing.innerHTML = data.outgoing_requests.map(r => {
        const rname = r.recipient_name || r.recipient_email.split('@')[0];
        return `
          <div class="bg-[#0B0B1A] border border-[#25254A] rounded-2xl p-4 flex items-center justify-between space-x-3">
            <div class="flex items-center space-x-3 min-w-0">
              <div class="w-9 h-9 rounded-xl bg-slate-800 border border-slate-700 text-slate-300 flex items-center justify-center font-bold text-xs shrink-0">
                ${rname[0].toUpperCase()}
              </div>
              <div class="min-w-0">
                <div class="font-bold text-white text-xs truncate">${rname}</div>
                <div class="text-[11px] text-slate-400 truncate">${r.recipient_email}</div>
                <div class="text-[10px] text-amber-400/90 font-medium flex items-center space-x-1">
                  <i data-lucide="clock" class="w-3 h-3"></i>
                  <span>Invitation en attente</span>
                </div>
              </div>
            </div>

            <button 
              type="button" 
              onclick="revokeOrDeleteFriend(${r.request_id}, 'Voulez-vous annuler cette invitation ?')" 
              class="px-2.5 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 text-[11px] font-semibold flex items-center space-x-1 transition-colors shrink-0"
              title="Annuler l'invitation"
            >
              <i data-lucide="trash-2" class="w-3 h-3"></i>
              <span>Annuler</span>
            </button>
          </div>
        `;
      }).join('');
    }
  }

  if (window.lucide && lucide.createIcons) lucide.createIcons();
}

// Initialisation globale au chargement
window.loadFriendsData = loadFriendsData;
window.handleSendFriendRequest = handleSendFriendRequest;
window.acceptFriendRequest = acceptFriendRequest;
window.rejectFriendRequest = rejectFriendRequest;
window.revokeOrDeleteFriend = revokeOrDeleteFriend;
window.enterReadOnlyMode = enterReadOnlyMode;
window.exitReadOnlyMode = exitReadOnlyMode;
window.renderProfileSelector = renderProfileSelector;
window.toggleProfileDropdown = toggleProfileDropdown;
window.openFriendsModal = openFriendsModal;
window.closeFriendsModal = closeFriendsModal;
window.switchFriendsTab = switchFriendsTab;
window.renderFriendsView = renderFriendsView;
