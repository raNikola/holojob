# Design System

Status: **planning only** (2026-11-04). Nothing here is built. No application code, dependency, test or data was changed. The redesign has not started.

**Current preset: `b1a1cZcRs`.** It superseded `b7CScIWmG` on 2026-11-04 ([decision](../DECISIONS.md#design-system-preset-changed-to-b1a1czcrs-2026-11-04)). The old preset is not a live reference.

| Document | Content |
|---|---|
| [TOKENS.md](TOKENS.md) | Actual preset values, and the semantic extension proposed for owner approval |
| [COMPONENTS.md](COMPONENTS.md) | Component inventory: use shadcn, compose primitives, or keep custom |
| [MIGRATION_PLAN.md](MIGRATION_PLAN.md) | Every page and shared component: current state, target, risks, order |
| [REDESIGN_BACKLOG.md](REDESIGN_BACKLOG.md) | Epic, tasks, acceptance criteria, facts and assumptions, decisions |
| [preset/](preset/) | Reference snapshot of the preset, not wired into the app |

Decisions: [planning](../DECISIONS.md#design-system-and-ui-redesign-planning-2026-11-04), [preset change](../DECISIONS.md#design-system-preset-changed-to-b1a1czcrs-2026-11-04). Roadmap: [ROADMAP.md](../ROADMAP.md#roadmap-v2-recorded-2026-11-04).

## Overview

The goal is to replace the custom frontend styling and components with shadcn/ui as the single Design System. **Design System = the preset plus a central semantic extension** (fit score, job status, priority, success, warning, error), defined once in the token layer.

The redesign changes how the app looks and how its markup is built. It does not change behaviour, the backend, the APIs or the routing.

**Name:** the app keeps its current name until the owner decides otherwise. The repo says Holojob and `index.html` still says Career OS. The word "HolyJobs" appears only as the title of the epic the owner named, and nowhere in the repo.

## Preset and source

| Item | Value | Source |
|---|---|---|
| Preset ID | `b1a1cZcRs` | Owner |
| Style | `base-mira` | CLI output |
| Primitives | Base UI (`@base-ui/react`), accepted by the owner | CLI output |
| Base colour | `mist` | CLI output |
| Icons | `lucide` | CLI output |
| Accent theme | No name in the output. The values equal Tailwind's `blue` palette (primary is blue 700) | Compared with `tailwindcss/theme.css` |
| Fonts | Geist for everything: headings through `--font-heading: var(--font-sans)`, body through `html { @apply font-sans }` | CLI output |
| CLI used | `shadcn@4.23.0`, in `node:20-bookworm` (Node 20.20.2) | Run on 2026-11-04 |

`-t vite` was used because the app is a Vite app. The earlier check with `b7CScIWmG` showed a `template` only selects a scaffold, and the app has **no router and does not get one**. The `react-router` scaffold was not regenerated for this preset.

### How the preset was retrieved

In a throwaway container with `--security-opt label=disable`, mounting only a new empty scratch folder, so the container could not see the repo:

```
npx shadcn@4.23.0 init -t vite -p b1a1cZcRs -n ds-new -y --no-monorepo
```

The owner's official command, `pnpm dlx shadcn@latest apply --preset b1a1cZcRs -y`, was also run, only on a scratch project (`@latest` was 4.23.0).

**`apply` over an existing preset is not clean:** on a project that already had `b7CScIWmG`, it gave the same tokens but kept the old `@import` of Lora, the `--font-serif` line and the Lora dependency. Reasoning from that: when a preset changes, do not rely on `apply` alone; review the diff against `preset/`.

Nothing was installed into the frontend or copied into `src/`.

### Reproducing it from Git, without the website

Everything needed is in [preset/](preset/README.md), with `MANIFEST.sha256`:

- `init.b1a1cZcRs.json`: the raw answer of the official endpoint.
- `components.generated.json`: the `components.json` the CLI wrote.
- `index.generated.css`: the CSS the CLI wrote, with every token.
- `registry-base-mira/`: the source of all 38 components, as the CLI wrote it, plus the hook, `utils` and `theme-provider`.
- `shadcn-tailwind.4.23.0.css`: the file the CSS imports from the `shadcn` package.
- `locked-versions.json`: the locked direct dependencies.

The npm packages still come from the npm registry, not from Git. Once the first slice commits `src/components/ds/*`, `components.json` and the token file, **those committed files are the master**.

## Usage rules

1. Check [COMPONENTS.md](COMPONENTS.md) first. Use a Design System component if one fits, compose primitives if not, and add a custom component only with a recorded reason.
2. **No arbitrary colours inside components.** No hex, no `oklch()`, no Tailwind palette class (`stone-*`, `teal-*`, `emerald-*`, ...). Use semantic classes only (`bg-primary`, `text-muted-foreground`, `bg-success-subtle`).
3. No font outside the preset. No new `font-*` family.
4. No `dark:` for colour. Tokens switch with the theme; `dark:` stays only where layout or a preset component needs it.
5. Icons come from `lucide-react` only.
6. Behaviour stays where it is: `src/modules/*` holds logic. A migration changes markup, not modules.

## Naming

| What | Rule |
|---|---|
| Design System components | `src/components/ds/`, lower-case file names as the CLI writes them (`button.jsx`) |
| Existing kit | `src/components/ui/` stays; each file is reworked by hand in its own slice, keeping its props |
| Why `ds/`, not the CLI's default `ui/` | `button.jsx` beside `Button.jsx` breaks on case-insensitive disks and the CLI could overwrite existing files. Verified: with `aliases.ui` set to `@/components/ds` the CLI writes there |
| Semantic tokens | `--success`, `--success-subtle`, `--success-subtle-foreground`, and domain aliases such as `--fit-strong` |
| Language | JavaScript. `"tsx": false` in `components.json`. Verified: the CLI writes `.jsx` with the types stripped |

## Tokens and theme management

- **One token file.** Every colour, radius and font value lives in the token layer, once. Components read tokens.
- **Preset tokens are not edited by hand.** A preset change means regenerating and reviewing the diff against `preset/`.
- **Extension tokens** live in a separate, labelled block. They are marked "extension, not defined by the preset", and values need owner approval.
- **Domain aliases point at semantic tokens.** `--fit-strong: var(--success)`. Components never pick a colour for a job state; `src/modules/jobs/matchScore.js` picks the variant and the variant maps to a token.
- **Theme switching stays as it is:** the `.dark` class on `<html>` (`TopBar.jsx`). The CLI's `theme-provider` and `next-themes` are not added, because they write a browser storage key that is not on the allowlist.

## Reusable component rules

- A component goes in `ds/` only if it comes from the registry. Project compositions go in `ui/` or the feature folder.
- Logic stays out of `ds/`. The files there stay close to the registry source so a later diff is readable. Every edit to one is listed in [COMPONENTS.md](COMPONENTS.md#required-edits-to-registry-files).
- Props of `src/components/ui/*` stay stable while call sites migrate.
- `className` overrides may set layout (spacing, width). They may not set colour.

## Responsive guidelines

- Breakpoints stay Tailwind's defaults. The preset defines none; its `use-mobile` hook uses 768 px, the same width as `md` and the `DESKTOP` query in `JobTable.jsx`.
- Existing layout switches stay (table to cards, sidebar to bottom bar, Settings navigation to a `<select>`).
- **Control sizes are an open owner decision:** the preset's default button and input are `h-7` (28 px), and the current `Button` has `min-h-[44px]`.
- How it looks at a given width is the owner's acceptance, not Claude's.

## Accessibility guidelines

These can be checked without a browser, by functional tests:

- Dialogs and drawers have `role`, an accessible name, Escape to close, and focus returned on close. Base UI provides these; a jsdom test checks the wiring.
- Form fields keep `label`, `aria-required`, `aria-invalid` and `aria-describedby`, as `Input.jsx` and `SelectField.jsx` have today.
- Icon-only buttons keep an `aria-label`.
- Status is never colour alone: the text label stays (`FitScore`, `Badge`).
- Contrast is computed from token values ([TOKENS.md](TOKENS.md#computed-contrast)). A computed ratio is a number, not a visual approval.

## Testing and browser policy (permanent)

Owner decision, 2026-11-04.

**Responsibilities**

- Claude Code owns unit, integration, functional regression, build, lint and existing tests.
- The owner owns visual look and aesthetics, responsive look and UX acceptance, and final design approval.

**Browser use**

- Default: no browser tests. Use the existing Vitest, pytest and other automated tests.
- Run a browser only when a function cannot be reliably verified without it.
- No crawling all pages, no mass screenshots, no visual regression, no pixel comparison, no screenshot baseline.
- Maximum **one** targeted browser smoke test per implementation slice, only with a justified need. Additional browser tests only with the owner's approval.

**Reporting**

- Claude must state what it could not verify without a browser.
- Visually unverified UI must never be presented as visually approved.

## Rules for Claude Code and future AI developers

- Read this file and [COMPONENTS.md](COMPONENTS.md) before touching `src/components/**`.
- Run the shadcn CLI only with `components.json` present, so it writes to `ds/`. Never with `--overwrite` against `ui/`. Read the diff before committing.
- Do not add a dependency, a browser storage key, a cookie or a route as a side effect of adding a component.
- Do not change a test's meaning to fit new markup. A test that pins old markup is updated only to pin the same behaviour.
- Confirm dialogs for AI and privacy flows are never removed, merged or auto-confirmed.
- End each slice report with "Not verified without a browser" and hand the look to the owner.

## Integration proposal

### How the preset is committed

The first implementation slice commits `components.json` (with `tsx: false`, `aliases.ui` pointing at `@/components/ds`), the token file, the `cn` re-export and the generated components. `preset/` stays as the record of what the CLI originally produced.

### shadcn components to install

Listed per task in [COMPONENTS.md](COMPONENTS.md#install-list). Each is added in the slice that first uses it, never in bulk.

**Not installed:** `sonner` (would bring `next-themes`), `command` (would bring `cmdk`), `drawer` (`sheet` covers the side panels), the `theme-provider`.

### New dependencies

Versions locked in the CLI's scaffold on 2026-11-04. Pin exact versions.

| Package | Version | Where | Why | Note |
|---|---|---|---|---|
| `@base-ui/react` | 1.9.0 | dependencies | Primitives | 21 MB on disk; imported by subpath. Bundle effect not measured |
| `class-variance-authority` | 0.7.1 | dependencies | Variants | |
| `cn` | 0.4.0 | dependencies | Class merging | Zero dependencies, no install script, maintained by shadcn. Replaces `clsx` + `tailwind-merge`. Young: 0.5.2 was already published on the day of this check |
| `@fontsource-variable/geist` | 5.3.0 | dependencies | Self-hosted font | OFL-1.1. Serbian Latin and Cyrillic letters and tabular digits checked in the font files |
| `tw-animate-css` | 1.4.0 | devDependencies | CSS at build time | |
| `shadcn` | 4.23.0 | devDependencies | `shadcn/tailwind.css` is imported at build time | 32 dependencies of its own. The `frontend` stage of the `Dockerfile` runs a full `npm ci`, and the runtime stage `npm ci --omit=dev`, so it does not reach the running image |

Existing versions meet the peer requirements (React 19.2.7, Tailwind 4.3.0, Vite 8.0.16). The scaffold locked `lucide-react` 1.68.0 and the repo has 1.17.0; whether the icon names the registry uses exist in 1.17.0 is checked in the first slice.

### Config changes needed

- `@` alias in `vite.config.js` and `vitest.config.js`. `jsconfig.json` declares it, and neither build config does.
- `src/index.css` becomes the token layer. `--color-accent`, `--color-accent-hover` and `--color-border` go away. Measured: they have no consumers. Only `var(--color-surface)` (6) and `var(--color-text)` (1) are used.
- `--font-sans` **collides by name:** the repo sets it to DM Sans in `src/index.css` and the preset sets it to Geist. Changing it flips the whole app at once, so it moves only in the global cutover.
- `index.html`: the Google Fonts links go away once Geist is applied, which also removes an external request from every page load.

### Custom components

Replace, compose or preserve: see [COMPONENTS.md](COMPONENTS.md).

### Migration without breaking behaviour

1. Add the Design System beside the existing kit; nothing imports it yet.
2. Rework `src/components/ui/*` internals on top of it, one component per slice, keeping props. This moves most call sites at once (`Button` is imported by 54 files, `Card` by 43, `Alert` by 39).
3. Apply the global preset rules (font, radius, default border, surfaces).
4. Migrate screens one at a time, removing palette classes and `dark:` colour variants.
5. A ratchet test holds the directories already migrated free of palette classes.

### Branching

**No long-lived redesign branch** (owner decision). After these docs are reviewed and approved, implementation goes through **small independent branches and PRs**, one slice each, each independently testable, so it does not collide with the scoring and matching roadmap. Each PR needs the owner's approval to merge or deploy.

Between slices, `main` can hold a mix of old and new styling. Whether that state may be deployed is an open owner decision ([REDESIGN_BACKLOG.md](REDESIGN_BACKLOG.md#open-po-decisions)).

### Testing and regression strategy

Functional only, under the policy above:

- Per slice: the targeted Vitest files and lint, as the repo's commit policy says.
- Before a push or merge: the repo's full gate.
- Existing tests stay the regression net. 8 test files use `getByRole`, `getByText` or `querySelector`, 6 are `*.dom.test.*`, and 14 read `src/` source text directly, so they may pin markup. Each such failure is judged: same behaviour, new markup means updating the test; changed behaviour means fixing the code.
- New functional tests: each adapter keeps its props and events; dialogs close, restore focus and keep their `confirm` paths; the token file holds every required name; a ratchet test finds no palette classes in migrated directories.
- jsdom and Base UI portals: `vitest.config.js` defaults to `environment: 'node'`, and DOM tests opt in. Whether Base UI primitives work under jsdom 24 has not been tried; the first slice tries it.

### Proposed lines for CLAUDE.md

**Not applied.** The owner decides. Proposed text:

```markdown
## Design System

`docs/design-system/README.md` is the rule set for all UI work; read it and `COMPONENTS.md` before touching
`src/components/**`. Design System = shadcn/ui preset `b1a1cZcRs` (`base-mira`, Base UI, Geist, lucide) plus a central
semantic extension (fit score, job status, priority, success, warning, error), defined once in the token layer.
No arbitrary colours or fonts in components: semantic classes only, no hex, no Tailwind palette classes. Registry
components live in `src/components/ds/`; `src/components/ui/` keeps its props. No new router, browser storage key or
cookie as a side effect of a component. Implementation goes through small independent branches and PRs, never a
long-lived redesign branch.

## UI testing and browser policy

- Claude Code owns unit, integration, functional regression, build, lint and existing tests.
- The owner owns visual look and aesthetics, responsive look and UX acceptance, and final design approval.
- Default: no browser tests. Use the existing Vitest, pytest and other automated tests.
- Run a browser only when a function cannot be reliably verified without it. No crawling all pages, no mass
  screenshots, no visual regression, no pixel comparison, no screenshot baseline.
- Maximum ONE targeted browser smoke test per implementation slice, only with a justified need. Additional browser
  tests only with the owner's approval.
- Claude must state what it could not verify without a browser. Visually unverified UI must never be presented as
  visually approved.
```

## Interaction with the roadmap waves

| Wave | Interaction | Handling |
|---|---|---|
| 0 | Implementation waits for the minimal backup (owner decision) | Task A starts after it. Planning comes first |
| 1 | Discovery safety: no UI overlap expected, except texts on Activity and Jobs | Activity slice carries over whatever Wave 1 adds |
| 2 | Insufficient Data state, scoring correctness and hard/soft requirements add UI to Jobs and Job Details | **Conflict.** Needs a state and a token. Task D waits for the Wave 2 UI; the token is reserved now (`--fit-insufficient`) |
| 3 | Three-level role filter adds to `JobFilters.jsx` | Migrate filters first or after, not at the same time |
| 5 | Application Tracking reworks the tracker panel and removes the shadow badge | **Conflict.** Task E does not restyle what Wave 5 is about to rewrite |
| 6 | Profile import slices; Phase 4 fact gate and confirm for AI and application flows | Task F and G wait for the flows being rebuilt there |
| 7 | UX, Settings, (d) overlap the Settings task | **Overlap.** One owner decision on whether Wave 7's Settings work merges into Task H |
| 8 | Step 5 server master changes the data flow of Jobs and Profile | Markup-only slices do not conflict if `modules/*` stays untouched |

The other waves are not reordered. Sequencing of slices against Waves 2 to 5 stays an open owner decision.
