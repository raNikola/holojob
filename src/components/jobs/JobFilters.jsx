import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, X } from 'lucide-react'
import Card from '../ui/Card'
import Input from '../ui/Input'
import SelectField from '../ui/SelectField'
import MultiSelectDropdown from '../ui/MultiSelectDropdown'
import InfoTip from '../ui/InfoTip'
import SalaryFilter from './SalaryFilter'
import { APPLIED_FILTER, statusFilterOptions } from '../../modules/applications/appliedFilter'
import {
  CLEAR_ALL_FILTERS,
  activeFilterChips,
  countByValue,
  getCompanyOptions,
  moreFiltersCount,
  normalizeMultiFilter,
} from '../../modules/jobs/jobFilters'
import { salaryRangeOf } from '../../modules/jobs/salaryFilter'
import { FILTER_HELP } from '../../modules/jobs/filterHelp'
import { JOB_STATUSES } from '../../modules/jobs/jobStorage'
import { MATCH_LABELS, PRIORITIES, hasMatchScores } from '../../modules/jobs/matchScore'

const SHOWN_PRIORITIES = PRIORITIES.filter((p) => p !== 'Reject')
const tip = (key, label) => <InfoTip text={FILTER_HELP[key]} label={`About ${label}`} />

function Checkbox({ label, help, checked, onChange, className = 'self-end pb-2.5', disabledNote = null }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <label className={`flex items-center gap-2 text-sm ${disabledNote ? 'text-stone-400' : 'text-stone-700 dark:text-stone-300'}`} title={disabledNote ?? undefined}>
        <input
          type="checkbox"
          disabled={Boolean(disabledNote)}
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
        />
        {label}
      </label>
      {help}
    </div>
  )
}

