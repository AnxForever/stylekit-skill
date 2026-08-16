#!/usr/bin/env python3
"""
Verify StyleKit API specs for internal consistency (verified-facts gate).

Coding agents hallucinate tokens and violate style rules when the data they
read is internally inconsistent. This script checks every style in the
catalog for the contradictions that cause those failures:

  - A forbidden class appearing inside a shipped component template
    (agents copy templates, so a template that violates its own style is
    a guaranteed wrong output).
  - A required class that appears in NO component template
    (agents then have no example to follow).
  - A token class that is neither in any template nor in the style's
    colors — i.e. tokens referencing colors not in the palette.
  - Missing core fields (doList/dontList/aiRules/components/tokens).

Usage:
    verify-spec.py [slug]          # check one style (default: all 146)
    verify-spec.py --json [slug]   # machine-readable report

Exit code 0 = clean, 1 = violations found (or network error).
"""

import json
import re
import sys
import urllib.request

BASE = "https://www.stylekit.top/api/styles"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


TAILWIND_CLASS_RE = re.compile(
    r"-?[a-zA-Z][a-zA-Z0-9-]*(?::[a-zA-Z0-9-]+)*(?:\[[^\]]+\])?(?:\/[a-zA-Z0-9_.%-]+)?"
)
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![\w])")


def class_tokens(code: str) -> set:
    """Extract every full Tailwind class token from a code string.

    Handles variants (hover:), arbitrary values (shadow-[...]),
    opacity modifiers (bg-white/20), and arbitrary properties
    ([background-image:...]).
    """
    tokens = set()
    for m in re.finditer(r'className(?:=\{`|="|=\{\s*")([^"`}]+)', code):
        tokens.update(TAILWIND_CLASS_RE.findall(m.group(1)))
    return tokens


def check_spec(spec: dict) -> list:
    issues = []
    slug = spec.get("slug", "?")
    tokens = spec.get("tokens") or {}
    forbidden = set((tokens.get("forbidden") or {}).get("classes", []))
    required = tokens.get("required") or {}
    colors = spec.get("colors") or {}
    palette = set()
    for key in ("primary", "secondary"):
        v = colors.get(key)
        if isinstance(v, str) and v.startswith("#"):
            palette.add(v.lower())
    for v in colors.get("accent", []):
        if isinstance(v, str) and v.startswith("#"):
            palette.add(v.lower())

    # 1. Core fields present
    for field in ("doList", "dontList", "aiRules", "components", "tokens"):
        if not spec.get(field):
            issues.append(f"{slug}: missing required field '{field}'")

    components = spec.get("components") or {}
    code_tokens = set()
    for cname, c in components.items():
        if isinstance(c, dict) and c.get("code"):
            code_tokens.update(class_tokens(c["code"]))

    # 2. Forbidden classes must not appear in component templates.
    #    Compare full tokens so "shadow" does not false-positive on
    #    "shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]" and "bg-white" does not
    #    false-positive on "bg-white/20".
    for cls in sorted(forbidden):
        if cls in code_tokens:
            issues.append(
                f"{slug}: forbidden class '{cls}' appears in component template"
            )

    # 3. Required button/card/input classes should appear somewhere in templates.
    #    A required entry like "border-2 md:border-4" is a variant group; check
    #    each concrete token so "border-2" matches the template.
    for cname, reqs in required.items():
        if not isinstance(reqs, list):
            continue
        for req in reqs:
            missing = [tok for tok in req.split() if tok and tok not in code_tokens]
            if missing:
                issues.append(
                    f"{slug}: required '{req}' (component {cname}) has no "
                    f"template example ({', '.join(missing)})"
                )

    # 4. Token color references should resolve to the palette.
    token_colors = tokens.get("colors") or {}
    for area, mapping in token_colors.items():
        if not isinstance(mapping, dict):
            continue
        for k, v in mapping.items():
            if not isinstance(v, str):
                continue
            for hexval in HEX_RE.findall(v):
                if hexval.lower() not in palette:
                    issues.append(
                        f"{slug}: token colors.{area}.{k} references {hexval} "
                        f"not in style palette"
                    )

    return issues


def main() -> None:
    args = sys.argv[1:]
    json_out = "--json" in args
    slugs = [a for a in args if not a.startswith("-")]

    if slugs:
        try:
            specs = [get_json(f"{BASE}/{slug}") for slug in slugs]
        except urllib.error.HTTPError as err:
            print(json.dumps({"error": f"HTTP {err.code}"}))
            sys.exit(1)
        except urllib.error.URLError as err:
            print(json.dumps({"error": f"network: {err.reason}"}))
            sys.exit(1)
    else:
        try:
            catalog = get_json(BASE)
        except urllib.error.URLError as err:
            print(json.dumps({"error": f"network: {err.reason}"}))
            sys.exit(1)
        all_slugs = [s["slug"] for s in catalog.get("styles", [])]
        specs = []
        for slug in all_slugs:
            try:
                specs.append(get_json(f"{BASE}/{slug}"))
            except urllib.error.URLError as err:
                print(f"WARN: fetch {slug} failed: {err.reason}", file=sys.stderr)

    report = {}
    for spec in specs:
        slug = spec.get("slug", "?")
        issues = check_spec(spec)
        report[slug] = issues

    total_issues = sum(len(v) for v in report.values())
    checked = len(report)
    if json_out:
        print(json.dumps({"checked": checked, "issues": total_issues, "by_style": report}, ensure_ascii=False, indent=2))
    else:
        print(f"Verified {checked} styles, {total_issues} issue(s)")
        for slug, issues in report.items():
            for issue in issues:
                print(f"  - {issue}")
    sys.exit(1 if total_issues else 0)


if __name__ == "__main__":
    main()
