import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import Input from '../../src/components/ui/Input'
import SelectField from '../../src/components/ui/SelectField'
import MultiSelectField from '../../src/components/ui/MultiSelectField'
import RoleCombobox from '../../src/components/ui/RoleCombobox'
import { RequiredNote } from '../../src/components/ui/RequiredMark'
import { REQUIRED_PROFILE_FIELDS, profileFieldErrors, validateStep } from '../../src/utils/validators'

const mark = '<span aria-hidden="true" class="ml-0.5 text-red-500">*</span>'
const render = (el) => renderToStaticMarkup(el)

describe('required marks', () => {
  it('shows the asterisk and aria-required on a required field only', () => {
    const required = render(h(Input, { label: 'Full name', required: true, value: '', onChange() {} }))
    const optional = render(h(Input, { label: 'Phone', value: '', onChange() {} }))
    expect(required).toContain(mark)
    expect(required).toContain('aria-required="true"')
    expect(optional).not.toContain('*')
    expect(optional).not.toContain('aria-required')
  })

  it('marks selects, multi-selects and the role combobox', () => {
    expect(render(h(SelectField, { label: 'Q', id: 'q', required: true, value: '', onChange() {} }))).toContain(mark)
    expect(render(h(SelectField, { label: 'Q', id: 'q', value: '', onChange() {} }))).not.toContain('*')
    expect(render(h(MultiSelectField, { label: 'Q', required: true, options: ['a'], onChange() {} }))).toContain(mark)
    const combo = render(h(RoleCombobox, { label: 'Target roles', required: true, selected: [], onChange() {} }))
    expect(combo).toContain(mark)
    expect(combo).toContain('aria-required="true"')
  })

  it('prints the "* Required" note', () => {
    expect(render(h(RequiredNote))).toContain('Required')
  })
})

describe('error state', () => {
  it('stays plain until an error is passed, then turns red and invalid', () => {
    const calm = render(h(Input, { label: 'Email', required: true, value: '', onChange() {} }))
    expect(calm).not.toContain('aria-invalid')
    expect(calm).not.toContain('border-red-400')
    const bad = render(h(Input, { label: 'Email', required: true, error: 'A valid email address is required.', value: '', onChange() {} }))
    expect(bad).toContain('aria-invalid="true"')
    expect(bad).toContain('border-red-400')
    expect(bad).toContain('A valid email address is required.')
  })

  it('flags every empty required profile field after a failed Continue', () => {
    const errors = profileFieldErrors({ fullName: '', email: '', currentRole: '', experienceYears: '', targetRoles: [] })
    expect(Object.keys(errors).sort()).toEqual([...REQUIRED_PROFILE_FIELDS].sort())
  })

  it('reports no error for a complete profile, and the phone only when malformed', () => {
    const ok = { fullName: 'A B', email: 'a@b.co', currentRole: 'PM', experienceYears: '5', targetRoles: ['PM'] }
    expect(profileFieldErrors(ok)).toEqual({})
    expect(Object.keys(profileFieldErrors({ ...ok, phone: 'abc' }))).toEqual(['phone'])
    expect(REQUIRED_PROFILE_FIELDS).not.toContain('phone')
  })

  it('keeps validateStep(2) in step with the per-field errors', () => {
    const bp = { fullName: '', email: 'x', currentRole: '', experienceYears: '', targetRoles: [], phone: 'abc' }
    const result = validateStep(2, { basicProfile: bp })
    expect(result.errors).toEqual(Object.values(profileFieldErrors(bp)))
    expect(result.valid).toBe(false)
  })
})
