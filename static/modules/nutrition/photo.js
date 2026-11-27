// static/modules/nutrition/photo.js - Scanner code-barres & capture photo

// ===================================================================
// SCANNER CODE-BARRES OPENFOODFACTS & SYNC DYNAMIQUE (BALI-295)
// ===================================================================

let barcodeVideoStream = null;
let barcodeScannerAnimationId = null;
let currentScannedProduct = null;
let barcodeTargetSlot = 'lunch';

function openBarcodeScannerModal(targetSlot) {
  barcodeTargetSlot = targetSlot || currentActiveMealSlot || 'lunch';
  currentScannedProduct = null;

  const modal = document.getElementById('modal-barcode-scanner');
  if (modal) modal.classList.remove('hidden');

  resetBarcodeScannerStep();

  const slotLabels = {
    breakfast: 'au petit-déjeuner',
    lunch: 'au déjeuner',
    snack: 'au goûter',
    dinner: 'au dîner'
  };
  const btnLabel = document.getElementById('btn-barcode-add-meal-label');
  if (btnLabel) {
    btnLabel.textContent = `Ajouter ${slotLabels[barcodeTargetSlot] || 'au repas'}`;
  }

  if ('BarcodeDetector' in window) {
    startCameraBarcodeScanner();
  }
  if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
}

function closeBarcodeScannerModal() {
  stopCameraBarcodeScanner();
  const modal = document.getElementById('modal-barcode-scanner');
  if (modal) modal.classList.add('hidden');
}

function resetBarcodeScannerStep() {
  currentScannedProduct = null;
  const stepScan = document.getElementById('barcode-step-scan');
  const stepResult = document.getElementById('barcode-step-result');
  const statusEl = document.getElementById('barcode-scan-status');
  const manualInput = document.getElementById('barcode-manual-input');

  if (stepScan) stepScan.classList.remove('hidden');
  if (stepResult) stepResult.classList.add('hidden');
  if (statusEl) statusEl.textContent = '';
  if (manualInput) manualInput.value = '';
}

async function startCameraBarcodeScanner() {
  const video = document.getElementById('barcode-video-preview');
  const placeholder = document.getElementById('barcode-camera-placeholder');
  const overlay = document.getElementById('barcode-scan-overlay');
  const statusEl = document.getElementById('barcode-scan-status');

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (statusEl) statusEl.textContent = 'Caméra non supportée sur ce navigateur. Saisie manuelle requise.';
    return;
  }

  try {
    stopCameraBarcodeScanner();
    if (statusEl) statusEl.textContent = 'Activation de la caméra...';
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
    });
    barcodeVideoStream = stream;
    if (video) {
      video.srcObject = stream;
      video.classList.remove('hidden');
      await video.play();
    }
    if (placeholder) placeholder.classList.add('hidden');
    if (overlay) overlay.classList.remove('hidden');
    if (statusEl) statusEl.textContent = 'Visez le code-barres avec votre caméra.';

    if ('BarcodeDetector' in window) {
      const barcodeDetector = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e'] });
      const detectFrame = async () => {
        if (!barcodeVideoStream || video.paused || video.ended) return;
        try {
          const barcodes = await barcodeDetector.detect(video);
          if (barcodes && barcodes.length > 0) {
            const rawVal = barcodes[0].rawValue;
            if (rawVal) {
              if (statusEl) statusEl.textContent = `Code détecté : ${rawVal}`;
              stopCameraBarcodeScanner();
              lookupBarcode(rawVal);
              return;
            }
          }
        } catch (e) {
          console.warn('[barcode] frame detect error:', e);
        }
        barcodeScannerAnimationId = requestAnimationFrame(detectFrame);
      };
      barcodeScannerAnimationId = requestAnimationFrame(detectFrame);
    }
  } catch (err) {
    console.error('[barcode] camera error:', err);
    if (statusEl) statusEl.textContent = 'Accès caméra refusé ou indisponible. Utilisez la saisie manuelle.';
    if (video) video.classList.add('hidden');
    if (placeholder) placeholder.classList.remove('hidden');
    if (overlay) overlay.classList.add('hidden');
  }
}

