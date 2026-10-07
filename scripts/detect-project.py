#!/usr/bin/env python3
"""
Detect the target project's frontend context so generated UI matches the
project's actual stack instead of guessing.

Usage:
    detect-project.py [directory]          # detect in the given dir (default: cwd)
    detect-project.py --json [directory]   # same output, JSON only (default)

Prints one JSON object to stdout:
    {
      "framework": "next" | "react" | "vue" | "svelte" | "angular" | "expo" | "react-native" | "swiftui" | "flutter" | null,
      "reactVersion": "19.0.0" | null,
      "tailwind": {"version": 4 | 3 | null, "hasConfigFile": bool, "usesCssConfig": bool},
      "shadcn": {"detected": bool, "componentsJson": str | null, "aliases": {...} | null, "installedComponents": [...]},
      "styleKitInstalled": bool,
      "hasGlobalCss": bool,
      "cssFiles": [...],
      "platforms": ["web" | "react-native" | "swiftui" | "flutter", ...],
      "componentLibraries": [declared mobile-relevant package names, ...],
      "projects": [{"path": relative path, "framework": ..., "platforms": [...], "componentLibraries": [...]}]
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


IGNORED = {
    "node_modules", ".next", ".git", "dist", "build", "coverage", ".turbo", ".venv",
    ".expo", ".dart_tool", ".gradle", ".build", "Pods", "DerivedData", "vendor",
}

MOBILE_COMPONENT_LIBRARIES = {
    "@ant-design/react-native",
    "@gluestack-ui/themed",
    "@gorhom/bottom-sheet",
    "@ionic/react",
    "@ionic/vue",
    "@radix-ui/react-dialog",
    "@react-native-community/datetimepicker",
    "@react-native-picker/picker",
    "@react-navigation/native",
    "@rneui/base",
    "@rneui/themed",
    "@shopify/restyle",
    "@tamagui/core",
    "@tamagui/ui",
    "antd-mobile",
    "framework7",
    "framework7-react",
    "framework7-vue",
    "native-base",
    "react-native-elements",
    "react-native-paper",
    "react-native-ui-lib",
    "react-native-web",
    "swiper",
    "tamagui",
    "vaul",
    "vant",
}


def source_tree(root: Path):
    for directory, dirs, files in os.walk(root, followlinks=False):
        xcode_projects = {
            d for d in dirs
            if d.endswith(".xcodeproj") and not (Path(directory) / d).is_symlink()
        }
        dirs[:] = sorted(
            d for d in dirs
            if d not in IGNORED and not d.endswith(".xcodeproj") and not (Path(directory) / d).is_symlink()
        )
        yield Path(directory), dirs, files, xcode_projects


def source_files(root: Path):
    for directory, _, files, _ in source_tree(root):
        for filename in sorted(files):
            path = Path(directory) / filename
            if not path.is_symlink():
                yield path


def dependencies(package: dict, include_peer_optional: bool = False) -> dict:
    result = {}
    sections = ["dependencies", "devDependencies"]
    if include_peer_optional:
        sections.extend(("optionalDependencies", "peerDependencies"))
    for section in sections:
        values = package.get(section, {})
        if isinstance(values, dict):
            result.update(values)
    return result


def node_frameworks(deps: dict) -> tuple[str | None, set[str]]:
    """Return the declared JS framework and its evidenced target platforms."""
    web_framework = None
    if "next" in deps:
        web_framework = "next"
    elif "react" in deps or "react-dom" in deps or "preact" in deps:
        web_framework = "react"
    elif "vue" in deps:
        web_framework = "vue"
    elif "svelte" in deps:
        web_framework = "svelte"
    elif any(k in deps for k in ("@angular/core", "angular")):
        web_framework = "angular"

    has_native_react = "expo" in deps or "react-native" in deps
    if "next" in deps:
        framework = "next"
    elif "expo" in deps:
        framework = "expo"
    elif "react-native" in deps:
        framework = "react-native"
    else:
        framework = web_framework

    platforms = set()
    if has_native_react:
        platforms.add("react-native")
    if (
        web_framework == "react"
        and has_native_react
        and "react-dom" not in deps
        and "react-native-web" not in deps
        and "next" not in deps
    ):
        web_framework = None
    if web_framework or "react-native-web" in deps:
        platforms.add("web")
    return framework, platforms


def declares_flutter_sdk(path: Path) -> bool:
    """Recognize Flutter only in a pubspec dependency SDK declaration."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False

    in_dependencies = False
    dependency_indent = None
    for line in lines:
        if line and not line[0].isspace():
            in_dependencies = bool(re.match(r"^(?:dependencies|dev_dependencies):\s*(?:#.*)?$", line))
            dependency_indent = None
            continue
        if not in_dependencies or not line.strip() or line.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" \t"))
        if dependency_indent is None or indent <= dependency_indent:
            entry = re.match(r"^[ \t]+[^:#][^:]*:\s*(.*)$", line)
            if not entry:
                dependency_indent = None
                continue
            dependency_indent = indent
            if re.fullmatch(r"\{\s*sdk:\s*flutter\s*\}", entry.group(1).strip()):
                return True
            continue
        if re.match(r"^[ \t]+sdk:\s*flutter\s*(?:#.*)?$", line):
            return True
    return False


