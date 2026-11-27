// static/modules/auth.js - Authentification Email & Google Identity Services

    function openAuthModal() {
      // Fermer les autres modales pour éviter toute superposition opaque
      const wizardModal = document.getElementById('modal-connect-wizard');
      if (wizardModal && !wizardModal.classList.contains('hidden')) {
        wizardModal.classList.add('hidden');
      }
      const profModal = document.getElementById('modal-profile');
      if (profModal && !profModal.classList.contains('hidden')) {
        profModal.classList.add('hidden');
      }
      const modal = document.getElementById('modal-auth');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
      }
      if (currentGoogleConfig && currentGoogleConfig.google_client_id) {
        initGoogleIdentityServices();
      }
      if (window.lucide && lucide.createIcons) {
        try { lucide.createIcons(); } catch (e) {}
      }
    }

    function closeAuthModal() {
      const modal = document.getElementById('modal-auth');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    // Alias de compatibilité
    function openGoogleAuthModal() {
      openAuthModal();
    }
    function closeGoogleAuthModal() {
      closeAuthModal();
    }

    function switchAuthTab(tab) {
      const panelGoogle = document.getElementById('auth-panel-google');
      const panelEmail = document.getElementById('auth-panel-email');
      const tabGoogle = document.getElementById('tab-auth-google');
      const tabEmail = document.getElementById('tab-auth-email');

      if (tab === 'google') {
        if (panelGoogle) panelGoogle.classList.remove('hidden');
        if (panelEmail) panelEmail.classList.add('hidden');
        if (tabGoogle) {
          tabGoogle.className = "py-2 rounded-lg bg-brand-500/20 text-brand-300 border border-brand-500/30 flex items-center justify-center space-x-1.5 transition-all";
        }
        if (tabEmail) {
          tabEmail.className = "py-2 rounded-lg text-slate-400 hover:text-white flex items-center justify-center space-x-1.5 transition-all";
        }
      } else {
        if (panelGoogle) panelGoogle.classList.add('hidden');
        if (panelEmail) panelEmail.classList.remove('hidden');
        if (tabEmail) {
          tabEmail.className = "py-2 rounded-lg bg-brand-500/20 text-brand-300 border border-brand-500/30 flex items-center justify-center space-x-1.5 transition-all";
        }
        if (tabGoogle) {
          tabGoogle.className = "py-2 rounded-lg text-slate-400 hover:text-white flex items-center justify-center space-x-1.5 transition-all";
        }
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    function setAuthEmailMode(mode) {
      currentAuthEmailMode = mode;
      const btnLogin = document.getElementById('btn-mode-login');
      const btnRegister = document.getElementById('btn-mode-register');
      const nameField = document.getElementById('email-field-name');
      const submitLabel = document.getElementById('btn-submit-email-label');
      const passHint = document.getElementById('password-hint');
      const errBox = document.getElementById('auth-email-error');
      if (errBox) errBox.classList.add('hidden');

      if (mode === 'register') {
        if (nameField) nameField.classList.remove('hidden');
        if (passHint) passHint.classList.remove('hidden');
        if (submitLabel) submitLabel.innerText = "Créer mon compte VitalTrack";
        if (btnRegister) {
          btnRegister.className = "font-bold text-brand-400 pb-1 border-b-2 border-brand-400 transition-all";
        }
        if (btnLogin) {
          btnLogin.className = "text-slate-400 hover:text-slate-200 pb-1 border-b-2 border-transparent transition-all";
        }
      } else {
        if (nameField) nameField.classList.add('hidden');
        if (passHint) passHint.classList.add('hidden');
        if (submitLabel) submitLabel.innerText = "Se connecter";
        if (btnLogin) {
          btnLogin.className = "font-bold text-brand-400 pb-1 border-b-2 border-brand-400 transition-all";
        }
        if (btnRegister) {
          btnRegister.className = "text-slate-400 hover:text-slate-200 pb-1 border-b-2 border-transparent transition-all";
        }
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    function togglePasswordVisibility() {
      const passInp = document.getElementById('auth-password-input');
      const icon = document.getElementById('icon-toggle-password');
      if (!passInp) return;
      if (passInp.type === 'password') {
        passInp.type = 'text';
        if (icon) icon.setAttribute('data-lucide', 'eye-off');
      } else {
        passInp.type = 'password';
        if (icon) icon.setAttribute('data-lucide', 'eye');
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    function showEmailAuthError(msg) {
      const errBox = document.getElementById('auth-email-error');
      const errText = document.getElementById('auth-email-error-text');
      if (errBox && errText) {
        errText.innerText = msg;
        errBox.classList.remove('hidden');
      }
    }

    async function handleEmailAuthSubmit() {
      const emailInp = document.getElementById('auth-email-input');
      const passInp = document.getElementById('auth-password-input');
      const nameInp = document.getElementById('auth-email-name');
      const btn = document.getElementById('btn-submit-email-auth');

      const email = emailInp ? emailInp.value.trim() : '';
      const password = passInp ? passInp.value : '';
      const name = (nameInp && nameInp.value.trim()) ? nameInp.value.trim() : 'Utilisateur VitalTrack';

      if (!email || !email.includes('@')) {
        showEmailAuthError("Veuillez renseigner une adresse email valide.");
        return;
      }
      if (!password || password.length < 6) {
        showEmailAuthError("Le mot de passe doit comporter au moins 6 caractères.");
        return;
      }

      if (btn) btn.disabled = true;

      try {
        const endpoint = currentAuthEmailMode === 'register' ? '/api/auth/register' : '/api/auth/login';
        const bodyPayload = currentAuthEmailMode === 'register'
          ? { email, password, name }
          : { email, password };

        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(bodyPayload)
        });

        const data = await res.json();

        if (res.ok) {
          // Stocker le token JWT dans localStorage
          if (data.access_token) {
            localStorage.setItem(JWT_STORAGE_KEY, data.access_token);
          }
          currentUnifiedSession = data.session || {
            is_authenticated: true,
            email: data.user ? data.user.email : email,
            name: data.user ? data.user.name : name,
            auth_method: 'email_password'
          };
          localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(currentUnifiedSession));
          renderUnifiedAuthState(currentUnifiedSession, data.profile);
          closeAuthModal();
          await loadDashboardData();
          showToast(`✓ ${data.message || 'Authentification réussie !'}`, "success");
        } else {
          showEmailAuthError(data.detail || "Erreur lors de l'authentification.");
        }
      } catch (e) {
        showEmailAuthError("Impossible de joindre le serveur VitalTrack.");
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function continueAsGuest() {
      closeAuthModal();
      alert("Mode Invité / Démo activé. Vous pouvez explorer toutes les fonctionnalités de VitalTrack.");
    }

    function toggleUserDropdown() {
      const menu = document.getElementById('header-user-dropdown');
      if (menu) {
        menu.classList.toggle('hidden');
      }
    }

    // Fermer le dropdown au clic en dehors
    document.addEventListener('click', (e) => {
      const container = document.getElementById('header-auth-container');
      const menu = document.getElementById('header-user-dropdown');
      if (container && menu && !container.contains(e.target)) {
        menu.classList.add('hidden');
      }
    });

    async function loadUnifiedAuthState() {
      // 1. Lecture immédiate du cache local (si JWT Bearer présent)
      try {
        const cached = localStorage.getItem(GOOGLE_SESSION_KEY);
        const hasToken = Boolean(localStorage.getItem(JWT_STORAGE_KEY));
        if (cached && hasToken) {
          const parsed = JSON.parse(cached);
          if (parsed && parsed.is_authenticated) {
            currentUnifiedSession = parsed;
            renderUnifiedAuthState(parsed, currentData ? currentData.profile : null);
          }
        }
      } catch (e) {}

      // 2. Appel backend pour synchronisation avec transmission automatique du Bearer Token
      try {
        const [confRes, meRes] = await Promise.all([
          apiFetch('/api/auth/config'),
          apiFetch('/api/auth/me')
        ]);

        if (confRes && confRes.ok) {
          currentGoogleConfig = await confRes.json();
          initGoogleIdentityServices();
        }

        if (meRes && meRes.ok) {
          const data = await meRes.json();
          if (data.session && data.session.is_authenticated) {
            currentUnifiedSession = data.session;
            localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(data.session));
            renderUnifiedAuthState(currentUnifiedSession, data.profile);
          } else if (data.current_user && localStorage.getItem(JWT_STORAGE_KEY)) {
            currentUnifiedSession = {
              is_authenticated: true,
              email: data.current_user.email,
              name: data.current_user.name,
              picture: data.current_user.picture || '',
              auth_method: data.current_user.auth_provider || 'email'
            };
            localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(currentUnifiedSession));
            renderUnifiedAuthState(currentUnifiedSession, data.profile);
          } else {
            currentUnifiedSession = { is_authenticated: false };
            renderUnifiedAuthState(currentUnifiedSession, data.profile);
          }
        }
      } catch (e) {
        console.warn("Erreur chargement session (mode local résilient) :", e);
      }
    }

    function initGoogleIdentityServices() {
      const noticeEl = document.getElementById('gsi-unconfigured-notice');
      if (!currentGoogleConfig.google_client_id || typeof google === 'undefined' || !google.accounts || !google.accounts.id) {
        if (noticeEl) noticeEl.classList.remove('hidden');
        return;
      }
      if (noticeEl) noticeEl.classList.add('hidden');
      try {
        google.accounts.id.initialize({
          client_id: currentGoogleConfig.google_client_id,
          callback: handleGoogleCredentialResponse,
          auto_select: false
        });

        const btnContainer = document.getElementById('gsi-button-container');
        if (btnContainer) {
          btnContainer.innerHTML = '';
          google.accounts.id.renderButton(btnContainer, {
            theme: "filled_blue",
            size: "large",
            shape: "pill",
            text: "signin_with",
            locale: "fr"
          });
        }
      } catch (e) {
        console.warn("Erreur init Google GIS :", e);
      }
    }

    async function handleGoogleCredentialResponse(response) {
      if (!response.credential) return;
      try {
        const res = await fetch('/api/auth/google', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ credential: response.credential })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.access_token) {
            localStorage.setItem(JWT_STORAGE_KEY, data.access_token);
          }
          currentUnifiedSession = data.session;
          localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(data.session));
          renderUnifiedAuthState(data.session, data.profile);
          syncGoogleAccountStorage(data.session.email);
          closeAuthModal();
          await loadDashboardData();
          alert(`Bienvenue ${data.session.name} ! Votre compte Google et vos données sont synchronisés.`);
        } else {
          const errData = await res.json().catch(() => ({}));
          alert(errData.detail || "Authentification Google refusée.");
        }
      } catch (e) {
        alert("Erreur lors de l'authentification Google.");
      }
    }

    async function logoutSession() {
      try {
        if (typeof navigator !== 'undefined' && navigator.serviceWorker && navigator.serviceWorker.controller) {
          navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_API_CACHE' });
        }
        if (typeof caches !== 'undefined') {
          caches.delete('vitaltrack-api-v2').catch(() => {});
        }
        if (localStorage.getItem(JWT_STORAGE_KEY)) {
          await apiFetch('/api/auth/logout', { method: 'POST' });
        }
      } catch (e) {
        console.warn("Déconnexion backend différée :", e);
      } finally {
        localStorage.removeItem(JWT_STORAGE_KEY);
        localStorage.removeItem(GOOGLE_SESSION_KEY);
        currentUnifiedSession = { is_authenticated: false };
        renderUnifiedAuthState(currentUnifiedSession, null);
        closeAuthModal();
        await loadDashboardData();
        alert("Déconnexion réussie.");
      }
    }

    // Alias pour compatibilité
    async function logoutGoogle() {
      await logoutSession();
    }

    async function saveGoogleClientId() {
      const inp = document.getElementById('google-input-client-id');
      const val = inp ? inp.value.trim() : '';
      if (!val) {
        alert("Veuillez saisir un Client ID valide.");
        return;
      }
      try {
        const res = await apiFetch('/api/auth/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ google_client_id: val })
        });
        if (res.ok) {
          const data = await res.json();
          currentGoogleConfig = data.config;
          initGoogleIdentityServices();
          alert("✓ Google Client ID enregistré avec succès !");
        }
      } catch (e) {
        alert("Erreur lors de l'enregistrement du Client ID.");
      }
    }

    function renderUnifiedAuthState(session, profile) {
      const headerContainer = document.getElementById('header-auth-container');
      const profEmail = document.getElementById('prof-google-email');
      const profAvatar = document.getElementById('prof-google-avatar');
      const profActionBtn = document.getElementById('btn-prof-google-action');

      const connView = document.getElementById('auth-connected-view');
      const loginView = document.getElementById('auth-login-view');
      const uAvatar = document.getElementById('auth-user-avatar');
      const uInitials = document.getElementById('auth-user-initials');
      const uName = document.getElementById('auth-user-name');
      const uEmail = document.getElementById('auth-user-email');
      const uBadge = document.getElementById('auth-provider-badge');

      if (session && session.is_authenticated) {
        const rawEmail = session.email || '';
        const rawName = session.name || (rawEmail ? rawEmail.split('@')[0] : '') || 'Utilisateur';
        const email = escapeHtml(rawEmail);
        const name = escapeHtml(rawName);
        const picture = sanitizeUrl(session.picture || '');
        const initials = escapeHtml(rawName.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || 'VT');
        const firstName = escapeHtml(rawName.split(' ')[0] || '');
        const isGoogle = (session.auth_method && session.auth_method.includes('google'));

        // Header : Avatar utilisateur connecté avec menu déroulant
        if (headerContainer) {
          headerContainer.innerHTML = `
            <button type="button" onclick="toggleUserDropdown()" id="btn-header-avatar" class="flex items-center space-x-1.5 p-1 rounded-xl bg-[#151D2A] hover:bg-[#1F2A3C] border border-brand-500/40 text-white text-xs font-medium transition-all active:scale-95 shadow-sm" title="${name} (${email})">
              <div class="w-7 h-7 rounded-lg overflow-hidden flex items-center justify-center bg-gradient-to-tr from-brand-600 to-electric-cyan text-white font-bold text-xs shrink-0">
                ${picture ? `<img src="${picture}" class="w-full h-full object-cover" alt="Avatar">` : `<span>${initials}</span>`}
              </div>
              <span class="hidden sm:inline font-semibold px-1 text-brand-300">${firstName}</span>
              <span class="w-2 h-2 rounded-full bg-brand-400 mr-1"></span>
              <i data-lucide="chevron-down" class="w-3.5 h-3.5 text-slate-400 hidden sm:inline"></i>
            </button>

            <!-- Menu Déroulant Profil -->
            <div id="header-user-dropdown" class="absolute right-0 top-full mt-2 w-56 rounded-2xl bg-[#151D2A] border border-[#1F2A3C] shadow-2xl p-2 space-y-1 z-50 hidden">
              <div class="px-3 py-2 border-b border-[#1F2A3C] mb-1">
                <div class="text-xs font-bold text-white truncate">${name}</div>
                <div class="text-[10px] text-brand-400 truncate">${email}</div>
                <span class="inline-block mt-1 text-[9px] px-1.5 py-0.2 rounded-full bg-brand-500/20 text-brand-300 border border-brand-500/30">${isGoogle ? 'Compte Google' : 'Compte Email'}</span>
              </div>
              <button onclick="toggleUserDropdown(); openProfileModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">
                <i data-lucide="user" class="w-4 h-4 text-brand-400"></i>
                <span>Mon Profil</span>
              </button>
              <button onclick="toggleUserDropdown(); openFriendsModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">
                <i data-lucide="users" class="w-4 h-4 text-brand-400"></i>
                <span>Amis & Partage</span>
              </button>
              <button onclick="toggleUserDropdown(); openConnectWizardModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">
                <i data-lucide="link-2" class="w-4 h-4 text-indigo-400"></i>
                <span>Appareils Connectés</span>
              </button>
              <button onclick="toggleUserDropdown(); openAuthModal()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-[#1F2A3C] flex items-center space-x-2 transition-colors">
                <i data-lucide="shield" class="w-4 h-4 text-sky-400"></i>
                <span>Sécurité & Sessions</span>
              </button>
              <div class="border-t border-[#1F2A3C] pt-1">
                <button onclick="toggleUserDropdown(); logoutSession()" class="w-full text-left px-3 py-2 rounded-xl text-xs text-red-300 hover:bg-red-950/40 flex items-center space-x-2 transition-colors">
                  <i data-lucide="log-out" class="w-4 h-4 text-red-400"></i>
                  <span>Déconnexion</span>
                </button>
              </div>
            </div>
          `;
        }

        // Modale Profil
        if (profEmail) profEmail.innerText = `${rawEmail} (${isGoogle ? 'Google' : 'Email'})`;
        if (profAvatar) {
          profAvatar.innerHTML = picture
            ? `<img src="${picture}" class="w-full h-full object-cover">`
            : `<div class="w-full h-full bg-brand-600 flex items-center justify-center text-white font-bold text-xs">${initials}</div>`;
        }
        if (profActionBtn) {
          profActionBtn.innerText = "Gérer Compte";
          profActionBtn.className = "px-2.5 py-1.5 rounded-lg bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/40 text-brand-300 text-[11px] font-semibold transition-all";
        }

        // Modale Auth
        if (connView) connView.classList.remove('hidden');
        if (loginView) loginView.classList.add('hidden');
        if (uAvatar) {
          if (picture) {
            uAvatar.src = picture;
            uAvatar.classList.remove('hidden');
            if (uInitials) uInitials.classList.add('hidden');
          } else {
            uAvatar.classList.add('hidden');
            if (uInitials) {
              uInitials.innerText = initials;
              uInitials.classList.remove('hidden');
            }
          }
        }
        if (uName) uName.innerText = rawName;
        if (uEmail) uEmail.innerText = rawEmail;
        if (uBadge) uBadge.innerText = isGoogle ? "Google" : "Email & Mot de passe";

      } else {
        // Déconnecté
        if (headerContainer) {
          headerContainer.innerHTML = `
            <button type="button" onclick="openAuthModal()" id="btn-header-auth" class="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 border border-white/20 text-white text-xs font-medium transition-all active:scale-95 shadow-sm" title="Se connecter / S'inscrire">
              <i data-lucide="user" class="w-4 h-4 text-brand-400"></i>
              <span class="hidden sm:inline">Connexion</span>
            </button>
          `;
        }

        if (profEmail) profEmail.innerText = "Non connecté";
        if (profAvatar) {
          profAvatar.innerHTML = `
            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
            </svg>
          `;
        }
        if (profActionBtn) {
          profActionBtn.innerText = "Se connecter";
          profActionBtn.className = "px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 border border-white/20 text-white text-[11px] font-semibold transition-all";
        }

        if (connView) connView.classList.add('hidden');
        if (loginView) loginView.classList.remove('hidden');
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    // Alias pour compatibilité
    function renderGoogleAuthState(session, profile) {
      renderUnifiedAuthState(session, profile);
    }

    // Exposition globale explicite des handlers d'interface
    window.openProfileModal = openProfileModal;
    window.closeProfileModal = closeProfileModal;
    window.saveUserProfile = saveUserProfile;
    window.openConnectWizardModal = openConnectWizardModal;
    window.closeConnectWizardModal = closeConnectWizardModal;
    window.selectWizardDevice = selectWizardDevice;
    window.submitDeviceConnection = submitDeviceConnection;
    window.openAuthModal = openAuthModal;
    window.closeAuthModal = closeAuthModal;
    window.switchTab = switchTab;
    window.generateDeviceToken = generateDeviceToken;
    window.toggleTokenVisibility = toggleTokenVisibility;
    window.copyTokenToClipboard = copyTokenToClipboard;
    window.fetchOrInitDeviceToken = fetchOrInitDeviceToken;
    window.testHealthConnectIngestion = testHealthConnectIngestion;
    window.formatRelativeTime = formatRelativeTime;
    window.renderLiveSyncBanner = renderLiveSyncBanner;
    window.triggerSyncFromBanner = triggerSyncFromBanner;

    function syncGoogleAccountStorage(email) {
      if (!email) return;
      const key = `vitaltrack_backup_${email}`;
      const existing = localStorage.getItem(key);
      if (existing) {
        try {
          const parsed = JSON.parse(existing);
          apiFetch('/api/backup/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: parsed, overwrite: false })
          });
        } catch (e) {}
      } else if (currentData) {
        localStorage.setItem(key, JSON.stringify(currentData));
      }
    }

// Fonctions de modale de synchronisation par date (BALI-291)
