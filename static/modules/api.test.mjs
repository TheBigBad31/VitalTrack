/** @vitest */
import { describe, it, expect } from 'vitest'
import { escapeHtml, sanitizeUrl } from './api.js'

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