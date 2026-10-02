# stylekit-skill

[简体中文](README.md) · **English**

> An Agent Skill for applying a named visual direction to frontend UI in the context of an existing product.

[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

This is the Agent Skill for [StyleKit](https://github.com/AnxForever/stylekit). It reads the style catalogue, implementation specs and public asset catalogue, then helps create or restyle UI in the target project. It can fetch public APIs directly or reuse data returned by StyleKit CLI or MCP.

## Workflow

```text
Understand the project → Pick a style → Read its spec → Implement in context → Review the result
```

| Step | What happens |
| --- | --- |
| **1. Understand context** | Check the framework, Tailwind version and existing components |
| **2. Pick a style** | Match the user's intent to a catalogue slug |
| **3. Read the spec** | Get the available style guidance, tokens, recipes and checks |
| **4. Implement and review** | Apply the style to the product, then inspect code and the actual page |

The Skill routes between new UI, focused restyles, migrations and consistency reviews. For a focused restyle, it keeps the current structure and states unless the user asks to change them.

## Scripts and spec files

The scripts require Python 3.10 or newer. After installation, they live inside the Skill's own `scripts/` directory. When running from a target project, use the installed Skill path; do not assume the target project has its own `scripts/` copy.

Fetch one spec and use that same saved file for generation and evaluation:

```bash
python3 <skill-root>/scripts/fetch-style.py neo-brutalist --json > /tmp/stylekit-spec.json
python3 <skill-root>/scripts/eval-check.py neo-brutalist ./button.tsx --spec /tmp/stylekit-spec.json --component button --strict
```

`--spec` accepts JSON from the CLI or API. `--from-file` accepts an MCP tool-result JSON envelope, preferring `structuredContent` and then a text block containing the complete JSON. `_stylekitSource.degraded` marks a legacy spec that may not include the full lint contract. For a local StyleKit API, pass `--base-url http://127.0.0.1:3189/api/styles`.

`eval-check.py` checks statically readable class rules only. Its `pass` does not prove that UI compiles, looks right, behaves correctly or meets accessibility needs. Dynamic expressions or unavailable rules can produce `inconclusive`, which needs manual review.

The default benchmark uses four fixed template tasks to check the evaluator and sample data; it does not measure real model output quality. `--llm` calls an OpenAI-compatible endpoint for a small comparison. To observe whether an agent actually applies the Skill, run a manual forward test in an isolated consumer project; [the protocol and evidence limits are here](references/forward-test.md).

## Public assets

The asset script searches StyleKit's `/api/assets` catalogue; the returned catalogue defines its available kinds. It can retrieve specific animations, backgrounds, gradients, shadows, typography, component patterns, prompt resources, templates and experience packs. It reports availability, content level, sources, license and dependencies instead of implying every search result includes reusable code.

```bash
python3 <skill-root>/scripts/fetch-asset.py search "grain texture" --kind background
python3 <skill-root>/scripts/fetch-asset.py get background ASSET_ID --json > /tmp/stylekit-asset.json
python3 <skill-root>/scripts/fetch-asset.py get template editorial-blog --output-dir ./stylekit-editorial-blog
python3 <skill-root>/scripts/fetch-asset.py get template editorial-blog --download-to /tmp/editorial-blog.zip
```

Replace the example ID with an exact `kind/id` from search results. Template files are written only to a new directory; a template ZIP requires an explicit destination. Neither action extracts a ZIP, installs dependencies or changes app configuration. Restricted assets show metadata only, and external sources are not followed automatically. See [references/assets.md](references/assets.md) for the workflow and limits. `--spec` accepts saved API JSON; `--from-file` accepts a compatible MCP structured result or complete JSON text block. For a local server, pass `--base-url http://127.0.0.1:3189/api/assets`.

## References

- `references/design-principles.md` — visual review and interaction guidance
- `references/assets.md` — asset search, licensing, template import and verification
- `references/style-signatures.md` — recognizable signatures for selected styles

## Install the Skill

```bash
npx skills add AnxForever/stylekit-skill
```

This installs only the Agent Skill; it does not install or configure the MCP server. On each Skill invocation, the instructions check the official GitHub `main` archive at most once every 24 hours and ask the agent to reread `SKILL.md` if updated. Offline checks continue with the installed version; local edits to managed files skip the entire update. Clients still decide whether to follow Skill instructions, so the repository cannot force every client to run the check. If your installation source is explicitly pinned to a tag or commit, disable automatic updates first; the updater does not detect the installer's pin and otherwise follows `main`.

Existing installations need a one-time migration. From the project directory, run `npx skills@latest update stylekit`; for a global installation, run `npx skills@latest update stylekit --global`. The Skills CLI may replace the existing Skill directory; save local customizations first. After migration, the bundled updater protects local changes. You can inspect or control it with:

```bash
python3 <skill-root>/scripts/update-skill.py --status
python3 <skill-root>/scripts/update-skill.py --disable
python3 <skill-root>/scripts/update-skill.py --enable
python3 <skill-root>/scripts/update-skill.py --force-check
```

A forced check bypasses only the 24-hour interval and never overwrites local changes. Disabling updates stops both automatic and forced checks until re-enabled.

## Optional MCP server

To call StyleKit through MCP, add this stdio server entry to your client's MCP configuration:

```json
{
  "mcpServers": {
    "stylekit": {
      "command": "npx",
      "args": ["-y", "--prefer-online", "stylekit-mcp@latest"]
    }
  }
}
```

This is a separate integration. The Skill does not edit client configuration. StyleKit MCP `0.4.0` provides nine read-only tools, including style briefs and public asset catalogue/detail access. With `@latest`, npm checks for the current package when the client starts the MCP process; an already running process must be restarted to use a new version.

## Related projects

| Project | What it is |
| --- | --- |
| [stylekit](https://github.com/AnxForever/stylekit) | The style library · [stylekit.top](https://stylekit.top) |
| [stylekit-mcp](https://github.com/AnxForever/stylekit-mcp) | Optional MCP server for MCP-compatible clients |
| **stylekit-skill** | This repository: the Agent Skill |

## Release maintenance

After changing `SKILL.md`, `scripts/`, `references/`, `agents/` or `assets/`, increment `RELEASE_VERSION` in `scripts/generate-release-manifest.py` and run `python3 scripts/generate-release-manifest.py`. CI checks the payload hashes and requires a version increase whenever managed files change. The manifest excludes itself and local update state.

## License

MIT — see [LICENSE](LICENSE)
