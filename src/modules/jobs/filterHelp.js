/** Tooltip texts of the Jobs filters. Each says what the filter does in `filterJobs` (jobFilters.js), not what it might be expected to do. */
export const FILTER_HELP = {
  searchText: 'Keeps jobs whose title, company, location, source, provider, description or search term contains this text. Case does not matter.',
  location: 'Keeps jobs whose location text contains this text. Case does not matter; a job with no location is hidden once you type here.',
  site: 'Where the ad was found: LinkedIn, Infostud, or a company career page such as nebius. Tick several to see them together; none ticked shows all.',
  status: 'Your own status for the job. “applied” lists jobs that have an application in the tracker, and shows nothing until the tracker has loaded.',
  priority: 'The priority the scorer gave each job, P1 first. The numbers count all jobs with that priority, whatever the other filters say. None ticked shows every priority.',
  minScore: 'Hides jobs whose match score is below this number (0 to 100). A job with no score counts as 0, so it is hidden too.',
  remoteOnly: 'Shows only jobs the ad marks as remote.',
  provider: 'The connector that fetched the ad: jobspy (LinkedIn), greenhouse, ashby, workable or infostud. Tick several to see them together; none ticked shows all.',
  matchLabel: 'Shows only jobs with this label (Excellent, Strong, Good, Weak, Reject), which comes from the match score.',
  salary: 'The pay the scorer read from the ad, in EUR per month. A job matches when its pay range overlaps yours; a single figure must lie inside it. Jobs with no readable pay follow “Include jobs without salary”.',
  hideClosed: 'Hides only jobs confirmed closed: seen in an earlier search and no longer listed. Jobs whose status is unknown stay, and so do jobs outside your places or needing a visa.',
  hideNeedsVisa: 'Hides jobs the work-authorization check marked “No visa” (the ad refuses sponsorship) or “Needs visa” (the ad says nothing). Other jobs stay.',
}
