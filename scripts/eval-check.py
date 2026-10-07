#!/usr/bin/env python3
"""Static StyleKit rule checks. Exit 0=pass, 1=fail, 2=error, 3=inconclusive.

Use --spec with a saved implementation brief for reproducible offline checks.
Required checks cover a single input file, not each element. --strict enforces
missing requirements; runtime expressions still need manual review.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from spec_input import load_spec_file


def load_script(name):
    module_spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


fetcher = load_script("fetch-style")
detector = load_script("detect-project")
BASE = fetcher.BASE
get_json = fetcher.get_json
ATTR = re.compile(r"\b(?:className|class)\s*=\s*")


def string_end(code, start):
    quote = code[start]
    pos = start + 1
    while pos < len(code):
        if code[pos] == "\\":
            pos += 2
            continue
        if code[pos] == quote:
            return pos
        pos += 1
    return -1


def brace_end(code, start):
    depth = 0
    pos = start
    while pos < len(code):
        char = code[pos]
        if char in "\"'`":
            end = string_end(code, pos)
            if end < 0:
                return -1
            pos = end + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return -1


def blank_interpolations(text):
    pos = 0
    while pos < len(text):
        start = text.find("${", pos)
        if start < 0:
            break
        end = brace_end(text, start + 1)
        stop = len(text) if end < 0 else end + 1
        text = text[:start] + " " * (stop - start) + text[stop:]
        pos = stop
    return text


def extract(code):
    found, attributes, dynamic = [], 0, 0
    position = 0
    while True:
        match = ATTR.search(code, position)
        if match is None:
            break
        attributes += 1
        start = match.end()
        while start < len(code) and code[start].isspace():
            start += 1
        if start >= len(code):
            dynamic += 1
            break
        opener = code[start]
        end = string_end(code, start) if opener in "\"'" else brace_end(code, start) if opener == "{" else -1
        if end < 0:
            dynamic += 1
            position = start + 1
            continue
        begin, stop = (start, end + 1) if opener in "\"'" else (start + 1, end)
        value = code[begin:stop].strip()
        literal = re.fullmatch(r'''(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`)''', value, re.S)
        if not literal or "\\" in value or (value.startswith("`") and "${" in value):
            dynamic += 1
        pos = begin
        while pos < stop:
            if code[pos] in "\"'`":
                close = string_end(code, pos)
                if close < 0 or close >= stop:
                    break
                text = code[pos + 1:close]
                if code[pos] == "`":
                    text = blank_interpolations(text)
                for token in re.finditer(r"\S+", text):
                    found.append({"raw": token.group(), "line": code.count("\n", 0, pos + 1 + token.start()) + 1})
                pos = close + 1
            else:
                pos += 1
        position = end + 1
    tokens = code.strip().split()
    plain = {"block", "inline", "flex", "grid", "hidden", "relative", "absolute", "fixed", "sticky", "italic", "underline", "truncate", "uppercase", "lowercase"}
    if not found and tokens and all(re.fullmatch(r'''[^\s"'{}=<>;`]+''', token) and (re.search(r"[-:\[\]]", token) or token in plain) for token in tokens):
        found = [{"raw": match.group(), "line": code.count("\n", 0, match.start()) + 1} for match in re.finditer(r"\S+", code)]
    return found, {"classAttributes": attributes, "dynamicAttributes": dynamic, "requiredScope": "file"}


def strip_variants(token):
    depth, colon = 0, -1
    for pos, char in enumerate(token):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == ":" and depth == 0:
            colon = pos
    return token[colon + 1:].removeprefix("!").removesuffix("!")


def class_tokens(code: str) -> set:
    return {entry["raw"] for entry in extract(code)[0]}


def normalized_rules(spec):
    canonical = spec.get("lintRules")
    if canonical is not None:
        if not isinstance(canonical, dict) or canonical.get("schemaVersion") != "stylekit-lint-v1":
            raise ValueError("Unsupported lint rule contract")
        return canonical, []
    tokens = spec.get("tokens") or {}
    if not isinstance(tokens, dict):
        raise ValueError("Invalid tokens payload")
    forbidden = tokens.get("forbidden") or {}
    required = {component: {"classes": " ".join(entries).split(), "source": "tokens"}
                for component, entries in (tokens.get("required") or {}).items()}
    return {
        "sources": ["tokens"] if tokens else [],
        "forbiddenClasses": [{"className": cls, "reason": (forbidden.get("reasons") or {}).get(cls, f'"{cls}" is forbidden in this style'), "source": "tokens"} for cls in forbidden.get("classes", [])],
        "forbiddenPatterns": [{"pattern": pattern, "flags": "", "source": "tokens", "reasons": forbidden.get("reasons") or {}} for pattern in forbidden.get("patterns", [])],
        "required": required,
        "exempt": list({strip_variants(cls) for requirement in required.values() for cls in requirement["classes"]}),
        "unsupportedRules": [],
    }, ["Legacy spec: only token rules are available; curated overrides require an implementation brief."]


def lint_code(spec: dict, code: str, component: str | None = None, strict: bool = False) -> dict:
    rules, warnings = normalized_rules(spec)
    extracted, coverage = extract(code)
    exact = {entry["className"]: entry for entry in rules["forbiddenClasses"]}
    exempt = set(rules["exempt"])
    patterns, unsupported = [], list(rules.get("unsupportedRules") or [])
    for entry in rules["forbiddenPatterns"]:
        try:
            flags = entry.get("flags", "")
            if any(flag not in "imsu" for flag in flags):
                raise ValueError("Unsupported regular expression flags")
            mask = (re.I if "i" in flags else 0) | (re.M if "m" in flags else 0) | (re.S if "s" in flags else 0)
            patterns.append((re.compile(entry["pattern"], mask), entry))
        except (ValueError, re.error):
            unsupported.append(entry["pattern"])
    violations = []
    for entry in extracted:
        raw, base = entry["raw"], strip_variants(entry["raw"])
        if base in exempt:
            continue
        rule = exact.get(base)
        kind = "forbidden-class"
        if rule is None:
            match = next(((pattern, rule) for pattern, rule in patterns if pattern.search(base)), None)
            if match:
                pattern, rule = match
                kind = "forbidden-pattern"
                rule = {**rule, "reason": rule.get("reasons", {}).get(base, f'"{base}" matches a forbidden pattern for this style ({rule["pattern"]})')}
        if rule:
            violations.append({"className": raw, "baseClassName": base, "line": entry["line"], "severity": "error", "source": rule["source"], "rule": kind, "reason": rule["reason"]})
    present = {entry["raw"] for entry in extracted}
    present_base = {strip_variants(raw) for raw in present if raw.removeprefix("!").removesuffix("!") == strip_variants(raw)}
    missing = []
    if component:
        requirement = rules["required"].get(component) or {}
        classes = [cls for cls in requirement.get("classes", []) if cls not in present and not (cls == strip_variants(cls) and cls in present_base)]
        if classes:
            missing.append({"component": component, "missing": classes, "source": requirement["source"]})
    if not rules["sources"]:
        warnings.append("No lint rules are available for this style.")
    if not extracted:
        warnings.append("No statically readable class tokens were found.")
    if coverage["dynamicAttributes"]:
        warnings.append("Runtime class expressions require manual review; only their string literals were checked.")
    if unsupported:
        warnings.append("Some forbidden patterns could not be compiled.")
    if missing and not strict:
        warnings.append("Missing required classes are advisory; enable strict to fail them.")
    failed = bool(violations or (strict and missing and not coverage["dynamicAttributes"]))
    uncertain = not rules["sources"] or not extracted or coverage["dynamicAttributes"] or unsupported
    status = "fail" if failed else "inconclusive" if uncertain else "pass"
    return {"slug": spec.get("slug", ""), "ok": status == "pass", "status": status, "violations": violations,
            "missingRequired": missing, "checkedClasses": len(extracted), "ruleSources": rules["sources"],
            "specSource": spec.get("_stylekitSource"), "coverage": coverage, "warnings": warnings}


def eval_code(spec: dict, code: str, component: str | None = None) -> list:
    """Compatibility adapter for the benchmark; uncertainty never counts as a pass."""
    report = lint_code(spec, code, component, strict=component is not None)
    issues = [f'{report["slug"]}: {entry["className"]}: {entry["reason"]}' for entry in report["violations"]]
    issues.extend(f'{report["slug"]}: missing {entry["component"]}: {" ".join(entry["missing"])}' for entry in report["missingRequired"])
    if report["status"] == "inconclusive":
        issues.append("inconclusive: " + " ".join(report["warnings"]))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("file", nargs="?", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--dir", type=Path)
    spec_inputs = parser.add_mutually_exclusive_group()
    spec_inputs.add_argument("--spec", type=Path, help="Use a saved complete CLI/API brief or legacy spec")
    spec_inputs.add_argument("--from-file", type=Path, help="Use a saved MCP tool result JSON envelope")
    parser.add_argument("--base-url", default=BASE, help="StyleKit API base used when no spec file is supplied")
    parser.add_argument("--component", choices=("button", "card", "input"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.file and (args.stdin or args.dir):
        parser.error("use one source: file, --stdin, or --dir")
    if not (args.file or args.stdin or args.dir):
        parser.error("provide a file, --stdin, or --dir")
    if args.strict and not args.component:
        parser.error("--strict requires --component")
    try:
        if args.spec:
            spec = load_spec_file(args.spec, args.slug)
        elif args.from_file:
            spec = load_spec_file(args.from_file, args.slug, from_mcp=True)
        else:
            spec = fetcher.fetch_spec(args.slug, args.base_url)
        if spec.get("slug") != args.slug:
            raise ValueError("Spec slug does not match the requested style")
        if args.stdin:
            sources = {"<stdin>": sys.stdin.read()}
        elif args.dir:
            if not args.dir.is_dir():
                raise ValueError(f"Not a directory: {args.dir}")
            sources = {str(p): p.read_text(encoding="utf-8") for p in detector.source_files(args.dir) if p.suffix in (".tsx", ".ts", ".jsx", ".js", ".html", ".vue", ".svelte")}
        else:
            sources = {str(args.file): args.file.read_text(encoding="utf-8")}
        if not sources:
            raise ValueError("No source files found")
        reports = [{"file": name, "report": lint_code(spec, code, args.component, args.strict)} for name, code in sources.items()]
        statuses = {entry["report"]["status"] for entry in reports}
        status = "fail" if "fail" in statuses else "inconclusive" if "inconclusive" in statuses else "pass"
        if args.json:
            print(json.dumps({"slug": args.slug, "status": status, "ok": status == "pass", "files": reports}, ensure_ascii=False, indent=2))
        else:
            for entry in reports:
                report = entry["report"]
                print(f'{entry["file"]}: {report["status"]} ({report["checkedClasses"]} classes)')
                for violation in report["violations"]:
                    print(f'  line {violation["line"]}: {violation["className"]}: {violation["reason"]}')
                for missing in report["missingRequired"]:
                    print(f'  missing {missing["component"]}: {" ".join(missing["missing"])}')
                for warning in report["warnings"]:
                    print(f"  {warning}")
        sys.exit({"pass": 0, "fail": 1, "inconclusive": 3}[status])
    except (OSError, ValueError, TypeError, KeyError) as err:
        print(json.dumps({"error": str(err)}) if args.json else f"Error: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
