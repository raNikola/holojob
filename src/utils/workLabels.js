import geography from '../data/geography.json'
import { REMOTE } from './workAuthorization'

// Display names for the work-authorization and location fields, shared by the
// profile form and the profile preview.
const COUNTRY_OPTIONS = geography.countries
  .map(({ code, name }) => ({ code, name }))
  .sort((a, b) => a.name.localeCompare(b.name))
const REGION_OPTIONS = Object.entries(geography.regions).map(([code, region]) => ({ code, name: region.name }))
// A right to work is held for a country, or for the EU as a whole.
export const JURISDICTION_OPTIONS = [...REGION_OPTIONS.filter((r) => r.code === 'EU'), ...COUNTRY_OPTIONS]
export const PLACE_OPTIONS = [{ code: REMOTE, name: 'Remote' }, ...REGION_OPTIONS, ...COUNTRY_OPTIONS]
export const placeName = (code) => PLACE_OPTIONS.find((option) => option.code === code)?.name || code
export const jurisdictionName = (code) => JURISDICTION_OPTIONS.find((option) => option.code === code)?.name || code

export const BASIS_LABELS = {
  citizen: 'Citizen',
  permanent_resident: 'Permanent resident',
  work_permit: 'I hold a work permit or visa',
  other: 'Other',
}
export const RELOCATION_LABELS = {
  none: 'No: only my own cities, or remote',
  abroad: 'Yes, to another country (not within my own)',
  anywhere: 'Yes, anywhere',
}