def has_swiftui_import(root: Path, manifest_roots: set[Path]) -> bool:
    """Require source evidence; a Package.swift manifest by itself is insufficient."""
    boundaries = {path for path in manifest_roots if path != root and root in path.parents}
    for source in source_files(root):
        if source.suffix != ".swift":
            continue
        if any(boundary == source.parent or boundary in source.parents for boundary in boundaries):
            continue
        try:
            content = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        content = re.sub(r"(?m)//.*$", "", content)
        if re.search(r"(?m)^\s*(?:@\w+\s+)*import\s+SwiftUI\b", content):
            return True
    return False


def discover_projects(root: Path) -> list[dict]:
    manifests = []
    xcode_roots = set()
    for directory, _, files, xcode_projects in source_tree(root):
        if xcode_projects:
            xcode_roots.add(directory)
        manifests.extend(
            directory / filename for filename in files
            if filename in {"package.json", "pubspec.yaml", "Package.swift"}
            and not (directory / filename).is_symlink()
        )
    manifest_roots = {path.parent for path in manifests} | xcode_roots
    projects = {}

    def get_project(project_root: Path) -> dict:
        return projects.setdefault(project_root, {
            "frameworks": set(),
            "platforms": set(),
            "componentLibraries": set(),
        })

    for manifest in manifests:
        project_root = manifest.parent
        project = get_project(project_root)
        if manifest.name == "package.json":
            package = read_json(manifest) or {}
            deps = dependencies(package)
            all_deps = dependencies(package, include_peer_optional=True)
            framework, platforms = node_frameworks(deps)
            if framework:
                project["frameworks"].add(framework)
                project["platforms"].update(platforms)
                project["componentLibraries"].update(MOBILE_COMPONENT_LIBRARIES.intersection(all_deps))
        elif manifest.name == "pubspec.yaml" and declares_flutter_sdk(manifest):
            project["frameworks"].add("flutter")
            project["platforms"].add("flutter")
        elif manifest.name == "Package.swift" and has_swiftui_import(project_root, manifest_roots):
            project["frameworks"].add("swiftui")
            project["platforms"].add("swiftui")

    for project_root in sorted(xcode_roots):
        if has_swiftui_import(project_root, manifest_roots):
            project = get_project(project_root)
            project["frameworks"].add("swiftui")
            project["platforms"].add("swiftui")

    result = []
    for project_root, project in projects.items():
        if not project["platforms"]:
            continue
        frameworks = sorted(project["frameworks"])
        result.append({
            "path": "." if project_root == root else project_root.relative_to(root).as_posix(),
            "framework": frameworks[0] if len(frameworks) == 1 else None,
            "platforms": sorted(project["platforms"]),
            "componentLibraries": sorted(project["componentLibraries"]),
        })
    return sorted(result, key=lambda project: project["path"])


def resolve_alias(root: Path, alias: str) -> Path | None:
    config = read_json(root / "tsconfig.json") or read_json(root / "jsconfig.json") or {}
    compiler = config.get("compilerOptions", {})
    base = root / compiler.get("baseUrl", ".")
    for pattern, targets in compiler.get("paths", {}).items():
        if not targets:
            continue
        prefix, star, suffix = pattern.partition("*")
        if star and alias.startswith(prefix) and alias.endswith(suffix):
            middle = alias[len(prefix):len(alias) - len(suffix) if suffix else None]
            return (base / targets[0].replace("*", middle)).resolve()
        if pattern == alias:
            return (base / targets[0]).resolve()
    if alias.startswith("@/"):
        relative = alias[2:]
        for candidate in (root / relative, root / "src" / relative):
            if candidate.exists():
                return candidate
        return None
    return root / alias if not alias.startswith("@") else None


def detect(directory: str) -> dict:
    root = Path(directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    pkg = read_json(root / "package.json") or {}

    deps = dependencies(pkg)
    projects = discover_projects(root)
    root_project = next((project for project in projects if project["path"] == "."), None)
    framework = root_project["framework"] if root_project else None
    platforms = sorted({platform for project in projects for platform in project["platforms"]})
    component_libraries = sorted({name for project in projects for name in project["componentLibraries"]})

    tailwind = {"version": None, "hasConfigFile": False, "usesCssConfig": False}
    tw = deps.get("tailwindcss")
    if tw:
        m = re.search(r"(\d+)", str(tw))
        tailwind["version"] = int(m.group(1)) if m else None
    tailwind["hasConfigFile"] = (root / "tailwind.config.js").exists() or (
        root / "tailwind.config.ts").exists() or (root / "tailwind.config.cjs").exists()

    # Tailwind v4 config lives in CSS (@theme / @import "tailwindcss")
    css_files = sorted(
        p for p in source_files(root) if p.suffix == ".css"
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
        aliases = data.get("aliases") or {}
        comp_dir = aliases.get("ui") or f"{aliases.get('components', 'components')}/ui"
        if comp_dir:
            comp_root = resolve_alias(root, comp_dir)
            if comp_root is not None and comp_root.is_dir():
                shadcn["installedComponents"] = sorted(
                    p.stem for p in comp_root.iterdir() if p.is_file() and p.suffix in {".tsx", ".jsx", ".vue", ".svelte", ".ts", ".js"}
                )

    return {
        "framework": framework,
        "reactVersion": deps.get("react"),
        "tailwind": tailwind,
        "shadcn": shadcn,
        "styleKitInstalled": any(name in deps for name in ("stylekit-core", "@stylekit/core", "stylekit")),
        "hasGlobalCss": bool(css_files),
        "cssFiles": [str(p.relative_to(root)) for p in css_files[:20]],
        "platforms": platforms,
        "componentLibraries": component_libraries,
        "projects": projects,
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
