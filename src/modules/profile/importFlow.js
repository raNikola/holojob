// The step before the import review screen, with its effects passed in so it can be tested without a browser: reading a
// source into a draft (writes nothing). Saving a reviewed draft is importApply.js.

import { draftParsedData } from './importDraft.js'

export const PDF_SOURCES = ['resume_pdf', 'linkedin_pdf']

export const MAX_TEXT_FILE_BYTES = 200 * 1024

/** The file types the "Upload a file" step accepts, and the import source each one is read as. */
export const FILE_KINDS = [
  { source: 'resume_pdf', extensions: ['pdf'], mime: ['application/pdf'] },
  { source: 'text_file', extensions: ['txt', 'md', 'markdown'], mime: ['text/plain', 'text/markdown'] },
]

/** The `accept` attribute of the file input. */
export const ACCEPT_ANY_FILE = FILE_KINDS.flatMap((k) => [...k.mime, ...k.extensions.map((e) => `.${e}`)]).join(',')

/** The import source for a file, by its extension first, then its type; null when the type is not supported. */
export function sourceForFile(file) {
  const extension = String(file?.name || '').split('.').pop().toLowerCase()
  const type = String(file?.type || '').toLowerCase()
  return (FILE_KINDS.find((k) => k.extensions.includes(extension)) || FILE_KINDS.find((k) => k.mime.includes(type)))?.source ?? null
}

/**
 * Read a TXT or Markdown file into an import draft: the text is read in the browser and parsed by the same server parser as pasted text
 * (the server removes Markdown markup); nothing is saved. A file that is not UTF-8 text is refused before anything is sent.
 * @param {File} file
 * @param {{ parse: (source: string, text: string) => Promise<object>, read?: (file: File) => Promise<string> }} deps
 */
export async function readTextFileDraft(file, { parse, read = (f) => f.text() }) {
  if (sourceForFile(file) !== 'text_file') throw new Error('This is not a text file.')
  if (file.size > MAX_TEXT_FILE_BYTES) throw new Error('The file is too large. The limit for a text file is 200 KB.')
  const text = await read(file)
  const replaced = (text.match(/\uFFFD/g) || []).length
  if (text.includes('\u0000') || replaced > Math.max(3, text.length * 0.02)) throw new Error('This file is not UTF-8 text. Save it as UTF-8 and try again, or paste the text.')
  const draft = await parse('text_file', text)
  return { ...draft, fileName: file.name || '' }
}

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
