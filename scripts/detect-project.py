#!/usr/bin/env python3
"""
Detect the target project's frontend context so generated UI matches the
project's actual stack instead of guessing.

Usage:
    detect-project.py [directory]          # detect in the given dir (default: cwd)
    detect-project.py --json [directory]   # same output, JSON only (default)

Prints one JSON object to stdout:
    {
      "framework": "next" | "react" | "vue" | "svelte" | "vanilla" | null,
      "reactVersion": "19.0.0" | null,
      "tailwind": {"version": 4 | 3 | null, "hasConfigFile": bool, "usesCssConfig": bool},
      "shadcn": {"detected": bool, "componentsJson": str | null, "aliases": {...} | null, "installedComponents": [...]},
      "styleKitInstalled": bool,
      "hasGlobalCss": bool,
      "cssFiles": [...]
    }
"""

import json
import os
import re
import sys
from pathlib import Path


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def detect(directory: str) -> dict:
    root = Path(directory).resolve()
    pkg = read_json(root / "package.json") or {}

    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    framework = None
    if "next" in deps:
        framework = "next"
    elif "react" in deps or "react-dom" in deps or "preact" in deps:
        framework = "react"
    elif "vue" in deps:
        framework = "vue"
    elif "svelte" in deps:
        framework = "svelte"
    elif any(k in deps for k in ("@angular/core", "angular")):
        framework = "angular"

    tailwind = {"version": None, "hasConfigFile": False, "usesCssConfig": False}
    tw = deps.get("tailwindcss")
    if tw:
        m = re.search(r"(\d+)", str(tw))
        tailwind["version"] = int(m.group(1)) if m else None
    tailwind["hasConfigFile"] = (root / "tailwind.config.js").exists() or (
        root / "tailwind.config.ts").exists() or (root / "tailwind.config.cjs").exists()

    # Tailwind v4 config lives in CSS (@theme / @import "tailwindcss")
    css_files = sorted(
        p for p in root.rglob("*.css")
        if "node_modules" not in p.parts and ".next" not in p.parts
    )
    for css in css_files[:20]:
        try:
            content = css.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "@theme" in content or "@import \"tailwindcss\"" in content or "@import 'tailwindcss'" in content:
            tailwind["usesCssConfig"] = True
            break

    shadcn = {"detected": False, "componentsJson": None, "aliases": None, "installedComponents": []}
    comp_json = root / "components.json"
    if comp_json.exists():
        data = read_json(comp_json) or {}
        shadcn["detected"] = True
        shadcn["componentsJson"] = str(comp_json.relative_to(root))
        shadcn["aliases"] = data.get("aliases")
        comp_dir = data.get("aliases", {}).get("components", "components")
        if comp_dir:
            comp_root = root / comp_dir
            if comp_root.exists():
                shadcn["installedComponents"] = sorted(
                    p.stem for p in comp_root.iterdir() if p.is_dir()
                )

    return {
        "framework": framework,
        "reactVersion": deps.get("react"),
        "tailwind": tailwind,
        "shadcn": shadcn,
        "styleKitInstalled": bool(deps.get("@stylekit/core") or deps.get("stylekit")),
        "hasGlobalCss": bool(css_files),
        "cssFiles": [str(p.relative_to(root)) for p in css_files[:20]],
    }


def main() -> None:
    args = sys.argv[1:]
    directory = "."
    for arg in args:
        if arg in ("--json", "--help", "-h"):
            continue
        directory = arg
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    try:
        result = detect(directory)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
