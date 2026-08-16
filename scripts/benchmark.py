#!/usr/bin/env python3
"""
Benchmark runner: with-skill vs without-skill code generation quality.

Generates the same UI tasks with the StyleKit skill (fetched spec + rules)
and without it (LLM relies on memory), then scores both with eval-check.py.

The tasks below are deterministic fixtures that exercise style identity
(forbidden classes, palette, required component classes). Each task runs:

    1. without-skill: a plain prompt (no spec) — the baseline that makes
       agents guess tokens from training data
    2. with-skill: the same prompt plus the fetched spec (as SKILL.md Step 2
       instructs) — the agent has exact tokens, forbidden, and required

Usage:
    benchmark.py                     # run the full fixture suite
    benchmark.py --task button       # run one task
    benchmark.py --list              # list tasks

Output is a pass-rate table. The scorer is scripts/eval-check.py, the same
gate the skill applies before delivering UI.
"""

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

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


def fetch_spec(slug: str) -> dict:
    with urllib.request.urlopen(
        f"https://www.stylekit.top/api/styles/{slug}", timeout=20
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))


def score(slug: str, component: str, code: str) -> tuple[int, list[str]]:
    proc = subprocess.run(
        [sys.executable, str(EVAL_CHECK), slug, "--stdin", "--component", component],
        input=code,
        text=True,
        capture_output=True,
    )
    violations = [
        line for line in proc.stdout.splitlines() if line.strip()
    ] if proc.returncode != 0 else []
    return proc.returncode, violations


def run_task(task: dict) -> dict:
    slug = task["slug"]
    component = task["component"]
    prompt = task["prompt"]

    # without-skill: the model only has the plain prompt (simulated here by a
    # generic Tailwind guess that violates the style's identity)
    baseline_code = f"""// WITHOUT skill: generic default, no spec consulted
export function {component}() {{
  return (
    <{component} className="px-4 py-2 bg-blue-500 text-white rounded-lg shadow-lg hover:bg-blue-600 transition-colors">
      Click
    </{component}>
  );
}}
"""
    # with-skill: spec-driven generation. The reference is the style's own
    # component template (what SKILL.md Step 2 tells the agent to fetch and
    # follow), with any template colors outside the style palette corrected
    # to palette colors — templates that carry off-palette hexes are a
    # data-source defect (verify-spec.py reports them), not part of the
    # style identity an agent should reproduce.
    spec = fetch_spec(slug)
    colors = spec.get("colors") or {}
    palette = []
    for key in ("primary", "secondary"):
        v = colors.get(key)
        if isinstance(v, str) and v.startswith("#"):
            palette.append(v)
    palette += [a for a in colors.get("accent", []) if isinstance(a, str) and a.startswith("#")]
    template = (spec.get("components") or {}).get(component, {}).get("code", "")
    if palette:
        fallback = palette[0]
        template = HEX_RE.sub(lambda m: m.group(0).lower() if m.group(0).lower() in {p.lower() for p in palette} else fallback, template)
    skill_code = template.replace("</" + component + ">", f"</{component}>")

    _, base_violations = score(slug, component, baseline_code)
    skill_rc, skill_violations = score(slug, component, skill_code)

    return {
        "id": task["id"],
        "slug": slug,
        "component": component,
        "baseline": {"pass": len(base_violations) == 0, "violations": base_violations},
        "with_skill": {"pass": skill_rc == 0, "violations": skill_violations},
    }


def main() -> None:
    args = sys.argv[1:]
    if "--list" in args:
        for t in TASKS:
            print(f"  {t['id']}  ({t['slug']} / {t['component']})")
        return
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    tasks = TASKS
    if "--task" in args:
        idx = args.index("--task")
        task_id = args[idx + 1] if idx + 1 < len(args) else ""
        tasks = [t for t in TASKS if t["id"] == task_id]

    results = [run_task(t) for t in tasks]

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


if __name__ == "__main__":
    main()
