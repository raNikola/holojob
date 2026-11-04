# Tokens

Part 1 lists the **actual preset values**, from the CLI's output in [preset/index.generated.css](preset/index.generated.css) (`shadcn@4.23.0`, preset `b1a1cZcRs`, retrieved 2026-11-04). Part 2 is the **extension, not defined by the preset**, with proposed values awaiting owner approval. None of this is in the app yet.

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

**Status: proposed values, marked for PO approval.** No value here is from the preset. Defined once in the token layer; components never name a colour.

The values are Tailwind palette values already installed in the repo (`node_modules/tailwindcss/theme.css`) and the same hues the app uses for these meanings today, so the meaning of a colour does not change. Only `error` reuses a preset value. They were not designed against `mist` or the blue primary, and how they sit beside them is for the owner to judge. In particular, `--info` (sky) is the nearest hue to `--primary` (blue), about 22 degrees apart in light mode, and `--fit-insufficient` points at `--info`, so that state may read like an action colour.

## Semantic scale (proposed)

| Token | Light | Dark | Palette source |
|---|---|---|---|
| `--success` | `oklch(0.508 0.118 165.612)` | `oklch(0.845 0.143 164.978)` | emerald 700 / 300 |
| `--success-subtle` | `oklch(0.95 0.052 163.051)` | `oklch(0.378 0.077 168.94)` | emerald 100 / 900 |
| `--success-subtle-foreground` | `oklch(0.432 0.095 166.913)` | `oklch(0.845 0.143 164.978)` | emerald 800 / 300 |
| `--success-border` | `oklch(0.905 0.093 164.15)` | `oklch(0.378 0.077 168.94)` | emerald 200 / 900 |
| `--warning` | `oklch(0.555 0.163 48.998)` | `oklch(0.879 0.169 91.605)` | amber 700 / 300 |
| `--warning-subtle` | `oklch(0.962 0.059 95.617)` | `oklch(0.414 0.112 45.904)` | amber 100 / 900 |
| `--warning-subtle-foreground` | `oklch(0.473 0.137 46.201)` | `oklch(0.879 0.169 91.605)` | amber 800 / 300 |
| `--warning-border` | `oklch(0.924 0.12 95.746)` | `oklch(0.414 0.112 45.904)` | amber 200 / 900 |
| `--error` | `var(--destructive)` | `var(--destructive)` | Preset value |
| `--error-subtle` | `oklch(0.936 0.032 17.717)` | `oklch(0.396 0.141 25.723)` | red 100 / 900 |
| `--error-subtle-foreground` | `oklch(0.444 0.177 26.899)` | `oklch(0.808 0.114 19.571)` | red 800 / 300 |
| `--error-border` | `oklch(0.885 0.062 18.334)` | `oklch(0.396 0.141 25.723)` | red 200 / 900 |
| `--info` | `oklch(0.5 0.134 242.749)` | `oklch(0.828 0.111 230.318)` | sky 700 / 300 |
| `--info-subtle` | `oklch(0.951 0.026 236.824)` | `oklch(0.391 0.09 240.876)` | sky 100 / 900 |
| `--info-subtle-foreground` | `oklch(0.443 0.11 240.79)` | `oklch(0.828 0.111 230.318)` | sky 800 / 300 |
| `--info-border` | `oklch(0.901 0.058 230.902)` | `oklch(0.391 0.09 240.876)` | sky 200 / 900 |

Neutral states use preset tokens: `--secondary` with `--secondary-foreground`, or `--muted-foreground` for text.

## Domain aliases (proposed)

These point at the scale above. The mapping copies today's code, so **no state changes meaning**.

### Fit score

Labels and thresholds come from `python/job_scoring/labels.py` via `job.matchLabel`; `MATCH_LABEL_VARIANT` in `src/modules/jobs/matchScore.js` maps them today.

| Token | Label | Points at | Today |
|---|---|---|---|
| `--fit-excellent` | Excellent | success | `high` |
| `--fit-strong` | Strong | success | `high` |
| `--fit-good` | Good | warning | `medium` |
| `--fit-weak` | Weak | neutral | `low` |
| `--fit-reject` | Reject | neutral | `default` |
| `--fit-insufficient` | Insufficient Data (Wave 2, not built) | info | New. Reserved so the state stays distinct from a low score |

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

### Other states already in the code

Reuse the scale; no new token:

- Run status (`STATUS_TONES`, `SOURCE_STATUS_TONES` in `src/modules/activity/runView.js`): ok success; partial, cancelled and unfinished warning; failed and interrupted error; skipped and unknown neutral; running info.
- Work authorization (`workAuthorization.js`): No visa and Outside your places error; Needs visa warning; Sponsored success.
- Requirement and gate marks (`engineShadow.js`): MET and pass success; PARTIAL and unknown warning; MISSING and fail error.

### Colours in use today with no proposed meaning

These decorate rather than signal, and are expected to go to neutral tokens. **Owner to confirm:**

- `violet-*`: the shadow-engine box and the "Scored" and "Avg Score" stat cards (`JobDiscoverySummary.jsx`). Wave 5 removes the shadow badge.
- `indigo-*`: the P1, P2 and P3 stat cards, and "stretch" in `RoleStrategyCard.jsx`.
- `green-*`: the "Apply" stat card.

## Computed contrast

Computed from the values above (OKLCH to sRGB, WCAG formula). These are numbers, not a visual approval. WCAG AA for normal text is 4.5:1.

| Pair | Light | Dark |
|---|---|---|
| success-subtle-foreground on success-subtle | 6.68 | 6.38 |
| warning-subtle-foreground on warning-subtle | 6.41 | 6.29 |
| error-subtle-foreground on error-subtle | 6.86 | 5.24 |
| info-subtle-foreground on info-subtle | 6.54 | 5.68 |
| success on background (light), on card (dark) | 5.37 | 11.45 |
| warning on background (light), on card (dark) | 5.05 | 12.01 |
| info on background (light), on card (dark) | 5.85 | 10.43 |

Preset pairs:

| Pair | Light | Dark |
|---|---|---|
| foreground on background | 19.71 | 19.00 |
| primary-foreground on primary | 6.26 | 8.11 |
| **primary as text on background** (`link` variant of button and badge) | 6.82 | **2.23, below AA** |
| secondary-foreground on secondary | 16.11 | 14.26 |
| muted-foreground on background | 4.61 | 8.07 |
| **muted-foreground on muted** | **4.15, below AA** | 6.05 |
| destructive on background (also `--error`) | 4.76 | 6.82 |
| sidebar-primary-foreground on sidebar-primary | 4.82 | **3.45, below AA** |

Values outside sRGB were clamped, so the blue ratios are close approximations. The pairs below AA are preset values, left unchanged because the owner decided on the complete preset. They are flagged in [the backlog](REDESIGN_BACKLOG.md#open-po-decisions). No registry component in the install list uses `sidebar-primary`, so that pair has no consumer yet.

The extension ratios did not change with the new preset: the backgrounds they sit on are the same.
