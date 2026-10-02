---
name: stylekit
description: Apply StyleKit visual styles or retrieve its public assets when creating or changing frontend UI, while honoring the user's request, existing product and accessibility.
---

# StyleKit

Use StyleKit to give frontend UI a recognizable visual direction. Begin with the user's goal and the target project's existing structure; a style spec guides the design but does not replace product decisions.

## Workflow

1. **Understand the project.** Inspect the files involved. When the stack or installed UI components are unclear, run the bundled detector with the actual target directory:

   ```bash
   python3 <skill-root>/scripts/detect-project.py <project-root>
   ```

   `<skill-root>` means the directory containing this `SKILL.md`; resolve it from the loaded Skill's location. These scripts are not copied into the target project's own `scripts/` directory. The detector reports dependency declarations, which may be version ranges; check the lockfile if an exact installed version affects the implementation.

2. **Choose a style or asset.** Use the exact slug when the user names a style. Otherwise search the style catalog and compare a small number of plausible matches:

   ```bash
   python3 <skill-root>/scripts/fetch-style.py --search "frosted glass"
   ```

   If the choice would materially change the result and the request is ambiguous, ask the user to choose between the closest options.

   For a request that needs a StyleKit asset such as an animation, background, gradient, shadow, type treatment, component pattern, prompt, template, or experience pack, search the public asset catalogue and fetch only the selected `kind/id`. Read [references/assets.md](references/assets.md) for availability, license, integration and verification guidance. The asset catalogue supplements a style brief; it does not replace one.

3. **Load the complete available specification.** Prefer one source for the whole task and pass the same saved specification to the evaluator:

   ```bash
   python3 <skill-root>/scripts/fetch-style.py <slug> --json > /tmp/stylekit-spec.json
   ```

   For a local StyleKit server, point at its styles API base, for example `--base-url http://127.0.0.1:3189/api/styles`.

   You can also reuse a saved CLI brief (`stylekit brief <slug> > /tmp/stylekit-brief.json`) with `--spec`, or a saved MCP tool result with `--from-file`:

   ```bash
   python3 <skill-root>/scripts/fetch-style.py <slug> --spec /tmp/stylekit-brief.json --json > /tmp/stylekit-spec.json
   python3 <skill-root>/scripts/fetch-style.py <slug> --from-file /tmp/stylekit-mcp-result.json --json > /tmp/stylekit-spec.json
   ```

   For MCP, request `stylekit_get_implementation_brief` and save its complete result; the script reads `structuredContent` first, then a text block containing the JSON brief. The Skill does not install MCP packages or change client configuration. Optional MCP setup is documented separately in the repository README.

   The API may return a legacy spec when the implementation-brief endpoint is unavailable. The saved JSON records this in `_stylekitSource.degraded`; legacy data may lack curated lint rules. Explain that limitation and use only the information the response actually contains.

4. **Apply the visual direction in context.** Use the style's philosophy, signature elements, tokens, recipes, and rules where they fit. Adapt example components to the product's content, interactions, responsive layout, and existing code. If a style rule conflicts with the user's explicit request, the product's established behavior, technical constraints, or accessibility, preserve those requirements and explain any visible tradeoff. Treat recipes and generated examples as starting points, not proof that the result is correct.

   For a focused restyle, keep the existing structure and states unless the user asks to change them. For new UI, include the states and responsive behavior the actual feature needs.

   Integrate `globalCss` with the project's cascade. In Tailwind v4, place generic resets that should yield to utilities in `@layer base` or scope them deliberately; unlayered selectors can override utility styles.

5. **Check the result.** Run the static evaluator against the exact saved spec used for generation:

   ```bash
   python3 <skill-root>/scripts/eval-check.py <slug> <component-file> --spec /tmp/stylekit-spec.json --component button --strict
   ```

   Use a single-component snippet for `--component ... --strict`. Never treat one full-page run as proof that every component passed: required classes are matched against the union of classes in the input file, not separately for each element. Check each control or component in isolation. Use `--dir <project-root>` for a broad scan without component-required checks. Dynamic class expressions, missing rules, or unsupported patterns can make the result `inconclusive`; inspect them manually instead of calling them passed. The checker covers static class rules only. It does not prove that the UI compiles, looks right, behaves correctly, or meets accessibility needs.

   Review the compiled page at relevant widths and exercise its important states. Inspect computed text and background colors for primary actions and small text; the cascade can make a class look correct while rendering it unreadable. For new UI, use the swap and signature checks in [references/design-principles.md](references/design-principles.md). Load [references/style-signatures.md](references/style-signatures.md) when selecting or applying one of its covered styles. Use [references/forward-test.md](references/forward-test.md) for a repeatable manual agent test.

## Asset integration

For assets beyond a style brief, use `fetch-asset.py` and follow [references/assets.md](references/assets.md). Do not use `eval-check.py` as evidence that an animation, template, or other asset is correctly integrated; it checks static style classes only.

## Specification conflicts

If a recipe, template, or rule contradicts another part of the same specification, run the consistency check against the saved input:

```bash
python3 <skill-root>/scripts/verify-spec.py <slug> --spec /tmp/stylekit-spec.json
```

Report the conflicting fields and classes. Do not silently weaken a rule or claim the official example passed. The user can decide whether to report the catalog issue; do not open an issue on their behalf.
