import Card from '../ui/Card'
import geography from '../../data/geography.json'

const NAMES = Object.fromEntries([
  ['REMOTE', 'Remote'],
  ...Object.entries(geography.regions).map(([code, region]) => [code, region.name]),
  ...geography.countries.map(({ code, name }) => [code, name]),
])
const name = (code) => NAMES[code] || code
const RELOCATION = { none: 'Not open to relocating', abroad: 'Open to relocating abroad', anywhere: 'Open to relocating anywhere' }

function WorkAuthorizationSummary({ prefs }) {
  const auth = prefs?.workAuthorization || {}
  const holds = auth.holds || []
  const allowed = prefs?.allowedLocations || []
  return (
    <Card title="Where you can work (used for scoring)" className="!p-4">
      <dl className="space-y-2 text-sm">
        <div>
          <dt className="text-xs text-stone-500">Work without a visa in</dt>
          <dd className="text-stone-800 dark:text-stone-200">
            {holds.length ? holds.map((h) => `${name(h.jurisdiction)}${h.basis ? ` (${h.basis.replace('_', ' ')})` : ''}`).join(', ') : 'Not set: visas are not checked'}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-stone-500">Sponsored roles</dt>
          <dd className="text-stone-800 dark:text-stone-200">{auth.openToSponsorship ? 'Open to them' : 'Not open to them'}</dd>
        </div>
        <div>
          <dt className="text-xs text-stone-500">Relocation</dt>
          <dd className="text-stone-800 dark:text-stone-200">{RELOCATION[prefs?.relocation] || RELOCATION.none}</dd>
        </div>
        <div>
          <dt className="text-xs text-stone-500">Takes jobs in</dt>
          <dd className="text-stone-800 dark:text-stone-200">{allowed.length ? allowed.map(name).join(', ') : 'Any location'}</dd>
        </div>
      </dl>
    </Card>
  )
}

function QueryList({ title, items }) {
  if (!items?.length) return null
  return (
    <Card title={title} className="!p-4">
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item} className="rounded-lg bg-stone-50 px-3 py-2 font-mono text-xs text-stone-700 dark:bg-stone-900 dark:text-stone-300">
            {item}
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function SearchStrategyCard({ intelligence }) {
  const s = intelligence.searchStrategy
  return (
    <div className="space-y-4">
      <QueryList title="JobSpy search terms (Module 3)" items={s.jobSpySearchTerms} />
      <QueryList title="LinkedIn search queries" items={s.linkedinSearchQueries} />
      <QueryList title="Recommended search queries" items={s.recommendedSearchQueries} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Location filters" className="!p-4">
          <div className="flex flex-wrap gap-2">
            {s.locationFilters?.map((l) => (
              <span key={l} className="rounded-md bg-stone-100 px-2 py-1 text-xs dark:bg-stone-800">{l}</span>
            ))}
          </div>
        </Card>
        <Card title="Remote filters" className="!p-4">
          <div className="flex flex-wrap gap-2">
            {s.remoteFilters?.map((r) => (
              <span key={r} className="rounded-md bg-stone-100 px-2 py-1 text-xs dark:bg-stone-800">{r}</span>
            ))}
          </div>
        </Card>
      </div>
      <WorkAuthorizationSummary prefs={intelligence.jobFitPreferences} />
      <Card title="Scoring weights (for Module 3 matching)" className="!p-4">
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
          {Object.entries(intelligence.scoringWeights || {}).map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-stone-500">{k}</dt>
              <dd className="font-medium text-stone-800 dark:text-stone-200">{v}%</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  )
}
