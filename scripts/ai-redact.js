/**
 * The central redaction step for the browser / Node AI features (scripts/run-ai.js).
 *
 * Nothing that identifies the owner or a recruiter may reach a provider (DECISIONS.md
 * principle 14). Every outgoing context passes through here before the prompt is built
 * and before the budget gate is asked. It fails closed: when it cannot run, or when a
 * final check still finds an identifier, run-ai.js refuses the call.
 *
 * What is removed:
 *   - the owner's name, e-mail, phone and links (from the profile on disk and from the
 *     hints the browser sends in context.redactionHints, which are removed from the
 *     context and never sent on);
 *   - recruiter / contact names, e-mails, phones and LinkedIn links (same hints);
 *   - every e-mail address in any text, the company's included (documented rule: the
 *     model never needs one);
 *   - phone numbers that look like phone numbers (a leading + or 0, or digit groups
 *     joined by spaces, dots, dashes or brackets); salary ranges, dates, decimals and
 *     long plain ids are left alone;
 *   - links to profile sites (LinkedIn, GitHub, GitLab, Bitbucket, Behance, Dribbble,
 *     X / Twitter, Facebook, Instagram, Xing) and the owner's own listed links.
 * Other URLs (a company's site in the job text) stay: company intelligence needs the company.
 * Same rules as the Python twin python/cv_analysis/redact.py (plus the phone refinements above); keep them in step.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { knownContactIdentity } from './application-store.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const PROFILE_PATH = path.join(ROOT, 'data/profile/candidate-profile.json')

export class RedactionError extends Error {}

const EMAIL_RE = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g
const SOCIAL_HOSTS = 'linkedin|github|gitlab|bitbucket|behance|dribbble|twitter|facebook|instagram|xing'
const SOCIAL_RE = new RegExp(`(?:https?:\\/\\/)?(?:[\\w-]+\\.)*(?:(?:${SOCIAL_HOSTS})\\.com|x\\.com|lnkd\\.in)\\b\\/?[^\\s"'<>]*`, 'gi')
const PHONE_RE = /\+?\(?\d[\d\s().\-/]{6,}\d/g
const FOLD_MAP = { đ: 'dj', Đ: 'Dj', ø: 'o', Ø: 'O', ł: 'l', Ł: 'L' }

const emptyIdentity = () => ({ names: [], emails: [], phones: [], links: [] })
const strings = (v, max = 200) => (Array.isArray(v) ? v : [v]).filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim().slice(0, 500)).slice(0, max)

let identitySource = readOwnerIdentity
let contactSource = () => knownContactIdentity(ROOT)

/** Tests replace the application-store reader; pass nothing to restore it. */
export function setContactSource(fn) {
  contactSource = fn || (() => knownContactIdentity(ROOT))
}

/** Tests replace the profile reader; pass nothing to restore it. */
export function setIdentitySource(fn) {
  identitySource = fn || readOwnerIdentity
}

/** The owner's identifiers from data/profile/candidate-profile.json. Missing file = none; unreadable file throws. */
export function readOwnerIdentity(file = PROFILE_PATH) {
  if (!fs.existsSync(file)) return emptyIdentity()
  let profile
  try {
    profile = JSON.parse(fs.readFileSync(file, 'utf-8'))
  } catch {
    throw new RedactionError(`profile mirror unreadable (${path.basename(file)}): cannot tell what to redact`)
  }
  const basic = profile?.basicProfile || {}
  const links = [...strings(profile?.resume?.parsedData?.links), ...strings(profile?.repositories?.githubLinks)]
  for (const [key, value] of Object.entries(basic)) {
    if (/link|url|linkedin|github|website|portfolio|site/i.test(key)) links.push(...strings(value))
  }
  return {
    names: strings(basic.fullName),
    emails: strings(basic.email),
    phones: strings(basic.phone),
    links,
  }
}

function sanitizeHints(hints) {
  const clean = (group) => ({
    names: strings(group?.names), emails: strings(group?.emails), phones: strings(group?.phones), links: strings(group?.links),
  })
  return { owner: clean(hints?.owner), contacts: clean(hints?.contacts) }
}

// --- folding for accent-insensitive name matching ---------------------------------

