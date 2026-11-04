# Tokens

Part 1 lists the **actual preset values**, from the CLI's output in [preset/index.generated.css](preset/index.generated.css) (`shadcn@4.23.0`, preset `b1a1cZcRs`, retrieved 2026-11-04). Part 2 is the **extension, not defined by the preset**. Part 3 is the measured contrast and the proposed corrections. None of this is in the app.

**All extension values and contrast corrections are PROVISIONAL**, approved for planning purposes only. Before implementation, the complete palette is reviewed again, finalized and approved by the PO, and these tables are revalidated.

# Part 1: Preset values

## Colours

| Token | Light | Dark |
|---|---|---|
| `--background` | `oklch(1 0 0)` | `oklch(0.148 0.004 228.8)` |
| `--foreground` | `oklch(0.148 0.004 228.8)` | `oklch(0.987 0.002 197.1)` |
| `--card` | `oklch(1 0 0)` | `oklch(0.218 0.008 223.9)` |
| `--card-foreground` | `oklch(0.148 0.004 228.8)` | `oklch(0.987 0.002 197.1)` |
| `--popover` | `oklch(1 0 0)` | `oklch(0.218 0.008 223.9)` |
| `--popover-foreground` | `oklch(0.148 0.004 228.8)` | `oklch(0.987 0.002 197.1)` |
| `--primary` | `oklch(0.488 0.243 264.376)` | `oklch(0.424 0.199 265.638)` |
| `--primary-foreground` | `oklch(0.97 0.014 254.604)` | `oklch(0.97 0.014 254.604)` |
| `--secondary` | `oklch(0.967 0.001 286.375)` | `oklch(0.274 0.006 286.033)` |
| `--secondary-foreground` | `oklch(0.21 0.006 285.885)` | `oklch(0.985 0 0)` |
| `--muted` | `oklch(0.963 0.002 197.1)` | `oklch(0.275 0.011 216.9)` |
| `--muted-foreground` | `oklch(0.56 0.021 213.5)` | `oklch(0.723 0.014 214.4)` |
| `--accent` | `oklch(0.963 0.002 197.1)` | `oklch(0.275 0.011 216.9)` |
| `--accent-foreground` | `oklch(0.218 0.008 223.9)` | `oklch(0.987 0.002 197.1)` |
| `--destructive` | `oklch(0.577 0.245 27.325)` | `oklch(0.704 0.191 22.216)` |
| `--border` | `oklch(0.925 0.005 214.3)` | `oklch(1 0 0 / 10%)` |
| `--input` | `oklch(0.925 0.005 214.3)` | `oklch(1 0 0 / 15%)` |
| `--ring` | `oklch(0.723 0.014 214.4)` | `oklch(0.56 0.021 213.5)` |

### Charts

| Token | Light | Dark |
|---|---|---|
| `--chart-1` | `oklch(0.809 0.105 251.813)` | `oklch(0.809 0.105 251.813)` |
| `--chart-2` | `oklch(0.623 0.214 259.815)` | `oklch(0.623 0.214 259.815)` |
| `--chart-3` | `oklch(0.546 0.245 262.881)` | `oklch(0.546 0.245 262.881)` |
| `--chart-4` | `oklch(0.488 0.243 264.376)` | `oklch(0.488 0.243 264.376)` |
| `--chart-5` | `oklch(0.424 0.199 265.638)` | `oklch(0.424 0.199 265.638)` |

### Sidebar

| Token | Light | Dark |
|---|---|---|
| `--sidebar` | `oklch(0.987 0.002 197.1)` | `oklch(0.218 0.008 223.9)` |
| `--sidebar-foreground` | `oklch(0.148 0.004 228.8)` | `oklch(0.987 0.002 197.1)` |
| `--sidebar-primary` | `oklch(0.546 0.245 262.881)` | `oklch(0.623 0.214 259.815)` |
| `--sidebar-primary-foreground` | `oklch(0.97 0.014 254.604)` | `oklch(0.97 0.014 254.604)` |
| `--sidebar-accent` | `oklch(0.963 0.002 197.1)` | `oklch(0.275 0.011 216.9)` |
| `--sidebar-accent-foreground` | `oklch(0.218 0.008 223.9)` | `oklch(0.987 0.002 197.1)` |
| `--sidebar-border` | `oklch(0.925 0.005 214.3)` | `oklch(1 0 0 / 10%)` |
| `--sidebar-ring` | `oklch(0.723 0.014 214.4)` | `oklch(0.56 0.021 213.5)` |

