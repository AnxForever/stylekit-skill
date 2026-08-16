---
name: stylekit
description: Apply a specific, consistent visual style to frontend UI you are generating. Use when building or styling web UI (pages, components, dashboards, landing pages) and you want a named aesthetic — Glassmorphism, Neo-Brutalist, Cyberpunk, Bauhaus, Apple, Stripe, Linear, and many more — instead of generic AI defaults. StyleKit gives you design tokens, component recipes, and AI rules for each style, with themes installable through the shadcn registry.
metadata:
  homepage: https://www.stylekit.top
---

# StyleKit

StyleKit is an open-source style library for AI coding with 146 curated
visual styles, each with machine-readable design tokens, component recipes, and
AI rules. Use it to make the UI you generate look like a deliberate, named style
instead of generic AI output.

## When to use

- The user asks for a specific look ("make it look like Stripe", "cyberpunk
  dashboard", "cozy cottagecore blog", "brutalist landing page").
- You are generating frontend UI and want a coherent, consistent design system
  rather than ad-hoc styling.
- The user wants their AI-generated site to match an aesthetic across many
  components.

## Workflow

For any request, follow this order:

1. **Pick a style** — match the user's intent to a catalog slug.
2. **Fetch the full spec** — pull tokens, recipes, and AI rules for that slug.
3. **Install the theme** (optional) — drop the shadcn registry theme into the project.
4. **Generate with the rules** — use the style's exact tokens and do/don't lists.

## Step 1 — Pick a style

Browse the catalog and machine-readable index:

- Human catalog: https://www.stylekit.top/styles
- Browse by theme: https://www.stylekit.top/collections (dark-mode, retro-vintage,
  anime-manga, game-ui, colorful-bold, hand-drawn)
- Colors / hex codes: https://www.stylekit.top/colors
- JSON list of every style: `GET https://www.stylekit.top/api/styles`
  → `{ total, styles: [{ slug, nameEn, description, styleType, keywords, colors, ... }] }`
- Full machine-readable spec for agents: https://www.stylekit.top/llms-full.txt
- Markdown spec for agents: https://www.stylekit.top/llms.txt

Each style has a `slug` (e.g. `glassmorphism`, `neo-brutalist`, `stripe-style`,
`bauhaus`). You need the slug for the next step.

## Step 2 — Fetch the full spec

For the chosen slug, fetch the machine-readable spec — do not guess tokens or
rules from memory (styles get updated):

- Full style pack: `GET https://www.stylekit.top/api/styles/{slug}`
  → `{ slug, name, description, philosophy, doList, dontList, aiRules, colors, components, globalCss, tokens, recipes, version }`
- Markdown rendering: `GET https://www.stylekit.top/api/styles/{slug}/md`
- Tokens only: `GET https://www.stylekit.top/api/styles/{slug}/tokens`
- Recipes only: `GET https://www.stylekit.top/api/styles/{slug}/recipes`
- Human page: https://www.stylekit.top/styles/{slug}

### Understand the style anatomy

Process the spec fields in this priority order:

1. **aiRules** — compact instruction string written specifically for AI. Highest priority; overrides general patterns when they conflict.
2. **doList / dontList** — hard constraints, not suggestions. Every generated component must satisfy all items.
3. **philosophy** — the "why" behind the style. Read first to determine ambiguous decisions (visual hierarchy, spacing intent, mood).
4. **colors** — `{ primary, secondary, accent[] }`. Always the source of truth for the palette.
5. **tokens** — semantic categories mapped to exact Tailwind classes. Use them instead of inventing classes.
6. **components** — code templates for button, card, input (and optionally nav, hero, footer). Starting points, not copy-paste targets.
7. **globalCss** — base CSS that must be included in the page/layout when using this style.

## Step 3 — Install the theme (optional)

Drop the theme into an existing shadcn/ui project (Tailwind v4):

```bash
npx shadcn add https://www.stylekit.top/r/<slug>.json
```

Requires a `tsconfig.json` in the target project. The CLI injects the style's
light + dark `cssVars` into `globals.css`. Full guide: https://www.stylekit.top/developers

## Step 4 — Generate with the style's rules

1. Use the style's **design tokens** (colors, spacing, typography, shadows,
   radii) — do not invent your own values.
2. Follow the **AI rules** and **doList/dontList** — these encode what makes the
   style read as intentional (e.g. Neo-Brutalist: thick borders, hard shadows,
   no rounded corners; Glassmorphism: high blur, translucency, inner glow).
3. Use the **component templates** and **recipes** as starting points; adapt to
   the user's content.
