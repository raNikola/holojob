import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { writeCoverLetter, writeInterviewPrep, writeSkillGap } from '../../scripts/run-ai.js'

const REPO_DATA = fileURLToPath(new URL('../../data', import.meta.url))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})

describe('saved AI answers', () => {
  it('the test run is pointed away from the real data folder', () => {
    expect(process.env.HOLOJOB_AI_OUTPUT_DIR).toBeTruthy()
    expect(path.resolve(process.env.HOLOJOB_AI_OUTPUT_DIR).startsWith(REPO_DATA)).toBe(false)
  })

  it('go under HOLOJOB_AI_OUTPUT_DIR when it is set', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-output-'))
    vi.stubEnv('HOLOJOB_AI_OUTPUT_DIR', dir)
    try {
      expect(writeInterviewPrep('job-1', { answer: 'ok' })).toBe(path.join(dir, 'interviews/job-1/interview_prep.json'))
      expect(writeCoverLetter('job-1', {})).toBe(path.join(dir, 'resumes/job-1/drafts/ai_cover_letter.md'))
      expect(writeSkillGap({})).toBe(path.join(dir, 'analytics/skill_gap.json'))
      expect(fs.existsSync(path.join(dir, 'analytics/skill_gap.json'))).toBe(true)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  it('go under data/ when it is not set', () => {
    // The default paths are the real files, so every write here is intercepted.
    vi.stubEnv('HOLOJOB_AI_OUTPUT_DIR', '')
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const write = vi.spyOn(fs, 'writeFileSync').mockImplementation(() => {})
    expect(writeInterviewPrep('job-1', {})).toBe(path.join(REPO_DATA, 'interviews/job-1/interview_prep.json'))
    expect(writeCoverLetter('job-1', {})).toBe(path.join(REPO_DATA, 'resumes/job-1/drafts/ai_cover_letter.md'))
    expect(writeSkillGap({})).toBe(path.join(REPO_DATA, 'analytics/skill_gap.json'))
    expect(write).toHaveBeenCalledTimes(3)
  })
})
