# Using StyleKit assets

Use the asset catalogue when the task calls for a concrete StyleKit asset beyond a visual style brief. The catalogue owns the available kinds; ask it instead of assuming that every site page has an API or a downloadable file.

## Search, select, fetch

Search all kinds or narrow the request to one kind, then use an exact `kind/id` from the result:

```bash
python3 <skill-root>/scripts/fetch-asset.py search "grain texture" --kind background
python3 <skill-root>/scripts/fetch-asset.py search "hover" --kind animation --offset 15
python3 <skill-root>/scripts/fetch-asset.py get background ASSET_ID --json > /tmp/stylekit-asset.json
```

Omitting `--kind` searches across the catalogue. Read `kindCounts` and `hasMore` before deciding the result set is complete. Do not guess a slug or turn a website page URL into an API route. `--spec` reads a saved API response and `--from-file` reads a successful MCP envelope (`structuredContent` or a complete JSON text block); both validate the schema and exact ID. A saved catalogue is only the page saved in that file and cannot discover later pages.

The default source is `https://www.stylekit.top/api/assets`. For a local server, `--base-url` accepts an origin, `/api`, or the full `/api/assets` base. The expected contract is `schemaVersion: "1"`; if the server does not return it, report the missing or incompatible endpoint instead of inventing another route.

## Check availability and rights

A result has two separate signals:

- `availability` tells whether the asset is `bundled`, `remote`, `external`, or `restricted`.
- `contentLevel` tells whether the response has reusable `source`, `metadata` only, a `remote` source, or `restricted` content.

Use the detail's `license`, `attribution`, `sourceUrls`, `dependencies`, and `capabilities` as supplied. Do not infer reuse rights from the fact that an item appears in search.

The CLI keeps content according to those signals:

- Restricted items retain identifying and rights metadata; the CLI omits their source data, code, and dependencies.
- External items show their source references, but the CLI does not follow them or copy their source. Check that source's license before retrieving or adapting it.
- Metadata-only items stay metadata-only. Explain when an implementation source is unavailable instead of fabricating one.
- Bundled source can be used in context after checking its license and attribution fields. Remote templates need an explicit materialization or download action.

## Templates

Template detail can arrive with the full project bundle or with download metadata only. Prefer a fresh output directory when the response includes `data.files`:

```bash
python3 <skill-root>/scripts/fetch-asset.py get template editorial-blog --output-dir ./stylekit-editorial-blog
```

The script validates every relative path, rejects traversal and absolute paths, decodes only paths named by `data.binaryFiles` as base64 (the API's `UTF-8 text; paths listed in binaryFiles contain base64` encoding contract), and writes other files as UTF-8 text. It refuses to overwrite an existing destination and caps materialization at 500 files / 100 MiB. Review the files and dependencies before merging anything into the project.

If the response has only the official template download metadata, save the ZIP to a new path explicitly:

```bash
python3 <skill-root>/scripts/fetch-asset.py get template editorial-blog --download-to /tmp/editorial-blog.zip
```

The ZIP action is limited to the exact official `/api/templates/<id>/download` route, does not follow redirects, verifies the archive, and refuses to overwrite. It does not extract, install, or edit the target application. If source files are absent from a response, report that state; do not call the metadata record a complete template.

## Style and theme exports

For a named visual style, use `fetch-style.py <slug>` to read the complete style brief and tokens; `fetch-asset.py get style <slug>` is an asset record, not a substitute for the lintable `stylekit-brief-v1` contract. For a shadcn theme, inspect the official install command via `stylekit add <slug>` or the MCP `stylekit_get_shadcn_install` tool. If the user only asked for a recommendation, return the command without running it. If they asked to apply it, inspect what files it changes and validate the resulting theme in the target project.

## Integrate and verify

Treat the fetched record as source material, not a finished feature. Inspect the target stack and existing design before using a snippet. Adapt only the relevant files and preserve the site's content, states, responsive behavior, and accessibility. Check any listed dependency against the lockfile; do not install packages or change client configuration automatically.

A style brief and an asset serve different roles. Use `fetch-style.py` for a named style's full philosophy, tokens, component recipes, and static style rules. A retrieved animation, background, type treatment, or component pattern can complement that direction, but its presence does not prove the result looks or behaves correctly. `eval-check.py` checks static style classes only; verify asset integration with the project's build and relevant browser states (including reduced motion where animation is involved).

StyleKit's personal `/api/kits` data is authenticated and is not the public asset catalogue. Knowledge-resource search returns approved published metadata only, not source code; do not treat an empty result or a metadata record as a downloadable asset.
