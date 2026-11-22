// static/modules/views/devices.js — Extracted from dashboard.js

        function formatRelativeTime(isoString) {

      if (!isoString) return null;

      try {

        const d = new Date(isoString);

        if (isNaN(d.getTime())) return null;

        const now = new Date();

        const diffMs = now - d;

        const diffMins = Math.floor(diffMs / 60000);

        if (diffMins < 1) return "À l'instant";

        if (diffMins === 1) return "Il y a 1 minute";

        if (diffMins < 60) return `Il y a ${diffMins} minutes`;

        const diffHours = Math.floor(diffMins / 60);

        if (diffHours === 1) return "Il y a 1 heure";

        if (diffHours < 24) return `Il y a ${diffHours} heures`;

        const diffDays = Math.floor(diffHours / 24);

        if (diffDays === 1) return "Hier";

        return `Il y a ${diffDays} jours`;

      } catch (e) {

        return null;

      }

    }



        function renderLiveSyncBanner() {

      const banner = document.getElementById('banner-health-connect-live');

      if (!banner) return;



      const titleEl = document.getElementById('live-hc-title');

      const badgeEl = document.getElementById('live-hc-status-badge');

      const statusTextEl = document.getElementById('live-hc-status-text');

      const iconEl = document.getElementById('live-hc-icon');

      const iconContainerEl = document.getElementById('live-hc-icon-container');

      const stepsEl = document.getElementById('live-hc-steps');

      const calsEl = document.getElementById('live-hc-cals');

      const hrEl = document.getElementById('live-hc-hr');

      const hrvEl = document.getElementById('live-hc-hrv');

      const sleepEl = document.getElementById('live-hc-sleep');

      const syncBtn = document.getElementById('live-hc-sync-btn');

      const syncTxt = document.getElementById('live-hc-sync-txt');



      const s = currentData.summary || {};

      const allDevices = currentData.devices || [];

      const connectedDevices = allDevices.filter(d => Boolean(d.connected || d.status === 'connected'));



      // Trouver l'appareil prioritaire (Health Connect > RingConn > Oura > premier connecté)

      let activeDevice = connectedDevices.find(d => (d.id || d.device_id) === 'health_connect')

        || connectedDevices.find(d => ['ringconn', 'oura'].includes(d.id || d.device_id))

        || connectedDevices[0]

        || null;



      const latestAct = (currentData.activities_history && currentData.activities_history.length > 0)

        ? currentData.activities_history[currentData.activities_history.length - 1]

        : null;



      const stepsVal = latestAct ? (latestAct.steps || s.steps) : s.steps;

      const calsVal = latestAct ? (latestAct.active_calories_kcal || 0) : null;

      const hrVal = latestAct ? (latestAct.resting_hr_bpm || s.resting_hr_bpm) : s.resting_hr_bpm;

      const hrvVal = latestAct ? (latestAct.hrv_ms || s.hrv_ms) : s.hrv_ms;

      const sleepVal = latestAct ? (latestAct.sleep_score || s.sleep_score) : s.sleep_score;



      if (stepsEl) stepsEl.innerText = stepsVal !== null && stepsVal !== undefined ? `${stepsVal.toLocaleString()} pas` : '-- pas';

      if (calsEl) calsEl.innerText = calsVal !== null && calsVal !== undefined ? `${calsVal} kcal` : '-- kcal';

      if (hrEl) hrEl.innerText = hrVal ? `${hrVal} BPM` : '--';

      if (hrvEl) hrvEl.innerText = hrvVal ? `${hrvVal} ms` : '--';

      if (sleepEl) sleepEl.innerText = sleepVal ? `${sleepVal} / 100` : '--';



      // 1. Cas : Aucun appareil connecté

      if (!activeDevice && connectedDevices.length === 0) {

        if (titleEl) titleEl.innerText = "Synchronisation appareils : Aucune passerelle connectée";

        if (badgeEl) {

          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 font-semibold flex items-center gap-1";

          badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-slate-500"></span><span id="live-hc-status-text">Non connecté</span>';

        }

        if (iconEl) iconEl.setAttribute('data-lucide', 'link-2');

        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-slate-800/60 border border-slate-700 flex items-center justify-center text-slate-400 shrink-0";

        if (syncTxt) syncTxt.innerText = "Connecter";

        if (syncBtn) {

          syncBtn.onclick = () => openConnectWizardModal('health_connect');

          syncBtn.title = "Ouvrir l'assistant de connexion d'appareils";

        }

        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-slate-900/60 via-[#151D2A] to-[#151D2A] border border-slate-700/50 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";

        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

        return;

      }



      // 2. Cas : Appareil connecté

      const devId = activeDevice.id || activeDevice.device_id;

      const devName = activeDevice.name || (devId === 'health_connect' ? 'Google Santé Connect (Android)' : (devId === 'withings' ? 'Withings' : devId));

      if (titleEl) titleEl.innerText = `Données en direct : ${devName}`;



      let iconName = 'smartphone';

      if (activeDevice.device_type === 'ring' || devId === 'ringconn' || devId === 'oura') iconName = 'circle-dot';

      else if (activeDevice.device_type === 'scale' || devId === 'withings') iconName = 'scale';

      if (iconEl) iconEl.setAttribute('data-lucide', iconName);



      if (syncBtn) {

        syncBtn.onclick = () => triggerSyncFromBanner(devId);

        syncBtn.title = `Lancer la synchronisation immédiate de ${devName}`;

      }

      if (syncTxt) syncTxt.innerText = "Synchroniser";



      const lastSyncRaw = activeDevice.last_sync_at || activeDevice.last_sync;

      const syncStatus = (activeDevice.sync_status || activeDevice.status || 'connected').toLowerCase();

      const relativeTime = formatRelativeTime(lastSyncRaw);



      if (syncStatus === 'error' || syncStatus === 'failed') {

        if (badgeEl) {

          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/30 font-semibold flex items-center gap-1";

          badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span><span id="live-hc-status-text">Erreur de synchronisation ⚠</span>';

        }

        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0";

        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-rose-950/30 via-[#151D2A] to-[#151D2A] border border-rose-500/30 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";

      } else if (!lastSyncRaw || syncStatus === 'waiting_first_sync') {

        if (badgeEl) {

          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 font-semibold flex items-center gap-1";

          badgeEl.innerHTML = '<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span><span id="live-hc-status-text">En attente du 1er envoi depuis votre téléphone</span>';

        }

        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0";

        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-amber-950/30 via-[#151D2A] to-[#151D2A] border border-amber-500/30 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";

      } else {

        const syncLabel = relativeTime ? `Synchronisé ${relativeTime.toLowerCase()} ✓` : 'Synchronisé ✓';

        if (badgeEl) {

          badgeEl.className = "text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold flex items-center gap-1";

          badgeEl.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span><span id="live-hc-status-text">${syncLabel}</span>`;

        }

        if (iconContainerEl) iconContainerEl.className = "w-11 h-11 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0";

        banner.className = "p-4 rounded-2xl bg-gradient-to-r from-emerald-950/40 via-[#151D2A] to-[#151D2A] border border-emerald-500/30 flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-300";

      }



      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

    }



    async function triggerSyncFromBanner(deviceId) {

      const syncIcon = document.getElementById('live-hc-sync-icon');

      const syncTxt = document.getElementById('live-hc-sync-txt');

      if (syncIcon) syncIcon.classList.add('animate-spin');

      if (syncTxt) syncTxt.innerText = "Synchronisation...";



      const targetId = deviceId || 'health_connect';

      try {

        await triggerDeviceSync(targetId);

      } finally {

        if (syncIcon) syncIcon.classList.remove('animate-spin');

        if (syncTxt) syncTxt.innerText = "Synchroniser";

      }

    }



    function renderDevicesView() {

      const grid = document.getElementById('devices-grid');

      if (!grid) return;



      const allDevices = currentData.devices || [];

      // Filtrer STRICTEMENT : seuls les appareils ajoutés / connectés sont affichés

      const connectedDevices = allDevices.filter(d => Boolean(d.connected || d.status === 'connected'));



      if (connectedDevices.length === 0) {

        grid.innerHTML = `

          <div class="col-span-full bg-[#0B0F17] border border-dashed border-[#1F2A3C] rounded-2xl p-8 text-center space-y-3">

            <div class="w-12 h-12 mx-auto rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">

              <i data-lucide="link-2" class="w-6 h-6"></i>

            </div>

            <h4 class="text-sm font-bold text-white">Aucun objet connecté dans votre profil pour le moment</h4>

            <p class="text-xs text-slate-400 max-w-md mx-auto">

              Ajoutez votre bague connectée RingConn, Google Santé Connect (Android), ou votre balance Withings pour lancer la synchronisation automatique.

            </p>

            <button type="button" onclick="openConnectWizardModal()" class="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-md shadow-indigo-600/20 inline-flex items-center space-x-2 transition-transform active:scale-95">

              <i data-lucide="plus" class="w-4 h-4"></i>

              <span>Ajouter mon premier appareil</span>

            </button>

          </div>

        `;

        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

        return;

      }



      // Rendu des cartes pour chaque appareil connecté

      const cardsHtml = connectedDevices.map(d => {

        const devId = d.id || d.device_id;

        const lastSyncVal = d.last_sync_at || d.last_sync;

        const wizTarget = (devId === 'ringconn' || devId === 'withings' || devId === 'oura' || devId === 'health_connect') ? devId : 'health_connect';



        // Métriques contextuelles selon l'appareil

        let metricsSnippet = '';

        if (devId === 'health_connect') {

          const act = (currentData.activities_history && currentData.activities_history.length > 0)

            ? currentData.activities_history[currentData.activities_history.length - 1]

            : null;

          if (act) {

            metricsSnippet = `

              <div class="p-2.5 rounded-xl bg-emerald-950/20 border border-emerald-500/30 text-[11px] text-slate-300 space-y-1">

                <span class="text-emerald-400 font-semibold block flex items-center space-x-1">

                  <i data-lucide="check-circle" class="w-3 h-3 text-emerald-400"></i>

                  <span>Dernier flux reçu :</span>

                </span>

                <div class="text-white font-medium">

                  <strong>${(act.steps || 0).toLocaleString()} pas</strong> • <strong>${act.active_calories_kcal || 0} kcal</strong> • FC ${act.resting_hr_bpm || 57} BPM • Sommeil ${act.sleep_score || 85}/100

                </div>

              </div>

            `;

          }

        } else if (devId === 'withings') {

          const w = (currentData.weights_history && currentData.weights_history.length > 0)

            ? currentData.weights_history[currentData.weights_history.length - 1]

            : null;

          if (w) {

            metricsSnippet = `

              <div class="p-2.5 rounded-xl bg-sky-950/20 border border-sky-500/30 text-[11px] text-slate-300 space-y-1">

                <span class="text-sky-400 font-semibold block flex items-center space-x-1">

                  <i data-lucide="check-circle" class="w-3 h-3 text-sky-400"></i>

                  <span>Dernière pesée reçue :</span>

                </span>

                <div class="text-white font-medium">

                  <strong>${w.weight_kg} kg</strong> ${w.body_fat_pct ? `• ${w.body_fat_pct}% MG` : ''} ${w.muscle_mass_kg ? `• ${w.muscle_mass_kg} kg Muscle` : ''}

                </div>

              </div>

            `;

          }

        }



        // Détermination fine du badge et statut de synchronisation

        const isWaitingFirstSync = (devId === 'health_connect' && (!lastSyncVal || d.sync_status === 'waiting_first_sync'));

        const syncBadgeHtml = isWaitingFirstSync

          ? `<span class="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1"><span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span><span>En attente du 1er envoi</span></span>`

          : `<span class="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1"><span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span><span>Synchronisé ✓</span></span>`;



        const syncStatusDesc = isWaitingFirstSync

          ? `<span class="text-amber-400 font-medium">En attente du 1er envoi depuis votre téléphone</span>`

          : `<span class="text-emerald-400 font-medium">Flux actif dans votre profil</span>`;



        const lastSyncLabel = lastSyncVal

          ? (typeof formatRelativeTime === 'function' && formatRelativeTime(lastSyncVal) ? formatRelativeTime(lastSyncVal) : lastSyncVal.slice(0, 16).replace('T', ' '))

          : (isWaitingFirstSync ? 'Aucune donnée reçue' : 'Enregistré');



        return `

          <div class="bg-[#0B0F17] hover:bg-[#111826] border border-[#1F2A3C] hover:border-brand-500/50 rounded-2xl p-4 flex flex-col justify-between space-y-4 transition-all group">

            <div class="flex items-start justify-between">

              <div class="flex items-center space-x-3">

                <div class="w-10 h-10 rounded-xl bg-brand-500/10 text-brand-400 border border-brand-500/20 flex items-center justify-center">

                  <i data-lucide="${d.device_type === 'ring' ? 'circle-dot' : (d.device_type === 'scale' ? 'scale' : 'smartphone')}" class="w-5 h-5"></i>

                </div>

                <div>

                  <h4 class="font-bold text-white text-sm">${d.name}</h4>

                  <span class="text-[10px] text-brand-400 font-medium">${devId === 'health_connect' ? 'Passerelle Android Santé Connect' : (devId === 'withings' ? 'Balance Wi-Fi & Impédancemètre' : d.device_type)}</span>

                </div>

              </div>

              ${syncBadgeHtml}

            </div>



            ${metricsSnippet}



            <div class="text-xs text-slate-300">

              <div class="flex justify-between py-1 border-b border-[#1F2A3C]/50">

                <span class="text-slate-400">Dernière synchronisation :</span>

                <span class="text-slate-200 font-medium">${lastSyncLabel}</span>

              </div>

              <div class="flex justify-between py-1">

                <span class="text-slate-400">Statut liaison :</span>

                ${syncStatusDesc}

              </div>

            </div>



            <div class="flex items-center space-x-2">

              <button type="button" onclick="openConnectWizardModal('${wizTarget}')" class="flex-1 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-all">

                <i data-lucide="settings" class="w-3.5 h-3.5"></i>

                <span>Configurer</span>

              </button>

              <button type="button" onclick="triggerDeviceSync('${devId}')" class="flex-1 py-2 rounded-xl bg-[#1F2A3C] hover:bg-[#2A374D] text-slate-200 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">

                <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-brand-400"></i>

                <span>Synchroniser</span>

              </button>

              <button type="button" onclick="disconnectDevice('${devId}')" title="Déconnecter et retirer du profil" class="p-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 transition-colors">

                <i data-lucide="trash-2" class="w-4 h-4"></i>

              </button>

            </div>

          </div>

        `;

      }).join('');



      // Carte d'ajout pour connecter un autre objet

      const addCardHtml = `

        <div onclick="openConnectWizardModal()" class="border-2 border-dashed border-[#1F2A3C] hover:border-indigo-500/60 rounded-2xl p-6 flex flex-col items-center justify-center text-center space-y-2.5 cursor-pointer transition-colors group min-h-[180px]">

          <div class="w-11 h-11 rounded-xl bg-[#151D2A] group-hover:bg-indigo-600/20 text-slate-400 group-hover:text-indigo-400 border border-[#1F2A3C] group-hover:border-indigo-500/30 flex items-center justify-center transition-all">

            <i data-lucide="plus" class="w-5 h-5"></i>

          </div>

          <div>

            <h5 class="text-xs font-bold text-slate-200 group-hover:text-white transition-colors">Ajouter un autre appareil</h5>

            <p class="text-[10px] text-slate-500 mt-0.5">RingConn Gen 3, Google Santé Connect, Withings...</p>

          </div>

        </div>

      `;



      grid.innerHTML = cardsHtml + addCardHtml;

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

      loadDataMapView();

    }

    async function loadDataMapView() {
      const weightsTbody = document.getElementById('data-map-weights-tbody');
      const metricsTbody = document.getElementById('data-map-metrics-tbody');
      if (!weightsTbody && !metricsTbody) return;

      try {
        const readOnlyParam = (window.currentReadOnlyFriend && window.currentReadOnlyFriend.active && window.currentReadOnlyFriend.friend_id) ? `?user_id=${window.currentReadOnlyFriend.friend_id}` : '';
        const res = await apiFetch(`/api/devices/data-map${readOnlyParam}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const summary = data.summary || {};
        const elTotal = document.getElementById('dm-summary-total');
        const elDisp = document.getElementById('dm-summary-displayed');
        const elHid = document.getElementById('dm-summary-hidden');
        const elNotRead = document.getElementById('dm-summary-notread');
        if (elTotal) elTotal.textContent = summary.total_metrics ?? 17;
        if (elDisp) elDisp.textContent = summary.ingested_and_displayed ?? '-';
        if (elHid) elHid.textContent = summary.ingested_not_displayed ?? '-';
        if (elNotRead) elNotRead.textContent = summary.not_read ?? '-';

        if (weightsTbody) {
          const weights = data.recent_weights || [];
          if (weights.length === 0) {
            weightsTbody.innerHTML = '<tr><td colspan="5" class="py-3 px-3 text-slate-500 text-center">Aucune pesée enregistrée récemment.</td></tr>';
          } else {
            weightsTbody.innerHTML = weights.map(w => {
              const src = escapeHtml(w.source || 'manual');
              const srcBadge = src === 'withings'
                ? '<span class="px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 font-semibold">Withings OAuth</span>'
                : (src === 'health_connect'
                  ? '<span class="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold">Santé Connect</span>'
                  : `<span class="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700 font-semibold">${src}</span>`);
              const fat = w.fat_mass_percent != null ? `${Number(w.fat_mass_percent).toFixed(1)} %` : '—';
              return `
                <tr class="hover:bg-[#151D2A]/40 transition-colors">
                  <td class="py-2 px-3 text-slate-200 font-medium">${escapeHtml(w.date || '—')}</td>
                  <td class="py-2 px-3 text-white font-bold font-mono">${w.weight_kg != null ? Number(w.weight_kg).toFixed(1) + ' kg' : '—'}</td>
                  <td class="py-2 px-3 text-slate-300 font-mono">${escapeHtml(fat)}</td>
                  <td class="py-2 px-3">${srcBadge}</td>
                  <td class="py-2 px-3 text-slate-400 font-mono text-[11px]">${escapeHtml(w.created_at || w.date || '—')}</td>
                </tr>
              `;
            }).join('');
          }
        }

        if (metricsTbody) {
          const metrics = data.metrics || [];
          if (metrics.length === 0) {
            metricsTbody.innerHTML = '<tr><td colspan="7" class="py-4 px-3 text-slate-500 text-center">Aucune métrique répertoriée.</td></tr>';
          } else {
            metricsTbody.innerHTML = metrics.map(m => {
              const sourcesPills = (m.supported_sources || []).map(s =>
                `<span class="inline-block px-1.5 py-0.5 rounded bg-[#151D2A] border border-[#1F2A3C] text-[10px] text-slate-300 mr-1 mb-0.5">${escapeHtml(s)}</span>`
              ).join('');
              const lp = m.last_point;
              const lastPointHtml = lp
                ? `<span class="text-white font-mono font-semibold">${escapeHtml(lp.value || '')}</span> <span class="text-[10px] text-slate-400">(${escapeHtml(lp.date || '')} · ${escapeHtml(lp.source || '')})</span>`
                : '<span class="text-slate-500 italic">Aucun point</span>';
              let statusBadge = '<span class="px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 text-[10px] font-semibold">● Non lu</span>';
              if (m.status === 'ingested_and_displayed') {
                statusBadge = '<span class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-semibold">● Affiché UI</span>';
              } else if (m.status === 'ingested_not_displayed') {
                statusBadge = '<span class="px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 text-[10px] font-semibold">● Stocké non affiché</span>';
              }
              return `
                <tr class="hover:bg-[#151D2A]/40 transition-colors">
                  <td class="py-2.5 px-3 text-white font-semibold">${escapeHtml(m.label || m.key)}</td>
                  <td class="py-2.5 px-3">${sourcesPills}</td>
                  <td class="py-2.5 px-3 text-slate-400 font-mono text-[11px]">${escapeHtml(m.table || '—')}</td>
                  <td class="py-2.5 px-3">${lastPointHtml}</td>
                  <td class="py-2.5 px-3 text-center font-mono text-slate-200">${m.points_7d_count ?? 0}</td>
                  <td class="py-2.5 px-3 text-slate-300 text-[11px]">${escapeHtml(m.ui_location || '—')}</td>
                  <td class="py-2.5 px-3 text-center">${statusBadge}</td>
                </tr>
              `;
            }).join('');
          }
        }
      } catch (err) {
        console.warn('[DataMap] Impossible de charger /api/devices/data-map:', err);
        if (weightsTbody) weightsTbody.innerHTML = '<tr><td colspan="5" class="py-3 px-3 text-rose-400 text-center">Impossible de charger la provenance des pesées.</td></tr>';
        if (metricsTbody) metricsTbody.innerHTML = '<tr><td colspan="7" class="py-4 px-3 text-rose-400 text-center">Impossible de charger la cartographie des flux.</td></tr>';
      }
    }
    window.loadDataMapView = loadDataMapView;



    async function triggerDeviceSync(deviceId) {

      try {

        if (typeof showToast === 'function') showToast(`Synchronisation de ${deviceId} en cours...`, 'info');

        const res = await apiFetch(`/api/devices/${deviceId}/sync`, {

          method: 'POST'

        });

        if (res.ok) {

          const data = await res.json();

          if (typeof showToast === 'function') showToast(`Synchronisation de ${data.name || deviceId} réussie ! Données biométriques mises à jour.`, 'success');

          else alert(`Synchronisation de ${data.name || deviceId} réussie ! Données mises à jour.`);

          await loadDashboardData();

        } else {

          // Fallback legacy

          await apiFetch('/api/devices/sync', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ device_id: deviceId })

          });

          if (typeof showToast === 'function') showToast(`Synchronisation de ${deviceId} effectuée.`, 'info');

          await loadDashboardData();

        }

      } catch (err) {

        if (typeof showToast === 'function') showToast(`Synchronisation déclenchée.`, 'info');

      }

    }



    async function disconnectDevice(deviceId) {

      if (!confirm(`Êtes-vous sûr de vouloir déconnecter et révoquer l'appareil '${deviceId}' ?`)) return;

      try {

        const res = await apiFetch(`/api/devices/${deviceId}`, {

          method: 'DELETE'

        });

        if (res.ok) {

          if (typeof showToast === 'function') showToast(`Appareil '${deviceId}' déconnecté et identifiants révoqués.`, 'info');

          await loadDashboardData();

        } else {

          if (typeof showToast === 'function') showToast(`Erreur lors de la déconnexion.`, 'error');

        }

      } catch (err) {

        if (typeof showToast === 'function') showToast(`Erreur réseau lors de la déconnexion.`, 'error');

      }

    }



    // =====================================================================

    // LOGIQUE MODAL PHOTO REPAS & CURSEUR

    // =====================================================================


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

              <input type="email" id="wiz-input-withings-email" placeholder="sebastienlamoliate@gmail.com" value="sebastienlamoliate@gmail.com" class="w-full bg-[#151D2A] border border-[#1F2A3C] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500">

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



    // =====================================================================

    // LOGIQUE SAUVEGARDE & PERSISTANCE DURABLE (Anti-Perte Vercel)

    // =====================================================================


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

        email = inp ? inp.value : 'sebastienlamoliate@gmail.com';

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



    // =====================================================================

    // LOGIQUE AUTHENTIFICATION UNIFIÉE (GOOGLE, EMAIL/MDP, SESSION & TOKEN BEARER)

    // =====================================================================

    let currentUnifiedSession = { is_authenticated: false };

    let currentGoogleConfig = { google_client_id: "", is_configured: false };

    let currentAuthEmailMode = 'login'; // 'login' ou 'register'




