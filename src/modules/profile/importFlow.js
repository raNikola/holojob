// The two steps around the import review screen, with their effects passed in so they can be tested
// without a browser: reading a source into a draft (writes nothing) and saving a reviewed draft.

import { applyImportDraft, draftParsedData, resolveChoices } from './importDraft.js'

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
 * Save a reviewed draft. For a PDF the file is stored first, best effort, as an upload always was: when
 * the API is unreachable or refuses it, the CV entry is kept without a stored file.
 * @returns {Promise<{ stored: boolean }>}
 */
export async function saveReviewedDraft({ draft, choices, file, upload, updateProfile }) {
  let stored = null
  if (file) {
    try {
      const id = await upload(file)
      if (id) stored = { id, filePath: `profile/cvs/${id}.pdf` }
    } catch { /* the entry is kept without a stored file */ }
  }
  updateProfile((prev) => applyImportDraft(prev, draft, resolveChoices(prev, draft, choices), stored ? { file: stored } : {}))
  return { stored: Boolean(stored) }
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
