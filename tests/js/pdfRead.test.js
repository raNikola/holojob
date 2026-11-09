import { describe, expect, it } from 'vitest'
import { MAX_PDF_BYTES, MAX_PDF_PAGES, isPdfFile, readPdfText } from '../../src/utils/pdfRead.js'

const H = 10
const item = (y, str, x = 10) => ({ str, width: str.length * 5, height: H, transform: [H, 0, 0, H, x, y] })
const pdfOf = (pages) => ({ numPages: pages.length, getPage: async (n) => ({ getTextContent: async () => ({ items: pages[n - 1] }) }) })
const file = (over = {}) => ({ name: 'cv.pdf', type: 'application/pdf', size: 1000, arrayBuffer: async () => new ArrayBuffer(8), ...over })
const read = (f, open) => readPdfText(f, { open })
const CANARY = 'CANARY-Zorbel-77'

describe('readPdfText', () => {
  it('lays out the text of every page', async () => {
    const text = await read(file(), async () => pdfOf([[item(100, 'Jane Sample'), item(80, 'Product Manager')], [item(100, 'Page two')]]))
    expect(text).toContain('Jane Sample')
    expect(text).toContain('Page two')
  })

  it('accepts a PDF whose type is empty when the name ends in .pdf (some systems send no type)', async () => {
    expect(isPdfFile({ name: 'CV.PDF', type: '' })).toBe(true)
    expect(isPdfFile({ name: 'cv.txt', type: '' })).toBe(false)
    await expect(read(file({ type: '' }), async () => pdfOf([[item(100, 'x y')]]))).resolves.toContain('x y')
  })

  it.each([
    ['no file', null, /No file/],
    ['a non-PDF', file({ name: 'cv.txt', type: 'text/plain' }), /upload a PDF/],
    ['an oversized file', file({ size: MAX_PDF_BYTES + 1 }), /too large/],
  ])('refuses %s before opening it', async (_n, f, message) => {
    let opened = false
    await expect(read(f, async () => { opened = true })).rejects.toThrow(message)
    expect(opened).toBe(false)
  })

  it('tells a password-protected PDF from a damaged one, in fixed sentences', async () => {
    const locked = Object.assign(new Error(`needs a password ${CANARY}`), { name: 'PasswordException' })
    await expect(read(file(), async () => { throw locked })).rejects.toThrow('password protected')
    await expect(read(file({ arrayBuffer: async () => { throw new Error(CANARY) } }), async () => pdfOf([]))).rejects.toThrow('may be damaged')
    await expect(read(file(), async () => { throw new Error(`Invalid PDF structure ${CANARY}`) })).rejects.toThrow('may be damaged')
  })

  it('refuses a PDF with too many pages before reading any of them', async () => {
    let touched = false
    const long = { numPages: MAX_PDF_PAGES + 1, getPage: async () => { touched = true } }
    await expect(read(file(), async () => long)).rejects.toThrow(`${MAX_PDF_PAGES + 1} pages`)
    expect(touched).toBe(false)
  })

  it('a page that cannot be read is a fixed sentence, not the library error', async () => {
    const broken = { numPages: 2, getPage: async (n) => { if (n === 2) throw new Error(`bad page ${CANARY}`); return { getTextContent: async () => ({ items: [item(100, 'ok')] }) } } }
    await expect(read(file(), async () => broken)).rejects.toThrow('Unable to read the pages')
  })

  it('an image-only (scanned) PDF says so and says there is no OCR', async () => {
    await expect(read(file(), async () => pdfOf([[], []]))).rejects.toThrow(/image-only or scanned.*no OCR/)
  })

  it('no error sentence carries anything from the file, its name or the library message', async () => {
    const messages = []
    const named = file({ name: `${CANARY}.pdf` })
    for (const open of [async () => { throw new Error(CANARY) }, async () => { throw Object.assign(new Error(CANARY), { name: 'PasswordException' }) }, async () => ({ numPages: 999 }), async () => pdfOf([[]])]) {
      try { await read(named, open) } catch (e) { messages.push(e.message) }
    }
    expect(messages).toHaveLength(4)
    expect(messages.join(' ')).not.toContain('CANARY')
  })
})
