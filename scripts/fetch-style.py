#!/usr/bin/env python3
"""Fetch complete generation inputs, or search the StyleKit catalogue."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from spec_input import load_spec_file, normalize_base_url, normalize_spec as normalize_style_spec, validate_spec_object

BASE = "https://www.stylekit.top/api/styles"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("API returned a non-object payload")
    return result


def normalize_spec(spec: dict) -> dict:
    """Compatibility wrapper for callers that import this script as a module."""
    return normalize_style_spec(spec)


def fetch_spec(slug: str, base_url: str = BASE) -> dict:
    base = normalize_base_url(base_url, BASE)
    encoded = urllib.parse.quote(slug, safe="")
    brief_url = f"{base}/{encoded}/brief"
    try:
        spec = get_json(brief_url)
        if spec.get("schemaVersion") != "stylekit-brief-v1":
            raise ValueError("Brief endpoint returned an incompatible contract")
        validate_spec_object(spec, slug)
        source = {
            "kind": "http-api",
            "contract": "stylekit-brief-v1",
            "url": brief_url,
            "degraded": False,
        }
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise
        legacy_url = f"{base}/{encoded}"
        spec = get_json(legacy_url)
        validate_spec_object(spec, slug)
        source = {
            "kind": "http-api",
            "contract": "legacy-style-spec",
            "url": legacy_url,
            "degraded": True,
            "reason": f"{brief_url} returned HTTP 404; using the legacy spec without the complete brief lint contract",
        }
    normalized = normalize_spec(spec)
    normalized["_stylekitSource"] = source
    return normalized


def print_colors(spec: dict) -> None:
    print("COLORS")
    print(json.dumps(spec.get("colors") or {}, ensure_ascii=False, indent=2))


def print_tokens(spec: dict) -> None:
    print("TOKENS")
    print(json.dumps(spec.get("tokens") or {}, ensure_ascii=False, indent=2))


def print_recipes(spec: dict) -> None:
    print("RECIPES")
    for component, recipe in normalize_spec(spec)["recipes"].items():
        print(f"  {component}:")
        # Include parameters, states, slots and structure, not only default classes.
        print(json.dumps(recipe, ensure_ascii=False, indent=2))


def print_spec(slug: str, mode: str, spec: dict | None = None) -> None:
    spec = normalize_spec(spec) if spec is not None else fetch_spec(slug)
    print(f"STYLE: {spec.get('nameEn', slug)} ({slug})")
    source = spec.get("_stylekitSource")
    if isinstance(source, dict):
        print("SOURCE")
        print(json.dumps(source, ensure_ascii=False))
        if source.get("degraded"):
            print(f"WARNING: {source.get('reason', 'legacy spec; some validation rules may be unavailable')}")
    if spec.get("category"):
        print(f"  category: {spec['category']}")
    if spec.get("provenance"):
        print("PROVENANCE")
        print(json.dumps(spec["provenance"], ensure_ascii=False))
    if mode in ("all", "colors"):
        print_colors(spec)
    if mode in ("all", "tokens"):
        print_tokens(spec)
    if mode in ("all", "recipes"):
        print_recipes(spec)
    if mode == "all":
        for heading, key in (("PHILOSOPHY", "philosophy"), ("AI RULES", "aiRules"),
                             ("GLOBAL CSS", "globalCss"), ("COMPONENT TEMPLATES", "components"),
                             ("DO", "doList"), ("DON'T", "dontList"),
                             ("READINESS", "readiness"), ("LINT RULES", "lintRules")):
            value = spec.get(key)
            if value is not None:
                print(heading)
                print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))


def search(query: str, json_output: bool = False, base_url: str = BASE) -> list:
    base = normalize_base_url(base_url, BASE)
    data = get_json(base)
    q = query.strip().casefold()
    matches = []
    for style in data.get("styles", []):
        fields = [style.get(key, "") for key in ("slug", "name", "nameEn", "description")]
        for key in ("keywords", "tags"):
            if isinstance(style.get(key), list):
                fields.extend(style[key])
        if any(q in str(value).casefold() for value in fields):
            matches.append(style)
    if json_output:
        print(json.dumps({"total": len(matches), "results": matches[:20]}, ensure_ascii=False, indent=2))
    elif not matches:
        print(f"No styles match '{query}'. Full catalog: {base}")
    else:
        for style in matches[:20]:
            print(f"  {style['slug']:<28} {style.get('nameEn', '')}")
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?")
    modes = parser.add_mutually_exclusive_group()
    for mode in ("tokens", "recipes", "colors"):
        modes.add_argument(f"--{mode}", action="store_true")
    parser.add_argument("--search")
    parser.add_argument("--json", action="store_true", help="Preserve the complete machine-readable spec")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--spec", type=Path, help="Read a saved CLI/API brief or legacy spec offline")
    inputs.add_argument("--from-file", type=Path, help="Read an MCP tool result JSON envelope (or a direct brief)")
    parser.add_argument("--base-url", default=BASE, help="StyleKit API base, origin, or /api prefix (default: %(default)s)")
    args = parser.parse_args()
    if not args.search and not args.slug:
        parser.error("provide a slug or --search <query>")
    if args.search and (args.spec or args.from_file):
        parser.error("--search cannot be combined with --spec or --from-file")
    if not args.search and args.from_file and not args.slug:
        parser.error("provide the expected style slug when using --from-file")
    try:
        if args.search:
            search(args.search, args.json, args.base_url)
            return
        if args.spec:
            spec = load_spec_file(args.spec, args.slug)
        elif args.from_file:
            spec = load_spec_file(args.from_file, args.slug, from_mcp=True)
        else:
            spec = fetch_spec(args.slug, args.base_url)
        if spec.get("slug") != args.slug:
            raise ValueError("Spec slug does not match the requested style")
        if args.json:
            print(json.dumps(spec, ensure_ascii=False, indent=2))
        else:
            mode = next((mode for mode in ("tokens", "recipes", "colors") if getattr(args, mode)), "all")
            print_spec(args.slug, mode, spec)
    except (OSError, ValueError) as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
