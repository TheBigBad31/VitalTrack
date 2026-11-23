// static/modules/views/devices.js - Vue Appareils (connexions, sync banner, Data Map)

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

              <button type="button" onclick="triggerDeviceSync('${devId}', { since_last_sync: true })" title="Synchroniser uniquement les données depuis la dernière synchro" class="flex-1 py-2 rounded-xl bg-[#1F2A3C] hover:bg-[#2A374D] text-slate-200 text-xs font-semibold flex items-center justify-center space-x-1.5 transition-colors">
                <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-brand-400"></i>
                <span>Synchroniser</span>
              </button>
              <button type="button" onclick="openDateSyncModal('${devId}')" title="Synchroniser depuis une date précise" class="p-2 rounded-xl bg-[#1F2A3C] hover:bg-[#2A374D] text-cyan-400 border border-slate-700/60 transition-colors flex items-center justify-center">
                <i data-lucide="calendar" class="w-3.5 h-3.5"></i>
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



window.renderDevicesView = renderDevicesView;
window.renderLiveSyncBanner = renderLiveSyncBanner;
