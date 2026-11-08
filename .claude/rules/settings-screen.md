---
paths:
  - "src/modules/settings/**"
  - "tests/js/settingsRegistry.test.js"
---

# Settings screen

`SettingsHome.jsx` is a shell: a left navigation (a `<select>` on mobile) over eight categories (Job search, Sources,
Applications, AI & costs, Privacy & security, Data & backups, General, Danger zone), a search box that only opens a
section, and every category kept mounted (hidden with CSS) so drafts survive switching. The map is
`src/modules/settings/settingsRegistry.js`; a new setting adds a section there and an entry in `RENDERERS`
(`tests/js/settingsRegistry.test.js` checks both), never a top-level card. Text that points to a section uses
`openSettings(sectionId)` / `SettingsLink`. Section titles stay verbatim (for example "AI budget", "Privacy: secrets and
keys"). Plan and as-built note: `docs/redesign/SETTINGS_PLAN.md`.
