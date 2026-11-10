/**
 * Where the source of the running version lives (AGPL-3.0 section 13: users who reach a modified version over a
 * network are offered its source). The commit is baked into the build (Dockerfile ARG HOLOJOB_COMMIT); a build
 * without it links to the repository root. Pure: no React, no storage, nothing is sent anywhere.
 */

export const SOURCE_REPO_URL = 'https://github.com/raNikola/holojob'

const COMMIT = /^[0-9a-f]{7,40}$/

/** The commit this build was made from, lowercase, or null when the build did not record one. */
export function buildCommit(env = import.meta.env) {
  const commit = String(env?.VITE_HOLOJOB_COMMIT ?? '').trim().toLowerCase()
  return COMMIT.test(commit) ? commit : null
}

/** The web address of the source tree at that commit; the repository root when there is no usable commit. */
export function sourceUrl(commit = buildCommit()) {
  const clean = String(commit ?? '').trim().toLowerCase()
  return COMMIT.test(clean) ? `${SOURCE_REPO_URL}/tree/${clean}` : SOURCE_REPO_URL
}
