# StyleKit Agent Skill

Give Cursor, Claude Code, Windsurf, or any Agent-Skills-compatible coding agent built-in knowledge of [StyleKit](https://www.stylekit.top) — how to browse its 146 curated visual styles and apply them with correct tokens and rules.

## Install

```bash
npx skills add AnxForever/stylekit-skill
```

Your agent can then apply any of the 146 styles on request ("make it look like Stripe", "cyberpunk dashboard", "cozy cottagecore blog") using the style's exact design tokens, component recipes, and AI rules.

## What it does

- Picks the right style slug from the catalog for the user's request
- Fetches the full machine-readable spec (tokens, recipes, do/don't rules) from the StyleKit API
- Optionally installs the theme into a shadcn/ui project via the registry
- Generates components that honor the style's constraints instead of generic AI output

## What it is not

This is a **user-facing skill** for people who build UI with StyleKit. It does not cover contributing new styles or animations to the StyleKit repository — that workflow lives in the main repo's contributor documentation.

## Source

The skill body is a single file: [`SKILL.md`](./SKILL.md). Full docs and catalog: https://www.stylekit.top

## License

MIT — see [LICENSE](./LICENSE).
