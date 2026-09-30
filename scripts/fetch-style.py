#!/usr/bin/env python3
"""Fetch complete generation inputs, or search the StyleKit catalogue."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.stylekit.top/api/styles"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("API returned a non-object payload")
    return result


def normalize_spec(spec: dict) -> dict:
    result = dict(spec)
    recipes = result.get("recipes") or {}
    if isinstance(recipes, dict):
        for wrapper in ("recipes", "components"):
            if isinstance(recipes.get(wrapper), dict):
                recipes = recipes[wrapper]
                break
    result["recipes"] = recipes if isinstance(recipes, dict) else {}
    return result


def fetch_spec(slug: str) -> dict:
    encoded = urllib.parse.quote(slug, safe="")
    try:
        spec = get_json(f"{BASE}/{encoded}/brief")
        if spec.get("schemaVersion") != "stylekit-brief-v1" or spec.get("slug") != slug:
            raise ValueError("Brief endpoint returned an incompatible contract")
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise
        spec = get_json(f"{BASE}/{encoded}")
        if spec.get("slug") != slug:
            raise ValueError("Style endpoint returned a different slug")
    return normalize_spec(spec)


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


def search(query: str, json_output: bool = False) -> list:
    data = get_json(BASE)
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
        print(f"No styles match '{query}'. Full catalog: {BASE}")
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
    parser.add_argument("--spec", type=Path, help="Read an already fetched spec offline")
    args = parser.parse_args()
    if not args.search and not args.slug:
        parser.error("provide a slug or --search <query>")
    try:
        if args.search:
            search(args.search, args.json)
            return
        spec = normalize_spec(json.loads(args.spec.read_text(encoding="utf-8"))) if args.spec else fetch_spec(args.slug)
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