### What the preset does not define

Not defined by the preset: success, warning or info colours, a status scale, and a `--destructive-foreground` token. The accent theme also has no name in the output; its values equal Tailwind's `blue` palette. Part 2 addresses the first; the second is noted for the first slice.

## Typography and fonts

| Item | Value |
|---|---|
| `--font-sans` | `'Geist Variable', sans-serif` |
| `--font-heading` | `var(--font-sans)` |
| Body font | **Geist.** `@layer base { html { @apply font-sans; } }` |
| Package | `@fontsource-variable/geist` 5.3.0, imported in CSS (self-hosted) |
| Subsets in the package | latin, latin-ext, cyrillic, cyrillic-ext, vietnamese |
| Variable axis | `wght` 100 to 900 |
| `--font-serif`, `--font-mono` | Not defined by the preset. Tailwind's default mono stack stays for the 3 `font-mono` uses in `src/` |
| Type scale | Not defined by the preset; Tailwind's default scale. Registry components set sizes themselves (default button `text-xs/relaxed`, input `text-sm`) |

**Checked in the font files** (with `fontkit`, no browser):

- Serbian Latin (`čćšžđ` and capitals) and Serbian Cyrillic (including `ђјљњћџ`) have glyphs.
- `tnum` exists. Default digits vary in width (384 to 663); with `tnum` all are 600, so `tabular-nums` in `FitScore.jsx` has an effect.

How the font looks is the owner's call.

## Radius

`--radius: 0.625rem`, same in both themes. Scale from `@theme inline`:

| Token | Value |
|---|---|
| `--radius-sm` | `calc(var(--radius) * 0.6)` |
| `--radius-md` | `calc(var(--radius) * 0.8)` |
| `--radius-lg` | `var(--radius)` |
| `--radius-xl` | `calc(var(--radius) * 1.4)` |
| `--radius-2xl` | `calc(var(--radius) * 1.8)` |
| `--radius-3xl` | `calc(var(--radius) * 2.2)` |
| `--radius-4xl` | `calc(var(--radius) * 2.6)` |

Applying this redefines `rounded-*` for every existing class, so it counts as a global change. Same value as the superseded preset.

## Spacing

Not defined by the preset. Tailwind's default scale.

## Borders and shadows

- `@layer base { * { @apply border-border outline-ring/50; } }` sets the default border and outline colour on every element.
- `body { @apply bg-background text-foreground; }`
- Shadows: not defined by the preset. Tailwind's defaults; registry components use them directly.
- Overlays: `dialog`, `sheet`, `drawer` and `alert-dialog` use `bg-black` with an opacity. This is the registry's only hard-coded colour and stays as supplied.

## Themes

Dark variant as generated: `@custom-variant dark (&:is(.dark *));`. The repo has `&:where(.dark, .dark *)` today. The two differ in specificity and in whether the `.dark` element itself matches. The repo has 951 `dark:` uses, so the first slice keeps the repo's variant until those are gone. This is a recorded temporary difference from the preset.

## Icons

`lucide` (`"iconLibrary": "lucide"`). The repo already uses `lucide-react`, in 73 files.

## Breakpoints

Not defined by the preset. Tailwind's defaults. The registry's `use-mobile` hook uses 768 px.

## Other preset settings

`style: base-mira`, `baseColor: mist`, `menuColor: default`, `menuAccent: subtle`, `rtl: false`, `cssVariables: true`, `prefix: ""`. CSS imports: `tailwindcss`, `tw-animate-css`, `shadcn/tailwind.css`, `@fontsource-variable/lora`.

# Part 2: Extension, not defined by the preset

**Status: O1 structure, aliases and values approved FOR PLANNING ONLY. All values are PROVISIONAL; none is permanently approved.** Centralized semantic tokens for success, warning, danger, information, fit scores and application states, plus job status and priority. No arbitrary colours in components. No value here is from the preset unless it says so.

The values are Tailwind palette values already installed in the repo (`node_modules/tailwindcss/theme.css`), and the same hues the app uses for these meanings today. All ratios are measured by [`preset/contrast_check.py`](preset/contrast_check.py); full table in [`preset/contrast-report.md`](preset/contrast-report.md). How they look beside Blue and Mist is the PO's call.

## Semantic scale (provisional)

