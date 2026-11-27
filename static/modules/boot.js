// static/modules/boot.js - Initialisation PWA, thème et démarrage

    const FALLBACK_DASHBOARD_DATA = {
      summary: {
        current_weight_kg: null,
        weight_trend_7d_kg: null,
        weight_7d_variation_kg: null,
        body_fat_pct: null,
        muscle_mass_kg: null,
        water_pct: null,
        bmi: null,
        target_weight_kg: 77.0,
        steps: 0,
        steps_target: 10000,
        calories_intake_kcal: 0.0,
        calories_burned_kcal: 0.0,
        bmr_kcal: 0.0,
        net_energy_balance_kcal: 0.0,
        target_calories_intake: 0.0,
        energy_status: "maintenance",
        recommendation: "Aucune donnée enregistrée aujourd'hui. Ajoutez votre première pesée, un repas ou synchronisez vos appareils connectés.",
        macros: {
          protein_g: 0.0,
          protein_pct: 0.0,
          carbs_g: 0.0,
          carbs_pct: 0.0,
          fat_g: 0.0,
          fat_pct: 0.0,
          fiber_g: 0.0
        },
        resting_hr_bpm: null,
        hrv_ms: null,
        sleep_score: null
      },
      weights_history: [],
      activities_history: [],
      recent_meals: [],
      devices: []
    };

    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js', { scope: '/' })
          .then((reg) => {
            console.log('[PWA] Service Worker actif, scope:', reg.scope);
          })
          .catch((err) => {
            console.warn('[PWA] Service Worker échec:', err);
          });
      });
    }

    // Accessibilité : Piège de focus et touche Escape sur les modales
    (function initModalFocusTrap() {
      let activeModal = null;
      let previousActiveElement = null;

      function getFocusableElements(container) {
        return Array.from(container.querySelectorAll(
          'button:not([disabled]):not([aria-hidden="true"]), ' +
          '[href]:not([disabled]):not([aria-hidden="true"]), ' +
          'input:not([disabled]):not([type="hidden"]):not([aria-hidden="true"]), ' +
          'select:not([disabled]):not([aria-hidden="true"]), ' +
          'textarea:not([disabled]):not([aria-hidden="true"]), ' +
          '[tabindex]:not([tabindex="-1"]):not([disabled])'
        )).filter(el => el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      }

      document.addEventListener('keydown', (e) => {
        if (!activeModal) return;
        if (e.key === 'Escape') {
          const closeBtn = activeModal.querySelector('button[onclick*="close"], button[aria-label*="Fermer"]');
          if (closeBtn) closeBtn.click();
          return;
        }
        if (e.key !== 'Tab') return;

        const focusables = getFocusableElements(activeModal);
        if (focusables.length === 0) {
          e.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first || !activeModal.contains(document.activeElement)) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last || !activeModal.contains(document.activeElement)) {
            e.preventDefault();
            first.focus();
          }
        }
      });

      const observer = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
          if (m.type === 'attributes' && m.attributeName === 'class') {
            const target = m.target;
            if (target.getAttribute('role') === 'dialog') {
              const isHidden = target.classList.contains('hidden');
              if (!isHidden) {
                previousActiveElement = document.activeElement;
                activeModal = target;
                const focusables = getFocusableElements(target);
                if (focusables.length > 0) {
                  setTimeout(() => focusables[0].focus(), 50);
                }
              } else if (activeModal === target) {
                activeModal = null;
                if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
                  previousActiveElement.focus();
                }
              }
            }
          }
        });
      });

      window.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[role="dialog"]').forEach(dialog => {
          observer.observe(dialog, { attributes: true, attributeFilter: ['class'] });
        });
      });
    })();

    function toggleMobileMoreMenu() {
      const menu = document.getElementById('mobile-more-menu');
      if (menu) menu.classList.toggle('hidden');
    }
    window.toggleMobileMoreMenu = toggleMobileMoreMenu;

    // Global loading bar control
    window.showGlobalLoading = function(show) {
      const loadingBar = document.getElementById('global-loading-bar');
      if (!loadingBar) return;
      if (show) {
        loadingBar.classList.add('active');
      } else {
        loadingBar.classList.remove('active');
      }
    };

    // Intercept native fetch calls to show/hide loading bar
    const originalFetch = window.fetch;
    window.fetch = async function(url, options = {}) {
      window.showGlobalLoading(true);
      try {
        const response = await originalFetch(url, options);
        return response;
      } finally {
        setTimeout(() => {
          const otherLoading = document.body && document.body.classList.contains('loading');
          if (!otherLoading) {
            window.showGlobalLoading(false);
          }
        }, 200);
      }
    };
