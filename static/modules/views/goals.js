// static/modules/views/goals.js - Vue Objectifs & Profils Métaboliques

    function selectGoalProfile(profileId, persist = true) {

      if (!GOAL_PROFILES[profileId]) return;

      activeGoalProfileId = profileId;

      const p = GOAL_PROFILES[profileId];



      // Mise à jour de l'affichage du header d'objectif

      const titleEl = document.getElementById('active-goal-title');

      const descEl = document.getElementById('active-goal-desc');

      if (titleEl) titleEl.innerText = p.title;

      if (descEl) descEl.innerText = p.desc;



      // Mise à jour des boutons

      ['weight_loss', 'maintenance', 'recomposition'].forEach(id => {

        const btn = document.getElementById(`btn-goal-${id}`);

        if (!btn) return;

        if (id === profileId) {

          btn.className = "goal-btn text-left p-3.5 rounded-xl border-2 border-brand-500 bg-brand-500/10 transition-all flex flex-col justify-between space-y-2";

          const statusSpan = btn.querySelector('.text-brand-400, .text-slate-500');

          if (statusSpan) {

            statusSpan.className = "text-brand-400 font-medium";

            statusSpan.innerText = "Actif ✓";

          }

        } else {

          btn.className = "goal-btn text-left p-3.5 rounded-xl border border-[#1F2A3C] bg-[#0B0F17] hover:border-slate-600 transition-all flex flex-col justify-between space-y-2";

          const statusSpan = btn.querySelector('.text-brand-400, .text-slate-500');

          if (statusSpan) {

            statusSpan.className = "text-slate-500";

            statusSpan.innerText = "Choisir";

          }

        }

      });



      // Recalcul de la cible calorique et des jauges

      let newTargetCalories = 2100;

      if (currentData && currentData.summary) {

        const burned = currentData.summary.calories_burned_kcal || 2280;

        newTargetCalories = Math.max(1200, Math.round(burned + p.delta));

        currentData.summary.target_calories_intake = newTargetCalories;

        currentData.summary.steps_target = p.steps;

        currentData.summary.recommendation = p.recommendation;

        if (currentData.profile) {
          currentData.profile.goal_profile_id = profileId;
          currentData.profile.target_calories_intake = newTargetCalories;
          currentData.profile.target_steps = p.steps;
          currentData.profile.protein_target_per_kg = p.protein_per_kg;
        }

        renderSummaryView();

      }

      const isReadOnly = Boolean(window.currentReadOnlyFriend && window.currentReadOnlyFriend.active);
      if (persist && !isReadOnly && typeof apiFetch === 'function') {
        apiFetch('/api/profile', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            goal_profile_id: profileId,
            target_calories_intake: newTargetCalories,
            target_steps: p.steps,
            protein_target_per_kg: p.protein_per_kg
          })
        }).then(res => {
          if (res && res.ok) {
            if (typeof invalidateJournalCache === 'function') invalidateJournalCache();
            if (typeof showToast === 'function') showToast(`Profil objectif « ${p.title} » enregistré`, 'success');
          }
        }).catch(err => console.warn('[Goals] Persistance profil objectif échouée:', err));
      }

    }



    // Initialisation au chargement de la page

    document.addEventListener("DOMContentLoaded", () => {

      if (window.lucide && lucide.createIcons) { try { lucide.createIcons(); } catch (e) {} }

      initDates();

      loadDashboardData();

      loadUnifiedAuthState();

      if (typeof loadFriendsData === 'function') {

        loadFriendsData();

      }

      initGoalWeightInput();

    });



    // Gestion du poids cible dans l'onglet Objectifs

    function initGoalWeightInput() {

      const targetWeightInput = document.getElementById('goal-target-weight-input');

      const targetWeightValue = document.getElementById('goal-target-weight-value');

      if (!targetWeightInput) return;



      let saving = false;



      const saveTargetWeight = async (weightKg) => {

        if (saving) return;

        saving = true;

        try {

          const res = await apiFetch('/api/profile', {

            method: 'PUT',

            body: JSON.stringify({ target_weight_kg: weightKg })

          });

          if (res.ok) {

            const profile = await res.json();

            // Mettre à jour l'affichage

            if (targetWeightValue) targetWeightValue.innerText = `${profile.target_weight_kg} kg`;

            // Re-render le graphique avec la nouvelle cible

            if (typeof renderWeightSummaryChart === 'function') {

              renderWeightSummaryChart();

            }

            if (typeof renderWeightView === 'function') {

              renderWeightView();

            }

          }

        } catch (err) {

          console.warn("Erreur mise à jour poids cible :", err);

        } finally {

          saving = false;

        }

      };



      // Écoute Entrée ou départ de la champ

      targetWeightInput.addEventListener('keydown', (e) => {

        if (e.key === 'Enter') {

          e.preventDefault();

          const weight = parseFloat(targetWeightInput.value) || 77;

          if (weight >= 30 && weight <= 300) {

            saveTargetWeight(weight);

          }

        }

      });



      // Pérsistance sur perte de focus (delay pour éviter les sauvegardes involontaires)

      let focusLossTimeout = null;

      targetWeightInput.addEventListener('blur', () => {

        clearTimeout(focusLossTimeout);

        focusLossTimeout = setTimeout(() => {

          const weight = parseFloat(targetWeightInput.value) || 77;

          if (weight >= 30 && weight <= 300) {

            saveTargetWeight(weight);

          }

        }, 500);

      });



      // Mise à jour visuelle en temps réel de la valeur affichée

      targetWeightInput.addEventListener('input', () => {

        const weight = parseFloat(targetWeightInput.value) || 77;

        if (targetWeightValue) targetWeightValue.innerText = `${weight} kg`;

      });

    }






function renderGoalsView() {
  if (currentData && currentData.profile) {
    if (currentData.profile.goal_profile_id && GOAL_PROFILES[currentData.profile.goal_profile_id]) {
      activeGoalProfileId = currentData.profile.goal_profile_id;
    }
    if (currentData.profile.target_weight_kg) {
      const targetWeight = Number(currentData.profile.target_weight_kg);
      const inputEl = document.getElementById('goal-target-weight-input');
      const valEl = document.getElementById('goal-target-weight-value');
      if (inputEl) inputEl.value = targetWeight.toFixed(1);
      if (valEl) valEl.textContent = `${targetWeight.toFixed(1)} kg`;
    }
  }
  if (typeof activeGoalProfileId !== 'undefined') {
    selectGoalProfile(activeGoalProfileId, false);
  }
}

window.renderGoalsView = renderGoalsView;


window.selectGoalProfile = selectGoalProfile;
window.initGoalWeightInput = initGoalWeightInput;
