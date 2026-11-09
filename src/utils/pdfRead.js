// Reading a PDF into text, with the pdf.js document opener passed in so every failure can be tested without pdf.js or a browser.
// Every error here is a fixed sentence: nothing from the file (its text, its name, pdf.js's own message) is ever put in its message.
// The library error is kept as `cause` only, which no screen shows.

import { pagesToText } from './pdfTextLayout.js'

export const MAX_PDF_BYTES = 10 * 1024 * 1024
/** A resume or a LinkedIn profile is a few pages; a much longer file is the wrong document and would be slow to read. */
export const MAX_PDF_PAGES = 40

export const isPdfFile = (file) => file?.type === 'application/pdf' || /\.pdf$/i.test(String(file?.name || ''))

/**
 * @param {File} file
 * @param {{ open: (data: ArrayBuffer) => Promise<{ numPages: number, getPage: (n: number) => Promise<{ getTextContent: () => Promise<{ items: object[] }> }> }> }} deps
 * @returns {Promise<string>} the text, laid out by pdfTextLayout
 */
export async function readPdfText(file, { open }) {
  if (!file) throw new Error('No file provided.')
  if (!isPdfFile(file)) throw new Error('Please upload a PDF file.')
  if (file.size > MAX_PDF_BYTES) throw new Error('File is too large. Maximum size is 10 MB.')

  let pdf
  try {
    pdf = await open(await file.arrayBuffer())
  } catch (error) {
    if (error?.name === 'PasswordException') throw new Error('This PDF is password protected. Save an unprotected copy, or paste the text.', { cause: error })
    throw new Error('Unable to read this PDF. The file may be damaged.', { cause: error })
  }
  if (pdf.numPages > MAX_PDF_PAGES) throw new Error(`This PDF has ${pdf.numPages} pages. A resume or profile is much shorter; check that it is the right file, or paste the text.`)

  const pages = []
  try {
    for (let i = 1; i <= pdf.numPages; i += 1) {
      const page = await pdf.getPage(i)
      const content = await page.getTextContent()
      pages.push(content.items)
    }
  } catch (error) {
    throw new Error('Unable to read the pages of this PDF. The file may be damaged.', { cause: error })
  }

  const text = pagesToText(pages)
  if (!text) throw new Error('No text could be extracted from this PDF. It may be image-only or scanned; there is no OCR, so paste the text instead.')
  return text
}