function foldChar(ch) {
  return (FOLD_MAP[ch] ?? ch).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

function foldedWithMap(text) {
  let out = ''
  const index = []
  for (let i = 0; i < text.length; i += 1) {
    const f = foldChar(text[i])
    out += f
    for (let k = 0; k < f.length; k += 1) index.push(i)
  }
  return { out, index }
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function nameSpans(text, names) {
  const { out, index } = foldedWithMap(text)
  const phrases = new Set()
  for (const name of names) {
    const folded = foldedWithMap(name).out.trim()
    if (folded.length >= 3) phrases.add(folded)
    for (const word of folded.match(/[\p{L}\p{N}_]+/gu) || []) if (word.length >= 3) phrases.add(word)
  }
  const spans = []
  for (const phrase of [...phrases].sort((a, b) => b.length - a.length)) {
    const re = new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRe(phrase)}(?![\\p{L}\\p{N}_])`, 'gu')
    for (const m of out.matchAll(re)) spans.push([index[m.index], index[m.index + m[0].length - 1] + 1])
  }
  return spans
}

function replaceSpans(text, spans, placeholder) {
  // Overlapping hits (the full name and its words) become one span, else replacing the later one corrupts the text.
  const merged = []
  for (const [start, end] of [...spans].sort((a, b) => a[0] - b[0] || b[1] - a[1])) {
    const last = merged[merged.length - 1]
    if (last && start < last[1]) last[1] = Math.max(last[1], end)
    else merged.push([start, end])
  }
  let result = text
  for (const [start, end] of merged.reverse()) {
    result = result.slice(0, start) + placeholder + result.slice(end)
  }
  return result
}

// --- patterns --------------------------------------------------------------------

function isPhone(match) {
  const digits = match.replace(/\D/g, '')
  if (digits.length < 8 || digits.length > 15) return false
  const m = match.trim()
  if (/^\d+\.\d+$/.test(m)) return false // a decimal
  if (/^\d{4}-\d{2}-\d{2}$/.test(m)) return false // an ISO date
  if (/^\d{4,}\s*[-–]\s*\d{4,}$/.test(m)) return false // 2019-2024, 80000-120000
  if (/^\d{1,2}[./]\d{1,2}[./]\d{4}$/.test(m) || /^\d{4}[./]\d{1,2}[./]\d{1,2}$/.test(m)) return false // 29.10.2026
  if (!/^[+(]/.test(m) && /\s[-–]\s/.test(m)) return false // "100 000 - 120 000"
  return /^[+(]/.test(m) || m.startsWith('0') || /[\s().\-/]/.test(m)
}

function linkPattern(link) {
  const bare = link.replace(/^https?:\/\//i, '').replace(/^www\./i, '').replace(/\/+$/, '')
  return bare.length >= 4 ? new RegExp(`(?:https?:\\/\\/)?(?:www\\.)?${escapeRe(bare)}\\/?[^\\s"'<>]*`, 'gi') : null
}

function phonePattern(phone) {
  let digits = phone.replace(/\D/g, '').replace(/^00/, '')
  if (digits.length < 7) return null
  const parts = digits.split('').map(escapeRe)
  const body = parts.join('[\\s().\\-/]*')
  // The same number written with + / 00 in front, or with a national 0 instead of the country code.
  return new RegExp(`(?:\\+|00)?[\\s(]*${body}`, 'g')
}

function applyPattern(text, re, placeholder, accept = () => true) {
  return text.replace(re, (m) => (accept(m) ? placeholder : m))
}

/** One string, redacted. `ids` is { owner, contacts } of identity groups. */
export function redactText(text, ids) {
  let out = String(text ?? '')
  const all = [ids.owner, ids.contacts]
  out = applyPattern(out, EMAIL_RE, '[EMAIL]')
  for (const email of all.flatMap((g) => g.emails)) out = applyPattern(out, new RegExp(escapeRe(email), 'gi'), '[EMAIL]')
  for (const link of [...new Set(all.flatMap((g) => g.links))].sort((a, b) => b.length - a.length)) {
    const re = linkPattern(link)
    if (re) out = applyPattern(out, re, '[LINK]')
  }
  out = applyPattern(out, SOCIAL_RE, '[LINK]')
  for (const phone of all.flatMap((g) => g.phones)) {
    const re = phonePattern(phone)
    if (re) out = applyPattern(out, re, '[PHONE]')
  }
  out = applyPattern(out, PHONE_RE, '[PHONE]', isPhone)
  out = replaceSpans(out, nameSpans(out, ids.owner.names), '[NAME]')
  out = replaceSpans(out, nameSpans(out, ids.contacts.names), '[CONTACT]')
  return out
}

/**
 * What is still in `text` that must not be: the kinds found, never the values. `names: false` leaves the name
 * check to the caller, who then checks the string values of the data (see `findStructuredLeaks`).
 */
export function findLeaks(text, ids, { names = true } = {}) {
  const found = new Set()
  const all = [ids.owner, ids.contacts]
  if (new RegExp(EMAIL_RE.source).test(text)) found.add('email')
  if (new RegExp(SOCIAL_RE.source, 'i').test(text)) found.add('profile link')
  for (const link of all.flatMap((g) => g.links)) {
    const re = linkPattern(link)
    if (re && new RegExp(re.source, 'i').test(text)) found.add('owner link')
  }
  for (const phone of all.flatMap((g) => g.phones)) {
    const re = phonePattern(phone)
    if (re && new RegExp(re.source).test(text)) found.add('phone')
  }
  if ([...text.matchAll(PHONE_RE)].some((m) => isPhone(m[0]))) found.add('phone')
  if (names && nameSpans(text, [...ids.owner.names, ...ids.contacts.names]).length) found.add('name')
  return [...found]
}

function stringValues(value, out = []) {
  walk(value, (s) => { out.push(s); return s })
  return out
}

/**
 * `findLeaks` for data that is sent as JSON. Emails, links and phones are looked for in the whole serialized text. A name
 * is looked for in the string values only: an object key or the fixed wording around the data is written by the code, so
 * a stored contact named "Name" must not refuse every prompt because the key `"name"` is in it. A name inside any value,
 * also in the middle of a sentence, is still found.
 */
export function findStructuredLeaks(value, ids) {
  const found = new Set(findLeaks(JSON.stringify(value), ids, { names: false }))
  if (nameInValues(value, ids)) found.add('name')
  return [...found]
}

/** True when a stored name is in a string value of `value`. Keys are not looked at. */
function nameInValues(value, ids) {
  const names = [...ids.owner.names, ...ids.contacts.names]
  return names.length > 0 && stringValues(value).some((s) => nameSpans(s, names).length)
}

function walk(value, fn) {
  if (typeof value === 'string') return fn(value)
  if (Array.isArray(value)) return value.map((v) => walk(v, fn))
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, walk(v, fn)]))
  return value
}

