import { useCallback, useEffect, useState } from 'react'
import { useOperationLog } from './useOperationLog'
import { saveProfileToDataDir } from '../modules/jobs/profileSync'
import { ensureApiAvailable } from '../utils/apiAvailability'

async function fetchJson(url) {
  if (!(await ensureApiAvailable())) return null
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

/** True when at least one GitHub link or local repo path is filled in. */
export function hasRepositories(profile) {
  const r = profile?.repositories
  return (r?.githubLinks?.filter(Boolean).length || 0) + (r?.localRepoPaths?.filter(Boolean).length || 0) > 0
}

/**
 * Saved repo-scan data plus the scan handler, shared by the Repos and Questionnaire
 * steps. Both read the same saved file on mount, so a scan run in one step shows
 * in the other. Same calls as before: save profile, POST /api/projects/scan.
 */
export function useRepoScan(profile) {
  const [projectIntel, setProjectIntel] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState('')
  const scanLog = useOperationLog()

  useEffect(() => {
    let live = true
    fetchJson('/api/projects/intelligence').then((proj) => { if (live && proj) setProjectIntel(proj) })
    return () => { live = false }
  }, [])

  const scan = useCallback(async () => {
    setScanning(true)
    scanLog.start('Saving profile to disk…')
    setScanMsg('')
    await saveProfileToDataDir(profile)
    scanLog.append('Cloning / scanning repos with Claude Code (1–3 min)…')
    try {
      const res = await fetch('/api/projects/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const data = await res.json()
      for (const text of [data.stdout, data.stderr]) {
        if (text) for (const line of text.split('\n').filter(Boolean)) scanLog.append(line)
      }
      if (data.payload) {
        setProjectIntel(data.payload)
        const n = data.payload.projects?.length || 0
        scanLog.append(`Done — ${n} repo(s) analyzed.`)
        setScanMsg(`Scanned ${n} repo(s). Skills and projects updated.`)
      } else {
        setScanMsg(data.stderr || 'Scan completed.')
        scanLog.append(data.stderr || 'Scan finished.')
      }
    } catch (e) {
      setScanMsg(`Error: ${e.message}`)
      scanLog.append(`Error: ${e.message}`)
    } finally {
      setScanning(false)
      scanLog.stop()
    }
  }, [profile, scanLog])

  return { projectIntel, scanning, scanMsg, scanLog, scan, canScan: hasRepositories(profile) }
}
