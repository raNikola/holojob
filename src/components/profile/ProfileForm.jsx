import { Plus, Trash2 } from 'lucide-react'
import Card from '../ui/Card'
import Input from '../ui/Input'
import TagInput from '../ui/TagInput'
import RoleCombobox from '../ui/RoleCombobox'
import ConfidenceTag from '../ui/ConfidenceTag'
import SelectField from '../ui/SelectField'
import { useProfile } from '../../context/ProfileContext'
import { LANGUAGE_PROFICIENCIES } from '../../utils/languages'
import { AUTHORIZATION_BASES, RELOCATION_OPTIONS, REMOTE } from '../../utils/workAuthorization'
import geography from '../../data/geography.json'

function ListEditor({ label, items = [], onChange, confidenceKey, confidence }) {
  const update = (index, value) => {
    const next = [...items]
    next[index] = value
    onChange(next)
  }
  const add = () => onChange([...items, ''])
  const remove = (index) => onChange(items.filter((_, i) => i !== index))

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-stone-700 dark:text-stone-300">{label}</span>
        {confidenceKey && <ConfidenceTag fieldKey={confidenceKey} confidence={confidence} />}
      </div>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="flex gap-2">
            <input
              value={item}
              onChange={(e) => update(i, e.target.value)}
              className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
              placeholder={`Entry ${i + 1}`}
            />
            <button type="button" onClick={() => remove(i)} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-red-500 dark:hover:bg-stone-800">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
        <button type="button" onClick={add} className="inline-flex items-center gap-1 text-sm text-teal-600 hover:text-teal-700 dark:text-teal-400">
          <Plus className="h-4 w-4" /> Add entry
        </button>
      </div>
    </div>
  )
}

const SELECT_CLASS = 'w-full rounded-lg border border-stone-300 px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50'
const COUNTRY_OPTIONS = geography.countries
  .map(({ code, name }) => ({ code, name }))
  .sort((a, b) => a.name.localeCompare(b.name))
const REGION_OPTIONS = Object.entries(geography.regions).map(([code, region]) => ({ code, name: region.name }))
// A right to work is held for a country, or for the EU as a whole.
const JURISDICTION_OPTIONS = [...REGION_OPTIONS.filter((r) => r.code === 'EU'), ...COUNTRY_OPTIONS]
const PLACE_OPTIONS = [{ code: REMOTE, name: 'Remote' }, ...REGION_OPTIONS, ...COUNTRY_OPTIONS]
const placeName = (code) => PLACE_OPTIONS.find((option) => option.code === code)?.name || code

const BASIS_LABELS = {
  citizen: 'Citizen',
  permanent_resident: 'Permanent resident',
  work_permit: 'Work permit or visa',
  other: 'Other',
}
const RELOCATION_LABELS = {
  none: 'No: only my own cities, or remote',
  abroad: 'Yes, to another country (not within my own)',
  anywhere: 'Yes, anywhere',
}

