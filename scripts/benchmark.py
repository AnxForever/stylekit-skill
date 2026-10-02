#!/usr/bin/env python3
"""
Benchmark runner: with-skill vs without-skill code generation quality.

Two modes:

1. Fixture mode (default, CI-safe): deterministic templates that exercise
   style identity. without-skill uses a generic Tailwind guess (no spec);
   with-skill uses the style's unmodified component template. No LLM calls, no API key.

2. LLM mode (--llm): calls a real model for BOTH arms of each task.
   without-skill prompt has no spec; with-skill prompt includes the fetched
   spec (as SKILL.md Step 2 instructs). Requires OPENAI_API_KEY (or
   OPENAI_BASE_URL) in the environment.

Both modes score the generated code with scripts/eval-check.py, the same
gate the skill applies before delivering UI.

Usage:
    benchmark.py                     # fixture mode, full suite
    benchmark.py --task <id>         # one task
    benchmark.py --llm [--model gpt-4o-mini]   # real LLM A/B
    benchmark.py --list              # list tasks
"""

import json
import os
import re
import subprocess
import sys
import argparse
import urllib.request
from pathlib import Path
import importlib.util
import tempfile

HERE = Path(__file__).resolve().parent
EVAL_CHECK = HERE / "eval-check.py"
FETCH = HERE / "fetch-style.py"

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![\w])")

TASKS = [
    {
        "id": "neo-brutalist-button",
        "slug": "neo-brutalist",
        "component": "button",
        "prompt": "Create a bold, aggressive CTA button for a streetwear brand.",
    },
    {
        "id": "neo-brutalist-card",
        "slug": "neo-brutalist",
        "component": "card",
        "prompt": "Create a product card for a limited-edition sneaker drop.",
    },
    {
        "id": "glassmorphism-button",
        "slug": "glassmorphism",
        "component": "button",
        "prompt": "Create a frosted-glass primary button for a SaaS landing page.",
    },
    {
        "id": "glassmorphism-card",
        "slug": "glassmorphism",
        "component": "card",
        "prompt": "Create a frosted-glass pricing card for a cloud storage product.",
    },
]


def fetch_spec(slug: str, base_url: str = "https://www.stylekit.top/api/styles") -> dict:
    module_spec = importlib.util.spec_from_file_location("stylekit_fetch", FETCH)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module.fetch_spec(slug, base_url)


def score(slug: str, component: str, code: str, spec: dict | None = None) -> tuple[int, list[str]]:
    # Both arms use exactly the same fetched inputs; do not refetch mid-experiment.
    with tempfile.TemporaryDirectory(prefix="stylekit-benchmark-") as directory:
        spec_file = Path(directory) / "spec.json"
        spec_file.write_text(json.dumps(spec if spec is not None else fetch_spec(slug)), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(EVAL_CHECK), slug, "--stdin", "--component", component, "--spec", str(spec_file)],
            input=code, text=True, capture_output=True,
        )
    violations = [line for line in (proc.stdout + proc.stderr).splitlines() if line.strip()] if proc.returncode != 0 else []
    return proc.returncode, violations


def llm_complete(prompt: str, model: str) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("error: --llm requires OPENAI_API_KEY", file=sys.stderr)
        sys.exit(2)
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    url = f"{base.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a frontend engineer generating React + Tailwind "
                        "components. Output ONLY the component code in one code "
                        "block. No explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def spec_prompt(task: dict, spec: dict, component: str) -> str:
    """The with-skill prompt: fetched spec facts, as SKILL.md Step 2 provides."""
    tokens = spec.get("tokens") or {}
    forbidden = (tokens.get("forbidden") or {}).get("classes", [])
    required = (tokens.get("required") or {}).get(component, [])
    colors = spec.get("colors") or {}
    template = (spec.get("components") or {}).get(component, {}).get("code", "")
    return (
        f"{task['prompt']}\n\n"
        f"Apply the '{spec.get('slug')}' style. These are the exact constraints:\n"
        f"AI rules: {spec.get('aiRules', '')}\n"
        f"Merged lint rules: {json.dumps(spec.get('lintRules') or {}, ensure_ascii=False)}\n"
        f"- Palette: primary {colors.get('primary')}, secondary {colors.get('secondary')}, "
        f"accent {', '.join(colors.get('accent', []))}\n"
        f"- Forbidden classes: {', '.join(forbidden[:12])}\n"
        f"- Required classes for {component}: {', '.join(required[:8])}\n"
        f"- Reference template:\n{template}\n\n"
        f"Generate a single React {component} component using these exact tokens."
    )


