import fs from 'node:fs'
import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'

describe('the import result says what Undo can do', () => {
  let UndoNote
  let UNDO_NOTE
  beforeAll(async () => {
    globalThis.React = React
    ;({ UndoNote, UNDO_NOTE } = await import('../../src/components/import/ImportResult.jsx'))
  })

  it('names the limit (until the page is reloaded) and the lasting copy (the server backup, data/backups, newest 10)', () => {
    const html = renderToStaticMarkup(createElement(UndoNote))
    expect(html).toMatch(/Undo works only until you reload this page/)
    expect(html).toMatch(/backup on the server \(data\/backups, the newest 10 import backups are kept\)/)
    expect(UNDO_NOTE).toMatch(/lasting copy/)
  })

  it('is shown exactly when the Undo button is (one condition for both)', () => {
    const source = fs.readFileSync('src/components/import/ImportResult.jsx', 'utf8')
    expect(source).toMatch(/const canUndo = !undone && !result\.duplicate && Boolean\(snapshotStore\.load\(\)\)/)
    expect(source).toMatch(/\{canUndo && <UndoNote \/>\}/)
    expect(source).toMatch(/\{canUndo && <Button variant="ghost" onClick=\{undo\}>Undo this import<\/Button>\}/)
  })
})
