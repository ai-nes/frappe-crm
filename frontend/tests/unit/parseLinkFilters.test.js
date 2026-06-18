import {
  getContextualLinkFilters,
  getDependentFieldsToClear,
  getProvinceScopedLinkFilters,
  parseLinkFilters,
} from '@/utils/fieldTransforms'

describe('parseLinkFilters', () => {
  it('returns null for falsy input', () => {
    expect(parseLinkFilters(null)).toBeNull()
    expect(parseLinkFilters(undefined)).toBeNull()
    expect(parseLinkFilters('')).toBeNull()
    expect(parseLinkFilters(0)).toBeNull()
  })

  it('parses a valid JSON string', () => {
    expect(parseLinkFilters('{"company":"ACME"}')).toEqual({ company: 'ACME' })
  })

  it('returns object as-is if already an object', () => {
    const obj = { company: 'ACME', enabled: 1 }
    expect(parseLinkFilters(obj)).toBe(obj)
  })

  it('returns null for invalid JSON string', () => {
    expect(parseLinkFilters('not json')).toBeNull()
  })

  it('handles array JSON', () => {
    expect(parseLinkFilters('[1,2]')).toEqual([1, 2])
  })
})

describe('getProvinceScopedLinkFilters', () => {
  it('filters CRM Ward by selected province', () => {
    expect(
      getProvinceScopedLinkFilters(
        { fieldtype: 'Link', options: 'CRM Ward' },
        { province: 'Ha Noi' },
      ),
    ).toEqual({ province: 'Ha Noi' })
  })

  it('filters CRM High School by selected province name', () => {
    expect(
      getProvinceScopedLinkFilters(
        { fieldtype: 'Link', options: 'CRM High School' },
        { province: 'Ha Noi' },
      ),
    ).toEqual({ province_name: 'Ha Noi' })
  })

  it('preserves existing filters when adding province scope', () => {
    expect(
      getProvinceScopedLinkFilters(
        { fieldtype: 'Link', options: 'CRM Ward' },
        { province: 'Ha Noi' },
        { enabled: 1 },
      ),
    ).toEqual({ enabled: 1, province: 'Ha Noi' })
  })

  it('returns base filters when no province scope applies', () => {
    const baseFilters = { enabled: 1 }
    expect(
      getProvinceScopedLinkFilters(
        { fieldtype: 'Link', options: 'CRM Province' },
        { province: 'Ha Noi' },
        baseFilters,
      ),
    ).toBe(baseFilters)
  })
})

describe('getContextualLinkFilters', () => {
  it('filters CRM Campus by selected province', () => {
    expect(
      getContextualLinkFilters(
        { fieldtype: 'Link', options: 'CRM Campus' },
        { province: 'Ha Noi' },
      ),
    ).toEqual({ province: 'Ha Noi' })
  })

  it('filters CRM Campaign by selected branch', () => {
    expect(
      getContextualLinkFilters(
        { fieldtype: 'Link', options: 'CRM Campaign' },
        { branch: 'Main Campus' },
      ),
    ).toEqual({ campus: 'Main Campus' })
  })

  it('filters CRM Department by selected campus', () => {
    expect(
      getContextualLinkFilters(
        { fieldtype: 'Link', options: 'CRM Department' },
        { campus: 'Main Campus' },
      ),
    ).toEqual({ campus: 'Main Campus' })
  })

  it('filters CRM Staff by campus and department context', () => {
    expect(
      getContextualLinkFilters(
        { fieldtype: 'Link', options: 'CRM Staff' },
        { branch: 'Main Campus', department: 'Admissions' },
      ),
    ).toEqual({ campus: 'Main Campus', department: 'Admissions' })
  })

  it('filters CRM Event by selected campaign and province', () => {
    expect(
      getContextualLinkFilters(
        { fieldtype: 'Link', options: 'CRM Event' },
        { crm_campaign: 'Open Day', province: 'Ha Noi' },
      ),
    ).toEqual({ crm_campaign: 'Open Day', province: 'Ha Noi' })
  })
})

describe('getDependentFieldsToClear', () => {
  it('clears only dependent fields that exist on the current doc', () => {
    expect(
      getDependentFieldsToClear('province', {
        province: 'Ha Noi',
        ward: 'Old Ward',
        high_school: 'Old School',
        crm_campaign: 'Campaign',
      }),
    ).toEqual(['ward', 'high_school'])
  })

  it('clears campaign when branch changes', () => {
    expect(
      getDependentFieldsToClear('branch', {
        branch: 'Main Campus',
        crm_campaign: 'Old Campaign',
      }),
    ).toEqual(['crm_campaign'])
  })
})
