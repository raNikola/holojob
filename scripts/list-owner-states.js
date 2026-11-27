#!/usr/bin/env node
/**
 * The owner's acted-on ads from the raw files, read only, one record per ad: [jobId, applied, appliedVoidedOnly, saved, rejected, keep].
 * Saved, Rejected and Keep come from data/jobs/job-state.json, Applied from the application store (a job id with any application;
 * `appliedVoidedOnly` is true when every application of it is voided). One ad can carry several flags: the list row shows a single
 * status (the Applied overlay wins), so the row cannot be used for this. Same set as `scripts/measure_package3.py`'s must-keep set.
 * Ids and flags only. Used by `scripts/measure_strong_reliability.py`.
 *
 *   scripts/node-sandbox node scripts/list-owner-states.js
 */
import { loadStore } from './application-store.js'
import { loadState } from './job-state-store.js'
import { isActive } from '../src/modules/applications/foldApplication.js'

const DATA_ROOT = '/srv/holojob'
const ads = new Map()
const one = (id) => {
  if (!ads.has(id)) ads.set(id, { applied: false, activeApplication: false, saved: false, rejected: false, keep: false })
  return ads.get(id)
}
for (const app of Object.values(loadStore(DATA_ROOT)?.applications ?? {})) {
  const id = app?.posting?.jobId
  if (typeof id !== 'string' || !id) continue
  const ad = one(id)
  ad.applied = true
  if (isActive(app)) ad.activeApplication = true
}
for (const entry of Object.values(loadState(DATA_ROOT).doc?.jobs ?? {})) {
  if (typeof entry.jobId !== 'string' || !entry.jobId) continue
  if (entry.status === 'saved') one(entry.jobId).saved = true
  if (entry.status === 'rejected') one(entry.jobId).rejected = true
  if (entry.keep === true) one(entry.jobId).keep = true
}
console.log(JSON.stringify([...ads].map(([id, a]) => [id, a.applied, a.applied && !a.activeApplication, a.saved, a.rejected, a.keep])))
