/**
 * What the server's redaction step (scripts/ai-redact.js) must remove from a prompt: the owner's
 * identifiers and every recruiter / contact the browser knows. Sent beside the context as
 * `redactionHints`; the server strips them before the prompt is built, so they never reach a provider.
 */

const text = (v) => (typeof v === 'string' && v.trim() ? [v.trim()] : [])

export function ownerHints(profile) {
  const basic = profile?.basicProfile || {}
  const links = [...(profile?.resume?.parsedData?.links || []), ...(profile?.repositories?.githubLinks || [])]
  for (const [key, value] of Object.entries(basic)) {
    if (/link|url|linkedin|github|website|portfolio|site/i.test(key)) links.push(...(Array.isArray(value) ? value : [value]))
  }
  return {
    names: text(basic.fullName),
    emails: text(basic.email),
    phones: text(basic.phone),
    links: links.flatMap(text),
  }
}

function contactParts(contact) {
  return {
    names: text(contact?.name),
    emails: text(contact?.email),
    phones: text(contact?.phone),
    links: [...text(contact?.linkedinUrl), ...text(contact?.linkedin)],
  }
}

export function contactHints(jobs = [], extraContact = null) {
  const parts = []
  for (const job of jobs) {
    const t = job?.applicationTracking
    if (t) parts.push(contactParts({ name: t.recruiterName, email: t.recruiterEmail, linkedin: t.recruiterLinkedIn }))
    for (const c of job?.outreach?.contacts || []) parts.push(contactParts(c))
  }
  if (extraContact) parts.push(contactParts(extraContact))
  const merge = (key) => [...new Set(parts.flatMap((p) => p[key]))]
  return { names: merge('names'), emails: merge('emails'), phones: merge('phones'), links: merge('links') }
}

export function buildRedactionHints({ profile, jobs, contact }) {
  return { owner: ownerHints(profile), contacts: contactHints(jobs, contact) }
}
