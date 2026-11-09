// Writes through named imports, the way a module that does `import { writeFileSync } from 'node:fs'` would. Used by realDataGuard.test.js.
import { renameSync, writeFileSync } from 'node:fs'
import { writeFile } from 'node:fs/promises'

export const writeNamed = (file) => writeFileSync(file, 'x')
export const renameNamed = (from, to) => renameSync(from, to)
export const writeNamedPromise = (file) => writeFile(file, 'x')