4. Keep the style consistent across every component you generate in the session,
   including responsive breakpoints (mobile-first).

### Example — good (uses exact token classes)

```tsx
// Neo-Brutalist button — token classes from the style pack
<button className="
  px-6 py-3
  bg-[#ff006e] text-white font-black
  border-2 md:border-4 border-black rounded-none
  shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] md:shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]
  hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px]
  active:translate-x-[4px] active:translate-y-[4px]
  transition-all duration-200
">
  Click Me
</button>
```

### Example — bad (guessing classes, ignoring tokens)

```tsx
// WRONG: rounded-lg violates neo-brutalist (must be rounded-none)
// WRONG: shadow-lg violates neo-brutalist (must use hard-edge shadow)
// WRONG: bg-blue-500 is not in the style's color palette
<button className="px-6 py-3 bg-blue-500 rounded-lg shadow-lg">Click Me</button>
```

## Anti-patterns

- **Don't mix tokens from different styles.** Each style's tokens are internally consistent; mixing produces incoherent UI.
- **Don't ignore aiRules.** They override general patterns and may contradict common Tailwind conventions.
- **Don't use generic Tailwind when style-specific tokens exist.** Use `shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]` for neo-brutalist, not `shadow-md`.
- **Don't skip the philosophy.** It determines visual hierarchy decisions.
- **Don't generate without checking doList/dontList.** A glassmorphism component without `backdrop-blur` is broken; a neo-brutalist component with `rounded-lg` is wrong.
- **Don't hardcode hex values.** Use the style's `colors` object and token classes.
- **Don't rely on memory — always fetch the spec.** Styles get updated; stale data leads to violations.

## Popular styles — visual signatures

| Style | Key Visual Traits | Forbidden | Required |
|-------|------------------|-----------|----------|
| `neo-brutalist` | Black borders, hard shadows, no rounding | `rounded-*`, `shadow-lg`, gradients | `rounded-none`, `border-black`, hard-edge `shadow-[...]` |
| `glassmorphism` | Frosted glass, blur, translucent | `rounded-none`, `bg-white`, `border-black` | `backdrop-blur-*`, `bg-white/N`, `border-white/N` |
| `neumorphism` | Soft extruded surfaces, subtle shadows | Hard shadows, high contrast borders | Dual shadows (light + dark), soft bg |
| `claymorphism` | Puffy 3D clay look, inner shadows | Flat shadows, sharp corners | Inner shadow, rounded corners, pastel bg |
| `apple-style` | Clean, precise, SF Pro feel | Heavy borders, loud colors | Subtle shadows, system fonts, generous whitespace |
| `material-design` | Elevation system, ripple effects | Hard-edge shadows, no-radius | `shadow-md`, `rounded-lg`, elevation layers |
| `pixel-art` | Pixelated edges, 8-bit aesthetic | Smooth gradients, anti-aliased borders | `rounded-none`, pixel fonts, step-based colors |
| `cyberpunk-neon` | Neon glows, dark bg, electric colors | Pastel colors, soft shadows | Neon `shadow-[0_0_Npx_color]`, dark bg, bright accents |
| `swiss-style` | Grid-based, Helvetica, minimal | Decorative elements, rounded corners | Grid alignment, sans-serif, high contrast |
| `art-deco` | Gold accents, geometric patterns, luxury | Casual fonts, muted colors | Gold/brass tones, geometric borders, serif fonts |
| `ghibli-style` | Warm watercolor, hand-drawn feel | Sharp edges, neon colors | Soft pastels, rounded shapes, warm tones |
| `vaporwave` | Purple/pink gradients, retro-futurism | Muted earth tones, minimal palette | Gradient bg, neon pink/cyan, retro fonts |
| `dark-mode` | Dark surfaces, subtle elevation | Pure white bg, low contrast | Dark bg, muted text, subtle borders |
| `editorial` | Typography-driven, magazine layout | Heavy UI chrome, small text | Large type, generous spacing, serif headings |
| `korean-minimal` | Soft, airy, pastel, generous whitespace | Heavy borders, loud colors | Subtle pastels, thin borders, rounded-2xl |

## Notes

- Styles span three axes: brand-inspired (Apple, Stripe, Linear, Notion,
  GitHub), aesthetic (Glassmorphism, Neo-Brutalist, Cyberpunk, Vaporwave), and
  cultural (Bauhaus, Ghibli, Wabi-Sabi, Ukiyo-e).
- Everything is free and open source (MIT). Full docs: https://www.stylekit.top/developers
