import { describe, it, expect } from 'vitest'
import fs from 'node:fs'

describe('panel type scale', () => {
  it('steps every size in the panel up by exactly one', () => {
    const css = fs.readFileSync('src/index.css', 'utf8')
    const block = css.slice(css.indexOf('.panel-text-up'))
    const get = (name) => new RegExp(`--text-${name}:\\s*([\\d.]+)rem`).exec(block)?.[1]
    // Tailwind's defaults: xs .75, sm .875, base 1, lg 1.125, xl 1.25, 2xl 1.5
    expect([get('xs'), get('sm'), get('base'), get('lg'), get('xl')]).toEqual(['0.875', '1', '1.125', '1.25', '1.5'])
    const drawer = fs.readFileSync('src/components/jobs/JobDetailDrawer.jsx', 'utf8')
    expect(drawer).toContain('<aside className="panel-text-up ')
  })
})
