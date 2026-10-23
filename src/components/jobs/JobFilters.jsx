import Card from '../ui/Card'
import Input from '../ui/Input'
import SelectField from '../ui/SelectField'
import MultiSelectDropdown from '../ui/MultiSelectDropdown'
import { normalizePriorityFilter } from '../../modules/jobs/jobFilters'
import { JOB_STATUSES } from '../../modules/jobs/jobStorage'
import { MATCH_LABELS, PRIORITIES, hasMatchScores } from '../../modules/jobs/matchScore'

export default function JobFilters({ filters, sites, providers, jobs, onChange }) {
  const showScoreFilters = hasMatchScores(jobs)
  return (
    <Card title="Filters" className="!p-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Input
          label="Search"
          value={filters.searchText}
          onChange={(e) => onChange({ searchText: e.target.value })}
          placeholder="Title, company, description…"
        />
        <Input
          label="Location"
          value={filters.location}
          onChange={(e) => onChange({ location: e.target.value })}
          placeholder="Filter by location"
        />
        <SelectField
          label="Site"
          value={filters.site}
          onChange={(v) => onChange({ site: v })}
          options={sites}
          placeholder="All sites"
        />
        <SelectField
          label="Provider"
          value={filters.provider}
          onChange={(v) => onChange({ provider: v })}
          options={providers}
          placeholder="All providers"
        />
        <SelectField
          label="Status"
          value={filters.status}
          onChange={(v) => onChange({ status: v })}
          options={JOB_STATUSES}
          placeholder="All statuses"
        />
        {showScoreFilters && (
          <>
            <Input
              label="Min score"
              type="number"
              min={0}
              max={100}
              value={filters.minScore}
              onChange={(e) => onChange({ minScore: e.target.value })}
              placeholder="e.g. 55"
            />
            <Input
              label="Min salary (EUR/month)"
              type="number"
              min={0}
              value={filters.minSalary ?? ''}
              onChange={(e) => onChange({ minSalary: e.target.value })}
              placeholder="e.g. 2500"
            />
            <Input
              label="Desired salary from (EUR/month)"
              type="number"
              min={0}
              value={filters.desiredSalaryMin ?? ''}
              onChange={(e) => onChange({ desiredSalaryMin: e.target.value })}
            />
            <Input
              label="Desired salary to (EUR/month)"
              type="number"
              min={0}
              value={filters.desiredSalaryMax ?? ''}
              onChange={(e) => onChange({ desiredSalaryMax: e.target.value })}
            />
            {filters.salaryFromProfile && (
              <p className="self-end pb-2 text-xs text-stone-500 sm:col-span-2 xl:col-span-3">
                Salary filters are pre-filled from your profile, so jobs paying less than your minimum are hidden. Clear Min salary to see them with the “Below min salary” badge. Jobs with no readable pay are never hidden.
              </p>
            )}
            <SelectField
              label="Match label"
              value={filters.matchLabel}
              onChange={(v) => onChange({ matchLabel: v })}
              options={MATCH_LABELS}
              placeholder="All labels"
            />
            <MultiSelectDropdown
              label="Priority"
              selected={normalizePriorityFilter(filters.priority)}
              onChange={(v) => onChange({ priority: v })}
              options={PRIORITIES.filter((p) => p !== 'Reject')}
              placeholder="All priorities"
            />
          </>
        )}
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
        <input
          type="checkbox"
          checked={filters.remoteOnly}
          onChange={(e) => onChange({ remoteOnly: e.target.checked })}
          className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
        />
        Remote only
      </label>
      {showScoreFilters && (
        <label className="mt-2 flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
          <input
            type="checkbox"
            checked={filters.hideNeedsVisa}
            onChange={(e) => onChange({ hideNeedsVisa: e.target.checked })}
            className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
          />
          Hide jobs that need a visa
        </label>
      )}
    </Card>
  )
}
