#!/usr/bin/env python3
"""Report template/rule drift using the same checks as eval-check.py.

Exit 0=checked without violations, 1=data violations, 2=input/network error,
3=inconclusive or incomplete catalogue coverage. Required-class differences
are notices; they need review for semantic equivalents before changing data.
"""
import argparse
import json
import sys
from pathlib import Path
import importlib.util

module_spec = importlib.util.spec_from_file_location("stylekit_eval", Path(__file__).with_name("eval-check.py"))
evaluator = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(evaluator)
BASE = evaluator.BASE
get_json = evaluator.get_json
class_tokens = evaluator.class_tokens


def check_spec(spec: dict) -> tuple[list, list]:
    issues, notices = [], []
    slug = spec.get("slug", "?")
    for field in ("doList", "dontList", "aiRules", "components"):
        if not spec.get(field):
            issues.append(f"{slug}: missing required field '{field}'")
    if not spec.get("tokens") and not spec.get("lintRules"):
        notices.append(f"{slug}: no declared lint rules; static compliance cannot be verified")
    for component, template in (spec.get("components") or {}).items():
        if not isinstance(template, dict) or not template.get("code"):
            issues.append(f"{slug}: {component} has no template code")
            continue
        report = evaluator.lint_code(spec, template["code"], component)
        for entry in report["violations"]:
            issues.append(f'{slug}: {component} line {entry["line"]}: {entry["className"]}: {entry["reason"]}')
        for entry in report["missingRequired"]:
            notices.append(f'{slug}: {component} required-table drift: {" ".join(entry["missing"])}')
        if report["status"] == "inconclusive":
            notices.append(f"{slug}: {component} could not be fully verified: " + " ".join(report["warnings"]))
    return issues, notices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--spec", type=Path, help="Check a saved spec without network access")
    args = parser.parse_args()
    try:
        if args.spec:
            spec = json.loads(args.spec.read_text(encoding="utf-8"))
            if args.slug and spec.get("slug") != args.slug:
                raise ValueError("Spec slug does not match requested style")
            specs, requested = [spec], [spec.get("slug", "?")]
        else:
            requested = [args.slug] if args.slug else [style["slug"] for style in get_json(BASE).get("styles", [])]
            if not requested:
                raise ValueError("Catalogue returned no styles")
            specs = []
        fetch_errors = {}
        if not args.spec:
            for slug in requested:
                try:
                    specs.append(evaluator.fetcher.fetch_spec(slug))
                except (OSError, ValueError) as error:
                    fetch_errors[slug] = str(error)
        issues_by_style, notices_by_style = {}, {}
        inconclusive = bool(fetch_errors)
        for spec in specs:
            slug = spec.get("slug", "?")
            issues, notices = check_spec(spec)
            issues_by_style[slug] = issues
            notices_by_style[slug] = notices
            for template in (spec.get("components") or {}).values():
                if isinstance(template, dict) and template.get("code"):
                    inconclusive |= evaluator.lint_code(spec, template["code"])["status"] == "inconclusive"
        issue_count = sum(map(len, issues_by_style.values()))
        notice_count = sum(map(len, notices_by_style.values()))
        status = "fail" if issue_count else "inconclusive" if inconclusive else "pass"
        report = {"status": status, "requested": len(requested), "checked": len(specs), "issues": issue_count,
                  "notices": notice_count, "by_style": issues_by_style, "notices_by_style": notices_by_style, "fetch_errors": fetch_errors}
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Verified {len(specs)} of {len(requested)} styles: {status}, {issue_count} issue(s), {notice_count} notice(s)")
            for entries in issues_by_style.values():
                for entry in entries:
                    print(f"  - {entry}")
            for entries in notices_by_style.values():
                for entry in entries:
                    print(f"  notice: {entry}")
            for slug, error in fetch_errors.items():
                print(f"  unverified {slug}: {error}")
        sys.exit({"pass": 0, "fail": 1, "inconclusive": 3}[status])
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"error": str(error)}) if args.json else f"Error: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