/** Contacts recorded in the application store. Fails closed: an unreadable store means nothing can be trusted. */
function storedContacts() {
  try {
    const found = contactSource() || emptyIdentity()
    return { names: strings(found.names), emails: strings(found.emails), phones: strings(found.phones), links: strings(found.links) }
  } catch (e) {
    throw new RedactionError(`application store unreadable: cannot tell which contacts to redact (${e.constructor.name})`)
  }
}

const mergeIdentity = (a, b) => ({
  names: [...a.names, ...b.names], emails: [...a.emails, ...b.emails], phones: [...a.phones, ...b.phones], links: [...a.links, ...b.links],
})

/**
 * The context a provider may see, and the identifiers used. Throws RedactionError.
 * Strings are redacted value by value, so JSON structure and ids are never mangled.
 */
export function redactContext(context) {
  try {
    const { redactionHints, ...rest } = context || {}
    const hints = sanitizeHints(redactionHints)
    const disk = identitySource() || emptyIdentity()
    const ids = {
      owner: {
        names: [...hints.owner.names, ...strings(disk.names)], emails: [...hints.owner.emails, ...strings(disk.emails)],
        phones: [...hints.owner.phones, ...strings(disk.phones)], links: [...hints.owner.links, ...strings(disk.links)],
      },
      contacts: mergeIdentity(hints.contacts, storedContacts()),
    }
    return { context: walk(rest, (s) => redactText(s, ids)), ids }
  } catch (e) {
    if (e instanceof RedactionError) throw e
    throw new RedactionError(`redaction failed: ${e.constructor.name}`)
  }
}

/** Last check on the finished prompt. Throws RedactionError naming the kinds, never the values. */
export function assertClean(messages, ids, { context } = {}) {
  const prompt = messages.map((m) => String(m.content ?? '')).join('\n')
  // With the context given, a name is checked against its values; the prompt around it is the code's own text.
  const leaks = context === undefined ? findLeaks(prompt, ids) : [...findLeaks(prompt, ids, { names: false }), ...(nameInValues(context, ids) ? ['name'] : [])]
  if (leaks.length) throw new RedactionError(`redaction check found ${leaks.join(', ')} left in the prompt`)
}
