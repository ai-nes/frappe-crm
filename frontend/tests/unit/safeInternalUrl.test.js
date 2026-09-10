import { describe, expect, it } from 'vitest'
import { safeInternalUrl } from '../../src/utils/safeInternalUrl'

describe('safeInternalUrl', () => {
  it('allows same-origin and HTTPS provider links', () => {
    expect(safeInternalUrl('/crm/settings')).toContain('/crm/settings')
    expect(safeInternalUrl('https://status.example.com/runbook')).toBe(
      'https://status.example.com/runbook',
    )
  })

  it('rejects executable and protocol-relative links', () => {
    expect(safeInternalUrl('javascript:alert(1)')).toBeNull()
    expect(safeInternalUrl('data:text/html,payload')).toBeNull()
    expect(safeInternalUrl('//evil.example/runbook')).toBeNull()
  })
})
