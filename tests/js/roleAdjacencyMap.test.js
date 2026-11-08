import { describe, expect, it } from 'vitest'
import { expandRoleVariants } from '../../src/modules/intelligence/roleAdjacencyMap.js'

describe('expandRoleVariants', () => {
  it('keeps the roles it was given', () => {
    expect(expandRoleVariants(['Senior Technical Product Manager'])).toContain('Senior Technical Product Manager')
  })

  it('never adds the opening words of a role: "Senior Product" matches a Senior Product Designer', () => {
    const variants = expandRoleVariants(['Senior Product Manager', 'Technical Product Manager', 'Senior Technical Product Manager', 'Platform Product Manager'])
    for (const fragment of ['Senior Product', 'Technical Product', 'Senior Technical', 'Platform Product']) expect(variants).not.toContain(fragment)
  })
})
