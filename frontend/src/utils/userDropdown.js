const logoutItem = {
  name1: 'logout',
  label: 'Log out',
  icon: 'log-out',
  is_standard: 1,
}

export function buildUserDropdownItems(items, mapItem) {
  const visibleItems = (items || []).filter((item) => !item.hidden)
  const groups = [{ group: 'Dropdown Items', hideLabel: true, items: [] }]

  visibleItems.forEach((item) => {
    if (item.type === 'Separator') {
      groups.push({ group: '', hideLabel: true, items: [] })
      return
    }
    groups[groups.length - 1].items.push(mapItem(item))
  })

  const hasLogout = visibleItems.some(
    (item) => item.is_standard && item.name1 === 'logout',
  )
  if (!hasLogout) {
    if (groups[groups.length - 1].items.length) {
      groups.push({ group: '', hideLabel: true, items: [] })
    }
    groups[groups.length - 1].items.push(mapItem(logoutItem))
  }

  return groups
}