| Token | Light | Dark | Source |
|---|---|---|---|
| `--success` | `oklch(0.508 0.118 165.612)` | `oklch(0.845 0.143 164.978)` | emerald 700 / 300 |
| `--success-subtle` | `oklch(0.95 0.052 163.051)` | `oklch(0.378 0.077 168.94)` | emerald 100 / 900 |
| `--success-subtle-foreground` | `oklch(0.432 0.095 166.913)` | `oklch(0.845 0.143 164.978)` | emerald 800 / 300 |
| `--success-border` | `oklch(0.905 0.093 164.15)` | `oklch(0.378 0.077 168.94)` | emerald 200 / 900 |
| `--warning` | `oklch(0.473 0.137 46.201)` | `oklch(0.879 0.169 91.605)` | amber 800 / 300. Light was amber 700, changed for margin on muted |
| `--warning-subtle` | `oklch(0.962 0.059 95.617)` | `oklch(0.414 0.112 45.904)` | amber 100 / 900 |
| `--warning-subtle-foreground` | `oklch(0.473 0.137 46.201)` | `oklch(0.879 0.169 91.605)` | amber 800 / 300 |
| `--warning-border` | `oklch(0.924 0.12 95.746)` | `oklch(0.414 0.112 45.904)` | amber 200 / 900 |
| `--danger` | `var(--destructive)` | `var(--destructive)` | Preset value |
| `--danger-subtle` | `oklch(0.936 0.032 17.717)` | `oklch(0.396 0.141 25.723)` | red 100 / 900 |
| `--danger-subtle-foreground` | `oklch(0.444 0.177 26.899)` | `oklch(0.808 0.114 19.571)` | red 800 / 300 |
| `--danger-border` | `oklch(0.885 0.062 18.334)` | `oklch(0.396 0.141 25.723)` | red 200 / 900 |
| `--info` (information) | `oklch(0.5 0.134 242.749)` | `oklch(0.828 0.111 230.318)` | sky 700 / 300 |
| `--info-subtle` | `oklch(0.951 0.026 236.824)` | `oklch(0.391 0.09 240.876)` | sky 100 / 900 |
| `--info-subtle-foreground` | `oklch(0.443 0.11 240.79)` | `oklch(0.828 0.111 230.318)` | sky 800 / 300 |
| `--info-border` | `oklch(0.901 0.058 230.902)` | `oklch(0.391 0.09 240.876)` | sky 200 / 900 |

Neutral states use preset tokens: `--secondary` with `--secondary-foreground` for fills, `--muted-foreground` for text. The `-border` tokens are decorative, because the text label carries the meaning, so no 3:1 target applies to them.

### Measured ratios for the scale

| Pair | Light | Dark |
|---|---|---|
| success-subtle-foreground on success-subtle | 6.68 | 6.38 |
| warning-subtle-foreground on warning-subtle | 6.41 | 6.29 |
| danger-subtle-foreground on danger-subtle | 6.86 | 5.24 |
| info-subtle-foreground on info-subtle | 6.54 | 5.68 |
| success text on background / card / muted | 5.37 / 5.37 / 4.82 | 12.99 / 11.45 / 9.74 |
| warning text on background / card / muted | 7.13 / 7.13 / 6.41 | 13.63 / 12.01 / 10.22 |
| info text on background / card / muted | 5.85 / 5.85 / 5.26 | 11.83 / 10.43 / 8.87 |
| danger (`--destructive`) on background / card | 4.76 / 4.76 | 6.82 / 6.01 |

`warning` text on `muted` in light mode rose from 4.54 to 6.41 with amber 800, a value already in this scale. `--danger` must not be used as text on `muted` or on a tint; see the corrections below.

## Domain aliases (provisional)

These point at the scale above. Apart from what is marked new, the mapping copies today's code, so **no state changes meaning**.

### Fit score

Labels and thresholds come from `python/job_scoring/labels.py` via `job.matchLabel`; `MATCH_LABEL_VARIANT` in `src/modules/jobs/matchScore.js` maps them today.

| Token | Label | Points at | Today |
|---|---|---|---|
| `--fit-excellent` | Excellent | success | `high` |
| `--fit-strong` | Strong | success | `high` |
| `--fit-good` | Good | warning | `medium` |
| `--fit-weak` | Weak | neutral | `low` |
| `--fit-reject` | Reject | neutral | `default` |
| `--fit-insufficient` | Insufficient Data (Wave 2, not built) | neutral | **New.** Same colour as Weak and Reject, so its label and the absence of a score band tell it apart from a low score |

### Priority and apply recommendation

`PRIORITY_VARIANT` and `APPLY_VARIANT` in `matchScore.js`.

