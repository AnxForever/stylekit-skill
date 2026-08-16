#!/usr/bin/env python3
"""
Fetch a StyleKit style spec from the public API and print a compact,
code-generation-oriented reference.

Usage:
    fetch-style.py <slug>                # full spec: tokens, recipes, rules
    fetch-style.py <slug> --tokens       # tokens only
    fetch-style.py <slug> --recipes      # recipes only
    fetch-style.py <slug> --colors       # palette only
    fetch-style.py --search <query>      # find slugs matching a query
"""

import json
import sys
import urllib.request

BASE = "https://www.stylekit.top/api/styles"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def print_colors(spec: dict) -> None:
    colors = spec.get("colors", {})
    print("COLORS")
    print(f"  primary:   {colors.get('primary')}")
    print(f"  secondary: {colors.get('secondary')}")
    print(f"  accent:    {', '.join(colors.get('accent', []))}")


def print_tokens(spec: dict) -> None:
    tokens = spec.get("tokens", {})
    print("TOKENS")
    for category, mapping in tokens.items():
        if not isinstance(mapping, dict):
            continue
        print(f"  {category}:")
        for key, value in mapping.items():
            if isinstance(value, list):
                print(f"    {key}: {' '.join(value)}")
            elif isinstance(value, dict):
                print(f"    {key}: {json.dumps(value, ensure_ascii=False)}")
            else:
                print(f"    {key}: {value}")


def print_recipes(spec: dict) -> None:
    recipes = spec.get("recipes", {})
    if isinstance(recipes, dict) and "components" in recipes:
        recipes = recipes["components"]
    if not isinstance(recipes, dict):
        print("RECIPES: none")
        return
    print("RECIPES")
    for component, recipe in recipes.items():
        if isinstance(recipe, dict):
            skeleton = recipe.get("skeleton", {})
            base = skeleton.get("baseClasses", [])
            print(f"  {component}:")
            if base:
                print(f"    base: {' '.join(base)}")
            variants = recipe.get("variants", {})
            for name, variant in variants.items():
                if isinstance(variant, dict):
                    print(f"    variant {name}: {' '.join(variant.get('classes', []))}")


def print_spec(slug: str, mode: str) -> None:
    spec = get_json(f"{BASE}/{slug}")
    print(f"STYLE: {spec.get('nameEn')} ({slug})")
    print(f"  category: {spec.get('category')} | styleType: {spec.get('styleType')}")
    print(f"  version: {spec.get('version')}")
    if mode in ("all", "colors"):
        print_colors(spec)
    if mode in ("all", "tokens"):
        print_tokens(spec)
    if mode in ("all", "recipes"):
        print_recipes(spec)
    if mode == "all":
        print("RULES")
        for rule in spec.get("doList", []) or []:
            print(f"  DO:   {rule}")
        for rule in spec.get("dontList", []) or []:
            print(f"  DON'T: {rule}")
        ai_rules = spec.get("aiRules", "")
        if ai_rules:
            print("AI RULES")
            for line in ai_rules.splitlines():
                if line.strip():
                    print(f"  {line}")


def search(query: str) -> None:
    data = get_json(BASE)
    q = query.lower()
    matches = [
        s
        for s in data.get("styles", [])
        if q in s.get("slug", "").lower()
        or q in s.get("nameEn", "").lower()
        or q in s.get("description", "").lower()
        or q in s.get("keywords", []) if isinstance(s.get("keywords"), list) and any(
            q in str(k).lower() for k in s.get("keywords", [])
        )
        or any(q in str(t).lower() for t in s.get("tags", []))
    ]
    if not matches:
        print(f"No styles match '{query}'. Full catalog: {BASE}")
        return
    for s in matches[:20]:
        print(f"  {s['slug']:<28} {s.get('nameEn', '')}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--search" and len(args) > 1:
        search(args[1])
        return

    mode = "all"
    slug = args[0]
    if len(args) > 1:
        flag = args[1]
        if flag == "--tokens":
            mode = "tokens"
        elif flag == "--recipes":
            mode = "recipes"
        elif flag == "--colors":
            mode = "colors"
        elif flag == "--search":
            search(args[2])
            return
        else:
            print(f"Unknown flag: {flag}")
            sys.exit(1)

    try:
        print_spec(slug, mode)
    except urllib.error.HTTPError as err:
        print(f"Error: {err.code} for {slug}. Check the slug against {BASE}")
        sys.exit(1)
    except urllib.error.URLError as err:
        print(f"Network error: {err.reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
