# Epic: UI Redesign & Design System

**Status: POSTPONED. Epic, all Tasks and all Sub-tasks are To Do.** Nothing is built and nothing is authorized. Work starts only when the PO explicitly authorizes implementation and every [prerequisite](#implementation-prerequisites) is met. No GitHub issues are created.

**All colours are PROVISIONAL.** Every semantic token value and contrast correction is for planning only. No current value is permanently approved. Before implementation, the complete palette is reviewed again, finalized and approved by the PO.

**Goal:** replace the custom styling and components with one Design System (shadcn/ui preset `b1a1cZcRs` plus a semantic extension), with no change to behaviour, backend, APIs or routing.

The roadmap entry is [Epic: UI Redesign & Design System](../ROADMAP.md#epic-ui-redesign--design-system---deferred--to-do). Priorities of scoring, matching, discovery and application tracking are not changed by this Epic.

## Scope

**In scope:** token layer, Design System components, global layout, and the markup and styling of every screen.

**Out of scope:**

- Behaviour, `src/modules/*` logic (only the class strings in `fitScore.js` and `engineShadow.js` change), Python, Node routes, data files, browser storage keys, new routing.
- New features, including what the waves add (Insufficient Data state, role filter, tracker rework).
- Renaming the app.
- Playwright, screenshot baselines, visual regression tooling and Chrome tests.

## Implementation prerequisites

Future gates. **These are not authorization to execute anything now.** All six must be met before the first Sub-task starts.

| # | Gate | Status |
|---|---|---|
| G1 | Complete and verify the minimal Wave 0 backup | To Do |
| G2 | Finalize and approve the colour palette | To Do |
| G3 | Recalculate contrast ratios against the final colours (`preset/contrast_check.py`) | To Do |
| G4 | Verify the semantic-token mappings | To Do |
| G5 | Recheck framework and dependency compatibility | To Do |
| G6 | Obtain separate PO implementation approval | To Do |

## Approved decisions

PO decisions. Full text: [DECISIONS.md](../DECISIONS.md#design-system-final-planning-decisions-epic-postponed-2026-11-04).

| # | Decision |
|---|---|
| Preset | `b1a1cZcRs`: Blue / Mist / Geist / Base UI / Lucide. Complete preset, within the provisional colour rule |
| Name | The app keeps its current name until the PO decides otherwise |
| Branching | Small independent branches and PRs; no long-lived branch |
| O1 | Token structure, aliases and values approved **for planning purposes only**. `--input` follows C2, with no separate border token. C1, C3 and U1 to U3 stay planning recommendations. `--fit-insufficient` is neutral. `--app-state-offer-accepted` may use success. Warning text on muted surfaces gets a better margin. **Values remain provisional** |
| O2 | Controlled sequencing: foundations first; Jobs and Scoring UI aligned with the scoring roadmap; tracker aligned with the tracker changes; small slices that avoid conflicts with parallel work |
| O3 | Minimum 44 x 44 px interactive target on mobile; compact desktop controls allowed where appropriate |
| O4 | Geist for headings, body, tables, forms and numerical data; global activation in a separate slice, with functional regression verification and PO visual approval |
| O5 | Temporary mixed UI allowed during development; the final release is visually consistent |
| O6 | Settings redesign coordinated with the Settings roadmap (Wave 7) to avoid duplicate work |
| O7 | Neutral cards and surfaces by default; semantic colours only where they carry meaning (fit, status, priority, errors) |
| O8 | WCAG AA (4.5:1 normal text, 3:1 applicable non-text UI); smallest centralized corrections; no palette redesign; the original Cyan preset is not characterized as defective |
| O9 | No sidebar keyboard shortcut during migration; existing navigation and the browser storage policy are preserved |
| O10 | Accessible replacement for legacy teal: semantic or neutral text, accessible links, primary Blue for actions and fills where contrast is sufficient; never replaced blindly |
| Testing | See [Testing responsibilities](README.md#testing-and-browser-policy-permanent). Browser testing needs separate explicit authorization |

## Verified technical facts

Checked on 2026-11-04 by reading the repo or running the CLI. These can go stale; G5 rechecks them.

- Stack: React 19.2.7, Vite 8.0.16, Tailwind 4.3.0 with no config file, JavaScript, no router, no `components.json`.
- The preset resolves to `base-mira`, Base UI, `mist`, lucide, Geist, radius `0.625rem`, with `shadcn@4.23.0`.
- Body font is Geist (`html { @apply font-sans }`). `--font-sans` is defined by both the repo (DM Sans) and the preset.
- Geist has Serbian Latin and Cyrillic letters and a `tnum` feature (read from the font files).
- With `tsx: false` and `aliases.ui` set to `@/components/ds`, the CLI writes `.jsx` to `ds/` with types stripped.
- The preset's CSS builds in a scratch project with Vite 8.3.5 and Tailwind 4.3.4.
- 129 component files; 2,207 palette classes; 951 `dark:`.
- `--color-accent`, `--color-accent-hover` and `--color-border` have no consumers in `src/`.
- `ds/sidebar` as supplied writes a `sidebar_state` cookie and binds a keyboard shortcut. The scaffold's `theme-provider` writes a `localStorage` key `theme`.
- `button` and `input` default to `h-7`; the current `Button` has `min-h-[44px]`.
- Contrast measured by `preset/contrast_check.py` from the committed snapshot: with the provisional corrections, 0 applicable pairs stay below target.

**Not verified:** Base UI under the repo's jsdom 24; the registry's icon names in `lucide-react` 1.17.0; a build with the repo's Vite and Tailwind versions; bundle size in this app; whether kit rework keeps the 14 source-reading tests passing; how anything looks.

## Future recommendations

Claude's recommendations for implementation, unless the PO objects. Not decisions.

- `src/components/ds/` for registry files; exact version pins; `shadcn` and `tw-animate-css` as dev dependencies.
- `native-select` before `select`; `window.confirm` stays in MVP.
- Keep the repo's dark variant until `dark:` colour uses are gone.
- No `sonner`, `cmdk` or `next-themes`.
- A ratchet test for palette classes.
- Sub-task T8.3 (Activity) as the pilot screen.
- Placement of the screens the nine Tasks do not name, as listed under each Task. This is a planning choice the PO can move.

## Business rules

| # | Rule |
|---|---|
| BR1 | No behaviour changes. Any accessibility gain from a primitive (Escape, focus trap) is listed in the slice report |
| BR2 | No colour or font outside the token layer |
| BR3 | Interactive targets are at least 44 x 44 px on mobile; compact on desktop where appropriate |
| BR4 | Text meets 4.5:1 and applicable non-text UI 3:1, measured programmatically against the final palette |
| BR5 | Status keeps its text label; colour is never the only signal |
| BR6 | Fit, priority and status bands stay computed where they are today; the redesign only maps a result to a token |
| BR7 | Every AI, privacy and destructive confirm keeps its text, its condition and its `"confirm": true` path |
| BR8 | Never send more data anywhere: no change to AI context, redaction or payload whitelists |
| BR9 | No new browser storage key or cookie (`BROWSER_STORAGE_POLICY.md`; `browserStorageAllowlist.test.js`) |
| BR10 | Settings categories stay mounted; drafts survive switching. `useDraftDirty` guards stay |
| BR11 | `#/jobs/<id>` and Back keep working as today |
| BR12 | Coexistence of old and new UI is temporary; the final release is visually consistent |

## Functional requirements

| # | Requirement |
|---|---|
| FR1 | Registry components live in `src/components/ds/`, isolated from existing custom components until migration |
| FR2 | `src/components/ui/*` keep their props while their internals move to `ds/` |
| FR3 | All colours come from one token layer; domain aliases point at the semantic scale |
| FR4 | The theme stays the `.dark` class on `<html>` |
| FR5 | Each slice is its own branch and PR, testable alone |

## Definition of Done

**A Sub-task is Done when:**

1. The acceptance criteria that apply to it pass as automated tests, and any test edit is listed with its reason.
2. Targeted Vitest and lint pass.
3. No palette class remains in the files it migrated.
4. The report lists what could not be verified without a browser. Visually unverified UI is never presented as visually approved.
5. The PO has reviewed the look and approved the merge.

**A Task is Done when:** all its MVP Sub-tasks are Done, and the full gate passes before its last merge (full pytest, full Vitest, lint, build, `contrast_check.py` at 0).

**The Epic is Done when:** all nine Tasks are Done, no palette class, hex or `oklch()` remains outside the token layer, the release is visually consistent, and the PO has given final design approval.

## Revalidation after the final palette

The final palette may change any value, so this work is rechecked once G2 is met. Marked on each Sub-task below.

| Mark | Meaning | What is rechecked |
|---|---|---|
| **R1** | Defines token values | Every value in `TOKENS.md`, C1 to C3, and the token consistency test |
| **R2** | Maps states to tokens | The alias table it uses still carries the same meaning (G4) |
| **R3** | Depends on a measured pair or usage rule | `contrast_check.py` still passes for its pairs (G3), and U1 to U3 are still needed |
| None | No colour decision | Not rechecked |

---

# Tasks

Every Task and Sub-task below is **To Do**. Dependencies other than the gates are listed per Task. All Tasks depend on G1 to G6.

| Task | Depends on | Aligned with |
|---|---|---|
| T1 Design System Integration & Foundations | Gates | |
| T2 Application Layout & Navigation | T1.2 | |
| T3 Jobs Listing & Filtering | T1.2, T2 | Wave 3 role filter |
| T4 Job Details & Scoring UI | T1.2, T3.1 | Wave 2 UI |
| T5 Application Tracker | T1.2, T4.1 | Wave 5 |
| T6 Profile & Resume Management | T1.2 | Wave 6 profile import |
| T7 Tailoring & Application Preparation | T1.2, T2, T4.1 | Wave 6 Phase 4 protections |
| T8 Settings & Sources | T1.2, T2 | Wave 7 |
| T9 Responsive, Accessibility & Visual Consistency | All | |

## T1: Design System Integration & Foundations (To Do)

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T1.1 | MVP | To Do | Gates | **R1, R3** | Tooling and tokens, additive. Dependencies, `components.json`, `@` alias, `cn`, one `ds/button` that nothing imports |
| T1.2 | MVP | To Do | T1.1 | **R2, R3** | Rework the `ui/` kit on `ds/`, same props: Button, Badge, Alert, Card, Input, Textarea, SelectField, Tabs, StatCard, then the rest |
| T1.3 | MVP | To Do | T1.2, T2 | **R1, R3** | Global rules: radius scale, default border, surfaces. Remove unused variables |
| T1.4 | MVP | To Do | T1.3 | None | Global font migration to Geist in one change (`--font-sans`, the import, removing Google Fonts). A separate slice, with functional regression verification and PO visual approval |
| T1.5 | Later | To Do | T1.2 | **R3** | `ds/select` in place of `native-select`, where the PO asks |

**Acceptance criteria**

- Given a clean checkout, when `npm ci` and `npm run build` run in the node container, then the build passes and needs no network call to the shadcn website.
- Given T1.1, when a test reads the token file, then every preset token and every final extension token exists with the approved value, and held-back items are listed.
- Given T1.1, when the source is searched, then nothing in the app imports `ds/button` and no existing file under `src/components/` changed.
- Given `ui/Button` after T1.2, when rendered with each current variant and with `disabled`, then it renders one `button`, fires `onClick` once when enabled and never when disabled, and passes through `type` and `aria-label`.
- Given `ui/Input` after T1.2, when rendered with `label`, `required` and `error`, then the label is linked by `id` and `aria-required`, `aria-invalid` and `aria-describedby` are set as today.
- Given `ui/SelectField` after T1.2, when a value is chosen, then `onChange` receives the value string, as today.
- Given `ds/` controls, when a test reads them, then the mobile minimum of 44 x 44 px is present.
- Given any T1 slice, when the storage allowlist test runs, then it passes with no new key or `document.cookie` user.
- Given T1.1, T1.2 or T1.3, when `src/index.css` is read, then `--font-sans` is still DM Sans.
- Given T1.4, when `index.html` is read, then it has no `fonts.googleapis.com` link, `--font-sans` is Geist, and the full functional regression passes. Visual approval is recorded by the PO.

## T2: Application Layout & Navigation (To Do)

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T2.1 | MVP | To Do | T1.2 | **R3** | Sidebar and bottom bar: `ds/sidebar` with the [required edits](COMPONENTS.md#required-edits-to-registry-files) |
| T2.2 | MVP | To Do | T2.1 | **R3** | TopBar, StorageNotice, demo banner, "More" sheet, `TooltipProvider`, Dashboard, the two gates |

**Acceptance criteria**

- Given the sidebar, when it is collapsed and the app reloads, then it stays collapsed through `modules/sidebarState.js`, and no cookie is written.
- Given the sidebar, when Ctrl or Cmd+B is pressed, then nothing changes.
- Given any nav item, when clicked, then `navigate` is called with the same view as today, and on a job page the page closes.
- Given a `#/jobs/<id>` URL, when the app loads, then the job page shows and Back returns to the previous view.
- Given the dark toggle, when clicked, then `dark` toggles on `<html>`.
- Given the "More" sheet, when an item is chosen, then the view changes and the sheet closes.

## T3: Jobs Listing & Filtering (To Do)

Coordinate `JobFilters.jsx` with Wave 3 and the Active/All work.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T3.1 | MVP | To Do | T1.2, T2 | **R2, R3** | JobTable and rows on `ds/table`, mobile cards |
| T3.2 | MVP | To Do | T3.1 | **R2, R3** | JobFilters, SalaryFilter, JobListControls, BulkActionsBar, summary (stat cards neutral) |
| T3.3 | MVP | To Do | T3.1 | **R3** | PipelineOrchestrator, RescrapeProgress, health and import panels, AddJobDialog |

**Acceptance criteria**

- Given the existing `jobTable`, `jobsScreen.dom`, `keepAd.dom`, `salaryFilter*` and `manual*` tests, when they run, then they pass; any edit to them is listed with the reason.
- Given a list over 100 rows, when "Show more" is clicked, then the next batch appears and focus moves as today.
- Given select all, when used, then it states what it covers and acts on that set.
- Given a server-only row, when its actions show, then they are read-only with the same note and "Keep this ad" is offered.
- Given AddJobDialog, when "Extract the missing fields with AI" is used, then the confirm panel shows the same redacted text and nothing is sent without `"confirm": true`.
- Given migrated files, when the ratchet test runs, then they hold no palette class.

## T4: Job Details & Scoring UI (To Do)

Aligned with the scoring roadmap: waits for the Wave 2 UI. Does not build the Insufficient Data state, only styles it.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T4.1 | MVP | To Do | T1.2, T3.1 | **R3** | Drawer on `ds/sheet`, JobDetailBody, Job Details page |
| T4.2 | MVP | To Do | T4.1, Wave 2 UI | **R2, R3** | FitScore, badges, FitJudgement, EngineShadow; class strings in `fitScore.js` and `engineShadow.js` become tokens |

**Acceptance criteria**

- Given a label from `MATCH_LABELS`, when rendered, then `MATCH_LABEL_VARIANT` selects the same variant as today and the text label shows.
- Given Insufficient Data, when rendered, then it uses neutral styling and is told apart from a low score by its label and by showing no score as a band.
- Given a job with no score, when rendered, then `emptyLabel` shows.
- Given unsaved tracker input, when "Open full details" is clicked, then the guard asks first.
- Given a job missing from the stored list, when the drawer opens, then the button is disabled with the same tooltip.
- Given the drawer, when Escape is pressed, then it closes and focus returns to the opener (new, listed under BR1).
- Given a popup inside the panel, when it opens in a portal, then a test confirms it carries the panel's text-scale class.
- Given a fit judge run, when confirmed, then the dialog lists the same data as today.

## T5: Application Tracker (To Do)

Aligned with the tracker changes: does not restyle what Wave 5 is rewriting.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T5.1 | MVP | To Do | T1.2, T4.1, Wave 5 | **R2, R3** | ApplicationTrackerPanel, Summary, Timeline |
| T5.2 | MVP | To Do | T5.1 | **R2, R3** | ApplicationHome, Board, Statistics |

**Acceptance criteria**

- Given the tracker's forms, when dirty, then `useDraftDirty` reports it, and a field changed elsewhere keeps the typed value and shows "Reload fields".
- Given "Void", when clicked, then the same `window.confirm` text appears and voiding proceeds only on accept.
- Given a renamed stage, when shown, then its label shows, its key is unchanged, and its token goes by kind of state.
- Given the board, when a stage changes, then the same API call is made as today.

## T6: Profile & Resume Management (To Do)

Coordinate with the Wave 6 profile import slices.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T6.1 | MVP | To Do | T1.2 | **R3** | ProfileHome, ProfileForm, onboarding, Questionnaire, Repository form, Review |
| T6.2 | MVP | To Do | T6.1, Wave 6 import | **R3** | Import (Wizard, Review, Pdf, Paste, SourcePicker) |
| T6.3 | MVP | To Do | T1.2 | **R3** | CvLibrary, CvAnalysisReview, CvAnalyzeDialog, ResumeLibrary |
| T6.4 | MVP | To Do | T1.2 | **R2, R3** | Intelligence screens |

**Acceptance criteria**

- Given a required field empty, when submitting, then the same error shows and `requiredFields.test.js` passes.
- Given CV analysis, when started, then the dialog shows the exact redacted text and the provider, and `/api/ai/cv-analyze` is not called without `"confirm": true`.
- Given a profile field, when edited, then `ConfidenceTag` hides as today.

## T7: Tailoring & Application Preparation (To Do)

Anything that changes the flow waits for the Wave 6 Phase 4 protections.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T7.1 | MVP | To Do | T1.2, T4.1 | **R3** | JobTailorActions, JobAIToolsPanel, ApplicationAIInsights |
| T7.2 | MVP | To Do | T1.2 | **R3** | AICommandCenter, CareerStrategyScreen |
| T7.3 | MVP | To Do | T1.2, T2 | **R3** | Outreach |
| T7.4 | MVP | To Do | T1.2, T2 | **R2, R3** | Quality Audit |

**Acceptance criteria**

- Given a kept ad not in the scored file, when tailoring is asked for, then the same refusal text shows.
- Given "regenerate", when clicked, then the same confirm appears.
- Given any AI call, when `tests/js/aiRedaction.test.js` runs, then it passes unchanged.
- Given the outreach composer, when a contact is used, then the AI context still holds the placeholder `[CONTACT NAME]`.

## T8: Settings & Sources (To Do)

Coordinated with the Settings roadmap (Wave 7) to avoid duplicate work.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T8.1 | MVP | To Do | T1.2, T2 | **R3** | SettingsHome shell |
| T8.2 | MVP | To Do | T8.1 | **R3** | Panels: AI budget and AI settings, Secrets, Job boards, Application settings, Scoring weights, Reset, Migration |
| T8.3 | MVP | To Do | T1.2, T2 | **R2, R3** | Activity: source run history, recommended as the pilot screen |

**Acceptance criteria**

- Given a draft in one category, when switching category, then the draft survives.
- Given `settingsRegistry.test.js`, when run, then it passes and section titles are verbatim.
- Given the search box, when used, then it only opens a section.
- Given a change that raises what the gate allows, when saved, then the 409 confirm list appears as today.
- Given SecretsPanel, when rendered, then no key value is in the DOM, and only the last 4 characters show as today.
- Given `activityScreen.dom`, `activityLive.dom`, `useLiveRun.dom`, when run, then they pass.
- Given a running run, when "Cancel" is used, then the confirm appears and "Cancel requested" is not shown as "Cancelled".

## T9: Responsive, Accessibility & Visual Consistency (To Do)

Runs alongside the others, and closes the Epic.

| Sub-task | Phase | Status | Depends on | Revalidate | Content |
|---|---|---|---|---|---|
| T9.1 | MVP | To Do | T1 to T8 | **R3** | Ratchet covers all of `src/components`; the temporary dark variant is replaced by the preset's; leftovers removed (`.font-display`, `--color-surface`, `--color-text`, `dark:` colour variants) |
| T9.2 | MVP | To Do | T9.1 | **R3** | Accessibility pass by code, tests and `contrast_check.py` |
| T9.3 | MVP | To Do | T9.2 | **R1, R2, R3** | PO's visual, UX and responsive acceptance, screen by screen |
| T9.4 | Later | To Do | T9.1 | None | Replace `window.confirm` with `ds/alert-dialog`, one at a time |

**Acceptance criteria**

- Given all of `src/`, when the ratchet test runs, then there are no palette classes, no hex and no `oklch()` outside the token layer.
- Given every icon-only button, when a test scans them, then each has an accessible name.
- Given the final token file, when `contrast_check.py` runs against it, then 0 applicable pairs are below target.
- Given the full gate, when run before merge, then it passes.
- Given T9.3, when the PO reviews, then acceptance is recorded by the PO. Claude does not report UI as visually approved.

Toasts, breadcrumbs, a command palette and charts are not Sub-tasks: each would be a separate product decision.

# Dependency summary

```
G1 to G6 (all To Do)
  -> T1.1 -> T1.2 -> T2 -> T1.3 -> T1.4 (separate font slice)
     T1.2 + T2 -> T8.3 (pilot) -> T3 -> T8.1, T8.2
     T3.1 + Wave 2 UI -> T4 -> T5 (with or after Wave 5)
     T1.2 -> T6 (coordinate with Wave 6)
     T4.1 -> T7 (Wave 6 protections for flow changes)
  all -> T9
```
