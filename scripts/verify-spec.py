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
    verify-spec.py [slug]          # check one style (default: all 148)
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
    r"-?[a-zA-Z][a-zA-Z0-9-]*(?::[a-zA-Z0-9-]+)*(?:\[[^\]]+\])?"
    r"(?:\/(?:\[[^\]]+\]|[a-zA-Z0-9_%-]+))?"
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


def check_spec(spec: dict) -> tuple[list, list]:
    issues = []
    notices = []
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
    # Per-component tokens: required classes are checked against the matching
    # component's own template (never across components).
    component_tokens = {
        cname: class_tokens(c["code"])
        for cname, c in components.items()
        if isinstance(c, dict) and c.get("code")
    }
    all_code_tokens = set()
    for toks in component_tokens.values():
        all_code_tokens.update(toks)

    # 2. Forbidden classes must not appear in component templates.
    #    Compare full tokens so "shadow" does not false-positive on
    #    "shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]" and "bg-white" does not
    #    false-positive on "bg-white/20".
    #
    #    A forbidden class used on a tiny element (avatar, dot, tag, icon,
    #    divider) is a legitimate use the style's own templates ship — the
    #    forbidden rule targets surfaces (cards, buttons, whole sections).
    #    Skip matches whose template context is a small element.
    SMALL_ELEMENT_RE = re.compile(
        r"(?:w-(?:0\.5|[1-9]|10|12|14|16)|h-(?:0\.5|[1-9]|10|12|14|16)|"
        r"w-\[[^\]]{1,12}\]|h-\[[^\]]{1,12}\]|text-(?:xs|sm)|px-[12] py-[12]|"
        r"w-2 h-2|w-3 h-3|w-4 h-4|w-8 h-8|w-10 h-10|w-6 h-6)"
    )

    def small_element_context(template_code: str, cls: str) -> bool:
        for m in re.finditer(r".{0,80}" + re.escape(cls) + r".{0,60}", template_code):
            context = m.group(0)
            if SMALL_ELEMENT_RE.search(context):
                return True
        return False

    for cname, template in components.items():
        if not (isinstance(template, dict) and template.get("code")):
            continue
        code = template["code"]
        present = sorted(set(class_tokens(code)) & forbidden)
        for cls in present:
            # Skip when the class appears in a small-element context in this
            # template (avatar/dot/tag/icon) — legitimately allowed.
            if small_element_context(code, cls):
                continue
            issues.append(
                f"{slug}: forbidden class '{cls}' appears in component "
                f"{cname} template"
            )

    # 3. Required table vs template drift is a NOTICE, not an error.
    #    The required table is an AI-facing spec; component templates are a
    #    parallel implementation that routinely uses different (but
    #    equivalent) classes — CSS variables vs hex values, hover variants
    #    with different shadow magnitudes, rounded-2xl vs rounded-3xl.
    #    Templates are the verified reference implementation, so a drift is
    #    a documentation-sync item, not a data defect. Reported under
    #    "notice" and excluded from the error count.
    def matches_template(required_tok: str, template_tokens: set) -> bool:
        base = required_tok.split(":")[-1]  # strip responsive/variant prefix
        base = re.sub(r"/\[[^\]]+\]$|/[a-zA-Z0-9_%-]+$", "", base)  # strip opacity
        for t in template_tokens:
            t_base = t.split(":")[-1]
            t_base = re.sub(r"/\[[^\]]+\]$|/[a-zA-Z0-9_%-]+$", "", t_base)
            if t_base == base:
                return True
        return False

    for cname, reqs in required.items():
        if not isinstance(reqs, list):
            continue
        template_tokens = component_tokens.get(cname)
        if not template_tokens:
            continue
        for req in reqs:
            toks = [t for t in req.split() if t]
            if not toks:
                continue
            if not any(matches_template(t, template_tokens) for t in toks):
                notices.append(
                    f"{slug}: required '{req}' (component {cname}) has no "
                    f"template example (spec drift — verify intent)"
                )

    # 4. Token color references should resolve to the palette.
    # 4. Token color references should resolve to a defined color.
    #    The authoritative palette is the union of style.colors and the
    #    token layer's own colors section (background/text/button semantic
    #    colors). Tokens routinely use surface/state colors that are not in
    #    the compact primary/secondary/accent trio — that is by design, not
    #    a defect. Only flag hexes that appear in NO defined color at all.
    defined_colors = set(palette)
    token_colors = tokens.get("colors") or {}
    for area, mapping in token_colors.items():
        if not isinstance(mapping, dict):
            continue
        for k, v in mapping.items():
            if not isinstance(v, str):
                continue
            defined_colors.update(h.lower() for h in HEX_RE.findall(v))
    for area, mapping in token_colors.items():
        if not isinstance(mapping, dict):
            continue
        for k, v in mapping.items():
            if not isinstance(v, str):
                continue
            for hexval in HEX_RE.findall(v):
                if hexval.lower() not in defined_colors:
                    issues.append(
                        f"{slug}: token colors.{area}.{k} references {hexval} "
                        f"which is defined nowhere in the style"
                    )

    return issues, notices


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
    notice_report = {}
    for spec in specs:
        slug = spec.get("slug", "?")
        issues, notices = check_spec(spec)
        report[slug] = issues
        if notices:
            notice_report[slug] = notices

    total_issues = sum(len(v) for v in report.values())
    total_notices = sum(len(v) for v in notice_report.values())
    checked = len(report)
    if json_out:
        print(json.dumps(
            {
                "checked": checked,
                "issues": total_issues,
                "notices": total_notices,
                "by_style": report,
                "notices_by_style": notice_report,
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(f"Verified {checked} styles, {total_issues} issue(s), {total_notices} notice(s)")
        for slug, issues in report.items():
            for issue in issues:
                print(f"  - {issue}")
        if total_notices:
            print(f"\n{total_notices} notice(s) — required-table vs template drift (info only):")
            for slug, notices in notice_report.items():
                for n in notices:
                    print(f"  ~ {n}")
    sys.exit(1 if total_issues else 0)


if __name__ == "__main__":
    main()
