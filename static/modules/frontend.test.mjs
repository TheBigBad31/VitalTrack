import { describe, it, expect } from 'vitest';

// Pure helper tests for critical frontend calculations (macro goals, offline queue, XSS escaping)

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function computeMacroTargets({ weightKg = 75, calories = 2200, proteinPerKg = 1.8, fatRatio = 0.25 } = {}) {
  const proteinG = Math.round(weightKg * proteinPerKg);
  const proteinKcal = proteinG * 4;
  const fatKcal = Math.round(calories * fatRatio);
  const fatG = Math.round(fatKcal / 9);
  const carbsKcal = Math.max(0, calories - proteinKcal - fatKcal);
  const carbsG = Math.round(carbsKcal / 4);
  return { calories, proteinG, fatG, carbsG };
}

function enqueueOfflineMutation(queue, entry) {
  const next = Array.isArray(queue) ? [...queue] : [];
  next.push({ ...entry, queuedAt: entry.queuedAt || Date.now() });
  return next;
}

describe('Frontend critical calculations', () => {
  it('escapes XSS payloads in HTML interpolations', () => {
    const payload = `<script>alert("xss")</script>'&`;
    expect(escapeHtml(payload)).toBe('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;&#39;&amp;');
    expect(escapeHtml(null)).toBe('');
  });

  it('computes macro targets from weight and calorie goal', () => {
    const targets = computeMacroTargets({ weightKg: 80, calories: 2400, proteinPerKg: 2.0, fatRatio: 0.25 });
    expect(targets.proteinG).toBe(160);
    expect(targets.fatG).toBe(67);
    expect(targets.carbsG).toBe(290);
  });

  it('queues offline mutations preserving order', () => {
    let q = [];
    q = enqueueOfflineMutation(q, { url: '/api/meals', method: 'POST', queuedAt: 100 });
    q = enqueueOfflineMutation(q, { url: '/api/weight', method: 'POST', queuedAt: 200 });
    expect(q).toHaveLength(2);
    expect(q[0].url).toBe('/api/meals');
    expect(q[1].url).toBe('/api/weight');
  });
});
