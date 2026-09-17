# stylekit-skill

[简体中文](README.md) · **English**

> A frontend style Skill for AI agents — make generated UI follow a **specific, named** visual direction instead of the generic AI default.

[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

The Agent Skill implementation of [StyleKit](https://github.com/AnxForever/stylekit) (509 stars). It lets an AI ask the style library for design tokens, component recipes and do/don't rules — then generate against those rules.

---

## Why it exists

Ask an AI to build you a landing page and you get something that works and looks like every other AI-built landing page.

The problem is not the model — **"make it look good" is not a specification.** StyleKit turns a visual direction into something an agent can actually follow: a named style, real tokens, hard constraints, and a demo you can look at first.

---

## Workflow

```
Detect project context → Pick a style → Fetch the full spec → Install the theme → Generate with the rules
```

| Step | What happens |
| --- | --- |
| **1. Detect context** | Know the target project's stack before generating, instead of guessing |
| **2. Pick a style** | Match the user's intent to a catalog slug |
| **3. Fetch the spec** | Pull that style's tokens, component recipes and AI rules |
| **4. Install the theme** (optional) | Drop the shadcn registry theme into the project |
| **5. Generate with the rules** | Use the style's exact tokens and do/don't lists |

## Task routing

Different paths for different requests:

- **New UI** (page, component, dashboard, landing page) → the full workflow
- **Restyle / fix existing UI** ("this looks generic", "make it feel more Stripe") → edit only the parts that violate the style's tokens and rules; keep the existing structure and states
- **Migrate between styles** → fetch both specs, diff their tokens and forbidden lists, then update class by class. Never mix tokens from two styles
- **Review / audit consistency** → fetch the spec and check every component against doList/dontList and the token table, reporting violations concretely (file, element, class)

---

## Scripts

| Script | What it does |
| --- | --- |
| `detect-project.py` | Detect the target project's frontend context so generated UI matches its actual stack |
| `fetch-style.py` | Fetch a style spec from the public API and print a code-generation-oriented reference |
| `verify-spec.py` | Check API specs for internal consistency — **when the data contradicts itself, the agent invents tokens and breaks style rules** |
| `eval-check.py` | **The acceptance detector**: feed it code plus a style slug and it reports every concrete rule violation (forbidden classes, missing items) |
| `benchmark.py` | With-skill vs without-skill generation quality (fixture mode by default, CI-safe) |

`eval-check.py` and `benchmark.py` are the point of the design: **style constraints are detected, not assumed.** The benchmark adds a reproducible comparison for whether the skill itself is pulling its weight.

## References

- `references/design-principles.md` — iteration modes and design principles
- `references/style-signatures.md` — recognizable signatures per style

---

## Install

```bash
npx skills add AnxForever/stylekit-skill
```

## Related

| Project | What it is |
| --- | --- |
| [stylekit](https://github.com/AnxForever/stylekit) | The style library itself (509 stars) · [stylekit.top](https://stylekit.top) |
| [stylekit-mcp](https://github.com/AnxForever/stylekit-mcp) | MCP server — call it from Claude Code / Cursor |
| **stylekit-skill** | This repository: the Agent Skill |

## License

MIT — see [LICENSE](LICENSE)
