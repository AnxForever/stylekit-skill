---
name: stylekit
description: Apply a specific, consistent visual style to frontend UI you are generating. Use when building or styling web UI (pages, components, dashboards, landing pages) and you want a named aesthetic — Glassmorphism, Neo-Brutalist, Cyberpunk, Bauhaus, Apple, Stripe, Linear, and many more — instead of generic AI defaults. StyleKit gives you design tokens, component recipes, and AI rules for each style, with themes installable through the shadcn registry.
---

# StyleKit

Apply StyleKit's 146 curated visual styles to generated UI. Use the catalog, fetch the exact spec, install the theme, and honor the style's rules.

## Workflow

1. **Pick a style** — match the user's intent to a catalog slug.
2. **Fetch the full spec** — pull tokens, recipes, and AI rules for that slug.
3. **Install the theme** (optional) — drop the shadcn registry theme into the project.
4. **Generate with the rules** — use the style's exact tokens and do/don't lists.

## Step 1 — Pick a style

Match the user's request to a slug from the catalog:

- **Human catalog**: https://www.stylekit.top/styles
- **By theme**: https://www.stylekit.top/collections (dark-mode, retro-vintage, anime-manga, game-ui, colorful-bold, hand-drawn)
- **Colors / hex codes**: https://www.stylekit.top/colors
- **Machine-readable list**: `GET https://www.stylekit.top/api/styles` → `{ total, styles: [{ slug, nameEn, description, styleType, keywords, colors }] }`
- **Common style signatures**: see [references/style-signatures.md](references/style-signatures.md) for the visual traits of popular styles

For an ambiguous request, scan the `/api/styles` list keywords and pick the closest slug. When in doubt, ask the user between two candidates.

## Step 2 — Fetch the full spec

Fetch the machine-readable spec for the chosen slug — do not guess tokens or rules from memory (styles get updated):

```bash
python3 scripts/fetch-style.py <slug>            # full spec: tokens, recipes, rules
python3 scripts/fetch-style.py <slug> --tokens   # tokens only
python3 scripts/fetch-style.py <slug> --recipes  # recipes only
```

The script prints a compact spec for code generation. Raw endpoints are also available:

- Full pack: `GET https://www.stylekit.top/api/styles/{slug}`
- Markdown: `GET https://www.stylekit.top/api/styles/{slug}/md`
- Tokens: `GET https://www.stylekit.top/api/styles/{slug}/tokens`
- Recipes: `GET https://www.stylekit.top/api/styles/{slug}/recipes`
- Human page: https://www.stylekit.top/styles/{slug}

### Process the spec in priority order

1. **aiRules** — instruction string written for AI. Highest priority; overrides general patterns when they conflict.
2. **doList / dontList** — hard constraints. Every generated component must satisfy all items.
3. **philosophy** — the "why" behind the style. Determines ambiguous decisions (visual hierarchy, spacing, mood).
4. **colors** — `{ primary, secondary, accent[] }`. Source of truth for the palette.
5. **tokens** — semantic categories mapped to exact Tailwind classes. Use instead of inventing classes.
6. **components** — code templates for button, card, input (and optionally nav, hero, footer). Starting points.
7. **globalCss** — base CSS that must be included in the page/layout when using this style.

## Step 3 — Install the theme (optional)

Drop the theme into an existing shadcn/ui project (Tailwind v4):

```bash
npx shadcn add https://www.stylekit.top/r/<slug>.json
```

Requires a `tsconfig.json` in the target project. Injects the style's light + dark `cssVars` into `globals.css`. Full guide: https://www.stylekit.top/developers

## Step 4 — Generate with the style's rules

1. Use the style's **design tokens** (colors, spacing, typography, shadows, radii) — do not invent your own values.
2. Follow the **AI rules** and **doList/dontList** — they encode what makes the style read as intentional (e.g. Neo-Brutalist: thick borders, hard shadows, no rounded corners; Glassmorphism: high blur, translucency, inner glow).
3. Use **component templates** and **recipes** as starting points; adapt to the user's content.
4. Keep the style consistent across every component in the session, including responsive breakpoints (mobile-first).

### Good — uses exact token classes

```tsx
// Neo-Brutalist button — token classes from the fetched spec
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

### Bad — guessing classes, ignoring tokens

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

## Resources

- `references/style-signatures.md` — visual traits, forbidden, and required classes for popular styles
- `scripts/fetch-style.py` — fetch a style's spec from the API and print a compact code-generation reference
