# Design

Visual system for the ForkHub web UI. Identity: **Observatory** — an
instrument for watching the constellation of forks around a repo. The night
sky is the brand; forks are points of light; clusters are constellations.

This document is the source of truth. Every screen reads from these tokens.
Strategic intent lives in [PRODUCT.md](PRODUCT.md).

## Theme

Dark, by necessity, not by reflex: the core Explore view shows forks as points
of light, which only reads against a dark sky. The chrome (digest, control,
nav) stays calm and familiar — restrained product UI in the Linear/Raycast
mold. The Observatory "wonder" is concentrated in two places only: the ambient
glow and the constellation. Everywhere else the tool disappears into the task.

No light mode for v1 (the metaphor doesn't survive it). Revisit only if a
"day" reading mode is explicitly requested.

## Color

OKLCH only. Strategy: **Restrained chrome, one Committed surface** (the
constellation). Primary and accent are the only brand colors; everything else
is the indigo neutral ramp.

```css
:root {
  /* Surfaces — the night sky is the brand (environmental tint justified) */
  --night:      oklch(0.155 0.032 272);  /* app background */
  --sky-deep:   oklch(0.130 0.030 273);  /* constellation canvas (darker) */
  --surface:    oklch(0.205 0.030 270);  /* cards, panels */
  --surface-2:  oklch(0.255 0.028 268);  /* raised: menus, popovers, inputs */
  --line:       oklch(0.320 0.026 268);  /* borders, dividers */

  /* Text */
  --ink:        oklch(0.965 0.012 265);  /* primary text  (>15:1 on night) */
  --muted:      oklch(0.740 0.022 265);  /* secondary text (>5:1 on night) */
  --faint:      oklch(0.560 0.022 266);  /* tertiary/disabled (decorative) */

  /* Brand */
  --primary:        oklch(0.580 0.185 262);  /* cobalt: actions, selection, focus */
  --primary-bright: oklch(0.700 0.160 262);  /* hover / glow */
  --accent:         oklch(0.840 0.135 80);   /* starlight gold: links, live node, cost */

  /* Signal taxonomy — always paired with icon + label (never color alone) */
  --sig-feature:    oklch(0.740 0.150 158);  /* emerald  + plus glyph */
  --sig-fix:        oklch(0.760 0.115 205);  /* teal     + wrench */
  --sig-refactor:   oklch(0.720 0.150 300);  /* violet   + recycle */
  --sig-config:     oklch(0.815 0.135 112);  /* lime     + sliders (kept clear of the gold accent) */
  --sig-dependency: oklch(0.720 0.022 265);  /* slate    + box (neutral = maintenance) */
  --sig-adaptation: oklch(0.760 0.130 40);   /* orange   + arrows */
  --sig-release:    oklch(0.770 0.130 175);  /* aqua     + tag */
  --sig-removal:    oklch(0.700 0.170 18);   /* rose     + minus */

  /* State semantics */
  --success: var(--sig-feature);
  --warning: oklch(0.800 0.130 75);
  --danger:  var(--sig-removal);
  --info:    var(--primary-bright);
}
```

Rules:
- **Text on filled brand colors is white** (`--ink`), per Helmholtz-Kohlrausch —
  cobalt and the saturated signal hues are mid-luminance. Gold (`--accent`,
  L 0.84) is the exception: it takes **dark** text (`--night`) on a filled pill.
- Significance (1–10) is encoded as **fill count** on a 10-segment bar, tinted
  in the signal's category color — magnitude by quantity, not by hue shift.
- Accent (gold) is reserved: links, the live/active node, "you are here", and
  cost readouts. Never decorative.
- Chroma stays ≤ 0.19 on `--primary` (above ~0.23 it glows and kills text).

## Typography

Three families (display + body + mono), each with one job. Fixed rem scale
(product UI views at consistent DPI; no fluid headings).

```css
--font-display: 'Space Grotesk', system-ui, sans-serif;  /* wordmark, zone titles, big numerals */
--font-body:    'Inter', system-ui, sans-serif;          /* everything UI: labels, body, controls */
--font-mono:    'JetBrains Mono', ui-monospace, monospace;/* SHAs, diffs, counts, cost, timestamps */
```

Scale (rem, ratio ~1.2):
- `display-lg` 2.0rem / 700 / -0.02em — page + wordmark
- `display`    1.5rem / 600 / -0.02em — zone titles
- `title`      1.125rem / 600 — card / panel headers
- `body`       0.9375rem / 400 — default (line-height 1.55, prose ≤72ch)
- `label`      0.8125rem / 500 — controls, secondary
- `mono`       0.8125rem / 400 — data
- `eyebrow`    0.6875rem / 500 / 0.08em / uppercase — used **sparingly** as
  mono section labels, NOT above every section (banned reflex)

Space Grotesk is display-only — never in dense UI labels, buttons, or data.

## Spacing & Layout

- 4px base unit. Scale: 4 8 12 16 20 24 32 40 56 72 96.
- App shell: persistent top bar (wordmark + repo switcher + global sync/cost) +
  a left zone rail (Explore / Digest / Control). No sidebar card-grid.
- Constellation is full-bleed within the Explore zone with a docked inspector
  panel (right) that slides in on node/cluster selection — inline, not a modal.
- Responsive is **structural**: rail collapses to icons < 1024px; inspector
  becomes a bottom sheet < 768px; constellation stays canvas, gains pinch/zoom.
- Grids: `repeat(auto-fit, minmax(280px, 1fr))` where cards are genuinely the
  right affordance (digest feed). Avoid cards elsewhere.

## Elevation & Glow

Depth via tint + subtle glow, not heavy drop shadows (this is a night sky).
- Resting panel: `inset 0 0 0 1px var(--line)`.
- Raised (popover/menu): `inset 0 0 0 1px var(--line), 0 8px 24px oklch(0 0 0 / .4)`.
- Glow is a brand material: primary buttons and the live node carry a soft
  cobalt/gold halo (`0 0 28px oklch(... / .3)`). Use only on interactive or
  live elements — glow signals energy, not decoration.
- Z-scale (semantic): `--z-rail:10; --z-sticky:20; --z-inspector:30;
  --z-backdrop:40; --z-modal:50; --z-toast:60; --z-tooltip:70`.

## Iconography

One stroke style: 1.5–2px, rounded caps/joins, 24px grid (Lucide-grade,
inlined as SVG — never an icon-font dependency, and never `lucide-react`-style
runtime imports). Each signal category has a fixed glyph (see Color).

## Motion

Product cadence: 150–250ms, ease-out (quart/expo). Motion conveys state, not
choreography. No orchestrated page-load sequence.

- State: hover/focus 150ms; panel slide-in 220ms; signal enter fade+rise 200ms
  (stagger lists by ~40ms — legitimate, one list at a time).
- Constellation signatures (the one place motion is ambient): a very slow
  star-field drift, a soft pulse on the live node, cluster links that *draw*
  (stroke-dashoffset) when a cluster forms. All gentle, all paused under
  reduced motion.
- `@media (prefers-reduced-motion: reduce)`: drift stops, pulses become a
  static ring, draws become instant, transitions crossfade. Non-negotiable.
- Reveals enhance already-visible content — never gate visibility on a
  transition (headless/hidden-tab renders must still show everything).

## Components

Every interactive component ships all states: default, hover, focus-visible,
active, disabled, loading (skeleton, not spinner), error. Consistent vocabulary
across zones — one button shape, one input shape, one chip shape.

- **Button** — primary (cobalt fill, white text, glow), ghost (1px line),
  danger (rose). Focus = cobalt ring `0 0 0 3px oklch(... / .35)`.
- **Signal chip** — pill, category color + icon + label; significance bar
  variant appends `· N/10`.
- **Signal card** — avatar + repo + SHA(mono) + significance bar + category +
  summary; gold "in digest" / muted "filtered" footer.
- **Fork node** — circle sized by significance, category-colored, glow on
  hover; gold + halo when live/active; label on hover/zoom.
- **Cluster** — nodes joined by drawn links + a mono `⛓ name · N forks` tag.
- **Inspector panel** — docked right; node/cluster detail, agent reasoning,
  diff preview, cost. Slides in; never a modal.
- **Empty / first-run states teach**: "No repos tracked yet — add one to start
  watching its forks" with the action inline, not "Nothing here."

## Accessibility

WCAG 2.2 AA. Body ≥4.5:1, large ≥3:1 (verified against `--night`). Full
keyboard nav incl. the constellation (arrow-key node traversal + a list
fallback view of the same data). Visible focus everywhere. Status never by
color alone — always color + icon + label. All motion honors
`prefers-reduced-motion`.
```
