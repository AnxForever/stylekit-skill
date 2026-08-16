#!/usr/bin/env python3
"""
Benchmark runner: with-skill vs without-skill code generation quality.

Two modes:

1. Fixture mode (default, CI-safe): deterministic templates that exercise
   style identity. without-skill uses a generic Tailwind guess (no spec);
   with-skill uses the style's own component template with off-palette
   colors corrected. No LLM calls, no API key.

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
        f"- Palette: primary {colors.get('primary')}, secondary {colors.get('secondary')}, "
        f"accent {', '.join(colors.get('accent', []))}\n"
        f"- Forbidden classes: {', '.join(forbidden[:12])}\n"
        f"- Required classes for {component}: {', '.join(required[:8])}\n"
        f"- Reference template:\n{template}\n\n"
        f"Generate a single React {component} component using these exact tokens."
    )


def run_task(task: dict, llm: bool = False, model: str = "gpt-4o-mini") -> dict:
    slug = task["slug"]
    component = task["component"]
    prompt = task["prompt"]
    spec = fetch_spec(slug)

    if llm:
        baseline_code = llm_complete(prompt, model)
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
            template = HEX_RE.sub(
                lambda m: m.group(0).lower() if m.group(0).lower() in {p.lower() for p in palette} else fallback,
                template,
            )
        skill_code = template.replace("</" + component + ">", f"</{component}>")

    _, base_violations = score(slug, component, baseline_code)
    skill_rc, skill_violations = score(slug, component, skill_code)

    return {
        "id": task["id"],
        "slug": slug,
        "component": component,
        "mode": "llm" if llm else "fixture",
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

    llm = "--llm" in args
    model = "gpt-4o-mini"
    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model = args[idx + 1]

    tasks = TASKS
    if "--task" in args:
        idx = args.index("--task")
        task_id = args[idx + 1] if idx + 1 < len(args) else ""
        tasks = [t for t in TASKS if t["id"] == task_id]

    if llm and not os.environ.get("OPENAI_API_KEY"):
        print("error: --llm requires OPENAI_API_KEY")
        sys.exit(2)

    results = [run_task(t, llm=llm, model=model) for t in tasks]
    mode_label = "llm" if llm else "fixture"

    print(f"mode: {mode_label}" + (f" (model: {model})" if llm else ""))
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