export default function JobFilters({ filters, sites, providers, jobs, applicationStore = null, basicProfile = null, onChange, searchNote = null, offListDisabledNote = null }) {
  const showScoreFilters = hasMatchScores(jobs)
  const [moreOpen, setMoreOpen] = useState(false)
  // Until the open animation ends the extras clip their content; afterwards dropdowns may extend past the box.
  const [settled, setSettled] = useState(false)
  const settleTimer = useRef(null)
  useEffect(() => () => clearTimeout(settleTimer.current), [])
  const toggleMore = () => {
    clearTimeout(settleTimer.current)
    const next = !moreOpen
    setMoreOpen(next)
    const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (!next) setSettled(false)
    else if (reduced) setSettled(true)
    else {
      setSettled(false)
      settleTimer.current = setTimeout(() => setSettled(true), 220)
    }
  }
  const chips = activeFilterChips(filters)
  const salary = salaryRangeOf(filters)
  // Chips of filters that are not rendered (score filters without scores) are not counted in the toggle.
  const moreCount = moreFiltersCount(chips.filter((c) => showScoreFilters || ['provider', 'company', 'hideNoLongerListed', 'showOffList'].includes(c.key)))
  const priorityOptions = useMemo(
    () => countByValue(jobs, 'priority', SHOWN_PRIORITIES).map(({ value, count }) => ({ value, label: `${value} (${count})` })),
    [jobs],
  )

  const companyOptions = useMemo(() => getCompanyOptions(jobs), [jobs])

  return (
    <Card title="Filters" className="!p-4">
      {searchNote && <p className="mb-2 text-xs text-stone-500 dark:text-stone-400">{searchNote}</p>}
      <div className="flex flex-wrap items-end gap-3">
        <Input
          className="min-w-[10rem] flex-[2_1_10rem]"
          id="filter-search"
          label="Search"
          labelExtra={tip('searchText', 'Search')}
          value={filters.searchText}
          onChange={(e) => onChange({ searchText: e.target.value })}
          placeholder="Title, company, description…"
        />
        <Input
          className="min-w-[7rem] flex-[1.5_1_7rem]"
          id="filter-location"
          label="Location"
          labelExtra={tip('location', 'Location')}
          value={filters.location}
          onChange={(e) => onChange({ location: e.target.value })}
          placeholder="Filter by location"
        />
        <div className="w-32 flex-none">
          <MultiSelectDropdown
            label="Source"
            labelExtra={tip('site', 'Source')}
            selected={normalizeMultiFilter(filters.site)}
            onChange={(v) => onChange({ site: v })}
            options={sites}
            placeholder="All sources"
          />
        </div>
        <div className="w-32 flex-none">
          <SelectField
            id="filter-status"
            label="Status"
            labelExtra={tip('status', 'Status')}
            value={filters.status}
            onChange={(v) => onChange({ status: v })}
            options={statusFilterOptions(JOB_STATUSES, jobs, applicationStore)}
            placeholder="All statuses"
          />
        </div>
        {showScoreFilters && (
          <>
            <div className="w-32 flex-none">
              <MultiSelectDropdown
                label="Priority"
                labelExtra={tip('priority', 'Priority')}
                selected={normalizeMultiFilter(filters.priority)}
                onChange={(v) => onChange({ priority: v })}
                options={priorityOptions}
                placeholder="All priorities"
              />
            </div>
            <Input
              className="w-[5.5rem] flex-none"
              id="filter-min-score"
              label="Min score"
              labelExtra={tip('minScore', 'Min score')}
              type="number"
              min={0}
              max={100}
              value={filters.minScore}
              onChange={(e) => onChange({ minScore: e.target.value })}
              placeholder="e.g. 55"
            />
          </>
        )}
        <Checkbox
          label="Remote only"
          help={tip('remoteOnly', 'Remote only')}
          checked={filters.remoteOnly}
          onChange={(v) => onChange({ remoteOnly: v })}
        />
      </div>
      {filters.status === APPLIED_FILTER && !applicationStore && (
        <p className="mt-2 text-xs text-stone-500">The application tracker has not loaded, so no job can be shown as applied.</p>
      )}

      {/* The extras stay mounted (drafts and focus survive); collapsed they are invisible, so Tab skips them. */}
      <div
        id="more-filters"
        className={`grid transition-[grid-template-rows,opacity,visibility] duration-200 ease-out motion-reduce:transition-none ${moreOpen ? 'visible grid-rows-[1fr] opacity-100' : 'invisible grid-rows-[0fr] opacity-0'}`}
      >
        <div className={`min-h-0 ${moreOpen && settled ? '' : 'overflow-hidden'}`}>
          <div className="flex flex-wrap items-start gap-x-3 gap-y-2 pt-3">
            <div className="min-w-[10rem] flex-[1_1_10rem]">
              <MultiSelectDropdown
                label="Provider"
                labelExtra={tip('provider', 'Provider')}
                selected={normalizeMultiFilter(filters.provider)}
                onChange={(v) => onChange({ provider: v })}
                options={providers}
                placeholder="All providers"
              />
            </div>
            <div className="min-w-[10rem] flex-[1_1_10rem]">
              <MultiSelectDropdown
                label="Company"
                labelExtra={tip('company', 'Company')}
                selected={normalizeMultiFilter(filters.company)}
                onChange={(v) => onChange({ company: v })}
                options={companyOptions}
                placeholder="All companies"
              />
            </div>
            {showScoreFilters && (
              <>
                <div className="min-w-[9rem] flex-[1_1_9rem]">
                  <SelectField
                    id="filter-match-label"
                    label="Match label"
                    labelExtra={tip('matchLabel', 'Match label')}
                    value={filters.matchLabel}
                    onChange={(v) => onChange({ matchLabel: v })}
                    options={MATCH_LABELS}
                    placeholder="All labels"
                  />
                </div>
                <SalaryFilter
                  className="w-[22rem] max-w-full flex-none"
                  from={salary.from}
                  to={salary.to}
                  includeUnknown={filters.salaryIncludeUnknown !== false}
                  filters={filters}
                  profile={basicProfile}
                  onChange={onChange}
                />
              </>
            )}
            {/* The pair sits beside the Salary row on wide windows (top spacer = label row plus half the difference of input and checkbox heights, so they are centred on the input row); as a pair under the extras when they wrap. */}
            <div className="flex min-w-[26rem] max-w-full flex-[1_1_auto] flex-wrap items-center gap-x-5 gap-y-2 min-[1280px]:pt-[2.3rem]">
              {/* Wide windows: the visa box is centred in its half, the other sits at the right end; wrapped, both stay left. */}
              {showScoreFilters && (
                <div className="flex items-center min-[1280px]:flex-1 min-[1280px]:justify-center">
                  <Checkbox
                    className=""
                    label="Hide jobs that need a visa"
                    help={tip('hideNeedsVisa', 'Hide jobs that need a visa')}
                    checked={filters.hideNeedsVisa}
                    onChange={(v) => onChange({ hideNeedsVisa: v })}
                  />
                </div>
              )}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 min-[1280px]:flex-1 min-[1280px]:justify-end">
                <Checkbox
                  className=""
                  label="Show jobs absent from current results"
                  help={tip('showOffList', 'Show jobs absent from current results')}
                  checked={Boolean(filters.showOffList)}
                  onChange={(v) => onChange({ showOffList: v })}
                  disabledNote={offListDisabledNote}
                />
                <Checkbox
                  className=""
                  label="Hide jobs no longer listed"
                  help={tip('hideNoLongerListed', 'Hide jobs no longer listed')}
                  checked={Boolean(filters.hideNoLongerListed)}
                  onChange={(v) => onChange({ hideNoLongerListed: v })}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {chips.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Active filters">
          {chips.map((chip) => (
            <span key={chip.key} className="inline-flex items-center gap-1 rounded-full border border-teal-300 bg-teal-50 py-0.5 pl-2.5 pr-1 text-xs text-teal-900 dark:border-teal-800 dark:bg-teal-950 dark:text-teal-100">
              {chip.label}
              <button
                type="button"
                aria-label={`Remove filter ${chip.label}`}
                onClick={() => onChange(chip.patch)}
                className="rounded-full p-0.5 hover:bg-teal-200 dark:hover:bg-teal-800"
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Always the last row: the extras open above it and the chips sit directly above it. */}
      <div className="mt-3 flex items-center justify-end gap-4 border-t border-stone-200 pt-2 text-sm dark:border-stone-800">
        <button
          type="button"
          aria-expanded={moreOpen}
          aria-controls="more-filters"
          onClick={toggleMore}
          className="inline-flex items-center gap-1 text-stone-700 hover:text-teal-700 hover:underline dark:text-stone-300 dark:hover:text-teal-300"
        >
          More filters{moreCount > 0 ? ` (${moreCount})` : ''}
          <ChevronDown className={`h-4 w-4 transition-transform duration-200 motion-reduce:transition-none ${moreOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
        <button
          type="button"
          disabled={chips.length === 0}
          onClick={() => onChange(CLEAR_ALL_FILTERS)}
          className="text-stone-600 hover:text-teal-700 hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:no-underline dark:text-stone-400"
        >
          Clear all
        </button>
      </div>
    </Card>
  )
}
