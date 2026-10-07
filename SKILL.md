---
name: stylekit
description: Apply StyleKit visual styles and public assets when building, restyling, or reviewing UI. Use for named StyleKit styles, visual direction, mobile interface patterns, and component-library selection; preserve the target platform and existing product behavior.
---

# StyleKit

Use StyleKit to give frontend UI a recognizable visual direction. Begin with the user's goal and the target project's existing structure; a style spec guides the design but does not replace product decisions.

## Start with the installed copy

`<skill-root>` is the directory containing this file, not the target project's `scripts/` directory. Scripts require Python 3.10+. Replace placeholders with real paths and keep paths quoted. Save task artifacts in a new task-specific directory (`<work-dir>` below); do not reuse another task's spec file.

For a pinned tag/commit installation, disable updates before the first check. Otherwise run:

```bash
python3 "<skill-root>/scripts/update-skill.py" --auto
```

On `UPDATED`, reread this file. Other statuses continue with the installed instructions; offline checks do not block work. Updates follow GitHub `main` at most once per 24 hours and skip the entire update when managed files have local changes or path collisions. See [updates](references/updates.md) for pinning, controls, migration, and recovery; do not remove local protections to make a check pass.

## Route the actual task

| Request | Approach |
| --- | --- |
| Build new UI | Choose a direction, load its spec, implement the actual content and states. |
| Restyle or fix existing UI | Preserve behavior, routing, and data; change the relevant visual decisions. |
| Compare or recommend libraries | Identify the platform, compare suitable candidates with official sources; implement only if requested. |
| Review consistency | Inspect the existing result against the saved spec; report concrete findings. |
| Retrieve an asset or template | Follow [assets](references/assets.md); use exact returned `kind/id`, availability, and license. |

For mobile screens, responsive interactions, or libraries such as ChunUI, read [mobile UI](references/mobile-ui.md). Establish Web/H5, React Native/Expo, SwiftUI, or Flutter before choosing components. A mobile-looking browser page is still a web implementation.

## Understand and select

Inspect the target app and reuse its installed primitives. If the stack is unclear:

```bash
python3 "<skill-root>/scripts/detect-project.py" "<project-root>"
```

Detection is evidence, not a compatibility guarantee. Dependencies are declared ranges; inspect the lockfile and app subdirectory when versions or workspace boundaries matter. Do not migrate frameworks to match a suggested library.

For an explicit style, use its exact slug. Otherwise search and choose a fitting direction from the user's context; ask only when an unresolved choice materially changes the outcome. Library recommendations alone do not require fetching a style spec.

```bash
python3 "<skill-root>/scripts/fetch-style.py" --search "frosted glass"
python3 "<skill-root>/scripts/fetch-style.py" "<slug>" --json > "<work-dir>/spec.json"
```

Use the same saved spec for implementation and evaluation. `_stylekitSource.degraded` marks legacy data that may lack curated lint rules; explain that limit. If fetching fails, reuse an identified saved spec or state that the current catalog could not be verified; do not invent a successful fetch, slug, or rule.

For saved CLI/API/MCP inputs or a local API, read [spec sources and checks](references/spec-workflow.md). The Skill does not install MCP packages or edit client configuration.

## Implement in context

Use philosophy, tokens, signature elements, and recipes where they fit the product. Preserve explicit user choices, existing interactions, and accessibility when they conflict with a style rule. Recipes are starting points. For native targets, translate the visual intent into platform components; DOM markup and Tailwind classes are not native APIs.

Keep focused changes focused. For new UI, include its required loading, empty, error, and success states. Use [design principles](references/design-principles.md) for visual review and [style signatures](references/style-signatures.md) only for the styles it covers.

Integrate `globalCss` with the existing cascade. In Tailwind v4, put generic resets that should yield to utilities in `@layer base` or scope them deliberately; unlayered selectors can override utility styles.

## Verify what was built

For compatible web class rules, check isolated controls against the saved spec:

```bash
python3 "<skill-root>/scripts/eval-check.py" "<slug>" "<component-file>" --spec "<work-dir>/spec.json" --component button --strict
```

Required classes are matched across the entire input file, not per element. A full-page strict pass cannot prove every control passed. Missing rules or dynamic classes can be `inconclusive`; inspect them. This evaluator is not a SwiftUI, React Native, Flutter, asset, or accessibility validator. For scan modes and conflicting spec rules, read [spec sources and checks](references/spec-workflow.md).

Run the target project's relevant checks, render at appropriate sizes, and exercise the changed states. Inspect computed colors and focus behavior, not just class names. For native work, distinguish source review, build, simulator, and device checks. Report the implementation and actual verification separately, including any unavailable runtime. See [forward testing](references/forward-test.md) for repeatable agent evaluation.
