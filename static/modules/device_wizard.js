// static/modules/device_wizard.js - Assistant de connexion objets connectés & synchronisation

    function openConnectWizardModal(deviceId) {
      try {
        // Fermer les autres modales ou menus déroulants pouvant se superposer
        const drop = document.getElementById('header-user-dropdown');
        if (drop) { drop.classList.add('hidden'); }

        ['modal-meal', 'modal-weight', 'modal-activity', 'modal-profile', 'modal-auth', 'modal-saved-meals', 'modal-create-saved-meal'].forEach(id => {
          const el = document.getElementById(id);
          if (el) { el.classList.add('hidden'); el.classList.remove('flex'); }
        });

        const targetDev = (typeof deviceId === 'string' && deviceId) ? deviceId : (currentSelectedWizardDevice || 'ringconn');
        selectWizardDevice(targetDev);
        const modal = document.getElementById('modal-connect-wizard');
        if (modal) {
          modal.classList.remove('hidden');
          modal.classList.add('flex');
        }
        if (window.lucide && lucide.createIcons) {
          try { lucide.createIcons(); } catch (e) {}
        }
      } catch (err) {
        console.error("Erreur openConnectWizardModal:", err);
      }
    }

    function closeConnectWizardModal() {
      const modal = document.getElementById('modal-connect-wizard');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function selectWizardDevice(deviceId) {
      currentSelectedWizardDevice = deviceId;
      document.querySelectorAll('.wizard-device-card').forEach(c => {
        c.classList.remove('border-2', 'border-brand-500', 'bg-brand-500/10');
        c.classList.add('border', 'border-[#1F2A3C]', 'bg-[#0B0F17]');
      });

      const selCard = document.getElementById(`wiz-opt-${deviceId}`);
      if (selCard) {
        selCard.classList.remove('border-[#1F2A3C]', 'bg-[#0B0F17]');
        selCard.classList.add('border-2', 'border-brand-500', 'bg-brand-500/10');
      }

      const container = document.getElementById('wizard-config-container');
      const actionText = document.getElementById('wizard-action-text');

      if (deviceId === 'ringconn') {
        actionText.innerText = "Connecter ma bague RingConn Gen 3";
        container.innerHTML = `
          <div class="space-y-2.5">
            <div class="flex items-center space-x-2 text-brand-400 font-bold text-xs">
              <i data-lucide="sparkles" class="w-4 h-4"></i>
              <span>Connexion Optimale : Bague RingConn Gen 3</span>
            </div>
            <p class="text-xs text-slate-300">
              Votre bague <strong>RingConn Gen 3</strong> mesure en temps réel le sommeil (durée, score réparateur), l'HRV nocturne en ms, la fréquence cardiaque et les calories actives.
            </p>
            <div class="bg-[#151D2A] p-2.5 rounded-lg border border-[#1F2A3C] text-[11px] space-y-2">
              <span class="text-slate-400 block font-semibold">Modes d'interconnexion au choix :</span>
              <div class="text-slate-200">
                <span class="text-brand-400 font-bold">1. Passerelle Google Health Connect (Android)</span> : Synchronisation automatique native.
              </div>
              <div class="text-slate-200">
                <span class="text-brand-400 font-bold">2. Webhook RingConn / MacroDroid</span> :
                <div class="mt-1 p-1.5 rounded bg-[#0B0F17] font-mono text-[10px] text-brand-400 flex items-center justify-between">
                  <span>POST /api/webhooks/ringconn</span>
                  <button type="button" onclick="navigator.clipboard.writeText(window.location.origin + '/api/webhooks/ringconn'); alert('URL Webhook copiée !');" class="text-slate-400 hover:text-white ml-2 text-[10px] underline">Copier</button>
                </div>
              </div>
              <div class="text-slate-200">
                <span class="text-brand-400 font-bold">3. OpenAPI Cloud Directe</span> : Token d'accès OpenAPI RingConn.
              </div>
            </div>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Clé API / Token RingConn (Facultatif si synchronisé via Google Health) :</label>
              <input type="text" id="wiz-input-ringconn-key" placeholder="rc_live_... ou laisser vide pour passerelle Google Health" class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500">
            </div>
            <div class="pt-2">
              <button type="button" onclick="testRingConnIngestion()" class="w-full py-2 rounded-lg bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/40 text-brand-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">
                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                <span>Tester la réception / Synchroniser métriques RingConn</span>
              </button>
            </div>
          </div>
        `;
      } else if (deviceId === 'health_connect') {
        actionText.innerText = "Activer la passerelle Google Health Connect";
        container.innerHTML = `
          <div class="space-y-3.5">
            <div class="flex items-center space-x-2 text-sky-400 font-bold text-xs">
              <i data-lucide="smartphone" class="w-4 h-4"></i>
              <span>Passerelle Universelle Android Google Health Connect</span>
            </div>
            <p class="text-xs text-slate-300">
              Centralise toutes vos applications de santé sur smartphone (RingConn, balances connectées, trackers) et les pousse vers le webhook VitalTrack.
            </p>

            <!-- Téléchargements directs : APK & Profil MacroDroid -->
            <div class="p-3 rounded-xl bg-gradient-to-r from-indigo-950/40 to-[#151D2A] border border-indigo-500/30 space-y-2">
              <span class="text-[11px] font-bold text-indigo-300 flex items-center space-x-1.5">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span>Applications & Profils Android à installer :</span>
              </span>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-0.5">
                <a href="/static/downloads/vitaltrack-health-bridge.apk" download="vitaltrack-health-bridge.apk" class="py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center justify-center space-x-2 shadow-md shadow-indigo-600/25 transition-transform active:scale-95 text-center cursor-pointer">
                  <i data-lucide="smartphone" class="w-4 h-4"></i>
                  <span>Télécharger l'APK Android</span>
                </a>
                <a href="/static/downloads/macrodroid_health_connect_profile.json" download="macrodroid_health_connect_profile.json" class="py-2 px-3 rounded-xl bg-[#1F2A3C] hover:bg-[#2A374D] border border-slate-600 text-slate-200 font-semibold text-xs flex items-center justify-center space-x-2 transition-colors text-center cursor-pointer">
                  <i data-lucide="file-json" class="w-4 h-4 text-amber-400"></i>
                  <span>Profil MacroDroid (.json)</span>
                </a>
              </div>
            </div>

            <!-- Configuration Webhook & Jeton Secret -->
            <div class="p-3 rounded-xl bg-[#151D2A] border border-[#1F2A3C] text-[11px] text-slate-300 space-y-2.5">
              <!-- Endpoint Webhook -->
              <div class="space-y-1">
                <div class="flex justify-between items-center text-slate-400">
                  <span class="font-medium">URL du Webhook :</span>
                  <button type="button" onclick="navigator.clipboard.writeText(window.location.origin + '/api/webhooks/health-connect'); if (typeof showToast === 'function') showToast('URL Webhook copiée !', 'success'); else alert('URL Webhook copiée !');" class="text-brand-400 hover:text-brand-300 flex items-center space-x-1 text-[11px] font-semibold underline cursor-pointer">
                    <i data-lucide="copy" class="w-3 h-3"></i>
                    <span>Copier l'URL</span>
                  </button>
                </div>
                <div class="p-2 rounded-lg bg-[#0B0F17] font-mono text-[10px] text-brand-400 break-all border border-[#1F2A3C]/70 select-all">
                  ${window.location.origin}/api/webhooks/health-connect
                </div>
              </div>

              <!-- Jeton Secret X-Webhook-Token -->
              <div class="space-y-1 pt-1.5 border-t border-[#1F2A3C]/60">
                <div class="flex justify-between items-center text-slate-400">
                  <span class="font-medium">Jeton Secret (<code>X-Webhook-Token</code>) :</span>
                  <div class="flex items-center space-x-2">
                    <button type="button" onclick="generateDeviceToken('health_connect')" class="text-indigo-400 hover:text-indigo-300 font-semibold text-[11px] underline cursor-pointer" title="Régénérer un nouveau jeton d'appareil">
                      Régénérer
                    </button>
                    <button type="button" onclick="toggleTokenVisibility('health_connect')" id="wiz-token-toggle-health_connect" class="text-slate-400 hover:text-white flex items-center space-x-1 text-[11px] cursor-pointer">
                      <i data-lucide="eye" id="wiz-token-eye-icon-health_connect" class="w-3 h-3"></i>
                      <span id="wiz-token-eye-text-health_connect">Révéler</span>
                    </button>
                    <button type="button" onclick="copyTokenToClipboard('health_connect')" class="text-brand-400 hover:text-brand-300 flex items-center space-x-1 text-[11px] font-semibold underline cursor-pointer">
                      <i data-lucide="copy" class="w-3 h-3"></i>
                      <span>Copier mon Token</span>
                    </button>
                  </div>
                </div>
                <div class="p-2 rounded-lg bg-[#0B0F17] font-mono text-[10px] text-emerald-400 break-all border border-[#1F2A3C]/70 flex items-center justify-between">
                  <span id="wiz-token-display-val-health_connect" class="tracking-wider">Chargement du jeton...</span>
                </div>
              </div>

              <!-- Statut réel de réception -->
              <div class="flex justify-between items-center pt-1.5 border-t border-[#1F2A3C]/60 text-xs">
                <span class="text-slate-400">Statut de synchronisation :</span>
                <span id="wiz-sync-badge-health_connect" class="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                  <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                  <span>En attente du 1er envoi depuis votre téléphone</span>
                </span>
              </div>
            </div>

            <!-- Guide Xiaomi HyperOS / MIUI -->
            <div class="p-2.5 rounded-lg bg-[#0B0F17] border border-amber-500/30 text-[11px] space-y-1.5">
              <div class="flex items-center space-x-1.5 text-amber-400 font-bold">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i>
                <span>Réglages Requis Xiaomi HyperOS / MIUI</span>
              </div>
              <ul class="text-[10px] text-slate-300 list-disc list-inside space-y-0.5">
                <li><strong>Démarrage auto</strong> : <em>Paramètres > Applications > Gérer les applications > VitalTrack Bridge (ou MacroDroid) > Démarrage automatique</em> : <strong>Activé</strong>.</li>
                <li><strong>Batterie</strong> : <em>Économiseur de batterie MIUI</em> : régler sur <strong>« Pas de restrictions »</strong>.</li>
                <li><strong>Santé Connect</strong> : <em>Paramètres > Sécurité & Confidentialité > Health Connect > Applications autorisées</em> : accorder l'accès en lecture.</li>
              </ul>
            </div>

            <div class="pt-1">
              <button type="button" onclick="testHealthConnectIngestion()" class="w-full py-2.5 rounded-xl bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 text-sky-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors cursor-pointer shadow-sm">
                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                <span>Envoyer test webhook</span>
              </button>
            </div>
          </div>
        `;
        fetchOrInitDeviceToken('health_connect');
      } else if (deviceId === 'withings') {
        actionText.innerText = "Connecter ma Balance Withings";
        container.innerHTML = `
          <div class="space-y-2.5">
            <div class="flex items-center space-x-2 text-brand-400 font-bold text-xs">
              <i data-lucide="scale" class="w-4 h-4"></i>
              <span>Balance Withings Body Smart / Comp (Wi-Fi Direct)</span>
            </div>
            <p class="text-xs text-slate-300">
              Synchronisation directe Cloud-to-Cloud via OAuth 2.0 officiel de Withings.
            </p>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Identifiant Compte Withings (Email) :</label>
              <input type="email" id="wiz-input-withings-email" placeholder="votre.email@exemple.com" value="${escapeHtml((currentUnifiedSession && currentUnifiedSession.email) || '')}" class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500">
            </div>
            <div class="pt-1">
              <button type="button" onclick="testScaleIngestion('withings')" class="w-full py-2 rounded-lg bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/40 text-brand-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">
                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                <span>Tester la réception d'une pesée Withings</span>
              </button>
            </div>
          </div>
        `;
      } else {
        actionText.innerText = "Connecter Oura Ring Gen 3";
        container.innerHTML = `
          <div class="space-y-2.5">
            <div class="flex items-center space-x-2 text-indigo-400 font-bold text-xs">
              <i data-lucide="circle-dot" class="w-4 h-4"></i>
              <span>Oura Ring Gen 3 Cloud API v2</span>
            </div>
            <p class="text-xs text-slate-300">
              Interconnexion par Bearer Token personnel via l'API v2 d'Oura.
            </p>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Personal Access Token Oura :</label>
              <input type="password" id="wiz-input-oura-token" placeholder="Bearer token Oura..." class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500">
            </div>
          </div>
        `;
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    async function testRingConnIngestion() {
      const todayStr = new Date().toISOString().split('T')[0];
      const payload = {
        date: todayStr,
        source: "ringconn_gen3",
        steps: 11450,
        active_calories_kcal: 490.0,
        resting_hr_bpm: 56,
        hrv_ms: 62.0,
        sleep_score: 88,
        workout_minutes: 40,
        workout_type: "Marche & Cardio (RingConn Gen 3)"
      };
      try {
        const res = await fetch('/api/webhooks/ringconn', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          alert("✓ Succès ! Métriques RingConn Gen 3 reçues (11 450 pas, HRV 62 ms, Score Sommeil 88).");
          loadDashboardData();
        }
      } catch (e) {
        alert("Erreur lors du test webhook RingConn");
      }
    }

    let currentDeviceTokens = {};
    let deviceTokensRevealed = {};

    async function fetchOrInitDeviceToken(deviceId) {
      const displayEl = document.getElementById(`wiz-token-display-val-${deviceId}`);
      const badgeEl = document.getElementById(`wiz-sync-badge-${deviceId}`);

      // Mettre à jour le badge selon le statut réel de l'appareil
      if (currentData && currentData.devices) {
        const d = currentData.devices.find(dev => (dev.id || dev.device_id) === deviceId);
        if (d && badgeEl) {
          const hasSync = Boolean(d.last_sync_at || d.last_sync);
          if (hasSync) {
            const relTime = formatRelativeTime(d.last_sync_at || d.last_sync) || 'Récemment';
            badgeEl.className = "text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1";
            badgeEl.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span><span>Synchronisé (${relTime})</span>`;
          } else {
            badgeEl.className = "text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1";
            badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span><span>En attente du 1er envoi depuis votre téléphone</span>';
          }
        }
      }

      try {
        const res = await apiFetch(`/api/devices/${deviceId}/token`, { method: 'GET' });
        if (res && res.ok) {
          const data = await res.json();
          if (data && data.token) {
            currentDeviceTokens[deviceId] = data.token;
            updateTokenDisplay(deviceId);
            return data.token;
          }
        }
      } catch (e) {
        // En cas d'erreur de récupération
      }

      // Si aucun jeton n'existe encore pour l'utilisateur, on le génère automatiquement
      try {
        const genRes = await apiFetch(`/api/devices/${deviceId}/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: deviceId === 'health_connect' ? 'Google Health Connect' : deviceId })
        });
        if (genRes && genRes.ok) {
          const data = await genRes.json();
          if (data && data.token) {
            currentDeviceTokens[deviceId] = data.token;
            updateTokenDisplay(deviceId);
            return data.token;
          }
        } else {
          console.error("Échec création token automatique:", genRes ? genRes.status : "inconnu");
          if (displayEl) displayEl.innerText = "Non configuré";
        }
      } catch (err) {
        console.error("Erreur récupération/génération token:", err);
        if (displayEl) displayEl.innerText = "Non configuré";
      }
    }

    function updateTokenDisplay(deviceId) {
      const displayEl = document.getElementById(`wiz-token-display-val-${deviceId}`);
      const eyeIcon = document.getElementById(`wiz-token-eye-icon-${deviceId}`);
      const eyeText = document.getElementById(`wiz-token-eye-text-${deviceId}`);
      if (!displayEl) return;

      const token = currentDeviceTokens[deviceId] || "";
      const isRevealed = Boolean(deviceTokensRevealed[deviceId]);

      if (!token) {
        displayEl.innerText = "Aucun jeton actif";
        return;
      }

      if (isRevealed) {
        displayEl.innerText = token;
        if (eyeText) eyeText.innerText = "Masquer";
        if (eyeIcon) eyeIcon.setAttribute('data-lucide', 'eye-off');
      } else {
        const prefix = token.slice(0, 10);
        displayEl.innerText = prefix + "••••••••••••••••••••••••";
        if (eyeText) eyeText.innerText = "Révéler";
        if (eyeIcon) eyeIcon.setAttribute('data-lucide', 'eye');
      }
      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
    }

    function toggleTokenVisibility(deviceId) {
      deviceTokensRevealed[deviceId] = !deviceTokensRevealed[deviceId];
      updateTokenDisplay(deviceId);
    }

    async function copyTokenToClipboard(deviceId) {
      let token = currentDeviceTokens[deviceId];
      if (!token) {
        token = await fetchOrInitDeviceToken(deviceId);
      }
      if (token) {
        navigator.clipboard.writeText(token);
        if (typeof showToast === 'function') showToast("✓ Jeton secret copié dans le presse-papier !", "success");
        else alert("✓ Jeton secret copié dans le presse-papier !");
      } else {
        if (typeof showToast === 'function') showToast("Jeton introuvable.", "error");
      }
    }

    async function generateDeviceToken(deviceId) {
      try {
        if (typeof showToast === 'function') showToast("Génération d'un nouveau jeton...", "info");
        const res = await apiFetch(`/api/devices/${deviceId}/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: deviceId === 'health_connect' ? 'Google Health Connect' : 'Smart Sensor' })
        });
        if (res && res.ok) {
          const data = await res.json();
          if (data && data.token) {
            currentDeviceTokens[deviceId] = data.token;
            deviceTokensRevealed[deviceId] = true; // Révélé dès la génération
            updateTokenDisplay(deviceId);
            navigator.clipboard.writeText(data.token);
            if (typeof showToast === 'function') {
              showToast("✓ Nouveau jeton généré et copié dans le presse-papier !", "success");
            } else {
              alert(`✓ Jeton généré et copié dans le presse-papier :\n${data.token}`);
            }
            await loadDashboardData();
          }
        } else {
          const errData = await res.json().catch(() => ({}));
          console.error("Erreur génération token HTTP status:", res.status, errData);
          if (typeof showToast === 'function') showToast("Erreur génération jeton: " + (errData.detail || res.statusText), "error");
          else alert("Erreur génération jeton: " + (errData.detail || res.statusText));
        }
      } catch (err) {
        console.error("Erreur génération token:", err);
        if (typeof showToast === 'function') showToast("Erreur lors de la génération du jeton.", "error");
        else alert("Erreur lors de la génération du jeton.");
      }
    }

    async function testHealthConnectIngestion() {
      const todayStr = new Date().toISOString().split('T')[0];
      let token = currentDeviceTokens['health_connect'];
      if (!token) {
        token = await fetchOrInitDeviceToken('health_connect');
      }
      const headers = {
        'Content-Type': 'application/json',
        'X-Dry-Run': 'true'
      };
      if (token) {
        headers['X-Webhook-Token'] = token;
      }
      const payload = {
        date: todayStr,
        source: "health_connect",
        steps: 12100,
        active_calories_kcal: 530.0,
        resting_hr_bpm: 57,
        hrv_ms: 59.0,
        sleep_score: 85,
        token: token || undefined
      };
      try {
        if (typeof showToast === 'function') showToast("Test webhook en cours (simulation dry-run)...", "info");
        const res = await fetch('/api/webhooks/health-connect?dry_run=true', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          const popupMsg = "\u2713 Test Passerelle Health Connect (Simulation R\u00e9ussie)\n\n" +
            "\u2022 Statut : Authentifi\u00e9 & Valid\u00e9 (HTTP 200)\n" +
            "\u2022 Utilisateur : #" + (data.user_id || '1') + "\n" +
            "\u2022 Appareil : " + (data.device_id || 'health_connect') + "\n" +
            "\u2022 Jeton webhook : " + (token ? token.substring(0, 10) + '...' : '(aucun)') + "\n\n" +
            "M\u00e9triques v\u00e9rifi\u00e9es :\n" +
            "\u2022 Date : " + payload.date + "\n" +
            "\u2022 Pas : " + payload.steps + "\n" +
            "\u2022 Calories actives : " + payload.active_calories_kcal + " kcal\n" +
            "\u2022 Fr\u00e9quence card. repos : " + payload.resting_hr_bpm + " bpm\n" +
            "\u2022 HRV : " + payload.hrv_ms + " ms\n" +
            "\u2022 Score sommeil : " + payload.sleep_score + "/100\n\n" +
            "Note : Mode dry-run actif, aucune donn\u00e9e n'a \u00e9t\u00e9 ins\u00e9r\u00e9e en base de donn\u00e9es.";
          alert(popupMsg);
          if (typeof showToast === 'function') {
            showToast("\u2713 Test valid\u00e9 avec succ\u00e8s (dry-run, base inchang\u00e9e).", "success");
          }
          await fetchOrInitDeviceToken('health_connect');
        } else {
          const msg = "\u00c9chec du test webhook : " + (data.detail || res.statusText);
          if (typeof showToast === 'function') showToast(msg, "error");
          else alert(msg);
        }
      } catch (e) {
        if (typeof showToast === 'function') showToast("Erreur de communication lors du test webhook Google Health", "error");
        else alert("Erreur lors du test webhook Google Health");
      }
    }
    async function testScaleIngestion(sourceName) {
      const todayStr = new Date().toISOString().split('T')[0];
      const payload = {
        date: todayStr,
        source: sourceName,
        weight_kg: 79.4,
        body_fat_pct: 19.9,
        muscle_mass_kg: 38.3,
        water_pct: 56.8
      };
      try {
        const res = await fetch('/api/webhook/health', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          alert(`✓ Succès ! Pesée reçue via connecteur ${sourceName} : 79.4 kg, 19.9% masse grasse.`);
          loadDashboardData();
        }
      } catch (e) {
        alert("Erreur test balance");
      }
    }


    async function submitDeviceConnection() {
      const devId = currentSelectedWizardDevice;
      let apiKey = null;
      let email = null;
      let authType = 'connected';

      if (devId === 'ringconn') {
        const inp = document.getElementById('wiz-input-ringconn-key');
        apiKey = inp ? inp.value : null;
        authType = apiKey ? 'ringconn_openapi' : 'google_health_connect';
      } else if (devId === 'withings') {
        const inp = document.getElementById('wiz-input-withings-email');
        email = (inp && inp.value) ? inp.value.trim() : ((currentUnifiedSession && currentUnifiedSession.email) || '');
        authType = 'withings_oauth';
      } else if (devId === 'health_connect') {
        authType = 'google_health_connect';
      } else if (devId === 'oura') {
        const inp = document.getElementById('wiz-input-oura-token');
        apiKey = inp ? inp.value : null;
        authType = 'oura_bearer_token';
      }

      try {
        const res = await apiFetch('/api/devices/connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            device_id: devId,
            connected: true,
            auth_type: authType,
            api_key: apiKey,
            account_email: email
          })
        });

        if (res.ok) {
          closeConnectWizardModal();
          await loadDashboardData();
          switchTab('devices');
          showToast(`Félicitations ! L'appareil '${devId === 'ringconn' ? 'RingConn Gen 3' : (devId === 'health_connect' ? 'Google Health Connect' : devId)}' a été connecté avec succès à votre profil VitalTrack !`, 'success');
        }
      } catch (e) {
        closeConnectWizardModal();
      }
    }


function openDateSyncModal(deviceId) {
  const modal = document.getElementById('modal-date-sync');
  if (!modal) return;
  const inputDevId = document.getElementById('input-date-sync-device-id');
  const inputDate = document.getElementById('input-date-sync-start');
  const lastSyncLabel = document.getElementById('date-sync-last-val');
  if (inputDevId) inputDevId.value = deviceId || 'health_connect';
  if (inputDate) {
    const today = new Date().toISOString().split('T')[0];
    inputDate.value = today;
  }
  if (lastSyncLabel) {
    const statusEl = document.getElementById('live-health-connect-status') || document.getElementById('live-hc-status-text');
    const text = statusEl ? statusEl.innerText : 'Inconnue';
    lastSyncLabel.innerText = text;
  }
  modal.classList.remove('hidden');
}
function closeDateSyncModal() {
  const modal = document.getElementById('modal-date-sync');
  if (modal) modal.classList.add('hidden');
}
async function submitDateSync() {
  const inputDevId = document.getElementById('input-date-sync-device-id');
  const inputDate = document.getElementById('input-date-sync-start');
  const deviceId = (inputDevId && inputDevId.value) ? inputDevId.value : 'health_connect';
  const startDate = inputDate ? inputDate.value : null;
  if (!startDate) {
    if (typeof showToast === 'function') showToast('Veuillez sélectionner une date valide', 'warning');
    return;
  }
  closeDateSyncModal();
  await triggerDeviceSync(deviceId, { start_date: startDate });
}
function openBridgeFromDateSyncModal() {
  const inputDate = document.getElementById('input-date-sync-start');
  const startDate = inputDate ? inputDate.value : '';
  closeDateSyncModal();
  const url = startDate ? 'vitaltrack://sync?from_date=' + encodeURIComponent(startDate) : 'vitaltrack://sync?since_last=true';
  window.location.href = url;
  if (typeof showToast === 'function') {
    showToast('Ouverture du bridge Android VitalTrack (' + (startDate || 'dernière synchro') + ')...', 'info');
  }
}
window.openDateSyncModal = openDateSyncModal;
window.closeDateSyncModal = closeDateSyncModal;
window.submitDateSync = submitDateSync;
window.openBridgeFromDateSyncModal = openBridgeFromDateSyncModal;
window.triggerDeviceSync = triggerDeviceSync;
