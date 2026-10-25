import roleFamilies from '../data/roleFamilies.json'

// The family ids scoring knows (python/job_scoring/scorer.py reads the same file).
export const ROLE_FAMILY_IDS = Object.keys(roleFamilies)

export const ROLE_FAMILY_LABELS = {
  product: 'Product',
  engineering: 'Engineering',
  design: 'Design',
  qa: 'QA',
  data: 'Data',
  delivery: 'Delivery',
  marketing: 'Marketing',
  sales: 'Sales',
}

/**
 * A known family id, or '' when the profile sets none. Nothing is defaulted:
 * with no family the role-family gate is unknown and no off-track cap applies.
 * @param {unknown} value
 * @returns {string}
 */
export function normalizeRoleFamily(value) {
  return ROLE_FAMILY_IDS.includes(value) ? value : ''
}
