# Component inventory

Decision per category: **use shadcn**, **compose** primitives, or **keep custom** with a reason. Existing files are in `src/components/`; registry files will go to `src/components/ds/`. Counts are from `src/` on 2026-11-04. Nothing here is built.

The registry names below are confirmed: all of them were added to a scratch project with `shadcn@4.23.0` under `base-mira`.

## Buttons

| Today | Decision | Target |
|---|---|---|
| `ui/Button.jsx`, imported by 54 files. Variants `primary`, `secondary`, `ghost`, `danger` | Use shadcn, behind the same props | `ds/button`. Mapping: `primary` to `default`, `secondary` to `outline` or `secondary`, `ghost` to `ghost`, `danger` to `destructive` |
| 92 raw `<button>` in 47 files | Compose | `ds/button` with size `icon*` for icon buttons; keep every `aria-label` |
| `jobs/KeepAdButton.jsx`, `settings/SettingsLink.jsx` | Keep custom | Behaviour, composed over `ds/button` |

Note: today's `min-h-[44px]` against the preset's `h-7` is an [open decision](REDESIGN_BACKLOG.md#open-po-decisions).

## Inputs and forms

| Today | Decision | Target |
|---|---|---|
| `ui/Input.jsx` (10 files), `ui/Textarea.jsx` (6) | Use shadcn, same props | `ds/input`, `ds/textarea`, `ds/field`, `ds/label`. Keep `labelExtra`, `confidenceTag`, the `aria-*` wiring and the id rule |
| `ui/RequiredMark.jsx`, `ui/ConfidenceTag.jsx` | Keep custom | Project meaning; tokens only |
| `ui/TagInput.jsx` | Compose | `ds/input-group`, `ds/badge`. No registry equivalent |
| 54 raw `<input>` in 30 files, including checkboxes | Compose | `ds/input`, `ds/checkbox`, `ds/radio-group`, `ds/switch` by case |
| `ui/InfoTip.jsx` (3 files) | Use shadcn, or keep | `ds/tooltip` covers hover and focus. The tap behaviour and the `glyph`/`onActivate` modes may need `ds/popover`. Requires a `TooltipProvider`, once, in the shell |

## Selects and dropdowns

| Today | Decision | Target |
|---|---|---|
| `ui/SelectField.jsx` (8 files), native `<select>`, 24 raw uses in 12 files | **Use `ds/native-select`** first | Keeps the native control, `value` / `onChange` and mobile behaviour. Lowest behaviour risk and existing tests keep working. `ds/select` only where the owner asks |
| `ui/MultiSelectDropdown.jsx` | Keep custom, restyled | Documented keyboard behaviour (rows, Space, Escape, focus return). Compose with `ds/popover`, `ds/checkbox` |
| `ui/MultiSelectField.jsx` | Keep custom, restyled | As above |
| `ui/RoleCombobox.jsx` | Use `ds/combobox` if its tests hold | Otherwise keep it, restyled |
| Row and action menus | `ds/dropdown-menu` | Only where a menu exists today; no new menus |

## Tables and data grids

| Today | Decision | Target |
|---|---|---|
| `jobs/JobTable.jsx` (361 lines): one layout mounted, whole list sorted, batches of 100, selection as a Set, cards on mobile | **Keep custom logic, use `ds/table` markup** | No data-grid library. The behaviour is pinned by `jobTable.test.js` and `jobsScreen.dom.test.js` |
| `ui/SortableTh.jsx` (3 files) | Keep custom | No registry equivalent; `ds/table` head cell inside |
| 9 other `<table>` (Activity, AI budget, Applications, Quality) | Use `ds/table` | Markup only |
| "Show more" batches | Keep | `ds/pagination` is not used; batches are the agreed behaviour |

## Dialogs and drawers

| Today | Decision | Target |
|---|---|---|
| `jobs/AddJobDialog.jsx`, `cvs/CvAnalyzeDialog.jsx`, the dialog in `jobs/FitJudgementCard.jsx` | Use shadcn | `ds/dialog`. The confirm flows and `"confirm": true` paths stay exactly as they are |
| `jobs/JobDetailDrawer.jsx`, `outreach/ContactDetailDrawer.jsx`, `quality/AuditDetailDrawer.jsx` | Use shadcn | `ds/sheet` with `side="right"`. `useDraftDirty` guard unchanged |
| `window.confirm` (void an application, regenerate, restore backup, clear data, remove a key or cookie; in `ApplicationTrackerPanel`, `JobAIToolsPanel`, `JobDetailDrawer`, `ReviewScreen`, `SettingsHome`, `SecretsPanel`) | **Keep in MVP** | It is synchronous, and `ds/alert-dialog` is not; moving means restructuring handlers. Later, one at a time, `ds/alert-dialog`. No confirm is added or removed |
| Styled confirms (`CancelRun`, AI and CV confirm panels) | `ds/alert-dialog` or `ds/dialog` | Same text and same `confirm` flag |
| `layout/AppShell.jsx` "More" sheet | `ds/sheet` | `side="bottom"` |

**Behaviour to check:**

- Of the hand-built dialogs, only `AddJobDialog` handles Escape; `AddJobDialog`, `FitJudgementCard` and `CvAnalyzeDialog` set `aria-modal`; the three drawers set neither. Base UI adds Escape, focus trapping and focus return. This is an accessibility gain and a real behaviour change, and is listed per slice.
- Base UI dialogs render in a portal. `.panel-text-up` (the larger type in the job panel) applies by inheritance, so **a popup that portals out of the panel loses it**. Dark mode is unaffected, because `.dark` is on `<html>`.

## Navigation

| Today | Decision | Target |
|---|---|---|
| `#/jobs/<id>` hash, `view` state, `modules/appNavigation.js`, `modules/jobs/jobRoute.js` | **Keep** | No router. Not touched |
| `ds/breadcrumb` | Not in MVP | Nothing shows a trail today |

## Sidebar and header

| Today | Decision | Target |
|---|---|---|
| `layout/Sidebar.jsx`: collapse saved through `modules/sidebarState.js` (allowlisted key), bottom bar and "More" on mobile | **Compose, with the required edit below** | `ds/sidebar` as supplied conflicts with the repo. See the next section |
| `layout/TopBar.jsx` | Compose | Keep the dark toggle and its class handling |
| `layout/StorageNotice.jsx` | Compose | `ds/alert` |

## Tabs

| Today | Decision | Target |
|---|---|---|
| `ui/Tabs.jsx` (4 files), `intelligence/IntelligenceTabs.jsx` | Use shadcn, same props | `ds/tabs`. **`keepMounted`** on panels wherever drafts live (the prop exists in Base UI's `Tabs.Panel`) |
| `settings/SettingsHome.jsx` shell | Keep custom | Every category stays mounted so drafts survive, with a `<select>` on mobile and search that only opens a section. `settingsRegistry.test.js` pins the map |

## Cards

| Today | Decision | Target |
|---|---|---|
| `ui/Card.jsx` (43 files), props `title`, `description`, `action`, `className` | Use shadcn, same props | `ds/card` parts inside. `title` uses `--font-heading` through the registry |
| `ui/StatCard.jsx` (6 files) | Compose | `ds/card`. The `accent` prop's palette classes go away |
| `outreach/ContactCard.jsx`, `quality/QualityScoreCard.jsx`, `intelligence/*Card.jsx` | Compose | `ds/card` |

## Badges and status

| Today | Decision | Target |
|---|---|---|
| `ui/Badge.jsx` (17 files), variants `default`, `high`, `medium`, `warn`, `low`, `derived` | Use shadcn, **same variant names, extended** | `ds/badge` with success, warning, error, info and neutral from the [extension tokens](TOKENS.md#part-2-extension-not-defined-by-the-preset). Mapping: `high` success, `medium` warning, `warn` error, `low` and `default` neutral, `derived` info |
| `jobs/FitScore.jsx`, `jobs/JobScoreBadge.jsx`, `jobs/AuthorizationBadge.jsx` | Keep custom | Project meaning over `Badge`. Text labels stay |
| `modules/jobs/fitScore.js` `SCORE_TEXT`, `modules/jobs/engineShadow.js` | **Keep the modules, change only the class strings** to tokens | These are the only palette strings in `src/modules/` |
| `STATUS_VARIANT`, `MATCH_LABEL_VARIANT`, `PRIORITY_VARIANT`, `APPLY_VARIANT` | Keep | Names unchanged; these maps are the logic |

## Notifications

| Today | Decision | Target |
|---|---|---|
| `ui/Alert.jsx` (39 files), variants `error`, `success`, `info` | Use shadcn, same props | `ds/alert` with extension tokens |
| Inline messages | Keep | |
| Toasts | **None today, none added** | `sonner` is not installed: it would bring `next-themes`, and a new pattern is a product decision |

## Loading, empty and error states

| Today | Decision | Target |
|---|---|---|
| `animate-spin`, `animate-pulse` usage | Compose | `ds/spinner`, `ds/skeleton`. Same places only |
| `jobs/JobEmptyState.jsx`, `intelligence/IntelligenceEmptyState.jsx` | Compose | `ds/empty`, same texts |
| `ui/OperationConsole.jsx` (4 files) | Keep custom | Log view, no registry equivalent |
| `jobs/RescrapeProgress.jsx`, `onboarding/ProgressBar.jsx` | Compose | `ds/progress` where it is a bar; the step control stays custom |
| Gates `demo/DemoBootstrapGate.jsx`, `jobs/JobTextGate.jsx` | Keep | Behaviour; tokens only |

## Required edits to registry files

Registry source is otherwise kept as supplied.

| File | Edit | Why |
|---|---|---|
| `ds/sidebar` | **Remove the `document.cookie` write** (`sidebar_state`). Drive open state through `open` / `onOpenChange` from `modules/sidebarState.js` | Verified in source: it writes the cookie on every toggle. `tests/js/browserStorageAllowlist.test.js` scans for `document.cookie` and the storage policy forbids new keys |
| `ds/sidebar` | Remove the Ctrl/Cmd+B shortcut, or get owner approval | It is a behaviour addition (`SIDEBAR_KEYBOARD_SHORTCUT = "b"`) |
| `ds/badge`, `ds/alert` | Add the extension variants | Status colours are not in the preset |

Not used because of the same issue: `theme-provider` (writes `localStorage` key `theme`).

## Install list

Each added in the slice that first uses it.

**Task A:** `button`, then `badge`, `card`, `alert`, `input`, `textarea`, `label`, `field`, `native-select`, `tabs`, `tooltip`, `popover`, `checkbox`, `separator`, `input-group`.

**Task B:** `sidebar` (with `sheet`, `skeleton`, `tooltip`, `use-mobile`).

**Later:** `table`, `dialog`, `sheet`, `alert-dialog`, `dropdown-menu`, `radio-group`, `switch`, `spinner`, `skeleton`, `empty`, `progress`, `scroll-area`, `combobox`, `collapsible`, `toggle`, `toggle-group`.

**Not installed in MVP:** `sonner`, `command`, `drawer`, `breadcrumb`, `pagination`.
