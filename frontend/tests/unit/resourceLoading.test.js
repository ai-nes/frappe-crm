import { describe, expect, it } from 'vitest'
import { getResourceViewState } from '@/utils/resourceLoading'

describe('getResourceViewState', () => {
  it('keeps the initial state loading before the first response', () => {
    expect(
      getResourceViewState({ data: null, fetched: false, loading: false }),
    ).toBe('loading')
  })

  it('shows an error when the first request fails without data', () => {
    expect(
      getResourceViewState({
        data: null,
        fetched: false,
        loading: false,
        error: new Error('network'),
      }),
    ).toBe('error')
  })

  it('treats an empty response as ready content', () => {
    expect(getResourceViewState({ data: [], fetched: true })).toBe('ready')
  })

  it('keeps stale data visible while a refresh is running', () => {
    expect(
      getResourceViewState({
        data: [{ name: 'activity-1' }],
        fetched: true,
        loading: true,
      }),
    ).toBe('ready')
  })

  it('allows callers to mark a request as intentionally not applicable', () => {
    expect(
      getResourceViewState({ data: null, fetched: false }, { hasData: true }),
    ).toBe('ready')
  })
})