def run_task(task: dict, llm: bool = False, model: str = "gpt-4o-mini", base_url: str = "https://www.stylekit.top/api/styles") -> dict:
    slug = task["slug"]
    component = task["component"]
    prompt = task["prompt"]
    spec = fetch_spec(slug, base_url)

    if llm:
        baseline_code = llm_complete(f"{prompt}\nApply the {slug} style. Generate one React {component} using Tailwind CSS.", model)
        skill_code = llm_complete(spec_prompt(task, spec, component), model)
    else:
        # fixture mode: deterministic reference implementations
        baseline_code = f"""// WITHOUT skill: generic default, no spec consulted
export function {component}() {{
  return (
    <{component} className="px-4 py-2 bg-blue-500 text-white rounded-lg shadow-lg hover:bg-blue-600 transition-colors">
      Click
    </{component}>
  );
}}
"""
        # Use unmodified source templates: correcting them here would hide data drift.
        skill_code = (spec.get("components") or {}).get(component, {}).get("code", "")

    base_rc, base_violations = score(slug, component, baseline_code, spec)
    skill_rc, skill_violations = score(slug, component, skill_code, spec)

    return {
        "id": task["id"],
        "slug": slug,
        "component": component,
        "mode": "llm" if llm else "fixture",
        "provenance": spec.get("provenance"),
        "baseline_exit_code": base_rc,
        "with_skill_exit_code": skill_rc,
        "baseline": {"pass": base_rc == 0, "violations": base_violations},
        "with_skill": {"pass": skill_rc == 0, "violations": skill_violations},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--task")
    parser.add_argument("--base-url", default="https://www.stylekit.top/api/styles", help="StyleKit API base used to fetch specs")
    args = parser.parse_args()
    if args.list:
        for t in TASKS:
            print(f"  {t['id']}  ({t['slug']} / {t['component']})")
        return
    tasks = TASKS
    if args.task:
        tasks = [t for t in TASKS if t["id"] == args.task]

    if args.llm and not os.environ.get("OPENAI_API_KEY"):
        print("error: --llm requires OPENAI_API_KEY")
        sys.exit(2)

    if not tasks:
        print("error: no matching tasks", file=sys.stderr)
        sys.exit(2)

    results = [run_task(t, llm=args.llm, model=args.model, base_url=args.base_url) for t in tasks]
    mode_label = "llm" if args.llm else "fixture"

    if not args.llm:
        print("Synthetic fixture regression; these pass rates do not measure model generation quality.")
    print(f"mode: {mode_label}" + (f" (model: {args.model})" if args.llm else ""))
    print(f"{'task':<24} {'without-skill':<14} {'with-skill':<12}")
    print("-" * 52)
    for r in results:
        print(
            f"{r['id']:<24} {'PASS' if r['baseline']['pass'] else 'FAIL':<14} "
            f"{'PASS' if r['with_skill']['pass'] else 'FAIL':<12}"
        )
        for v in r["baseline"]["violations"][:2]:
            print(f"  baseline: {v}")
        for v in r["with_skill"]["violations"][:2]:
            print(f"  with-skill: {v}")
    print()
    base_pass = sum(1 for r in results if r["baseline"]["pass"])
    skill_pass = sum(1 for r in results if r["with_skill"]["pass"])
    total = len(results)
    print(f"without-skill pass rate: {base_pass}/{total}")
    print(f"with-skill pass rate:    {skill_pass}/{total}")
    if any(r["baseline_exit_code"] in (2, 3) or r["with_skill_exit_code"] in (2, 3) for r in results):
        sys.exit(2)
    if not args.llm and skill_pass != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
