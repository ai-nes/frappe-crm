import { describe, expect, it } from 'vitest'
import { buildUserDropdownItems } from '../../src/utils/userDropdown'

const names = (groups) =>
  groups.flatMap((group) => group.items.map((item) => item.name1))

describe('buildUserDropdownItems', () => {
  it('keeps logout available when settings are unreadable', () => {
    expect(names(buildUserDropdownItems(undefined, (item) => item))).toEqual([
      'logout',
    ])
  })

  it('does not duplicate the configured logout item', () => {
    const groups = buildUserDropdownItems(
      [
        { name1: 'about', is_standard: 1 },
        { name1: 'logout', is_standard: 1 },
      ],
      (item) => item,
    )

    expect(names(groups)).toEqual(['about', 'logout'])
  })

  it('preserves configured item order and separator boundaries', () => {
    const groups = buildUserDropdownItems(
      [
        { name1: 'about', is_standard: 1 },
        { type: 'Separator' },
        { name1: 'custom-report', is_standard: 0 },
        { type: 'Separator' },
      ],
      (item) => item,
    )

    expect(
      groups.map((group) => group.items.map((item) => item.name1)),
    ).toEqual([['about'], ['custom-report'], ['logout']])
  })
})
