// Whether the Jobs screen and the other screens read the server's list (docs/redesign/JOBS_LIST_SERVER_PLAN.md). ON: the screens that depended on the whole stored list
// work without it (P4) and the browser-only worked ads are in the list (requirement 8). Demo data and "no API" never reach the server's list (the route answers 404 in demo
// mode, and each screen works from the browser's own rows when it gets no answer). The switch stays only so the tests can run the list the browser works out itself; it
// is not a setting, and the plan lists its removal with the local "API on" path it selects.
let active = true

export const isServerListActive = () => active
export const setServerListActive = (value) => { active = Boolean(value) }
