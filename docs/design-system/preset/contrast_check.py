#!/usr/bin/env python3
"""Measure WCAG contrast for the Design System tokens. Standard library only.

Reads the committed preset snapshot (index.generated.css) and the proposals below, both PENDING PO verification.
Colours: OKLCH to linear sRGB, clipped to the sRGB gamut. Alpha: composited in gamma-encoded sRGB over its backdrop.
A browser on a wide-gamut screen can differ slightly. These are numbers, not a visual approval.

Usage, from the repo root:
    python3 docs/design-system/preset/contrast_check.py              prints the report
    python3 docs/design-system/preset/contrast_check.py --write      also writes contrast-report.md beside this file
Exit code 1 if an applicable pair is still below its target after the proposed corrections.
"""
import argparse
import math
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def parse(css):
    def block(name):
        body = css.split(name + " {", 1)[1].split("}", 1)[0]
        out = {}
        for key, value in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", body):
            m = re.fullmatch(r"oklch\(([\d.]+) ([\d.]+) ([\d.]+)(?: / (\d+)%)?\)", value.strip())
            if m:
                out[key] = (float(m[1]), float(m[2]), float(m[3]), int(m[4]) / 100 if m[4] else 1.0)
        return out
    return {"light": block(":root"), "dark": block(".dark")}


def to_gamma(color):
    L, C, H = color[:3]
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
              -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
              -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    def enc(v):
        v = max(0.0, min(1.0, v))
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return tuple(enc(v) for v in linear)


def over(top, alpha, backdrop):
    return tuple(t * alpha + b * (1 - alpha) for t, b in zip(top, backdrop))