function WorkAuthorizationEditor({ value, onChange }) {
  const holds = value?.holds || []
  const openToSponsorship = value?.openToSponsorship === true
  const set = (patch) => onChange({ holds, openToSponsorship, ...patch })
  const update = (index, patch) => set({ holds: holds.map((h, i) => (i === index ? { ...h, ...patch } : h)) })

  return (
    <div>
      <span className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">Where you can work without a visa</span>
      <p className="mb-2 text-xs text-stone-500 dark:text-stone-400">
        Leave empty and visas are not checked. For an EU passport, add &ldquo;EU / EEA / Switzerland&rdquo;.
      </p>
      <div className="space-y-2">
        {holds.map((entry, i) => (
          <div key={i} className="flex gap-2">
            <select value={entry.jurisdiction} onChange={(e) => update(i, { jurisdiction: e.target.value })} className={SELECT_CLASS}>
              <option value="">Country or region…</option>
              {JURISDICTION_OPTIONS.map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
            </select>
            <select value={entry.basis} onChange={(e) => update(i, { basis: e.target.value })} className={`${SELECT_CLASS} w-56`}>
              <option value="">Basis…</option>
              {AUTHORIZATION_BASES.map((b) => <option key={b} value={b}>{BASIS_LABELS[b]}</option>)}
            </select>
            <button type="button" onClick={() => set({ holds: holds.filter((_, j) => j !== i) })} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-red-500 dark:hover:bg-stone-800">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
        <button type="button" onClick={() => set({ holds: [...holds, { jurisdiction: '', basis: '' }] })} className="inline-flex items-center gap-1 text-sm text-teal-600 hover:text-teal-700 dark:text-teal-400">
          <Plus className="h-4 w-4" /> Add a country or region
        </button>
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
        <input type="checkbox" checked={openToSponsorship} onChange={(e) => set({ openToSponsorship: e.target.checked })} className="rounded border-stone-300 text-teal-600" />
        Open to roles that sponsor a work permit
      </label>
    </div>
  )
}

function PlacePicker({ selected = [], onChange }) {
  const available = PLACE_OPTIONS.filter((o) => !selected.includes(o.code))
  return (
    <div>
      <span className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">Where you&rsquo;ll take a job</span>
      <p className="mb-2 text-xs text-stone-500 dark:text-stone-400">
        Leave empty to consider every location. Jobs outside a list you set are still shown, scored low.
      </p>
      <div className="mb-2 flex flex-wrap gap-2">
        {selected.map((code) => (
          <span key={code} className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-3 py-1 text-xs font-medium text-teal-800 dark:bg-teal-950 dark:text-teal-200">
            {placeName(code)}
            <button type="button" onClick={() => onChange(selected.filter((c) => c !== code))} className="text-teal-600 hover:text-red-500" aria-label={`Remove ${placeName(code)}`}>×</button>
          </span>
        ))}
      </div>
      <select value="" onChange={(e) => e.target.value && onChange([...selected, e.target.value])} className={SELECT_CLASS}>
        <option value="">Add a place…</option>
        {available.map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
      </select>
    </div>
  )
}

function LanguageEditor({ languages = [], onChange }) {
  const update = (index, patch) =>
    onChange(languages.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)))
  const add = () => onChange([...languages, { language: '', proficiency: '' }])
  const remove = (index) => onChange(languages.filter((_, i) => i !== index))

  return (
    <div>
      <span className="mb-2 block text-sm font-medium text-stone-700 dark:text-stone-300">Languages</span>
      <div className="space-y-2">
        {languages.map((entry, i) => (
          <div key={i} className="flex gap-2">
            <input
              value={entry.language}
              onChange={(e) => update(i, { language: e.target.value })}
              className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
              placeholder="Language, e.g. Serbian"
            />
            <div className="w-44">
              <SelectField
                value={entry.proficiency}
                onChange={(value) => update(i, { proficiency: value })}
                options={LANGUAGE_PROFICIENCIES}
                placeholder="Proficiency"
              />
            </div>
            <button type="button" onClick={() => remove(i)} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-red-500 dark:hover:bg-stone-800">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
        <button type="button" onClick={add} className="inline-flex items-center gap-1 text-sm text-teal-600 hover:text-teal-700 dark:text-teal-400">
          <Plus className="h-4 w-4" /> Add language
        </button>
      </div>
    </div>
  )
}

export default function ProfileForm() {
  const { profile, updateProfile, markFieldEdited } = useProfile()
  const conf = profile._confidence || {}
  const bp = profile.basicProfile
  const pd = profile.resume.parsedData

  const setBasic = (field, value) => {
    markFieldEdited(field)
    updateProfile((prev) => ({
      ...prev,
      basicProfile: { ...prev.basicProfile, [field]: value },
    }))
  }

  const setParsed = (field, value) => {
    markFieldEdited(field)
    updateProfile((prev) => ({
      ...prev,
      resume: {
        ...prev.resume,
        parsedData: { ...prev.resume.parsedData, [field]: value },
      },
    }))
  }

  return (
    <div className="space-y-6">
      <Card title="Basic information" description="Review autofilled fields from your resume. Edit anything that looks wrong.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" value={bp.fullName} onChange={(e) => setBasic('fullName', e.target.value)} confidenceTag={<ConfidenceTag fieldKey="fullName" confidence={conf.fullName} />} />
          <Input label="Email" type="email" value={bp.email} onChange={(e) => setBasic('email', e.target.value)} confidenceTag={<ConfidenceTag fieldKey="email" confidence={conf.email} />} />
          <Input label="Phone" value={bp.phone} onChange={(e) => setBasic('phone', e.target.value)} confidenceTag={<ConfidenceTag fieldKey="phone" confidence={conf.phone} />} />
          <Input label="Location" value={bp.location} onChange={(e) => setBasic('location', e.target.value)} confidenceTag={<ConfidenceTag fieldKey="location" confidence={conf.location} />} />
          <Input label="Current role" value={bp.currentRole} onChange={(e) => setBasic('currentRole', e.target.value)} confidenceTag={<ConfidenceTag fieldKey="currentRole" confidence={conf.currentRole} />} />
          <Input label="Experience (years)" value={bp.experienceYears} onChange={(e) => setBasic('experienceYears', e.target.value)} confidenceTag={<ConfidenceTag fieldKey="experienceYears" confidence={conf.experienceYears} />} />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-stone-700 dark:text-stone-300">Remote preference</label>
            <select
              value={bp.remotePreference}
              onChange={(e) => setBasic('remotePreference', e.target.value)}
              className="w-full rounded-lg border border-stone-300 px-3 py-2.5 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
            >
              <option value="">Select...</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="office">Office only</option>
              <option value="flexible">Flexible</option>
            </select>
          </div>
          <Input label="Salary expectation" value={bp.salaryExpectation} onChange={(e) => setBasic('salaryExpectation', e.target.value)} placeholder="Amount and currency, per month or year" />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <Input label="Minimum salary (EUR/month)" type="number" min={0} value={bp.minSalaryEur ?? ''} onChange={(e) => setBasic('minSalaryEur', e.target.value === '' ? null : Number(e.target.value))} placeholder="Flags jobs paying less" />
          <Input label="Desired salary from (EUR/month)" type="number" min={0} value={bp.desiredSalaryMinEur ?? ''} onChange={(e) => setBasic('desiredSalaryMinEur', e.target.value === '' ? null : Number(e.target.value))} />
          <Input label="Desired salary to (EUR/month)" type="number" min={0} value={bp.desiredSalaryMaxEur ?? ''} onChange={(e) => setBasic('desiredSalaryMaxEur', e.target.value === '' ? null : Number(e.target.value))} />
        </div>
        <div className="mt-4 space-y-4">
          <RoleCombobox
            label="Target roles"
            selected={bp.targetRoles}
            onChange={(v) => setBasic('targetRoles', v)}
            hint="Search and select from 600+ tech roles, or add custom titles."
          />
          <TagInput label="Cities you can work onsite in" tags={bp.preferredLocations} onChange={(v) => setBasic('preferredLocations', v)} placeholder="Add a city, e.g. your own" />
          <LanguageEditor languages={bp.languages || []} onChange={(v) => setBasic('languages', v)} />
        </div>
      </Card>

      <Card title="Where you can work" description="Your right to work, whether you would move, and where you'll take a job. Scoring uses these to rank roles you can't legally take lower; nothing is hidden.">
        <div className="space-y-6">
          <WorkAuthorizationEditor value={bp.workAuthorization} onChange={(v) => setBasic('workAuthorization', v)} />
          <div>
            <label className="mb-1.5 block text-sm font-medium text-stone-700 dark:text-stone-300">Would you relocate for a job?</label>
            <select value={bp.relocation || 'none'} onChange={(e) => setBasic('relocation', e.target.value)} className={SELECT_CLASS}>
              {RELOCATION_OPTIONS.map((r) => <option key={r} value={r}>{RELOCATION_LABELS[r]}</option>)}
            </select>
          </div>
          <PlacePicker selected={bp.allowedLocations || []} onChange={(v) => setBasic('allowedLocations', v)} />
        </div>
      </Card>

      <Card title="Parsed resume data" description="Extracted from your resume. Add or remove entries as needed.">
        <div className="space-y-6">
          <TagInput label="Skills" tags={pd.skills} onChange={(v) => setParsed('skills', v)} confidenceKey="skills" confidence={conf.skills} />
          <ListEditor label="Projects" items={pd.projects} onChange={(v) => setParsed('projects', v)} confidenceKey="projects" confidence={conf.projects} />
          <ListEditor label="Work experience" items={pd.workExperience} onChange={(v) => setParsed('workExperience', v)} confidenceKey="workExperience" confidence={conf.workExperience} />
          <ListEditor label="Education" items={pd.education} onChange={(v) => setParsed('education', v)} confidenceKey="education" confidence={conf.education} />
          <ListEditor label="Certifications" items={pd.certifications} onChange={(v) => setParsed('certifications', v)} confidenceKey="certifications" confidence={conf.certifications} />
          <ListEditor label="Links" items={pd.links} onChange={(v) => setParsed('links', v)} confidenceKey="links" confidence={conf.links} />
        </div>
      </Card>
    </div>
  )
}