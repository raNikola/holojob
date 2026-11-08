#!/usr/bin/env node
/**
 * Check a backup zip without touching ./data: verify the manifest hashes, restore into a throwaway directory,
 * compare the restored files with the manifest, delete the directory. Prints counts and names only, never content.
 *
 *     node scripts/backup-check.js holojob-backup-2026-11-08_12-00.zip
 *
 * Exit 0 = pass, 1 = fail, 2 = usage. A zip made before manifests carried hashes cannot be checked: exit 1.
 */
import fs from 'node:fs'
import { checkBackupRestore } from './backup-handler.js'

const file = process.argv[2]
if (!file) {
  console.error('usage: node scripts/backup-check.js <backup.zip>')
  process.exit(2)
}
const report = await checkBackupRestore(fs.readFileSync(file))
if (!report.hashed && report.ok) console.log('FAIL: this archive has no file hashes (made before Wave 0), so it cannot be verified')
else console.log(`${report.ok ? 'PASS' : 'FAIL'}: ${report.checked} files restored to a temp directory and matching, ${report.merged} application files merged, ${report.refused.length} refused`)
for (const p of report.problems) console.log(`  ${p.name}: ${p.reason}`)
process.exit(report.ok && report.hashed ? 0 : 1)
