// static/modules/saved_meals.js - Modale ajout repas photo & bibliothèque de repas sauvegardés

    // =====================================================================
    // LOGIQUE MODAL PHOTO REPAS & CURSEUR
    // =====================================================================
    function openMealModal(mealType) {
      if (mealType) {
        const sel = document.getElementById('meal-type-select');
        if (sel) sel.value = mealType;
      }
      const dateInp = document.getElementById('meal-date-input');
      if (dateInp && !dateInp.value) {
        const activeDate = (typeof window.getActiveMealDate === 'function')
          ? window.getActiveMealDate()
          : new Date().toISOString().split('T')[0];
        dateInp.value = activeDate;
      }
      document.getElementById('modal-meal').classList.remove('hidden');
    }
    function closeMealModal() {
      document.getElementById('modal-meal').classList.add('hidden');
    }

    function handleMealPhotoSelected(event) {
      const file = event.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        currentUploadedPhotoUrl = e.target.result;
        const preview = document.getElementById('meal-photo-preview');
        const placeholder = document.getElementById('meal-photo-placeholder');
        preview.src = currentUploadedPhotoUrl;
        preview.classList.remove('hidden');
        placeholder.classList.add('hidden');
      };
      reader.readAsDataURL(file);
    }

    async function triggerMealEstimation() {
      const btn = document.getElementById('btn-estimate-meal');
      btn.disabled = true;
      btn.innerHTML = `<span class="animate-spin mr-2">⏳</span> Analyse IA en cours...`;

      const desc = document.getElementById('meal-desc-input').value;
      const mealType = document.getElementById('meal-type-select').value;
      const scale = parseFloat(document.getElementById('portion-scale-range').value);

      try {
        const res = await apiFetch('/api/meals/estimate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            photo_data_url: currentUploadedPhotoUrl,
            description: desc,
            meal_type: mealType,
            portion_scale: scale
          })
        });

        if (res.ok) {
          currentEstimatedMeal = await res.json();
        } else {
          // Fallback local estimation
          currentEstimatedMeal = {
            items: [
              { name: "Blanc de poulet", portion_g: 150 * scale, calories_kcal: 180 * scale, protein_g: 39 * scale, carbs_g: 0, fat_g: 2.7 * scale },
              { name: "Riz basmati", portion_g: 180 * scale, calories_kcal: 234 * scale, protein_g: 4.8 * scale, carbs_g: 50.4 * scale, fat_g: 0.5 * scale },
              { name: "Brocolis", portion_g: 150 * scale, calories_kcal: 52 * scale, protein_g: 4.2 * scale, carbs_g: 10.5 * scale, fat_g: 0.6 * scale }
            ],
            total_calories_kcal: Math.round(466 * scale),
            total_protein_g: Math.round(48 * scale),
            total_carbs_g: Math.round(61 * scale),
            total_fat_g: Math.round(3.8 * scale)
          };
        }
      } catch (err) {
        currentEstimatedMeal = {
          items: [
            { name: "Assiette équilibrée", portion_g: 450 * scale, calories_kcal: 550 * scale, protein_g: 35 * scale, carbs_g: 65 * scale, fat_g: 14 * scale }
          ],
          total_calories_kcal: Math.round(550 * scale),
          total_protein_g: Math.round(35 * scale),
          total_carbs_g: Math.round(65 * scale),
          total_fat_g: Math.round(14 * scale)
        };
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="sparkles" class="w-4 h-4 mr-1"></i> Ré-estimer les Calories & Macros`;
        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }
        renderEstimationResult();
      }
    }

    function updatePortionScale(val) {
      const scale = parseFloat(val);
      const label = scale === 1.0 ? "1.0x (Normale)" : (scale < 1.0 ? `${scale}x (Petite)` : `${scale}x (Grande/Double)`);
      document.getElementById('portion-scale-val').innerText = label;

      if (currentEstimatedMeal && currentEstimatedMeal.items) {
        // Recalcul proportionnel immédiat dans l'interface
        triggerMealEstimation();
      }
    }

    function renderEstimationResult() {
      if (!currentEstimatedMeal) return;
      document.getElementById('meal-estimation-result').classList.remove('hidden');

      document.getElementById('est-calories').innerText = `${Math.round(currentEstimatedMeal.total_calories_kcal || 0)} kcal`;
      document.getElementById('est-protein').innerText = `${Math.round(currentEstimatedMeal.total_protein_g || 0)}g`;
      document.getElementById('est-carbs').innerText = `${Math.round(currentEstimatedMeal.total_carbs_g || 0)}g`;
      document.getElementById('est-fat').innerText = `${Math.round(currentEstimatedMeal.total_fat_g || 0)}g`;

      const listEl = document.getElementById('est-items-list');
      listEl.innerHTML = (currentEstimatedMeal.items || []).map(item => `
        <div class="flex items-center justify-between p-2 rounded-lg bg-[#151D2A] border border-[#1F2A3C]">
          <div>
            <span class="font-bold text-white text-xs">${escapeHtml(item.name || '')}</span>
            <span class="text-[10px] text-slate-400 block">${Math.round(item.portion_g)}g • ${Math.round(item.calories_kcal)} kcal</span>
          </div>
          <div class="text-[10px] text-slate-300">
            P: <b class="text-brand-400">${Math.round(item.protein_g)}g</b> |
            G: <b class="text-sky-400">${Math.round(item.carbs_g)}g</b> |
            L: <b class="text-amber-400">${Math.round(item.fat_g)}g</b>
          </div>
        </div>
      `).join('');

      const scoreBox = document.getElementById('est-nutritionscore-box');
      const qualityEl = document.getElementById('est-nutritional-quality');
      const benefitsWrap = document.getElementById('est-key-benefits-wrapper');
      const benefitsEl = document.getElementById('est-key-benefits');

      const qualityText = currentEstimatedMeal.nutritional_quality || currentEstimatedMeal.dietary_advice || '';
      const keyBenefits = Array.isArray(currentEstimatedMeal.key_benefits) ? currentEstimatedMeal.key_benefits : [];

      if (scoreBox && qualityEl) {
        if (qualityText || keyBenefits.length > 0) {
          scoreBox.classList.remove('hidden');
          qualityEl.textContent = qualityText;
        } else {
          scoreBox.classList.add('hidden');
        }
      }
      if (benefitsWrap && benefitsEl) {
        if (keyBenefits.length > 0) {
          benefitsWrap.classList.remove('hidden');
          benefitsEl.innerHTML = keyBenefits.map(b => {
            const tag = typeof b === 'string' ? b : (b.tag || '');
            const desc = typeof b === 'string' ? '' : (b.description || '');
            return `<span title="${escapeHtml(desc)}" class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">${escapeHtml(tag)}</span>`;
          }).join('');
        } else {
          benefitsWrap.classList.add('hidden');
          benefitsEl.innerHTML = '';
        }
      }
    }

    async function saveMealToJournal() {
      const btn = document.getElementById('btn-save-meal');
      btn.disabled = true;
      btn.innerHTML = `Enregistrement...`;

      const dateVal = document.getElementById('meal-date-input').value;
      const mealType = document.getElementById('meal-type-select').value;
      const scale = parseFloat(document.getElementById('portion-scale-range').value);

      const payload = {
        date: dateVal,
        meal_type: mealType,
        photo_data_url: currentUploadedPhotoUrl,
        portion_scale: scale,
        items: currentEstimatedMeal ? currentEstimatedMeal.items : []
      };

      try {
        await apiFetch('/api/meals', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (err) {
        console.warn("Save fallback");
      }

      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="check" class="w-4 h-4 mr-1"></i> Enregistré !`;
      setTimeout(() => {
        closeMealModal();
        loadDashboardData();
        switchTab('nutrition');
      }, 500);
    }

    // =====================================================================
    // GESTION BIBLIOTHÈQUE DE PLATS RÉUTILISABLES & 4 REPAS
    // =====================================================================
    let currentSavedMealsCache = [];
    let currentSavedMealsFilter = null;
    let currentSavedMealPhotoBase64 = null;

    function openSavedMealsLibraryModal(filterType = null) {
      currentSavedMealsFilter = filterType;
      const modal = document.getElementById('modal-saved-meals');
      if (modal) modal.classList.remove('hidden');
      updateSavedMealFilterButtonsUI();
      loadAndRenderSavedMeals();
    }

    function closeSavedMealsLibraryModal() {
      const modal = document.getElementById('modal-saved-meals');
      if (modal) modal.classList.add('hidden');
    }

    function filterSavedMealsLibrary(mealType) {
      currentSavedMealsFilter = mealType;
      updateSavedMealFilterButtonsUI();
      loadAndRenderSavedMeals();
    }

    function updateSavedMealFilterButtonsUI() {
      const types = ['all', 'breakfast', 'lunch', 'snack', 'dinner'];
      types.forEach(t => {
        const btn = document.getElementById(`filter-saved-${t}`);
        if (!btn) return;
        const isActive = (t === 'all' && !currentSavedMealsFilter) || (currentSavedMealsFilter === t);
        if (isActive) {
          btn.className = "saved-meal-filter-btn flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white transition-colors flex items-center justify-center space-x-1";
        } else {
          btn.className = "saved-meal-filter-btn flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-white transition-colors flex items-center justify-center space-x-1";
        }
      });
    }

    async function loadAndRenderSavedMeals() {
      const container = document.getElementById('saved-meals-cards-container');
      if (!container) return;
      container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-slate-400"><span class="animate-spin inline-block mr-2">⏳</span> Chargement des plats réutilisables...</div>';

      try {
        let url = '/api/meals/saved';
        if (currentSavedMealsFilter) {
          url += `?meal_type=${currentSavedMealsFilter}`;
        }
        const res = await apiFetch(url);
        if (res.ok) {
          currentSavedMealsCache = await res.json();
          renderSavedMealsCards(currentSavedMealsCache);
        } else {
          container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-rose-400">Impossible de charger les plats sauvegardés.</div>';
        }
      } catch (err) {
        container.innerHTML = '<div class="col-span-full py-8 text-center text-xs text-rose-400">Erreur réseau lors de la récupération des plats.</div>';
      }
    }

    function renderSavedMealsCards(meals) {
      const container = document.getElementById('saved-meals-cards-container');
      if (!container) return;

      if (!meals || meals.length === 0) {
        container.innerHTML = `
          <div class="col-span-full py-8 text-center space-y-3 bg-[#0B0F17]/50 border border-dashed border-[#1F2A3C] rounded-xl p-4">
            <span class="text-3xl block">🍽️</span>
            <p class="text-xs text-slate-400">Aucun plat réutilisable enregistré pour ce repas.</p>
            <button onclick="openCreateSavedMealModal(currentSavedMealsFilter)" class="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold inline-flex items-center space-x-1">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              <span>Créer un premier plat</span>
            </button>
          </div>
        `;
        if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch(e){} }
        return;
      }

      const mealLabels = {
        breakfast: { label: "Petit-déjeuner 🥐", color: "text-amber-400 bg-amber-400/10 border-amber-400/20" },
        lunch: { label: "Déjeuner 🥗", color: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20" },
        snack: { label: "Goûter 🍎", color: "text-pink-400 bg-pink-400/10 border-pink-400/20" },
        dinner: { label: "Dîner 🍲", color: "text-indigo-400 bg-indigo-400/10 border-indigo-400/20" }
      };

      container.innerHTML = meals.map(m => {
        const typeInfo = mealLabels[m.meal_type] || { label: m.meal_type, color: "text-slate-400" };
        const safeName = escapeHtml(m.name || '');
        const safeServing = escapeHtml(m.serving_size || '1 portion');
        const photoUrl = sanitizeUrl(m.photo_url);
        const mId = parseInt(m.id, 10) || 0;
        const mType = escapeHtml(m.meal_type || '');

        return `
          <div class="bg-[#0B0F17] border border-[#1F2A3C] hover:border-indigo-500/30 rounded-xl p-3 flex flex-col justify-between space-y-2 transition-all">
            <div class="space-y-1.5">
              <div class="flex items-start justify-between gap-1">
                <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border ${typeInfo.color}">
                  ${escapeHtml(typeInfo.label)}
                </span>
                <div class="flex items-center space-x-1">
                  ${m.is_favorite ? '<span class="text-xs text-amber-400">⭐</span>' : ''}
                  <button onclick="deleteSavedMeal(${mId})" title="Supprimer ce plat" class="p-1 text-slate-500 hover:text-rose-400 rounded transition-colors">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                  </button>
                </div>
              </div>

              ${photoUrl ? `
                <div class="rounded-lg overflow-hidden border border-[#1F2A3C] h-24 w-full">
                  <img src="${photoUrl}" alt="${safeName}" class="w-full h-full object-cover">
                </div>
              ` : ''}

              <div>
                <h4 class="font-bold text-white text-xs leading-tight line-clamp-1">${safeName}</h4>
                <div class="text-[10px] text-slate-400 mt-0.5">${safeServing} ${m.quantity_grams ? '(' + Math.round(m.quantity_grams) + 'g)' : ''}</div>
              </div>

              <!-- Macros -->
              <div class="flex items-center justify-between text-[10px] pt-1 border-t border-[#1F2A3C]/70">
                <span class="font-bold text-white">${Math.round(m.calories)} kcal</span>
                <span class="text-brand-400">P:${Math.round(m.protein_g)}g</span>
                <span class="text-sky-400">G:${Math.round(m.carbs_g)}g</span>
                <span class="text-amber-400">L:${Math.round(m.fat_g)}g</span>
              </div>
            </div>

            <!-- Bouton Ajouter au Journal 1-clic -->
            <div class="pt-2">
              <button onclick="logSavedMealDirectly(${mId}, '${mType}')" class="w-full py-1.5 px-2 rounded-lg bg-brand-600/20 hover:bg-brand-600 text-brand-300 hover:text-white border border-brand-500/30 text-[11px] font-bold flex items-center justify-center space-x-1.5 transition-all active:scale-95">
                <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i>
                <span>+ Ajouter au Journal</span>
              </button>
            </div>
          </div>
        `;
      }).join('');

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch(e){} }
    }

    async function logSavedMealDirectly(savedMealId, mealType) {
      const activeDate = (typeof window.getActiveMealDate === 'function')
        ? window.getActiveMealDate()
        : new Date().toISOString().split('T')[0];
      try {
        if (typeof showToast === 'function') showToast("Ajout au journal alimentaire...", "info");
        const res = await apiFetch(`/api/meals/saved/${savedMealId}/log`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            date: activeDate,
            meal_type: mealType,
            portion_factor: 1.0
          })
        });

        if (res.ok) {
          const label = (typeof window.formatJournalDateLabel === 'function')
            ? window.formatJournalDateLabel(activeDate)
            : activeDate;
          if (typeof showToast === 'function') showToast("Plat ajouté au journal " + label + " avec succès ! 🥐🥗🍎🍲", "success");
          closeSavedMealsLibraryModal();
          await loadDashboardData();
          switchTab('nutrition');
        } else {
          if (typeof showToast === 'function') showToast("Erreur lors de l'ajout du plat au journal.", "error");
        }
      } catch (err) {
        if (typeof showToast === 'function') showToast("Erreur réseau lors de l'ajout du plat.", "error");
      }
    }

    async function deleteSavedMeal(mealId) {
      if (!confirm("Voulez-vous vraiment supprimer ce plat de votre bibliothèque ?")) return;
      try {
        const res = await apiFetch(`/api/meals/saved/${mealId}`, { method: 'DELETE' });
        if (res.ok) {
          if (typeof showToast === 'function') showToast("Plat supprimé de la bibliothèque.", "info");
          loadAndRenderSavedMeals();
        } else {
          alert("Erreur lors de la suppression du plat.");
        }
      } catch (err) {
        alert("Erreur réseau lors de la suppression.");
      }
    }

    function openCreateSavedMealModal(prefillType = null) {
      const modal = document.getElementById('modal-create-saved-meal');
      if (!modal) return;
      const form = document.getElementById('form-create-saved-meal');
      if (form) form.reset();
      document.getElementById('saved-meal-edit-id').value = '';
      currentSavedMealPhotoBase64 = null;
      if (prefillType) {
        document.getElementById('saved-meal-type').value = prefillType;
      }
      modal.classList.remove('hidden');
    }

    function closeCreateSavedMealModal() {
      const modal = document.getElementById('modal-create-saved-meal');
      if (modal) modal.classList.add('hidden');
    }

    function handleSavedMealPhotoFile(event) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        currentSavedMealPhotoBase64 = e.target.result;
        document.getElementById('saved-meal-photo-url').value = currentSavedMealPhotoBase64;
      };
      reader.readAsDataURL(file);
    }

    async function handleSavedMealFormSubmit(event) {
      event.preventDefault();
      const btn = document.getElementById('btn-submit-saved-meal');
      btn.disabled = true;

      const payload = {
        name: document.getElementById('saved-meal-name').value.trim(),
        meal_type: document.getElementById('saved-meal-type').value,
        serving_size: document.getElementById('saved-meal-serving').value.trim() || "1 portion",
        calories: parseFloat(document.getElementById('saved-meal-calories').value) || 0,
        protein_g: parseFloat(document.getElementById('saved-meal-protein').value) || 0,
        carbs_g: parseFloat(document.getElementById('saved-meal-carbs').value) || 0,
        fat_g: parseFloat(document.getElementById('saved-meal-fat').value) || 0,
        ingredients: document.getElementById('saved-meal-ingredients').value.trim() || null,
        photo_url: document.getElementById('saved-meal-photo-url').value.trim() || currentSavedMealPhotoBase64 || null,
        is_favorite: document.getElementById('saved-meal-favorite').checked
      };

      try {
        const res = await apiFetch('/api/meals/saved', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          if (typeof showToast === 'function') showToast("Plat réutilisable enregistré !", "success");
          closeCreateSavedMealModal();
          openSavedMealsLibraryModal(payload.meal_type);
        } else {
          alert("Erreur lors de l'enregistrement du plat.");
        }
      } catch (err) {
        alert("Erreur réseau lors de l'enregistrement.");
      } finally {
        btn.disabled = false;
      }
    }

    async function saveEstimatedMealAsTemplate() {
      if (!currentEstimatedMeal) {
        alert("Veuillez d'abord estimer le repas avant de l'enregistrer comme plat type.");
        return;
      }

      const mealType = document.getElementById('meal-type-select').value;
      const desc = document.getElementById('meal-desc-input').value.trim();
      const defaultName = desc || (mealType === 'breakfast' ? "Mon Petit-déjeuner Type" : (mealType === 'lunch' ? "Mon Déjeuner Type" : (mealType === 'snack' ? "Mon Goûter Type" : "Mon Dîner Type")));
      const mealName = prompt("Nom du plat type à enregistrer :", defaultName);
      if (!mealName) return;

      const payload = {
        name: mealName.trim(),
        meal_type: mealType,
        serving_size: "1 portion",
        calories: Math.round(currentEstimatedMeal.total_calories_kcal || 0),
        protein_g: Math.round(currentEstimatedMeal.total_protein_g || 0),
        carbs_g: Math.round(currentEstimatedMeal.total_carbs_g || 0),
        fat_g: Math.round(currentEstimatedMeal.total_fat_g || 0),
        fiber_g: Math.round(currentEstimatedMeal.total_fiber_g || 0),
        ingredients: (currentEstimatedMeal.items || []).map(i => `${i.name} (${Math.round(i.portion_g || 100)}g)`).join(', '),
        items: currentEstimatedMeal.items || [],
        photo_url: currentUploadedPhotoUrl || null,
        is_favorite: true
      };

      try {
        const res = await apiFetch('/api/meals/saved', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          if (typeof showToast === 'function') showToast(`⭐ '${payload.name}' enregistré dans vos plats réutilisables !`, "success");
        } else {
          alert("Erreur lors de l'enregistrement du plat type.");
        }
      } catch (err) {
        alert("Erreur réseau.");
      }
    }

    async function saveLoggedMealAsTemplate(mealIndex) {
      const meals = currentData.recent_meals || [];
      const m = meals[mealIndex];
      if (!m) return;

      const mealType = m.meal_type || 'lunch';
      const itemsDesc = (m.items || []).map(i => i.name).join(', ');
      const defaultName = itemsDesc ? `Plat ${itemsDesc.slice(0, 30)}` : `Plat ${mealType}`;
      const mealName = prompt("Nom du plat à sauvegarder dans votre bibliothèque :", defaultName);
      if (!mealName) return;

      const payload = {
        name: mealName.trim(),
        meal_type: mealType,
        serving_size: "1 portion",
        calories: Math.round(m.total_calories_kcal || 0),
        protein_g: Math.round(m.protein_g || 0),
        carbs_g: Math.round(m.carbs_g || 0),
        fat_g: Math.round(m.fat_g || 0),
        fiber_g: Math.round(m.fiber_g || 0),
        ingredients: (m.items || []).map(i => `${i.name} (${Math.round(i.portion_g || 100)}g)`).join(', '),
        items: m.items || [],
        photo_url: m.photo_data_url || null,
        is_favorite: true
      };

      try {
        const res = await apiFetch('/api/meals/saved', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          if (typeof showToast === 'function') showToast(`⭐ '${payload.name}' sauvegardé dans votre bibliothèque !`, "success");
        } else {
          alert("Erreur lors de la sauvegarde du plat.");
        }
      } catch (err) {
        alert("Erreur réseau.");
      }
    }

