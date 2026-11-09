// The step before the import review screen, with its effects passed in so it can be tested without a browser: reading a
// source into a draft (writes nothing). Saving a reviewed draft is importApply.js.

import { draftParsedData } from './importDraft.js'

export const PDF_SOURCES = ['resume_pdf', 'linkedin_pdf']

/**
 * Read a PDF into an import draft. The text is taken in the browser and parsed by the same server
 * parser as pasted text; nothing is saved and the file is not uploaded.
 * @param {File} file
 * @param {'resume_pdf'|'linkedin_pdf'} source
 * @param {{ extract: (file: File) => Promise<string>, parse: (source: string, text: string) => Promise<object> }} deps
 */
export async function readPdfDraft(file, source, { extract, parse }) {
  if (!PDF_SOURCES.includes(source)) throw new Error('This source is not a PDF.')
  const text = await extract(file)
  const draft = await parse(source, text)
  return { ...draft, fileName: file.name || '' }
}

/**
 * The parsed data for a CV added from My CVs: the server parser's reading, as the import wizard makes it.
 * When the parser cannot be reached or refuses the text, `fallback` (the older in-browser reader) is used and
 * the result says so, so the caller can tell the user.
 * @returns {Promise<{ parsedData: object, usedFallback: boolean }>}
 */
export async function cvEntryParsedData(rawText, { parse, fallback }) {
  try {
    return { parsedData: draftParsedData(await parse('resume_pdf', rawText)), usedFallback: false }
  } catch {
    return { parsedData: fallback(rawText), usedFallback: true }
  }
}
