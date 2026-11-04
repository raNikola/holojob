# Epic: HolyJobs UI Redesign & Design System

Status: **planning only**, recorded 2026-11-04. No GitHub issues are created. Implementation has not been approved. The title is the owner's; the app keeps its current name until the owner decides otherwise.

**Goal:** replace the custom styling and components with one Design System (shadcn/ui preset `b7CScIWmG` plus a semantic extension), with no change to behaviour, backend, APIs or routing.

## Scope

**In scope**

- Token layer, Design System components, global layout, and every screen's markup and styling.

**Out of scope**

- Behaviour, `src/modules/*` logic (only the class strings in `fitScore.js` and `engineShadow.js` change), Python, Node routes, data files, browser storage keys, new routing.
- New features, including what the waves add (Insufficient Data state, role filter, tracker rework).
- Renaming the app.
- Visual regression tooling, screenshot baselines and browser test suites (excluded by the [permanent policy](README.md#testing-and-browser-policy-permanent)).

## Business rules

| # | Rule |
|---|---|
| BR1 | No behaviour changes. Any accessibility gain from a primitive (Escape, focus trap) is listed in the slice report |
| BR2 | No colour or font outside the token layer |
| BR3 | Status keeps its text label; colour is never the only signal |
| BR4 | Fit, priority and status bands stay computed where they are today; the redesign only maps a result to a token |
| BR5 | Every AI, privacy and destructive confirm keeps its text, its condition and its `"confirm": true` path |
| BR6 | Never send more data anywhere: no change to AI context, redaction or payload whitelists |
| BR7 | No new browser storage key or cookie (`BROWSER_STORAGE_POLICY.md`; `browserStorageAllowlist.test.js`) |
| BR8 | Settings categories stay mounted; drafts survive switching. `useDraftDirty` guards stay |
| BR9 | `#/jobs/<id>` and Back keep working as today |
| BR10 | Each slice is its own branch and PR, testable alone. No long-lived branch |

## Verified facts

Checked on 2026-11-04 by reading the repo or running the CLI.

- Stack: React 19.2.7, Vite 8.0.16, Tailwind 4.3.0 with no config file, JavaScript, no router, no `components.json`.
- The preset resolves to `base-mira`, Base UI, `mist`, lucide, Lora, radius `0.625rem`.
- **Body font is Lora** (`html { @apply font-serif }`). The JSON endpoint alone does not show this; the CLI output does.
- Tokens are identical between the `vite` and `react-router` scaffolds.
- With `tsx: false` and `aliases.ui` set to `@/components/ds`, the CLI writes `.jsx` to `ds/` with types stripped (tried on `button` and `dialog`).
- 129 component files; 2,207 palette classes; 951 `dark:`.
- `--color-accent`, `--color-accent-hover` and `--color-border` have no consumers in `src/`.
- `ds/sidebar` as supplied writes a `sidebar_state` cookie and binds a keyboard shortcut.
- The scaffold's `theme-provider` writes a `localStorage` key `theme`.
- `button` and `input` default to `h-7`; the current `Button` has `min-h-[44px]`.
- `muted-foreground` on `muted` computes to 4.15:1 (light).

## Assumptions (not verified)

- Base UI primitives work under the repo's jsdom 24 test harness.
- The registry's lucide icon names exist in the repo's `lucide-react` 1.17.0.
- The bundle stays acceptable after adding Base UI and Lora (not measured).
- Lora's digits work with `tabular-nums`.
- Extension values sit well beside `mist` (a visual question for the owner).
- Reworking kit internals keeps the source-reading tests passing (14 test files read `src/` text directly).

## PO decisions

### Decided (2026-11-04)

1. Keep the current app name until the owner decides otherwise.
2. Apply the complete preset, colours and fonts.
3. Body font comes from the real CLI output: Lora.
4. Base UI primitives accepted.
5. Planning before Wave 0; implementation after the minimal Wave 0 backup.
6. No long-lived branch; small independent branches and PRs.
7. Design System = preset plus central semantic extension. No arbitrary colours in components.
8. Permanent testing and browser policy.

### Open PO decisions

| # | Decision | Why it matters | Recommendation |
|---|---|---|---|
| O1 | Approve the extension values and aliases in [TOKENS.md](TOKENS.md#part-2-extension-not-defined-by-the-preset) | Blocks the token slice | Approve, or adjust by eye once seen |
| O2 | Sequencing of slices against Waves 2 to 5 | Tasks D and E touch what those waves rewrite | Tasks A to C and H before or between; D after the Wave 2 UI; E with or after Wave 5 |
| O3 | Control size: preset `h-7` (28 px) or today's 44 px minimum | The app is used on a phone; the complete preset means small targets | Preset on desktop, 44 px on touch. This is a recorded deviation, so it needs your approval |
| O4 | Serif everywhere, confirmed once you see it | Follows from decision 2 and 3, and is larger than the earlier wording suggested: tables and numbers are Lora too | Decide after the first visible slice |
| O5 | May a mixed look be deployed between slices? | With no long-lived branch, `main` holds old and new together until screens are done | Merge freely, hold deploys until Tasks A and B are done, then your call per slice |
| O6 | Does Wave 7's Settings and UX work merge into Task H? | Otherwise Settings is touched twice | Merge |
| O7 | Colours with no meaning today (`violet`, `indigo`, `green` stat cards) go to neutral? | Removes decoration you may like | Yes |
| O8 | `muted-foreground` on `muted` at 4.15:1, a preset value below AA | Decision 2 keeps it | Keep, and avoid that pairing for body text |
| O9 | Ctrl/Cmd+B sidebar shortcut from the registry | Small behaviour addition | Leave out |

## Standard implementation choices

Claude's choices unless the owner objects:

- `src/components/ds/` for registry files; exact version pins; `shadcn` and `tw-animate-css` as dev dependencies.
- `native-select` before `select`.
- Keep the repo's dark variant until `dark:` colour uses are gone.
- No `sonner`, `cmdk` or `next-themes`.
- `window.confirm` stays in MVP.
- A ratchet test for palette classes.

---

# Phase 1 (MVP)

Each sub-task is one branch and PR. Each ends with lint, targeted Vitest and a "Not verified without a browser" list. Visual acceptance is **the owner's step**, never a Claude check.

## Task A: Design System foundations

Dependencies: minimal Wave 0 backup; approval of these docs; O1.

- **A1.** Tooling and tokens, additive.
- **A2.** Rework the `ui/` kit on `ds/`, same props: Button, Badge, Alert, Card, Input, Textarea, SelectField, Tabs, StatCard, then the rest. One or a few per PR.
- **A3.** Global cutover: Lora, radius scale, default border, surfaces. Remove Google Fonts and unused variables.

**Acceptance criteria**

- Given a clean checkout, when `npm ci` and `npm run build` run in the node container, then the build passes and needs no network call to the shadcn website.
- Given A1, when the token file is read by a test, then every preset token in `preset/index.generated.css` and every approved extension token exists with the same value.
- Given A1, when the source is searched, then nothing in the app imports `ds/button` yet and no existing file under `src/components/` changed.
- Given `ui/Button` after A2, when rendered with each current variant and with `disabled`, then it renders one `button`, fires `onClick` once when enabled and never when disabled, and passes through `type` and `aria-label`.
- Given `ui/Input` after A2, when rendered with `label`, `required` and `error`, then the label is linked by `id` and `aria-required`, `aria-invalid` and `aria-describedby` are set as today.
- Given `ui/SelectField` after A2, when a value is chosen, then `onChange` receives the value string, as today.
- Given any A slice, when the storage allowlist test runs, then it passes with no new key or `document.cookie` user.
- Given A3, when `index.html` is read, then it has no `fonts.googleapis.com` link.

## Task B: Global layout and navigation

Dependencies: A1, A2.

- **B1.** Sidebar and bottom bar. `ds/sidebar` with the [required edits](COMPONENTS.md#required-edits-to-registry-files).
- **B2.** TopBar, StorageNotice, demo banner, "More" sheet, `TooltipProvider`.

**Acceptance criteria**

- Given the sidebar, when it is collapsed and the app reloads, then it stays collapsed through `modules/sidebarState.js`, and no cookie is written.
- Given any nav item, when clicked, then `navigate` is called with the same view as today, and on a job page the page closes.
- Given a `#/jobs/<id>` URL, when the app loads, then the job page shows and Back returns to the previous view.
- Given the dark toggle, when clicked, then `dark` toggles on `<html>`.
- Given the "More" sheet, when an item is chosen, then the view changes and the sheet closes.

## Task C: Jobs list and filtering

Dependencies: A2, B. Coordinate `JobFilters.jsx` with Wave 3 (role filter) and the Active/All work.

- **C1.** JobTable and rows, on `ds/table`, mobile cards.
- **C2.** JobFilters, SalaryFilter, JobListControls, BulkActionsBar, summary.
- **C3.** PipelineOrchestrator, RescrapeProgress, health and import panels, AddJobDialog.

**Acceptance criteria**

- Given the existing `jobTable`, `jobsScreen.dom`, `keepAd.dom`, `salaryFilter*` and `manual*` tests, when they run, then they pass; any edit to them is listed with the reason.
- Given a list over 100 rows, when "Show more" is clicked, then the next batch appears and focus moves as today.
- Given select all, when used, then it states what it covers and acts on that set.
- Given a server-only row, when its actions show, then they are read-only with the same note and "Keep this ad" is offered.
- Given AddJobDialog, when "Extract the missing fields with AI" is used, then the confirm panel shows the same redacted text and nothing is sent without `"confirm": true`.
- Given migrated files, when the ratchet test runs, then they hold no palette class.

## Task D: Job Details and scoring UI

Dependencies: A2, C1, Wave 2 UI (O2).

- **D1.** Drawer on `ds/sheet`, JobDetailBody, Job Details page.
- **D2.** FitScore, badges, FitJudgement, EngineShadow; class strings in `fitScore.js`, `engineShadow.js` become tokens.

**Acceptance criteria**

- Given a label from `MATCH_LABELS`, when rendered, then `MATCH_LABEL_VARIANT` selects the same variant as today and the text label shows.
- Given a job with no score, when rendered, then `emptyLabel` shows.
- Given unsaved tracker input, when "Open full details" is clicked, then the guard asks first.
- Given a job missing from the stored list, when the drawer opens, then the button is disabled with the same tooltip.
- Given the drawer, when Escape is pressed, then it closes and focus returns to the opener (new, listed under BR1).
- Given a popup inside the panel, when it opens in a portal, then its text scale is checked by a test on the class it carries.
- Given a fit judge run, when confirmed, then the dialog lists the same data as today.

## Task E: Application Tracker

Dependencies: A2, D1, Wave 5 (O2). Do not restyle what Wave 5 is rewriting.

- **E1.** ApplicationTrackerPanel, Summary, Timeline.
- **E2.** ApplicationHome, Board, Statistics.

**Acceptance criteria**

- Given the tracker's forms, when dirty, then `useDraftDirty` reports it, and a field changed elsewhere keeps the typed value and shows "Reload fields".
- Given "Void", when clicked, then the same `window.confirm` text appears and voiding proceeds only on accept.
- Given a renamed stage, when shown, then its label shows and its key is unchanged.
- Given the board, when a stage changes, then the same API call is made as today.

## Task F: Profile and Resume management

Dependencies: A2. Coordinate with the Wave 6 profile import slices.

- **F1.** ProfileHome, ProfileForm, onboarding (Wizard, Welcome, Progress, Step), Questionnaire, Repository form, Review.
- **F2.** Import (Wizard, Review, Pdf, Paste, SourcePicker).
- **F3.** CvLibrary, CvAnalysisReview, CvAnalyzeDialog, ResumeLibrary.

**Acceptance criteria**

- Given a required field empty, when submitting, then the same error shows and `requiredFields.test.js` passes.
- Given CV analysis, when started, then the dialog shows the exact redacted text and the provider, and `/api/ai/cv-analyze` is not called without `"confirm": true`.
- Given a profile field, when edited, then `ConfidenceTag` hides as today.

## Task G: Tailoring and application preparation

Dependencies: A2, D1, Wave 6 Phase 4 protections for anything that changes the flow.

- **G1.** JobTailorActions, JobAIToolsPanel, ApplicationAIInsights.
- **G2.** AICommandCenter, CareerStrategyScreen.

**Acceptance criteria**

- Given a kept ad not in the scored file, when tailoring is asked for, then the same refusal text shows.
- Given "regenerate", when clicked, then the same confirm appears.
- Given any AI call, when `tests/js/aiRedaction.test.js` runs, then it passes unchanged.

## Task H: Settings and Sources

Dependencies: A2, B; O6.

- **H1.** SettingsHome shell.
- **H2.** Panels: AI budget and AI settings, Secrets, Job boards, Application settings, Scoring weights, Reset, Migration.

**Acceptance criteria**

- Given a draft in one category, when switching category, then the draft survives.
- Given `settingsRegistry.test.js`, when run, then it passes and section titles are verbatim.
- Given the search box, when used, then it only opens a section.
- Given a change that raises what the gate allows, when saved, then the 409 confirm list appears as today.
- Given SecretsPanel, when rendered, then no key value is in the DOM, and only the last 4 characters show as today.

## Task I: Remaining screens

Dependencies: A2, B. **I1 is the recommended pilot screen.**

- **I1.** Activity (well covered by DOM tests).
- **I2.** Dashboard, Intelligence.
- **I3.** Outreach.
- **I4.** Quality Audit.

**Acceptance criteria**

- Given `activityScreen.dom`, `activityLive.dom`, `useLiveRun.dom`, when run, then they pass.
- Given a running run, when "Cancel" is used, then the confirm appears and "Cancel requested" is not shown as "Cancelled".
- Given the outreach composer, when a contact is used, then the AI context still holds the placeholder `[CONTACT NAME]`.

## Task J: Responsive, accessibility and consistency

Runs alongside, and closes the epic.

- **J1.** Ratchet covers all of `src/components`; the temporary dark variant is replaced by the preset's.
- **J2.** Remove leftovers: `.font-display`, `--color-surface`, `--color-text`, and `dark:` colour variants.
- **J3.** Accessibility pass by code and tests.
- **J4.** Owner's visual, responsive and UX acceptance, screen by screen.

**Acceptance criteria**

- Given all of `src/`, when the ratchet test runs, then there are no palette classes, no hex and no `oklch()` outside the token layer.
- Given every icon-only button, when a test scans them, then each has an accessible name.
- Given the full gate, when run before merge, then it passes.
- Given J4, when the owner reviews, then acceptance is recorded by the owner. Claude does not report UI as visually approved.

# Later phases (optional)

- Replace `window.confirm` with `ds/alert-dialog`, one at a time.
- `ds/select` in place of `native-select`, where the owner asks.
- Toasts, breadcrumbs, a command palette: each a product decision.
- Charts using the preset's `--chart-*`, if charts are added.

# Dependency summary

```
Wave 0 backup + docs approved + O1
  -> A1 -> A2 -> A3
       A2 -> B -> I1 (pilot) -> C -> H
                                C -> D (after Wave 2 UI) -> E (with or after Wave 5)
                                     D -> G (Wave 6 protections for flow changes)
       A2 -> F (coordinate with Wave 6) ; I2-I4 any time after B
  all -> J
```
