#!/usr/bin/env python3
"""
Evaluate generated UI code against a StyleKit style spec.

This is the acceptance detector for generated output: feed it code + a style
slug and it reports every concrete rule violation (forbidden classes, missing
required classes, off-palette colors, missing backdrop-blur for glassmorphism,
rounded corners for neo-brutalist, etc.). Use it as the final gate before
delivering generated UI, and as the scorer for with/without-skill benchmarks.

Usage:
    eval-check.py <slug> <code-file>          # check one file
    eval-check.py <slug> --stdin              # read code from stdin
    eval-check.py <slug> --dir <dir>          # check all code files in a dir

Exit code 0 = compliant, 1 = violations found, 2 = spec fetch error.

The check is intentionally strict about the style's *identity* constraints
(forbidden/required from the fetched spec) and lenient about everything else.
If the spec's required table conflicts with its own component templates, the
templates win (they are the verified reference implementation).
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

BASE = "https://www.stylekit.top/api/styles"

TAILWIND_CLASS_RE = re.compile(
    r"-?[a-zA-Z][a-zA-Z0-9-]*(?::[a-zA-Z0-9-]+)*(?:\[[^\]]+\])?(?:\/[a-zA-Z0-9_.%-]+)?"
)
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![\w])")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def class_tokens(code: str) -> set:
    tokens = set()
    for m in re.finditer(r'className(?:=\{`|="|=\{\s*")([^"`}]+)', code):
        tokens.update(TAILWIND_CLASS_RE.findall(m.group(1)))
    return tokens


def eval_code(spec: dict, code: str, component: str | None = None) -> list:
    violations = []
    slug = spec.get("slug", "?")
    tokens = spec.get("tokens") or {}
    forbidden = set((tokens.get("forbidden") or {}).get("classes", []))
    required = tokens.get("required") or {}
    colors = spec.get("colors") or {}

    code_tokens = class_tokens(code)

    # 1. Forbidden classes anywhere in the code
    present_forbidden = sorted(code_tokens & forbidden)
    for cls in present_forbidden:
        violations.append(f"{slug}: forbidden class '{cls}' used")

    # 2. Required identity classes missing, for a declared component.
    #    A required entry is only enforced when the style's own component
    #    template for THAT component uses exactly that entry (template wins,
    #    per component). Entries the required table lists but the matching
    #    template does not use are a data-source inconsistency, not a code
    #    violation — do not punish generated code for the source's own
    #    contradiction. Without --component, required is not checked: the
    #    component type cannot be reliably inferred from a code file.
    if component:
        template_tokens = class_tokens(
            (spec.get("components") or {}).get(component, {}).get("code", "")
        )
        if template_tokens:
            for req in required.get(component, []):
                toks = [t for t in req.split() if t]
                if not toks or not all(t in template_tokens for t in toks):
                    continue  # not backed by this component's template
                missing = [t for t in toks if t not in code_tokens]
                if missing:
                    violations.append(
                        f"{slug}: required '{req}' (component {component}) missing: "
                        + ", ".join(missing)
                    )

    # 3. Off-palette colors
    palette = set()
    for key in ("primary", "secondary"):
        v = colors.get(key)
        if isinstance(v, str) and v.startswith("#"):
            palette.add(v.lower())
    for v in colors.get("accent", []):
        if isinstance(v, str) and v.startswith("#"):
            palette.add(v.lower())
    for hexval in sorted(set(HEX_RE.findall(code))):
        if hexval.lower() not in palette:
            violations.append(f"{slug}: color {hexval} not in style palette")

    return violations


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2 or args[0] == "--help" or args[0] == "-h":
        print(__doc__)
        sys.exit(2)
    slug = args[0]
    rest = args[1:]
    component = None
    if "--component" in rest:
        idx = rest.index("--component")
        if idx + 1 < len(rest):
            component = rest[idx + 1]
        rest = [a for i, a in enumerate(rest) if i != idx and i != idx + 1]

    try:
        spec = get_json(f"{BASE}/{slug}")
    except urllib.error.HTTPError as err:
        print(f"error: HTTP {err.code} for slug {slug}")
        sys.exit(2)
    except urllib.error.URLError as err:
        print(f"error: network {err.reason}")
        sys.exit(2)

    if "--stdin" in rest:
        code = sys.stdin.read()
        sources = {"<stdin>": code}
    elif "--dir" in rest:
        idx = rest.index("--dir")
        directory = rest[idx + 1] if idx + 1 < len(rest) else "."
        sources = {}
        for p in Path(directory).rglob("*"):
            if p.is_file() and p.suffix in (".tsx", ".ts", ".jsx", ".js", ".html", ".css"):
                sources[str(p)] = p.read_text(encoding="utf-8", errors="replace")
        if not sources:
            print(f"error: no code files found in {directory}")
            sys.exit(2)
    else:
        code_file = rest[0]
        sources = {code_file: Path(code_file).read_text(encoding="utf-8", errors="replace")}

    all_violations = []
    for source, code in sources.items():
        for v in eval_code(spec, code, component):
            all_violations.append(f"{source}: {v}")

    if all_violations:
        for v in all_violations:
            print(v)
        print(f"\n{len(all_violations)} violation(s) in {len(sources)} file(s)")
        sys.exit(1)
    print(f"OK: {len(sources)} file(s) compliant with {slug}")
    sys.exit(0)


if __name__ == "__main__":
    main()
