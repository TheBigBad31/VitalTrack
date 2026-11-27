/** @vitest */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  apiFetch,
  escapeHtml,
  sanitizeUrl,
  JWT_STORAGE_KEY,
  REFRESH_TOKEN_STORAGE_KEY,
  GOOGLE_SESSION_KEY
} from './api.js'

describe('escapeHtml', () => {
  it('should escape HTML special characters', () => {
    const input = '<div>Test "quote" & more</div>'
    expect(escapeHtml(input)).toBe('&lt;div&gt;Test &quot;quote&quot; &amp; more&lt;/div&gt;')
  })

  it('should return empty string for null', () => {
    expect(escapeHtml(null)).toBe('')
  })

  it('should return empty string for undefined', () => {
    expect(escapeHtml(undefined)).toBe('')
  })

  it('should return unchanged string without HTML chars', () => {
    expect(escapeHtml('plain text')).toBe('plain text')
  })

  it('should handle empty string', () => {
    expect(escapeHtml('')).toBe('')
  })

  it('should escape HTML tags', () => {
    expect(escapeHtml('<test>')).toBe('&lt;test&gt;')
  })
})

describe('sanitizeUrl', () => {
  it('should allow valid http URLs', () => {
    expect(sanitizeUrl('http://example.com')).toBe('http://example.com')
  })

  it('should allow valid https URLs', () => {
    expect(sanitizeUrl('https://example.com')).toBe('https://example.com')
  })

  it('should allow data: URLs', () => {
    expect(sanitizeUrl('data:image/png;base64,abc123')).toBe('data:image/png;base64,abc123')
  })

  it('should allow relative paths', () => {
    expect(sanitizeUrl('/relative/path')).toBe('/relative/path')
  })

  it('should reject javascript: URLs and return empty string', () => {
    expect(sanitizeUrl('javascript:alert(1)')).toBe('')
  })

  it('should reject data with bad MIME type and return empty string', () => {
    expect(sanitizeUrl('data:text/html,<script>alert(1)</script>')).toBe('')
  })

  it('should return empty string for null', () => {
    expect(sanitizeUrl(null)).toBe('')
  })

  it('should return empty string for undefined', () => {
    expect(sanitizeUrl(undefined)).toBe('')
  })

  it('should reject mailto: URLs', () => {
    expect(sanitizeUrl('mailto:test@example.com')).toBe('')
  })

  it('should reject about: URLs', () => {
    expect(sanitizeUrl('about:blank')).toBe('')
  })
})

describe('apiFetch auto-refresh on 401', () => {
  beforeEach(() => {
    localStorage.clear()
    window.showGlobalLoading = vi.fn()
    window.openAuthModal = vi.fn()
    globalThis.openAuthModal = window.openAuthModal
    vi.restoreAllMocks()
  })

  it('refreshes access token on 401 and retries request without opening auth modal', async () => {
    localStorage.setItem(JWT_STORAGE_KEY, 'expired-jwt')
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, 'valid-refresh-1')

    const fetchMock = vi.fn(async (url, opts) => {
      if (url === '/api/auth/refresh') {
        expect(JSON.parse(opts.body)).toEqual({ refresh_token: 'valid-refresh-1' })
        return new Response(
          JSON.stringify({ access_token: 'fresh-jwt-2', refresh_token: 'valid-refresh-2' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      }
      if (opts.headers.Authorization === 'Bearer expired-jwt') {
        return new Response(JSON.stringify({ detail: 'expired' }), { status: 401 })
      }
      expect(opts.headers.Authorization).toBe('Bearer fresh-jwt-2')
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const res = await apiFetch('/api/dashboard')
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })
    expect(localStorage.getItem(JWT_STORAGE_KEY)).toBe('fresh-jwt-2')
    expect(localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)).toBe('valid-refresh-2')
    expect(window.openAuthModal).not.toHaveBeenCalled()
  })

  it('deduplicates concurrent refresh calls (single-flight)', async () => {
    localStorage.setItem(JWT_STORAGE_KEY, 'expired-jwt')
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, 'valid-refresh-sf')

    let refreshCalls = 0
    const fetchMock = vi.fn(async (url, opts) => {
      if (url === '/api/auth/refresh') {
        refreshCalls += 1
        return new Response(
          JSON.stringify({ access_token: 'fresh-sf-jwt', refresh_token: 'valid-refresh-sf-2' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      }
      if (opts.headers.Authorization === 'Bearer expired-jwt') {
        return new Response(null, { status: 401 })
      }
      return new Response(JSON.stringify({ url }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const [r1, r2] = await Promise.all([apiFetch('/api/dashboard'), apiFetch('/api/weights')])
    expect(r1.status).toBe(200)
    expect(r2.status).toBe(200)
    expect(refreshCalls).toBe(1)
    expect(window.openAuthModal).not.toHaveBeenCalled()
  })

  it('clears tokens and opens auth modal when refresh fails', async () => {
    localStorage.setItem(JWT_STORAGE_KEY, 'expired-jwt')
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, 'revoked-refresh')
    localStorage.setItem(GOOGLE_SESSION_KEY, '{"is_authenticated":true}')

    const fetchMock = vi.fn(async (url) => {
      if (url === '/api/auth/refresh') {
        return new Response(JSON.stringify({ detail: 'revoked' }), { status: 401 })
      }
      return new Response(null, { status: 401 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const res = await apiFetch('/api/dashboard')
    expect(res.status).toBe(401)
    expect(localStorage.getItem(JWT_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(GOOGLE_SESSION_KEY)).toBeNull()
    expect(window.openAuthModal).toHaveBeenCalledTimes(1)
  })
})
