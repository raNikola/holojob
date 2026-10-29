import { describe, expect, it } from 'vitest'
import { NAV_ITEMS, VIEWS } from '../../src/modules/appNavigation'
import { NAV_GROUPS, resolveNavGroups } from '../../src/modules/navGroups'

describe('NAV_GROUPS', () => {
  const grouped = NAV_GROUPS.flatMap((group) => group.items)

  it('lists every navigation view exactly once', () => {
    expect([...grouped].sort()).toEqual(NAV_ITEMS.map((item) => item.id).sort())
    expect(new Set(grouped).size).toBe(grouped.length)
  })

  it('keeps the approved order and titles', () => {
    expect(NAV_GROUPS.map((group) => [group.title, group.items])).toEqual([
      [null, [VIEWS.DASHBOARD]],
      ['Work', [VIEWS.JOBS, VIEWS.APPLICATIONS, VIEWS.OUTREACH]],
      ['Candidate', [VIEWS.PROFILE, VIEWS.INTELLIGENCE, VIEWS.CVS, VIEWS.CAREER_STRATEGY]],
      ['Tools', [VIEWS.RESUMES, VIEWS.AI_COMMAND]],
      ['System', [VIEWS.QUALITY]],
      [null, [VIEWS.SETTINGS]],
    ])
  })

  it('pins only the Settings group and has unique group ids', () => {
    expect(NAV_GROUPS.filter((group) => group.pinned).map((group) => group.id)).toEqual(['settings'])
    expect(new Set(NAV_GROUPS.map((group) => group.id)).size).toBe(NAV_GROUPS.length)
  })

  it('resolves to the NAV_ITEMS entries', () => {
    const resolved = resolveNavGroups().flatMap((group) => group.items)
    expect(resolved).toHaveLength(NAV_ITEMS.length)
    for (const item of resolved) expect(item).toBe(NAV_ITEMS.find((entry) => entry.id === item.id))
  })
})