| Token | Value | Points at |
|---|---|---|
| `--priority-p1` | P1 | success |
| `--priority-p2` | P2 | warning |
| `--priority-p3` | P3 | neutral |
| `--priority-reject` | Reject | neutral |
| `--apply-apply` | Apply | success |
| `--apply-maybe` | Maybe | warning |
| `--apply-skip` | Skip | neutral |

### Job status

`STATUS_VARIANT` in `src/components/jobs/JobTable.jsx`.

| Token | Status (label) | Points at |
|---|---|---|
| `--job-status-new` | `new` ("Unreviewed") | neutral |
| `--job-status-saved` | `saved` | success |
| `--job-status-applied` | `applied_manually` | warning |
| `--job-status-rejected` | `rejected` | neutral |

### Application states

Today the stage badge is one neutral `Badge` for every stage (`ApplicationTrackingSummary.jsx`), and work stages can be renamed, so aliases go by kind of state, never by label. Wave 5 may change this.

| Token | States (keys) | Points at | Today |
|---|---|---|---|
| `--app-state-active` | `applied`, work stages (default `screen`, `tech`, `onsite`, `offer`) | neutral | Neutral |
| `--app-state-closed` | `rejected`, `ghosted`, `withdrawn`, `position_closed`, `offer_declined` | neutral | Neutral |
| `--app-state-unfiled` | `unfiled` | neutral | Neutral |
| `--app-state-offer-accepted` | `offer_accepted` | success | **New meaning:** neutral today. Approved for planning |
| `--app-state-stale` | A stale board card | warning | Amber (`ApplicationBoard.jsx`) |
| `--app-state-error` | A failed tracker call | danger | Red |

### Other states already in the code

Reuse the scale; no new token:

- Run status (`STATUS_TONES`, `SOURCE_STATUS_TONES` in `src/modules/activity/runView.js`): ok success; partial, cancelled and unfinished warning; failed and interrupted danger; skipped and unknown neutral; running info.
- Work authorization (`workAuthorization.js`): No visa and Outside your places danger; Needs visa warning; Sponsored success.
- Requirement and gate marks (`engineShadow.js`): MET and pass success; PARTIAL and unknown warning; MISSING and fail danger.

### Stat cards and decoration (decided, O7)

Neutral cards and surfaces by default. `violet-*` ("Scored", "Avg Score", shadow-engine box), `indigo-*` (P1, P2, P3 stat cards, "stretch" in `RoleStrategyCard.jsx`) and `green-*` ("Apply" stat card) go to neutral tokens.

# Part 3: Contrast (O8)

**Decided:** preserve the Blue / Mist / Geist direction, meet WCAG AA (4.5:1 normal text, 3:1 applicable non-text UI), make the smallest token or usage corrections, keep them centralized, do not redesign the palette or replace the preset.

**Measured** from the committed snapshot with [`preset/contrast_check.py`](preset/contrast_check.py). OKLCH to sRGB, clipped to the gamut; alpha composited over its backdrop. Reproduce: `python3 docs/design-system/preset/contrast_check.py`.

**All corrections are provisional planning recommendations.** Nothing is applied. They are recalculated against the final palette before implementation.

## Failing combinations in use

| Theme | Pair | Target | Now | Correction | After |
|---|---|---|---|---|---|
| Light | muted-foreground on muted | 4.5 | 4.15 | C1 | 4.95 |
| Light | muted-foreground on secondary | 4.5 | 4.19 | C1 | 5.00 |
| Light | muted-foreground on `bg-muted/50` | 4.5 | 4.38 | C1 | 5.22 |
| Light | placeholder on `bg-input/20` | 4.5 | 4.42 | C1 | 4.56 |
| Light | primary-foreground on `hover:bg-primary/80` | 4.5 | 4.21 | U2 | 4.67 |
| Light | destructive text on `bg-destructive/10` | 4.5 | 3.99 | U3 | 7.01 |
| Light | destructive text on `bg-destructive/20` (hover) | 4.5 | 3.31 | U3 | 5.82 |
| Light | destructive text on muted | 4.5 | 4.28 | U3 | 7.53 |
| Dark | `text-primary` on background (link variant) | 4.5 | 2.23 | U1 | 5.24 |
| Dark | `text-primary` on card or popover | 4.5 | 1.96 | U1 | 4.62 |
| Dark | destructive text on `bg-destructive/30` (hover) | 4.5 | 4.35 | U3 | 6.55 |
| Light | input border on background, card, popover | 3 | 1.25 | C2 | 3.06 |
| Dark | input border on background | 3 | 1.48 | C2 | 3.15 |
| Dark | input border on card or popover | 3 | 1.59 | C2 | 3.22 |
| Light | switch off: track on background | 3 | 1.25 | C2 | 3.06 |
| Dark | switch off: track on background | 3 | 1.48 | C2 | 3.15 |
| Light | focus border (`border-ring`) on background or card | 3 | 2.44 | C3 | 6.82 |
| Light | sidebar focus ring on sidebar | 3 | 2.35 | C3 | 6.58 |
| Dark | progress fill on track | 3 | 1.67 | U1 | 3.93 |
| Dark | switch, checkbox, radio on: fill on background | 3 | 2.23 | U1 | 5.24 |
| Dark | switch, checkbox, radio on: fill on card | 3 | 1.96 | U1 | 4.62 |

