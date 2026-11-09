import * as pdfjsLib from 'pdfjs-dist'
import { readPdfText } from './pdfRead'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

/** The text of a PDF, read in the browser with pdf.js (the limits and the error sentences are in pdfRead.js). */
export function extractTextFromPdf(file) {
  return readPdfText(file, { open: (data) => pdfjsLib.getDocument({ data }).promise })
}
