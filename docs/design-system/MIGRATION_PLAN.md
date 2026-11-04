# Migration plan

Status: **planning only** (2026-11-04). Nothing is migrated. Tasks (A to J) are defined in [REDESIGN_BACKLOG.md](REDESIGN_BACKLOG.md). Each row moves in small independent branches and PRs. Testing is functional only, under the [permanent policy](README.md#testing-and-browser-policy-permanent); visual appearance is the PO's acceptance.

Implementation is **not authorized**. It needs a separate approval, the minimal Wave 0 backup and the PO's verification of the O1 values.

## Audit summary

| Area | Finding |
|---|---|
| Framework | React 19.2.7 with `react-dom`, JavaScript, `jsconfig.json` with `checkJs` |
| Build | Vite 8.0.16, `@vitejs/plugin-react`, `@tailwindcss/vite`, custom `discoveryApiPlugin` |
| Routing | **None.** `view` state in `src/App.jsx`, saved through `modules/appNavigation.js`; `#/jobs/<id>` through `modules/jobs/jobRoute.js` and `useJobRoute`. Custom events open views (`OPEN_SETTINGS_EVENT`, ...) |
| Tailwind | v4, CSS-first, no config file |
| Styling | `src/index.css` (60 lines): `@theme` with fonts and a few colours, `.dark` overrides, `.panel-text-up` scale, fade-in. Everything else is utility classes in JSX |
| Volume | 129 component files, 1,909 `className`, 2,207 palette classes, 951 `dark:` |
| Palette classes by family | stone 1,523, teal 279, amber 185, red 107, emerald 68, violet 26, indigo 16, sky 4, green 4 (counted on bg, text, border, ring, from, to) |
| Custom variables in use | `var(--color-surface)` 6, `var(--color-text)` 1. `--color-accent`, `--color-accent-hover`, `--color-border` have none |
| UI libraries | None. `lucide-react` for icons (73 files) |
| Fonts | DM Sans and Sora from Google Fonts in `index.html` |
| Theme | `.dark` on `<html>`, toggled in `TopBar.jsx` |
| Tests | `tests/js` (Vitest; `environment: 'node'` by default, jsdom per file). 6 `*.dom.test.*`, 8 files query the DOM, 14 read `src/` source text. No visual regression, and none will be added |

## Compatibility issues with the preset

| # | Issue | Handling |
|---|---|---|
| 1 | Cost is in the markup: tokens alone do not reach palette classes | Screen slices remove them; ratchet test holds the result |
| 2 | Preset redefines `--color-accent` and `--color-border` | No consumers today (measured), so they are removed |
| 3 | Registry is `.tsx`; repo is JS | `tsx: false`. Verified to write `.jsx` |
| 4 | `@` alias only in `jsconfig.json` | Add to `vite.config.js` and `vitest.config.js` |
| 5 | Default `ui/` holds the existing kit | `aliases.ui` to `@/components/ds`. Verified |
| 6 | `shadcn/tailwind.css` makes the CLI package a build input | Pinned dev dependency; `frontend` Docker stage has it, runtime stage does not |
| 7 | Global rules in the preset CSS: `html { font-sans }`, `* { border-border }`, body colours, radius scale | Held back until slice A3, so A1 and A2 stay additive |
| 8 | `.panel-text-up` is inherited, and portals escape it; `panelTextScale.test.js` pins it | Handled in D1 |
| 9 | Base UI under jsdom 24 not tried | First slice tries it |
| 10 | `ds/sidebar` writes a cookie; `theme-provider` and `next-themes` write storage | Edit the first, leave out the others |
| 11 | Settings keeps categories mounted; tracker forms guard drafts; `window.confirm` is synchronous | Keep custom shell, `keepMounted` on tabs, `window.confirm` stays in MVP |
| 12 | Preset `h-7` against today's 44 px minimum | Decided (O3): 44 x 44 px minimum on mobile, compact desktop allowed. A recorded edit to `ds/` controls |
| 13 | `dark` variant differs from the repo's | Keep the repo's until `dark:` colour uses are gone |
| 14 | **New with this preset.** `--font-sans` is defined by both the repo (DM Sans) and the preset (Geist), and `body` in `src/index.css` reads it | `--font-sans` and the Geist import move only in the separate font migration, A4 (O4). Until then `--font-heading` resolves to DM Sans, which is harmless because nothing uses it |
| 15 | Dark `--primary` as text is 2.23:1 on the background; 141 `text-teal-*` classes need a target | Decided (O10): judged per use, never replaced blindly. Links use `--primary-strong` (U1, pending) |
| 17 | Measured contrast failures in specific pairs | Decided (O8): [smallest corrections](TOKENS.md#part-3-contrast-o8), centralized, pending PO verification |
| 16 | `ds/scroll-area` has an unused `React` import (`tsc` TS6133 in the scaffold) | Same in both presets. Fix if lint flags it after JS conversion |

## Pages

Complexity: S, M, L. Order is the recommended slice order; see [dependencies](REDESIGN_BACKLOG.md#dependency-summary).

| Order | Page (`view`) | Entry and main files | Current | Target | Required changes | Dependencies | Risks | Size |
|---|---|---|---|---|---|---|---|---|
| 1 | Shell | `layout/AppShell`, `Sidebar`, `TopBar`, `StorageNotice` | Custom, 9 raw buttons in AppShell, hand-built "More" | `ds/sidebar` (edited), `ds/sheet`, tokens | Compose, keep state module | A2 | Cookie and shortcut in the registry file; `sidebarState.test.js` | M |
| 2 | Activity | `activity/*` | Cards, tables, polling, cancel | `ds/card`, `ds/table`, Badge | Markup only | A2, B | DOM tests pin text and roles; a good pilot | S |
| 3 | Jobs | `jobs/JobDiscoveryScreen`, `JobTable`, `JobFilters`, `SalaryFilter`, `JobListControls`, `BulkActionsBar`, `JobDiscoverySummary`, `PipelineOrchestrator`, `RescrapeProgress`, `JobImportPanel`, `AddJobDialog` | Largest screen, 512 + 361 lines, long-list logic | `ds/table`, `ds/dialog`, kit | Keep logic, replace markup | A2, B, Wave 3 coordination | Most-used screen; source-reading tests; Active/All logic; AI confirm panel | L |
| 4 | Settings | `settings/*`, `ai/AIBudgetPanel`, `AISettingsPanel`, selectors, usage | Custom shell, mounted categories | Keep shell, tokens, kit | Panels migrate one by one | A2, B, coordinated with Wave 7 (O6) | Drafts; 409 confirm lists; secrets display | L |
| 5 | Job Details page and drawer | `jobs/JobDetailsPage`, `JobDetailDrawer`, `JobDetailBody`, `FitScore`, `JobScoreBadge`, `AuthorizationBadge`, `FitJudgementCard`, `FitJudgementSection`, `EngineShadowSection`, `ManualJobSection`, `JobDescription` | Hand-built drawer, panel type scale | `ds/sheet`, kit, extension tokens | Class strings in `fitScore.js`, `engineShadow.js` | C1, Wave 2 UI | Portal escapes `.panel-text-up`; focus trap is new; Wave 2 adds Insufficient Data; Wave 5 removes shadow badge | L |
| 6 | Applications | `applications/ApplicationHome`, `ApplicationBoard`, `ApplicationStatistics`; `jobs/ApplicationTrackerPanel`, `ApplicationTrackingSummary`, `ApplicationTimeline`, `ApplicationDashboard` | Tables, board, stateful forms | Kit, `ds/table` | Markup only | D1, **Wave 5** | Wave 5 rewrites this; draft guards; stage labels | M |
| 7 | Profile | `profile/*` | 66 palette classes in the form, 7 raw buttons, 6 selects | Kit, `native-select` | Markup only | A2 | Required-field tests; browser-held profile data | M |
| 8 | Profile edit and Onboarding | `onboarding/*`, `questionnaire/*`, `import/*`, `repositories/RepositoryForm`, `review/ReviewScreen` | Wizard, focus handling, PDF import | Kit | Markup only | A2, Wave 6 profile import | Wave 6 may rebuild import; wizard focus logic | L |
| 9 | My CVs | `cvs/*` | 70 palette classes in the review | Kit, `ds/dialog` | Markup only | A2 | CV analysis confirm and exact-text display | M |
| 10 | Resumes | `resumes/ResumeLibrary` | Simple list | Kit | Markup only | A2 | Low | S |
| 11 | AI tools on a job | `jobs/JobTailorActions`, `ai/JobAIToolsPanel`, `ai/ApplicationAIInsights` | Panels | Kit | Markup only | D1, Wave 6 for flows | Regenerate confirm; tailoring refusal | M |
| 12 | Career Strategy | `ai/CareerStrategyScreen` | Cards | Kit | Markup only | A2 | Low | S |
| 13 | AI Copilot | `ai/AICommandCenter` | Chat | Kit | Markup only | A2 | Low | S |
| 14 | Dashboard | `dashboard/DashboardHome` | Mostly kit (2 palette classes) | Kit carries it | Little | A2 | Low | S |
| 15 | Intelligence | `intelligence/*` | Cards, tabs | Kit, `ds/tabs` | Markup only | A2 | `stretch` indigo goes neutral (O7) | M |
| 16 | Outreach | `outreach/*` | Lists, composer, drawer | Kit, `ds/sheet` | Markup only | A2, B | `[CONTACT NAME]` placeholder; contact privacy | M |
| 17 | Quality Audit | `quality/*` | Cards, table, drawer | Kit, `ds/sheet`, `ds/table` | Markup only | A2, B | Low | M |
| n/a | Gates | `demo/DemoBootstrapGate`, `jobs/JobTextGate` | Small | Tokens | Colour only | A2 | Must render before any screen | S |

**Main user flows to keep working:** discover and re-scrape; filter and review jobs; keep an ad; add a job by hand and fill from an ad; open details; score and judge; tailor; mark applied and track; onboard and edit the profile; analyse a CV; configure AI and keys; restore a backup.

## Shared components (`src/components/ui`)

"Importers" is the number of files importing it.

| Order | Component | Importers | Current | Target | Changes | Risks | Size |
|---|---|---|---|---|---|---|---|
| 1 | `Button` | 54 | Palette variants, `min-h-[44px]` | Adapter over `ds/button` | Map variants; 44 px on mobile (O3) | `className` overrides at call sites | S |
| 2 | `Badge` | 17 | Six variants, palette | Adapter over `ds/badge` plus extension | Add variants | Meaning map must not move | S |
| 3 | `Alert` | 39 | Three variants, icons | Adapter over `ds/alert` | Map variants | Low | S |
| 4 | `Card` | 43 | `title`, `description`, `action` | Adapter over `ds/card` | Keep props | Heading font change | S |
| 5 | `StatCard` | 6 | `accent` prop with palette | `ds/card` | Drop palette `accent`; neutral by default (O7) | Low | S |
| 6 | `Input` | 10 | Label, error, aria | `ds/input`, `ds/field` | Keep props and id rule | `requiredFields.test.js` | S |
| 7 | `Textarea` | 6 | As Input | `ds/textarea` | Same | Low | S |
| 8 | `SelectField` | 8 | Native select | `ds/native-select` | Same | Low | S |
| 9 | `Tabs` | 4 | Custom buttons, `active`, `onChange` | `ds/tabs` | Keep props; check `keepMounted` | Roles change to `tab` | S |
| 10 | `InfoTip` | 3 | Hover, focus, tap, glyph, action | `ds/tooltip` or `ds/popover` | Keep modes | Tap on touch | M |
| 11 | `SortableTh` | 3 | Sort header | Custom, in `ds/table` | Tokens | `tableSort.test.js` | S |
| 12 | `OperationConsole` | 4 | Log view | Keep custom | Tokens | Low | S |
| 13 | `RequiredMark` | 1 | Mark | Keep custom | Tokens | Low | S |
| 14 | `ConfidenceTag` | 1 | Over Badge | Keep custom | None | Low | S |
| 15 | `TagInput` | 1 | Custom | Compose | Tokens | Keyboard | S |
| 16 | `MultiSelectDropdown` | 1 | Custom with documented keyboard | Keep custom, compose | Tokens, `ds/popover` | Keyboard and focus | M |
| 17 | `MultiSelectField` | 1 | Custom | Keep custom, compose | Tokens | Keyboard | M |
| 18 | `RoleCombobox` | 1 | Custom | `ds/combobox` if tests hold | Tokens at least | Keyboard | M |

## Slice order

1. **A1** additive foundations (the [proposed first slice](#proposed-first-implementation-slice)).
2. **A2** kit adapters: Button, Badge, Alert, Card, then the rest of the table above.
3. **B** shell.
4. **A3** global rules (radius, default border, surfaces). It comes after the kit and shell so the visible change lands on Design System components. The look is reviewed by the PO.
4a. **A4** global font migration to Geist: a separate controlled step, with functional regression verification and PO visual approval. It may run at any point after A3.
5. **I1** Activity as the pilot screen.
6. **C** Jobs, **H** Settings.
7. **D** Job Details, after the Wave 2 UI.
8. **E** Tracker, with or after Wave 5.
9. **F**, **G**, **I2** to **I4**, as the waves allow.
10. **J** closes.

## Proposed first implementation slice

Not built and not authorized. It needs a separate implementation approval, the minimal Wave 0 backup and PO verification of the O1 values. On its own small branch and PR:

- Add the dependencies, exact versions, and `components.json` (`tsx: false`, `aliases.ui` to `@/components/ds`).
- Add the `@` alias to `vite.config.js` and `vitest.config.js`.
- Add the `cn` re-export.
- Add the preset tokens, the verified extension tokens and the verified contrast corrections to the token layer. Remove the three unused variables. **Hold back** the global rules (`html { font-sans }`, `* { border-border }`, body colours, radius scale) and the fonts (`--font-sans` and the Geist import).
- Add one `ds/button.jsx`, imported by nothing in the app.

**Verification, functional only:**

- `ds/button` renders under jsdom and fires clicks (this also answers the Base UI and jsdom question).
- A test confirms the token file holds every required name with the snapshot's value, except the held-back ones it lists.
- A test confirms `--font-sans` is still DM Sans after this slice, so Geist is not active (O4).
- A test confirms the 44 x 44 px minimum classes are on `ds/button` for mobile (O3).
- `contrast_check.py`, run against the values committed, reports 0 applicable pairs below target.
- The storage allowlist test still passes.
- Lint, targeted Vitest and build pass.

**No browser is used.** Colour tokens are not used by any screen yet. No visible change is intended, and Claude cannot confirm that without a browser, so the report says so and the PO reviews. Rollback is reverting the one PR.

# Appendix: every component file

Generated from `src/components` on 2026-11-04. Palette classes count the families stone, teal, amber, red, emerald, violet, indigo, sky and green.

| File | Lines | button | input | select | textarea | table | Palette classes | `dark:` |
|---|---|---|---|---|---|---|---|---|
| `activity/ActivityScreen.jsx` | 143 | 2 | 0 | 0 | 0 | 0 | 10 | 5 |
| `activity/CancelRun.jsx` | 52 | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `activity/LiveRunPanel.jsx` | 89 | 0 | 0 | 0 | 0 | 1 | 6 | 3 |
| `activity/RunDetails.jsx` | 154 | 0 | 0 | 0 | 0 | 1 | 12 | 6 |
| `ai/AIBudgetPanel.jsx` | 266 | 0 | 6 | 1 | 0 | 3 | 10 | 2 |
| `ai/AICommandCenter.jsx` | 141 | 1 | 1 | 0 | 0 | 0 | 24 | 11 |
| `ai/AIFeatureToggles.jsx` | 29 | 0 | 1 | 0 | 0 | 0 | 4 | 1 |
| `ai/AIHealthStatus.jsx` | 43 | 0 | 0 | 0 | 0 | 0 | 10 | 4 |
| `ai/AIModelSelector.jsx` | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ai/AIProviderSelector.jsx` | 41 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| `ai/AISettingsPanel.jsx` | 197 | 0 | 1 | 0 | 0 | 0 | 10 | 3 |
| `ai/AIUsageDashboard.jsx` | 34 | 0 | 0 | 0 | 0 | 0 | 5 | 2 |
| `ai/ApplicationAIInsights.jsx` | 56 | 0 | 0 | 0 | 0 | 0 | 9 | 4 |
| `ai/CareerStrategyScreen.jsx` | 126 | 0 | 0 | 0 | 0 | 0 | 12 | 3 |
| `ai/JobAIToolsPanel.jsx` | 263 | 0 | 0 | 0 | 0 | 0 | 21 | 7 |
| `applications/ApplicationBoard.jsx` | 140 | 1 | 0 | 1 | 0 | 0 | 36 | 18 |
| `applications/ApplicationHome.jsx` | 222 | 0 | 0 | 0 | 0 | 1 | 23 | 10 |
| `applications/ApplicationStatistics.jsx` | 98 | 0 | 0 | 0 | 0 | 2 | 23 | 8 |
| `cvs/CvAnalysisReview.jsx` | 253 | 0 | 1 | 0 | 0 | 0 | 70 | 29 |
| `cvs/CvAnalyzeDialog.jsx` | 103 | 3 | 0 | 0 | 0 | 0 | 29 | 13 |
| `cvs/CvLibrary.jsx` | 267 | 2 | 2 | 0 | 0 | 0 | 35 | 15 |
| `dashboard/DashboardHome.jsx` | 112 | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `demo/DemoBootstrapGate.jsx` | 57 | 0 | 0 | 0 | 0 | 0 | 3 | 1 |
| `import/ImportReview.jsx` | 298 | 3 | 2 | 4 | 0 | 0 | 48 | 22 |
| `import/ImportWizard.jsx` | 107 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `import/PasteStep.jsx` | 38 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| `import/PdfStep.jsx` | 51 | 0 | 1 | 0 | 0 | 0 | 12 | 3 |
| `import/SourcePicker.jsx` | 36 | 1 | 0 | 0 | 0 | 0 | 14 | 6 |
| `intelligence/AtsKeywordsCard.jsx` | 45 | 0 | 0 | 0 | 0 | 0 | 16 | 8 |
| `intelligence/CandidateIntelligenceScreen.jsx` | 181 | 2 | 0 | 0 | 0 | 0 | 13 | 6 |
| `intelligence/IntelligenceEmptyState.jsx` | 25 | 0 | 0 | 0 | 0 | 0 | 8 | 4 |
| `intelligence/IntelligenceSummaryCard.jsx` | 60 | 0 | 0 | 0 | 0 | 0 | 13 | 6 |
| `intelligence/IntelligenceTabs.jsx` | 29 | 1 | 0 | 0 | 0 | 0 | 11 | 6 |
| `intelligence/RoleStrategyCard.jsx` | 37 | 0 | 0 | 0 | 0 | 0 | 20 | 10 |
| `intelligence/SearchStrategyCard.jsx` | 94 | 0 | 0 | 0 | 0 | 0 | 23 | 9 |
| `intelligence/SkillsMapCard.jsx` | 37 | 0 | 0 | 0 | 0 | 0 | 4 | 2 |
| `jobs/AddJobDialog.jsx` | 239 | 2 | 0 | 0 | 0 | 0 | 26 | 12 |
| `jobs/ApplicationDashboard.jsx` | 18 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `jobs/ApplicationTimeline.jsx` | 20 | 0 | 0 | 0 | 0 | 0 | 7 | 3 |
| `jobs/ApplicationTrackerPanel.jsx` | 345 | 0 | 0 | 4 | 0 | 0 | 27 | 13 |
| `jobs/ApplicationTrackingSummary.jsx` | 110 | 0 | 0 | 0 | 0 | 0 | 13 | 6 |
| `jobs/AuthorizationBadge.jsx` | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `jobs/BulkActionsBar.jsx` | 40 | 0 | 0 | 0 | 0 | 0 | 6 | 3 |
| `jobs/EngineShadowSection.jsx` | 166 | 0 | 0 | 0 | 0 | 0 | 47 | 18 |
| `jobs/FitJudgementCard.jsx` | 201 | 4 | 0 | 0 | 0 | 0 | 50 | 22 |
| `jobs/FitJudgementSection.jsx` | 89 | 0 | 0 | 0 | 0 | 0 | 31 | 12 |
| `jobs/FitScore.jsx` | 17 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| `jobs/JobDescription.jsx` | 42 | 1 | 0 | 0 | 0 | 0 | 8 | 3 |
| `jobs/JobDetailBody.jsx` | 168 | 0 | 0 | 0 | 0 | 0 | 35 | 10 |
| `jobs/JobDetailDrawer.jsx` | 89 | 2 | 0 | 0 | 0 | 0 | 12 | 7 |
| `jobs/JobDetailsPage.jsx` | 118 | 0 | 0 | 0 | 0 | 0 | 8 | 4 |
| `jobs/JobDiscoveryScreen.jsx` | 513 | 3 | 0 | 0 | 0 | 0 | 21 | 11 |
| `jobs/JobDiscoverySummary.jsx` | 79 | 0 | 0 | 0 | 0 | 0 | 60 | 28 |
| `jobs/JobEmptyState.jsx` | 28 | 0 | 0 | 0 | 0 | 0 | 14 | 7 |
| `jobs/JobFilters.jsx` | 283 | 3 | 1 | 0 | 0 | 0 | 26 | 10 |
| `jobs/JobImportPanel.jsx` | 65 | 0 | 1 | 0 | 0 | 0 | 10 | 5 |
| `jobs/JobListControls.jsx` | 56 | 1 | 2 | 0 | 0 | 0 | 17 | 6 |
| `jobs/JobScoreBadge.jsx` | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `jobs/JobTable.jsx` | 362 | 3 | 3 | 0 | 0 | 1 | 66 | 28 |
| `jobs/JobTailorActions.jsx` | 173 | 1 | 0 | 0 | 0 | 0 | 21 | 9 |
| `jobs/JobTextGate.jsx` | 41 | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `jobs/JobUrlImport.jsx` | 97 | 0 | 1 | 0 | 1 | 0 | 23 | 11 |
| `jobs/KeepAdButton.jsx` | 28 | 1 | 0 | 0 | 0 | 0 | 5 | 2 |
| `jobs/ManualJobSection.jsx` | 111 | 0 | 0 | 0 | 0 | 0 | 8 | 2 |
| `jobs/PipelineHealthPanel.jsx` | 56 | 0 | 0 | 0 | 0 | 0 | 9 | 3 |
| `jobs/PipelineOrchestrator.jsx` | 330 | 0 | 0 | 1 | 0 | 0 | 32 | 15 |
| `jobs/RescrapeProgress.jsx` | 67 | 1 | 0 | 0 | 0 | 0 | 16 | 7 |
| `jobs/SalaryFilter.jsx` | 132 | 2 | 2 | 0 | 0 | 0 | 24 | 8 |
| `layout/AppShell.jsx` | 117 | 9 | 0 | 0 | 0 | 0 | 41 | 20 |
| `layout/Sidebar.jsx` | 147 | 3 | 0 | 0 | 0 | 0 | 36 | 18 |
| `layout/StorageNotice.jsx` | 48 | 1 | 0 | 0 | 0 | 0 | 18 | 9 |
| `layout/TopBar.jsx` | 31 | 1 | 0 | 0 | 0 | 0 | 8 | 4 |
| `onboarding/OnboardingWizard.jsx` | 278 | 1 | 0 | 0 | 0 | 0 | 10 | 5 |
| `onboarding/ProgressBar.jsx` | 45 | 1 | 0 | 0 | 0 | 0 | 14 | 6 |
| `onboarding/StepLayout.jsx` | 11 | 0 | 0 | 0 | 0 | 0 | 4 | 2 |
| `onboarding/WelcomeStep.jsx` | 120 | 0 | 0 | 0 | 0 | 0 | 16 | 8 |
| `outreach/ContactCard.jsx` | 63 | 1 | 0 | 0 | 0 | 0 | 21 | 8 |
| `outreach/ContactDetailDrawer.jsx` | 98 | 2 | 0 | 0 | 1 | 0 | 13 | 7 |
| `outreach/ContactList.jsx` | 67 | 0 | 1 | 1 | 0 | 0 | 7 | 4 |
| `outreach/FollowUpPanel.jsx` | 44 | 0 | 0 | 0 | 0 | 0 | 9 | 4 |
| `outreach/LinkedInSearchLinks.jsx` | 33 | 0 | 0 | 0 | 0 | 0 | 8 | 3 |
| `outreach/ManualContactForm.jsx` | 124 | 0 | 5 | 2 | 1 | 0 | 33 | 16 |
| `outreach/OutreachActivityTimeline.jsx` | 42 | 0 | 0 | 0 | 0 | 0 | 9 | 3 |
| `outreach/OutreachComposer.jsx` | 128 | 0 | 0 | 1 | 1 | 0 | 14 | 6 |
| `outreach/OutreachDashboard.jsx` | 210 | 2 | 0 | 1 | 0 | 0 | 27 | 13 |
| `outreach/RelatedContactsPanel.jsx` | 204 | 0 | 3 | 0 | 0 | 0 | 27 | 12 |
| `profile/CompleteProfileCard.jsx` | 27 | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `profile/ProfileForm.jsx` | 287 | 7 | 3 | 6 | 0 | 0 | 66 | 30 |
| `profile/ProfileHome.jsx` | 162 | 0 | 0 | 0 | 0 | 0 | 29 | 13 |
| `quality/AtsScorePanel.jsx` | 28 | 0 | 0 | 0 | 0 | 0 | 4 | 1 |
| `quality/AuditDetailDrawer.jsx` | 82 | 2 | 0 | 0 | 0 | 0 | 31 | 13 |
| `quality/CoverLetterQualityPanel.jsx` | 25 | 0 | 0 | 0 | 0 | 0 | 7 | 2 |
| `quality/JobLeadQualityPanel.jsx` | 19 | 0 | 0 | 0 | 0 | 0 | 4 | 1 |
| `quality/OutreachQualityPanel.jsx` | 28 | 0 | 0 | 0 | 0 | 0 | 8 | 2 |
| `quality/QualityDashboard.jsx` | 257 | 1 | 0 | 0 | 0 | 1 | 36 | 13 |
| `quality/QualityScoreCard.jsx` | 21 | 0 | 0 | 0 | 0 | 0 | 15 | 7 |
| `quality/ResumeQualityPanel.jsx` | 25 | 0 | 0 | 0 | 0 | 0 | 7 | 2 |
| `questionnaire/QuestionField.jsx` | 86 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `questionnaire/QuestionnaireForm.jsx` | 299 | 2 | 0 | 0 | 0 | 0 | 32 | 12 |
| `repositories/RepositoryForm.jsx` | 93 | 2 | 1 | 0 | 0 | 0 | 17 | 7 |
| `resumes/ResumeLibrary.jsx` | 101 | 0 | 0 | 0 | 0 | 0 | 16 | 7 |
| `review/ReviewScreen.jsx` | 211 | 1 | 0 | 0 | 0 | 0 | 23 | 9 |
| `settings/ApplicationMigrationPanel.jsx` | 103 | 0 | 0 | 0 | 0 | 0 | 6 | 3 |
| `settings/ApplicationSettingsPanel.jsx` | 228 | 0 | 3 | 0 | 0 | 0 | 36 | 14 |
| `settings/CompleteProfilePanel.jsx` | 21 | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `settings/JobBoardsPanel.jsx` | 137 | 1 | 1 | 0 | 0 | 0 | 24 | 10 |
| `settings/ResetProfilePanel.jsx` | 113 | 0 | 1 | 0 | 0 | 0 | 17 | 8 |
| `settings/ScoringWeightsPanel.jsx` | 126 | 0 | 1 | 0 | 0 | 0 | 8 | 3 |
| `settings/SecretsPanel.jsx` | 388 | 0 | 1 | 0 | 0 | 0 | 26 | 10 |
| `settings/SettingsHome.jsx` | 354 | 2 | 3 | 1 | 0 | 0 | 53 | 23 |
| `settings/SettingsLink.jsx` | 11 | 1 | 0 | 0 | 0 | 0 | 2 | 1 |
| `ui/Alert.jsx` | 21 | 0 | 0 | 0 | 0 | 0 | 18 | 9 |
| `ui/Badge.jsx` | 11 | 0 | 0 | 0 | 0 | 0 | 24 | 12 |
| `ui/Button.jsx` | 10 | 1 | 0 | 0 | 0 | 0 | 19 | 8 |
| `ui/Card.jsx` | 15 | 0 | 0 | 0 | 0 | 0 | 7 | 4 |
| `ui/ConfidenceTag.jsx` | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ui/InfoTip.jsx` | 65 | 1 | 0 | 0 | 0 | 0 | 20 | 8 |
| `ui/Input.jsx` | 27 | 0 | 1 | 0 | 0 | 0 | 9 | 4 |
| `ui/MultiSelectDropdown.jsx` | 126 | 2 | 2 | 0 | 0 | 0 | 25 | 11 |
| `ui/MultiSelectField.jsx` | 101 | 3 | 1 | 0 | 0 | 0 | 37 | 16 |
| `ui/OperationConsole.jsx` | 46 | 0 | 0 | 0 | 0 | 0 | 9 | 1 |
| `ui/RequiredMark.jsx` | 10 | 0 | 0 | 0 | 0 | 0 | 4 | 1 |
| `ui/RoleCombobox.jsx` | 144 | 2 | 1 | 0 | 0 | 0 | 31 | 14 |
| `ui/SelectField.jsx` | 31 | 0 | 0 | 1 | 0 | 0 | 9 | 4 |
| `ui/SortableTh.jsx` | 28 | 1 | 0 | 0 | 0 | 0 | 4 | 2 |
| `ui/StatCard.jsx` | 12 | 0 | 0 | 0 | 0 | 0 | 8 | 4 |
| `ui/Tabs.jsx` | 21 | 1 | 0 | 0 | 0 | 0 | 11 | 6 |
| `ui/TagInput.jsx` | 40 | 1 | 1 | 0 | 0 | 0 | 12 | 7 |
| `ui/Textarea.jsx` | 25 | 0 | 0 | 0 | 1 | 0 | 9 | 4 |
