# Spec sources and static checks

Read this when reusing CLI/API/MCP output, changing the API source, diagnosing incomplete specs, or performing detailed consistency checks. Use a task-specific directory and the same saved specification throughout.

## Sources

The default source is the public styles API. A local server can be selected with `--base-url http://127.0.0.1:3189/api/styles`; this is an example address, not an assumed running service.

To normalize a previously saved API brief or legacy style response:

```bash
python3 "<skill-root>/scripts/fetch-style.py" "<slug>" --spec "<work-dir>/saved-api-response.json" --json > "<work-dir>/spec.json"
```

For an available MCP connection, request `stylekit_get_implementation_brief` and save the complete tool result:

```bash
python3 "<skill-root>/scripts/fetch-style.py" "<slug>" --from-file "<work-dir>/mcp-result.json" --json > "<work-dir>/spec.json"
```

`--spec` accepts the full `stylekit-brief-v1` contract or a supported legacy style response. Arbitrary JSON, token-only output, and CLI display summaries are not interchangeable with a full spec. `--from-file` reads `structuredContent` first, then a text block containing the complete JSON brief. Neither Python command installs a CLI, starts a server, or configures a client. An MCP error or malformed result is not a usable spec.

If the StyleKit CLI is already part of the workflow, its `brief` command is another valid source. The published `stylekit-cli@0.3.1` was checked on 2026-10-07: its output normalizes through `--spec` as `stylekit-brief-v1`. Check the installed version's help or use this exact package name/version for a reproducible invocation:

```bash
npx --yes stylekit-cli@0.3.1 brief "<slug>" > "<work-dir>/cli-brief.json"
python3 "<skill-root>/scripts/fetch-style.py" "<slug>" --spec "<work-dir>/cli-brief.json" --json > "<work-dir>/spec.json"
```

`npx` may download the package. This is optional; `fetch-style.py` reads the HTTP brief directly without Node or npm. The npm package is `stylekit-cli`, while its installed executable is `stylekit`; do not substitute the unrelated npm package named `stylekit`.

The HTTP loader falls back to the legacy endpoint only when the implementation-brief endpoint returns 404. `_stylekitSource.degraded` records that fallback; legacy data may lack curated lint rules. Other failures do not establish that a legacy endpoint is safe or equivalent. Use only fields actually present.

## Static class checks

Use isolated component files or snippets for `--component ... --strict`. Required classes are checked against the union of classes in an input, not independently for each element. Use `--dir "<project-root>"` for a broad scan without component-required checks.

The evaluator checks statically readable web classes. It does not compile CSS, resolve every expression, validate native UI, or prove visual/interaction quality. Missing rules and unsupported patterns can make results `inconclusive`; review them rather than calling them passed. Keep application build, runtime, accessibility, and asset-integration results separate.

If a recipe contradicts another part of its spec:

```bash
python3 "<skill-root>/scripts/verify-spec.py" "<slug>" --spec "<work-dir>/spec.json"
```

Report the conflicting fields and classes. Preserve user/product requirements rather than silently weakening the official rule or claiming its example passed. Do not open an upstream issue unless the user requests it.
