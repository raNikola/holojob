import Card from '../ui/Card'
import { buildCommit, sourceUrl } from '../../modules/about/sourceInfo'

/** Settings > General > About and source code: the licence and the link to the source of this running version. */
export default function AboutPanel() {
  const commit = buildCommit()
  return (
    <Card title="About and source code">
      <p className="text-sm text-stone-600 dark:text-stone-400">
        Holojob is free software under the GNU Affero General Public License v3.0. You can get the source code of the
        version you are running.
      </p>
      <p className="mt-3 text-sm">
        <a
          href={sourceUrl(commit)}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-stone-900 underline underline-offset-2 dark:text-stone-50"
        >
          Source code{commit ? ` (commit ${commit.slice(0, 7)})` : ''}
        </a>
      </p>
    </Card>
  )
}