function stopCameraBarcodeScanner() {
  if (barcodeScannerAnimationId) {
    cancelAnimationFrame(barcodeScannerAnimationId);
    barcodeScannerAnimationId = null;
  }
  if (barcodeVideoStream) {
    barcodeVideoStream.getTracks().forEach(t => t.stop());
    barcodeVideoStream = null;
  }
  const video = document.getElementById('barcode-video-preview');
  if (video) {
    video.srcObject = null;
    video.classList.add('hidden');
  }
  const placeholder = document.getElementById('barcode-camera-placeholder');
  if (placeholder) placeholder.classList.remove('hidden');
  const overlay = document.getElementById('barcode-scan-overlay');
  if (overlay) overlay.classList.add('hidden');
}

async function lookupManualBarcode() {
  const input = document.getElementById('barcode-manual-input');
  const code = (input && input.value || '').trim();
  if (!code) {
    if (typeof showToast === 'function') showToast('Veuillez saisir un code-barres.', 'warning');
    return;
  }
  stopCameraBarcodeScanner();
  await lookupBarcode(code);
}

async function lookupBarcode(barcode) {
  const statusEl = document.getElementById('barcode-scan-status');
  if (statusEl) statusEl.textContent = `Recherche OpenFoodFacts (${barcode})...`;

  try {
    const res = await fetch(`/api/meals/barcode/${encodeURIComponent(barcode)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Produit non trouvé sur OpenFoodFacts');
    }
    const product = await res.json();
    currentScannedProduct = product;
    displayScannedProduct(product);
  } catch (err) {
    console.error('[barcode] lookup error:', err);
    if (statusEl) statusEl.textContent = `Erreur : ${err.message}`;
    if (typeof showToast === 'function') showToast(err.message, 'error');
  }
}

function displayScannedProduct(product) {
  const stepScan = document.getElementById('barcode-step-scan');
  const stepResult = document.getElementById('barcode-step-result');
  if (stepScan) stepScan.classList.add('hidden');
  if (stepResult) stepResult.classList.remove('hidden');

  const nameEl = document.getElementById('barcode-result-name');
  if (nameEl) nameEl.textContent = product.name || 'Produit sans nom';

  const brandEl = document.getElementById('barcode-result-brand');
  if (brandEl) brandEl.textContent = product.brand || 'Marque inconnue';

  const codeEl = document.getElementById('barcode-result-code');
  if (codeEl) codeEl.textContent = `Code : ${product.barcode || ''}`;

  const nutriEl = document.getElementById('barcode-result-nutriscore');
  if (nutriEl) {
    const grade = (product.nutriscore || '?').toUpperCase();
    nutriEl.textContent = `Nutri-Score ${grade}`;
    const colors = {
      A: 'bg-emerald-600 text-white',
      B: 'bg-lime-600 text-white',
      C: 'bg-yellow-500 text-black',
      D: 'bg-orange-500 text-white',
      E: 'bg-rose-600 text-white'
    };
    nutriEl.className = `px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-wider ${colors[grade] || 'bg-slate-700 text-slate-300'}`;
  }

  const imgEl = document.getElementById('barcode-result-photo');
  const imgPh = document.getElementById('barcode-result-photo-placeholder');
  if (imgEl && imgPh) {
    if (product.photo_url) {
      imgEl.src = product.photo_url;
      imgEl.classList.remove('hidden');
      imgPh.classList.add('hidden');
    } else {
      imgEl.classList.add('hidden');
      imgPh.classList.remove('hidden');
    }
  }

  const cals100 = product.calories_100g || 0;
  const p100 = product.protein_100g || 0;
  const g100 = product.carbs_100g || 0;
  const l100 = product.fat_100g || 0;
  const f100 = product.fiber_100g || 0;

  const calsEl = document.getElementById('barcode-result-cals');
  if (calsEl) calsEl.textContent = `${Math.round(cals100)} kcal`;

  const macrosEl = document.getElementById('barcode-result-macros');
  if (macrosEl) {
    macrosEl.textContent = `P: ${Math.round(p100*10)/10}g | G: ${Math.round(g100*10)/10}g | L: ${Math.round(l100*10)/10}g | Fibres: ${Math.round(f100*10)/10}g`;
  }

  const qtyInput = document.getElementById('barcode-portion-qty');
  if (qtyInput) qtyInput.value = 100;
  updateBarcodeLivePortionMacros();

  if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
}

function updateBarcodeLivePortionMacros() {
  if (!currentScannedProduct) return;
  const qtyInput = document.getElementById('barcode-portion-qty');
  const qty = parseFloat(qtyInput && qtyInput.value) || 0;
  const ratio = qty / 100.0;

  const cals = Math.round((currentScannedProduct.calories_100g || 0) * ratio);
  const liveEl = document.getElementById('barcode-live-portion-cals');
  if (liveEl) liveEl.textContent = `${cals} kcal pour ${qty}g`;
}

async function addScannedProductToCatalog() {
  if (!currentScannedProduct) return;
  try {
    const payload = {
      name: currentScannedProduct.name,
      brand: currentScannedProduct.brand || null,
      barcode: currentScannedProduct.barcode || null,
      nutriscore: currentScannedProduct.nutriscore || null,
      calories_per_100g: currentScannedProduct.calories_100g || 0,
      protein_per_100g: currentScannedProduct.protein_100g || 0,
      carbs_per_100g: currentScannedProduct.carbs_100g || 0,
      fat_per_100g: currentScannedProduct.fat_100g || 0,
      fiber_per_100g: currentScannedProduct.fiber_100g || 0,
      category: 'other',
      item_type: 'food',
      default_portion_g: 100,
      default_unit: 'g',
      photo_url: currentScannedProduct.photo_url || null
    };

    const res = await fetch('/api/catalog/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Impossible d'enregistrer au catalogue");
    }

    const created = await res.json();
    if (typeof invalidateCatalogCache === 'function') invalidateCatalogCache();
    if (typeof loadCatalogItems === 'function') loadCatalogItems();
    if (typeof showToast === 'function') showToast(`'${created.name}' sauvegardé dans le catalogue !`, 'success');
    return created;
  } catch (err) {
    console.error('[barcode] add to catalog error:', err);
    if (typeof showToast === 'function') showToast(err.message, 'error');
    return null;
  }
}

async function addScannedProductToActiveMeal() {
  if (!currentScannedProduct) return;
  const qtyInput = document.getElementById('barcode-portion-qty');
  const qty = parseFloat(qtyInput && qtyInput.value);
  if (!qty || qty <= 0) {
    if (typeof showToast === 'function') showToast('Veuillez saisir une portion valide.', 'warning');
    return;
  }

  // 1. Sauvegarder d'abord dans le catalogue si ce n'est pas déjà fait
  let catItem = await addScannedProductToCatalog();

  // 2. Ajouter l'aliment au repas sélectionné
  const slot = barcodeTargetSlot || currentActiveMealSlot || 'lunch';
  const targetDate = currentJournalDate || new Date().toISOString().slice(0, 10);

  const payload = {
    date: targetDate,
    name: currentScannedProduct.name,
    quantity: qty,
    unit: 'g',
    calories: Math.round(((currentScannedProduct.calories_100g || 0) * qty) / 100.0),
    protein_g: Math.round(((currentScannedProduct.protein_100g || 0) * qty) / 10.0) / 10.0,
    carbs_g: Math.round(((currentScannedProduct.carbs_100g || 0) * qty) / 10.0) / 10.0,
    fat_g: Math.round(((currentScannedProduct.fat_100g || 0) * qty) / 10.0) / 10.0,
    fiber_g: Math.round(((currentScannedProduct.fiber_100g || 0) * qty) / 10.0) / 10.0,
    barcode: currentScannedProduct.barcode || null,
    nutriscore: currentScannedProduct.nutriscore || null,
    food_item_id: catItem ? catItem.id : null
  };

  try {
    const res = await fetch(`/api/meals/journal/${slot}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Erreur lors de l'ajout au repas");
    }

    closeBarcodeScannerModal();
    if (typeof showToast === 'function') {
      showToast(`'${currentScannedProduct.name}' (${qty}g) ajouté à votre repas !`, 'success');
    }
    if (typeof loadMealsJournal === 'function') {
      await loadMealsJournal(targetDate);
    }
  } catch (err) {
    console.error('[barcode] add to meal error:', err);
    if (typeof showToast === 'function') showToast(err.message, 'error');
  }
}

window.openBarcodeScannerModal = openBarcodeScannerModal;
window.closeBarcodeScannerModal = closeBarcodeScannerModal;
window.resetBarcodeScannerStep = resetBarcodeScannerStep;
window.startCameraBarcodeScanner = startCameraBarcodeScanner;
window.stopCameraBarcodeScanner = stopCameraBarcodeScanner;
window.lookupManualBarcode = lookupManualBarcode;
window.lookupBarcode = lookupBarcode;
window.updateBarcodeLivePortionMacros = updateBarcodeLivePortionMacros;
window.addScannedProductToCatalog = addScannedProductToCatalog;
window.addScannedProductToActiveMeal = addScannedProductToActiveMeal;