def lum(rgb):
    def dec(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * dec(rgb[0]) + 0.7152 * dec(rgb[1]) + 0.0722 * dec(rgb[2])


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def layer(spec, theme):
    name, _, pct = spec.partition("/")
    return theme[name], theme[name][3] * (int(pct) / 100 if pct else 1.0)


def resolve(spec, theme):
    """'token', or a stack 'token/NN>token' with the top layer first. Returns gamma sRGB."""
    parts = spec.split(">")
    base = to_gamma(theme[parts[-1]])
    for part in reversed(parts[:-1]):
        color, alpha = layer(part, theme)
        base = over(to_gamma(color), alpha, base)
    return base


def contrast(fg, bg, theme):
    back = resolve(bg, theme)
    color, alpha = layer(fg, theme)
    return ratio(over(to_gamma(color), alpha, back), back)


# O1 extension: Tailwind palette values already in the repo (light, dark). PENDING PO verification.
EXTENSION = {
    "success": ((0.508, 0.118, 165.612, 1), (0.845, 0.143, 164.978, 1)),
    "success-subtle": ((0.95, 0.052, 163.051, 1), (0.378, 0.077, 168.94, 1)),
    "success-subtle-foreground": ((0.432, 0.095, 166.913, 1), (0.845, 0.143, 164.978, 1)),
    "warning": ((0.555, 0.163, 48.998, 1), (0.879, 0.169, 91.605, 1)),
    "warning-subtle": ((0.962, 0.059, 95.617, 1), (0.414, 0.112, 45.904, 1)),
    "warning-subtle-foreground": ((0.473, 0.137, 46.201, 1), (0.879, 0.169, 91.605, 1)),
    "danger-subtle": ((0.936, 0.032, 17.717, 1), (0.396, 0.141, 25.723, 1)),
    "danger-subtle-foreground": ((0.444, 0.177, 26.899, 1), (0.808, 0.114, 19.571, 1)),
    "info": ((0.5, 0.134, 242.749, 1), (0.828, 0.111, 230.318, 1)),
    "info-subtle": ((0.951, 0.026, 236.824, 1), (0.391, 0.09, 240.876, 1)),
    "info-subtle-foreground": ((0.443, 0.11, 240.79, 1), (0.828, 0.111, 230.318, 1)),
}

BOTH, LIGHT, DARK = ("light", "dark"), ("light",), ("dark",)
TEXT_AA, UI_AA = 4.5, 3.0

# (label, fg, bg, themes, target, corrected fg, corrected bg, consumer). Corrected None keeps the same spec.
ROWS = [
    ("foreground on background", "foreground", "background", BOTH, TEXT_AA, None, None, True),
    ("card-foreground on card", "card-foreground", "card", BOTH, TEXT_AA, None, None, True),
    ("popover-foreground on popover", "popover-foreground", "popover", BOTH, TEXT_AA, None, None, True),
    ("primary-foreground on primary", "primary-foreground", "primary", BOTH, TEXT_AA, None, None, True),
    ("primary-foreground on primary, hover (`bg-primary/80`)", "primary-foreground", "primary/80>background", BOTH, TEXT_AA, None, "primary/85>background", True),
    ("secondary-foreground on secondary", "secondary-foreground", "secondary", BOTH, TEXT_AA, None, None, True),
    ("accent-foreground on accent", "accent-foreground", "accent", BOTH, TEXT_AA, None, None, True),
    ("muted-foreground on background", "muted-foreground", "background", BOTH, TEXT_AA, None, None, True),
    ("muted-foreground on card or popover", "muted-foreground", "card", BOTH, TEXT_AA, None, None, True),
    ("muted-foreground on muted", "muted-foreground", "muted", BOTH, TEXT_AA, None, None, True),
    ("muted-foreground on secondary (neutral badge text)", "muted-foreground", "secondary", BOTH, TEXT_AA, None, None, True),
    ("muted-foreground on `bg-muted/50` (table footer, row hover)", "muted-foreground", "muted/50>background", BOTH, TEXT_AA, None, None, True),
    ("placeholder on `bg-input/20` over background", "muted-foreground", "input/20>background", LIGHT, TEXT_AA, None, None, True),
    ("placeholder on `bg-input/30` over background", "muted-foreground", "input/30>background", DARK, TEXT_AA, None, None, True),
    ("foreground on `hover:bg-input/50` (outline button)", "foreground", "input/50>background", LIGHT, TEXT_AA, None, None, True),
    ("`text-foreground/60` on muted (inactive tab)", "foreground/60", "muted", LIGHT, TEXT_AA, None, None, True),
    ("background on foreground (tooltip)", "background", "foreground", BOTH, TEXT_AA, None, None, True),
    ("`text-primary` on background (link variant)", "primary", "background", BOTH, TEXT_AA, "primary-strong", None, True),
    ("`text-primary` on card or popover (link variant)", "primary", "card", BOTH, TEXT_AA, "primary-strong", None, True),
    ("destructive on background", "destructive", "background", BOTH, TEXT_AA, None, None, True),
    ("destructive on card or popover (alert, menu item)", "destructive", "card", BOTH, TEXT_AA, None, None, True),
    ("destructive text on muted", "destructive", "muted", BOTH, TEXT_AA, "danger-subtle-foreground", None, True),
    ("destructive text on `bg-destructive/10` (button, badge)", "destructive", "destructive/10>background", LIGHT, TEXT_AA, "danger-subtle-foreground", None, True),
    ("destructive text on `bg-destructive/20` (light hover)", "destructive", "destructive/20>background", LIGHT, TEXT_AA, "danger-subtle-foreground", None, True),
    ("destructive text on `bg-destructive/20` (dark)", "destructive", "destructive/20>background", DARK, TEXT_AA, "danger-subtle-foreground", None, True),
    ("destructive text on `bg-destructive/30` (dark hover)", "destructive", "destructive/30>background", DARK, TEXT_AA, "danger-subtle-foreground", None, True),
    ("sidebar-foreground on sidebar", "sidebar-foreground", "sidebar", BOTH, TEXT_AA, None, None, True),
    ("sidebar-foreground/70 on sidebar (group label)", "sidebar-foreground/70", "sidebar", BOTH, TEXT_AA, None, None, True),
    ("sidebar-accent-foreground on sidebar-accent", "sidebar-accent-foreground", "sidebar-accent", BOTH, TEXT_AA, None, None, True),
    ("sidebar-primary-foreground on sidebar-primary", "sidebar-primary-foreground", "sidebar-primary", BOTH, TEXT_AA, None, None, False),
    ("input border on background", "input", "background", BOTH, UI_AA, None, None, True),
    ("input border on card or popover", "input", "card", BOTH, UI_AA, None, None, True),
    ("switch off: track (`bg-input`) on background", "input", "background", BOTH, UI_AA, None, None, True),
    ("focus border (`border-ring`) on background", "ring", "background", BOTH, UI_AA, None, None, True),
    ("focus border (`border-ring`) on card", "ring", "card", BOTH, UI_AA, None, None, True),
    ("sidebar focus ring on sidebar", "sidebar-ring", "sidebar", BOTH, UI_AA, None, None, True),
    ("invalid border (destructive) on background", "destructive", "background", BOTH, UI_AA, None, None, True),
    ("progress fill on track (`bg-primary` on muted)", "primary", "muted", BOTH, UI_AA, "primary-strong", None, True),
    ("switch, checkbox, radio on: fill on background", "primary", "background", BOTH, UI_AA, "primary-strong", None, True),
    ("switch, checkbox, radio on: fill on card", "primary", "card", BOTH, UI_AA, "primary-strong", None, True),
    ("check mark or thumb (primary-foreground) on the fill", "primary-foreground", "primary", BOTH, UI_AA, "primary-foreground", "primary-strong", True),
    ("tab underline (foreground) on background", "foreground", "background", BOTH, UI_AA, None, None, True),
    ("chart-1 on background", "chart-1", "background", BOTH, UI_AA, None, None, False),
    ("chart-2 on background", "chart-2", "background", BOTH, UI_AA, None, None, False),
    ("chart-3 on background", "chart-3", "background", BOTH, UI_AA, None, None, False),
    ("chart-4 on background", "chart-4", "background", BOTH, UI_AA, None, None, False),
    ("chart-5 on background", "chart-5", "background", BOTH, UI_AA, None, None, False),
]
for name in ("success", "warning", "info"):
    for back in ("background", "card", "muted"):
        ROWS.append((f"{name} text on {back} (extension)", name, back, BOTH, TEXT_AA, None, None, True))
for name in ("success", "warning", "danger", "info"):
    ROWS.append((f"{name}-subtle-foreground on {name}-subtle (extension)", f"{name}-subtle-foreground", f"{name}-subtle", BOTH, TEXT_AA, None, None, True))


def themes(path):
    t = parse(Path(path).read_text())
    for i, name in enumerate(BOTH):
        for key, pair in EXTENSION.items():
            t[name][key] = pair[i]
    return t


def corrected(t):
    """O8 token corrections, PENDING PO verification. Everything else stays the preset's value."""
    c = {name: dict(t[name]) for name in BOTH}
    c["light"]["muted-foreground"] = (0.518, 0.021, 213.5, 1.0)
    c["light"]["input"] = (0.664, 0.005, 214.3, 1.0)
    c["dark"]["input"] = (1.0, 0.0, 0.0, 0.35)
    c["light"]["primary-strong"] = t["light"]["primary"]
    c["dark"]["primary-strong"] = t["dark"]["sidebar-primary"]
    for name in BOTH:
        c[name]["ring"] = c[name]["primary-strong"]
        c[name]["sidebar-ring"] = c[name]["primary-strong"]
    return c


def run():
    t = themes(HERE / "index.generated.css")
    c = corrected(t)
    rows, unresolved = [], 0
    for label, fg, bg, scope, target, cfg, cbg, consumer in ROWS:
        for theme in scope:
            now = contrast(fg, bg, t[theme])
            after = contrast(cfg or fg, cbg or bg, c[theme])
            if consumer and after < target:
                unresolved += 1
            rows.append((label, theme, target, now, after, consumer))
    return rows, unresolved


def report(rows, unresolved):
    out = ["# Contrast report", "",
           "Generated by `contrast_check.py` from `index.generated.css` and the proposals in the script. Numbers, not a visual approval.",
           "Target: 4.5:1 for text, 3:1 for applicable non-text UI (WCAG AA). \"After\" applies the proposed corrections, pending PO verification.", "",
           f"Applicable pairs still below target after corrections: **{unresolved}**.", "",
           "| Pair | Theme | Target | Now | After | Result |", "|---|---|---|---|---|---|"]
    for label, theme, target, now, after, consumer in rows:
        if now >= target and after >= target:
            state = "Pass"
        elif not consumer and now < target:
            state = "Below, no consumer"
        elif now < target and after >= target:
            state = "**Fixed**"
        elif now >= target:
            state = "**Regressed**"
        else:
            state = "**Still below**"
        out.append(f"| {label} | {theme} | {target} | {now:.2f} | {after:.2f} | {state} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    rows, unresolved = run()
    text = report(rows, unresolved)
    print(text)
    if args.write:
        (HERE / "contrast-report.md").write_text(text)
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
