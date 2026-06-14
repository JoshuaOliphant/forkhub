# Product

## Register

product

## Users

Developers who maintain or watch popular GitHub repositories and want to know
what is happening across the fork ecosystem — what others changed and why —
without manually trawling hundreds of forks. They are technically fluent,
comfortable with GitHub concepts (forks, diffs, SHAs), and willing to
self-host a tool from PyPI.

Their context is periodic check-in, not all-day monitoring: a daily or weekly
"what diverged" read, plus occasional deep dives into one repo's fork
landscape. The job to be done: turn the noise of N forks into a short list of
meaningful divergences and convergent trends worth acting on — upstreaming a
fix, adopting a feature, or simply staying aware.

## Product Purpose

ForkHub monitors the constellation of forks around a GitHub repository, uses a
Claude Agent SDK agent to classify what changed and why (signals: a category
plus a 1–10 significance score), clusters independent-but-similar changes via
vector similarity, and surfaces the interesting divergences through digests.

The web UI is the visual consumer of the ForkHub library (nothing
interesting lives only in the UI). It is one dashboard with three zones:

- **Explore** — the fork constellation and its clusters, navigated spatially.
- **Digest** — the triage feed of scored signals: what's new and noteworthy.
- **Control** — track/untrack repos, run syncs, watch agent progress and cost.

Success: a user opens ForkHub and within seconds understands what is new and
noteworthy across their forks, and can explore *why* a change was flagged.

## Brand Personality

**Observatory.** ForkHub is an instrument for observing something vast and
scattered. Forks are points of light; clusters are constellations you
discover; the digest is the night's notable sightings. The feel is calm,
exploratory, and quietly wondrous — three words: *observational, spacious,
precise*. It is technical and trustworthy without being sterile, and it
favors breathing room over density. The emotional goal is the satisfaction of
seeing structure emerge from noise.

## Anti-references

- **GitHub's own UI** — its navy/blue chrome, octicon language, and familiar
  dashboard. ForkHub watches GitHub; it must not look like GitHub.
- **Generic B2B SaaS dashboards** — the sidebar + uniform card grid +
  hero-metric tiles template.
- **Cluttered enterprise tools** (Jira, Datadog) — nested panels, dense noise,
  no room to breathe.
- **AI-generated slop tells** — cream/beige backgrounds, tiny uppercase
  tracked eyebrows over every section, gradient text, identical icon-card
  grids, decorative glassmorphism.

## Design Principles

1. **Signal over noise.** The product filters N forks down to what matters;
   the UI must do the same. Every screen answers "what deserves my attention?"
   first, and lets the rest recede.
2. **The map is the message.** Treat the constellation as a real navigational
   model, not decoration. Spatial relationships — divergence, clustering,
   distance — carry meaning a terminal cannot show.
3. **Explain as you go.** Shippable to strangers means signals, significance,
   and clusters are self-explanatory in context (first-run, empty states,
   inline definitions). Never assume the reader read the docs.
4. **Show the agent's reasoning and its cost.** Trust comes from transparency:
   surface why something was classified the way it was, and what the analysis
   cost. Don't hide the machine.
5. **Earn its own identity.** Deliberately not GitHub, not generic SaaS. Every
   default gets a "would this read as a GH clone or AI-generated?" check before
   it ships.

## Accessibility & Inclusion

Target WCAG 2.2 AA. Body text ≥4.5:1 contrast (large text ≥3:1), full keyboard
navigation with visible focus states, and `prefers-reduced-motion`
alternatives for every animation. Because signals are color-coded by category,
status must never rely on color alone — pair color with shape, label, or
position so the taxonomy survives color blindness and grayscale.
