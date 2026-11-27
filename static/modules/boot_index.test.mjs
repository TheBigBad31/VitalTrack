import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const STATIC_DIR = path.resolve(__dirname, '..');
const INDEX_HTML_PATH = path.join(STATIC_DIR, 'index.html');

function extractModuleScripts(html) {
  const regex = /<script\s+[^>]*src="(\/static\/modules\/[^"]+)"[^>]*><\/script>/gi;
  const scripts = [];
  let match;
  while ((match = regex.exec(html)) !== null) {
    const cleanRelPath = match[1].split('?')[0].replace(/^\/static\//, '');
    scripts.push(cleanRelPath);
  }
  return scripts;
}

function createBootContext() {
  const storageMap = new Map();
  const makeStorage = () => ({
    getItem: (k) => (storageMap.has(k) ? storageMap.get(k) : null),
    setItem: (k, v) => storageMap.set(k, String(v)),
    removeItem: (k) => storageMap.delete(k),
    clear: () => storageMap.clear(),
  });

  const noop = () => {};
  const emptyList = [];
  const makeStubElement = () => ({
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    style: {},
    dataset: {},
    innerHTML: '',
    innerText: '',
    textContent: '',
    value: '',
    checked: false,
    addEventListener: noop,
    removeEventListener: noop,
    querySelector: () => null,
    querySelectorAll: () => emptyList,
    getAttribute: () => null,
    setAttribute: noop,
    appendChild: noop,
    remove: noop,
    focus: noop,
    click: noop,
    contains: () => false,
    getClientRects: () => emptyList,
    offsetWidth: 0,
    offsetHeight: 0,
  });

  const documentStub = {
    readyState: 'loading',
    body: makeStubElement(),
    documentElement: makeStubElement(),
    activeElement: null,
    addEventListener: noop,
    removeEventListener: noop,
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => emptyList,
    createElement: () => makeStubElement(),
    dispatchEvent: noop,
  };

  class MutationObserverStub {
    constructor(cb) {
      this._cb = cb;
    }
    observe() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }

  const sandbox = {
    console,
    setTimeout: () => 0,
    clearTimeout: noop,
    setInterval: () => 0,
    clearInterval: noop,
    requestAnimationFrame: noop,
    cancelAnimationFrame: noop,
    URL,
    URLSearchParams,
    Intl,
    Date,
    Math,
    JSON,
    Promise,
    Map,
    Set,
    WeakMap,
    WeakSet,
    RegExp,
    Array,
    Object,
    Number,
    String,
    Boolean,
    Error,
    TypeError,
    ReferenceError,
    encodeURIComponent,
    decodeURIComponent,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    document: documentStub,
    navigator: {
      onLine: true,
      userAgent: 'vitest-boot-runner',
      clipboard: { writeText: async () => {} },
      serviceWorker: { register: async () => ({ scope: '/' }) },
    },
    location: {
      href: 'https://vital-track-one.vercel.app/',
      origin: 'https://vital-track-one.vercel.app',
      pathname: '/',
      search: '',
      hash: '',
      reload: noop,
    },
    history: { replaceState: noop, pushState: noop },
    localStorage: makeStorage(),
    sessionStorage: makeStorage(),
    MutationObserver: MutationObserverStub,
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => '' }),
    alert: noop,
    confirm: () => false,
    prompt: () => null,
    addEventListener: noop,
    removeEventListener: noop,
    dispatchEvent: noop,
    indexedDB: undefined,
  };

  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;

  return vm.createContext(sandbox);
}

