# Design Principles

Quality bar for generated UI. Apply these alongside the style's own rules — the style spec defines *what* the UI looks like; these define *how well* it is built.

## Intent First

Before generating, define:

- **purpose** — what this UI must achieve
- **audience** — who uses it and what they value
- **tone** — aesthetic direction
- **visual emphasis** — what should attract attention, if the task needs a new direction

## Iteration Modes

- `new`: create complete structure from scratch with full state coverage.
- `polish`: keep structure stable, improve typography/spacing/consistency first.
- `debug`: prioritize overflow/clipping/z-index/state regressions with minimal structural changes.
- `contrast-fix`: enforce WCAG contrast and readability without breaking brand tone.
- `layout-fix`: fix grid/flex rhythm, responsive breakpoints, and viewport overflow.
- `component-fill`: complete missing components and interaction states before adding effects.

## Reference-driven Generation

- Screenshot input: extract layout hierarchy and spacing first, then map to semantic components.
- Figma input: align frame structure and token cues (color/type/spacing) with code architecture.
- Mixed input: keep one source-of-truth per decision (layout/color/type/motion) to avoid conflicts.
- Never copy a visual reference blindly; explicitly restore missing states (hover/focus/loading/error).

## Anti-generic Heuristics

- Avoid interchangeable templates with no style point-of-view.
- Avoid default purple-on-white gradient clichés unless the style explicitly requires it.
- Choose typography for the product and platform. A system font can be the right choice for native UI, dense tools, or an established design system.
- Add texture, depth, or motion when it supports the chosen direction; a focused repair does not need a new visual theme.

## Token Hierarchy

Follow the project's existing token model. When a new model is needed, separate:

1. Brand tokens
2. Semantic tokens (primary/surface/text/border)
3. Component tokens (button/card/input)
4. State tokens (hover/active/focus/disabled)

Component layering model: **Base → Variant → Size → State → Override**.

## Typography Direction

- Use an expressive display face only when the visual direction calls for it; preserve platform scaling and existing brand typography.
- Use scale/weight/spacing contrast to drive hierarchy.
- Keep type rhythm consistent across breakpoints.

## Accessibility Baseline

- Contrast target: WCAG AA (4.5:1 for normal text)
- Focus-visible states required for keyboard users
- Touch targets: prefer comfortable hit areas for primary actions. For Web, WCAG 2.2's minimum is 24 by 24 CSS px or a documented exception; use the native platform's units and guidance for apps.
- Respect `prefers-reduced-motion`
- Mention interaction states (hover/active/focus/disabled) in the component spec

## Pre-delivery Validation

Run these before delivering generated UI:

- **Swap test**: if replacing your key choices with defaults still looks similar, the style identity is weak.
- **Squint test**: hierarchy should remain clear when details are blurred.
- **Signature test**: identify the concrete choices that carry the selected style; judge them relative to the scope of the change.
- **Token test**: token names/values should reflect product semantics, not generic template language.

## Anti-pattern Blacklist

- Do not use absolute positioning as the main page layout strategy.
- Do not rely on nested scrolling containers for core content flow.
- Do not remove focus styles without visible focus-visible replacements.
- Do not ship forms without loading/disabled/error-recovery states.
- Avoid god components and deep prop drilling for basic UI assembly.
