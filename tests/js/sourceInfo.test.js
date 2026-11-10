import { describe, expect, it } from 'vitest'
import { SOURCE_REPO_URL, buildCommit, sourceUrl } from '../../src/modules/about/sourceInfo.js'

describe('source link of the running version', () => {
  it('links to the tree at the baked-in commit', () => {
    const commit = '0123456789abcdef0123456789abcdef01234567'
    expect(buildCommit({ VITE_HOLOJOB_COMMIT: commit })).toBe(commit)
    expect(sourceUrl(commit)).toBe(`${SOURCE_REPO_URL}/tree/${commit}`)
    expect(sourceUrl('ABCDEF1')).toBe(`${SOURCE_REPO_URL}/tree/abcdef1`)
  })

  it.each([undefined, '', 'unknown', 'main', 'abc', 'g'.repeat(40), '../../etc', 'abcdef1 ; rm'])(
    'falls back to the repository root for %j, never builds a path from it', (value) => {
      expect(buildCommit({ VITE_HOLOJOB_COMMIT: value })).toBeNull()
      expect(sourceUrl(value)).toBe(SOURCE_REPO_URL)
    })
})