describe('index.html sequential module boot (BALI-321)', () => {
  it('loads all /static/modules/*.js scripts in exact HTML order with 0 ReferenceError', () => {
    const html = fs.readFileSync(INDEX_HTML_PATH, 'utf8');
    const scripts = extractModuleScripts(html);

    expect(scripts.length).toBeGreaterThanOrEqual(15);
    expect(scripts.indexOf('modules/boot.js')).toBeLessThan(
      scripts.indexOf('modules/dashboard.js')
    );

    const context = createBootContext();

    for (const relPath of scripts) {
      const absPath = path.join(STATIC_DIR, relPath);
      expect(fs.existsSync(absPath), `Missing script referenced by index.html: ${relPath}`).toBe(true);
      const code = fs.readFileSync(absPath, 'utf8');
      expect(
        () => vm.runInContext(code, context, { filename: relPath }),
        `Boot error while evaluating ${relPath}`
      ).not.toThrow();
    }

    // Verify top-level bindings are initialized (no TDZ left behind from dashboard.js)
    const stateCheck = vm.runInContext(
      `({
        hasFallback: typeof FALLBACK_DASHBOARD_DATA === 'object' && FALLBACK_DASHBOARD_DATA !== null,
        hasCurrentData: typeof currentData === 'object' && currentData !== null,
        hasConfig: typeof CONFIG === 'object',
        hasUnifiedSession: typeof currentUnifiedSession === 'object',
        hasLoadDashboardData: typeof loadDashboardData === 'function',
        hasLoadUnifiedAuthState: typeof loadUnifiedAuthState === 'function',
      })`,
      context
    );

    expect(stateCheck).toEqual({
      hasFallback: true,
      hasCurrentData: true,
      hasConfig: true,
      hasUnifiedSession: true,
      hasLoadDashboardData: true,
      hasLoadUnifiedAuthState: true,
    });

    // Verify critical window-exported handlers across all split modules
    const expectedWindowFns = [
      'apiFetch',
      'switchTab',
      'openProfileModal',
      'closeProfileModal',
      'saveUserProfile',
      'formatRelativeTime',
      'triggerDeviceSync',
      'openAuthModal',
      'closeAuthModal',
      'openConnectWizardModal',
      'closeConnectWizardModal',
      'selectWizardDevice',
      'submitDeviceConnection',
      'generateDeviceToken',
      'toggleTokenVisibility',
      'copyTokenToClipboard',
      'fetchOrInitDeviceToken',
      'testHealthConnectIngestion',
      'renderLiveSyncBanner',
      'triggerSyncFromBanner',
      'handleCatItemTypeChange',
      'handleDishIngredientSelectChange',
      'addIngredientToDish',
      'removeDishIngredient',
      'updateDishIngredientQuantity',
      'openBarcodeScannerModal',
      'closeBarcodeScannerModal',
      'resetBarcodeScannerStep',
      'startCameraBarcodeScanner',
      'stopCameraBarcodeScanner',
      'lookupManualBarcode',
      'lookupBarcode',
      'updateBarcodeLivePortionMacros',
      'addScannedProductToCatalog',
      'addScannedProductToActiveMeal',
      'refreshNutritionWithMetricsSync',
      'quickAddWater',
      'loadHydrationWidget',
      'handleActivityDateChange',
    ];

    for (const fnName of expectedWindowFns) {
      expect(typeof context.window[fnName], `window.${fnName} should be a function`).toBe('function');
    }
  });
});

describe('Service Worker cache sync & v3 purge (BALI-322)', () => {
  it('precaches all local JS scripts referenced by index.html and purges v2 caches on activate', async () => {
    const html = fs.readFileSync(INDEX_HTML_PATH, 'utf8');
    const swPath = path.join(STATIC_DIR, 'sw.js');
    const swCode = fs.readFileSync(swPath, 'utf8');

    const localJsRegex = /<script\s+[^>]*src="(\/static\/[^"]+\.js)(?:\?[^"]*)?"[^>]*><\/script>/gi;
    const htmlJsAssets = [];
    let match;
    while ((match = localJsRegex.exec(html)) !== null) {
      htmlJsAssets.push(match[1]);
    }
    expect(htmlJsAssets.length).toBeGreaterThanOrEqual(20);

    // Every module script tag in index.html uses ?v=1.2.0
    const moduleScriptTagRegex = /<script\s+[^>]*src="(\/static\/modules\/[^"]+)"[^>]*><\/script>/gi;
    while ((match = moduleScriptTagRegex.exec(html)) !== null) {
      expect(match[1]).toMatch(/\?v=1\.2\.0$/);
    }

    const listeners = {};
    const deletedKeys = [];
    const existingKeys = ['vitaltrack-cache-v2', 'vitaltrack-api-v2', 'vitaltrack-cache-v3', 'vitaltrack-api-v3'];
    let claimed = false;

    const swSandbox = {
      URL,
      Response: class ResponseStub {},
      fetch: async () => ({ status: 200, clone: () => ({}) }),
      caches: {
        open: async () => ({ addAll: async () => {}, match: async () => null, put: async () => {} }),
        keys: async () => existingKeys,
        delete: async (k) => {
          deletedKeys.push(k);
          return true;
        },
        match: async () => null,
      },
      clients: {
        claim: async () => {
          claimed = true;
        },
      },
      skipWaiting: async () => {},
      location: { origin: 'https://vital-track-one.vercel.app' },
      addEventListener: (name, fn) => {
        listeners[name] = fn;
      },
    };
    swSandbox.self = swSandbox;

    const swCtx = vm.createContext(swSandbox);
    vm.runInContext(swCode, swCtx, { filename: 'static/sw.js' });

    const swExports = vm.runInContext('({ CACHE_NAME, API_CACHE_NAME, STATIC_ASSETS })', swCtx);
    expect(swExports.CACHE_NAME).toBe('vitaltrack-cache-v3');
    expect(swExports.API_CACHE_NAME).toBe('vitaltrack-api-v3');

    for (const jsAsset of htmlJsAssets) {
      expect(
        swExports.STATIC_ASSETS,
        `Missing ${jsAsset} in STATIC_ASSETS of static/sw.js`
      ).toContain(jsAsset);
    }

    // Trigger activate event and verify v2 caches are deleted while v3 caches are preserved
    let waitPromise = Promise.resolve();
    listeners.activate({
      waitUntil: (p) => {
        waitPromise = p;
      },
    });
    await waitPromise;

    expect(deletedKeys).toEqual(['vitaltrack-cache-v2', 'vitaltrack-api-v2']);
    expect(claimed).toBe(true);

    // auth.js references vitaltrack-api-v3
    const authCode = fs.readFileSync(path.join(STATIC_DIR, 'modules', 'auth.js'), 'utf8');
    expect(authCode).toContain("caches.delete('vitaltrack-api-v3')");
    expect(authCode).not.toContain('vitaltrack-api-v2');
  });
});