After all corrections, the checker reports **0 applicable pairs below target and no regressions**.

## Below target, no consumer

No planned component uses these, so nothing changes. A rule stops them being used as they are:

| Theme | Pair | Target | Measured | Rule |
|---|---|---|---|---|
| Dark | sidebar-primary-foreground on sidebar-primary | 4.5 | 3.45 | Active sidebar item uses `sidebar-accent`, as the registry does (14.25) |
| Light | chart-1 on background | 3 | 1.81 | No charts today. Check again if charts are added |
| Dark | chart-4, chart-5 on background | 3 | 2.89, 2.23 | As above |

## Proposed corrections

Token changes, one place each. C2 is accepted for planning as proposed, with no separate `--input-border` token:

| ID | Token | Theme | Original | Proposed |
|---|---|---|---|---|
| C1 | `--muted-foreground` | Light | `oklch(0.56 0.021 213.5)` | `oklch(0.518 0.021 213.5)` |
| C2 | `--input` | Light | `oklch(0.925 0.005 214.3)` | `oklch(0.664 0.005 214.3)` |
| C2 | `--input` | Dark | `oklch(1 0 0 / 15%)` | `oklch(1 0 0 / 35%)` |
| C3 | `--ring`, `--sidebar-ring` | Light | `oklch(0.723 0.014 214.4)` | `var(--primary)` |
| C3 | `--ring`, `--sidebar-ring` | Dark | `oklch(0.56 0.021 213.5)` | `var(--sidebar-primary)` |

Usage changes, using existing or provisional tokens:

| ID | Change | Where |
|---|---|---|
| U1 | New alias `--primary-strong`: light `var(--primary)`, dark `var(--sidebar-primary)`. No new colour value. Used for link text and on-state fills. `--primary` stays for buttons, where its text is 6.26 and 8.11 | `ds/button` and `ds/badge` link variants, `field` and `empty` link hover, `progress`, `switch`, `checkbox`, `radio-group` |
| U2 | `hover:bg-primary/80` becomes `hover:bg-primary/85` | `ds/button`, `ds/badge` |
| U3 | Text on destructive tints or muted uses `--danger-subtle-foreground` | `ds/button`, `ds/badge`, `ds/dropdown-menu`; app code |

## Side effects

- **C2 also changes fills.** `--input` also drives `bg-input/20` and `bg-input/30`, so input fields get a stronger tint in both themes. Accepted by the PO for planning.
- **C2 is the largest visible change here.** Light input borders go from very pale to mid-grey.
- **C3 uses Blue for focus rather than grey.** A grey at 3:1 would match the corrected input border, so a focused field would only differ by its faint halo. Blue differs in hue, but the luminance change from the resting border to the focus border is 2.23:1 in light and 1.67:1 in dark, below 3:1. AA does not require 3:1 there; the halo adds to it.
- **Dark `--sidebar-primary`** is slightly outside sRGB and was clipped, so its ratios are close approximations.

## Clarification on the source of these problems

The PO's original Cyan preset was **not** the source of the reported dark-mode contrast regressions. Blue/Geist was recommended in the design discussion and then selected. No statement here characterizes the original preset as defective.

Measured against the earlier snapshot in Git (`b9bb4cc`):

- Most pairs above use tokens that are identical in both presets (muted, input, ring, destructive), so their ratios are unchanged.
- Dark `--primary` as text or fill fell with Blue: on background 2.72 to 2.23, on card 2.40 to 1.96, on muted 2.04 to 1.67.
- Dark sidebar-primary-foreground on sidebar-primary fell from 5.66 to 3.45.
- Blue improved light mode: `hover:bg-primary/80` rose from 3.51 to 4.21, and primary-foreground on primary from 5.07 to 6.26.
