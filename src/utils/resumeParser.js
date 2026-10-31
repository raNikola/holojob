import * as pdfjsLib from 'pdfjs-dist'
import { pagesToText } from './pdfTextLayout'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

const MAX_FILE_SIZE = 10 * 1024 * 1024

export async function extractTextFromPdf(file) {
  if (!file) throw new Error('No file provided.')
  if (file.type !== 'application/pdf') throw new Error('Please upload a PDF file.')
  if (file.size > MAX_FILE_SIZE) throw new Error('File is too large. Maximum size is 10 MB.')

  let pdf
  try {
    const arrayBuffer = await file.arrayBuffer()
    pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise
  } catch {
    throw new Error('Unable to read this PDF. The file may be corrupted or password-protected.')
  }

  const pages = []
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i)
    const content = await page.getTextContent()
    pages.push(content.items)
  }

  const rawText = pagesToText(pages)
  if (!rawText) throw new Error('No text could be extracted from this PDF. It may be image-only or scanned.')
  return rawText
}
