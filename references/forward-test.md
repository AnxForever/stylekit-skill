# Manual forward test

The fixture benchmark checks evaluator behavior; it does not show that an agent followed the Skill or produced a usable page. For a practical sample, test the installed Skill in a small consumer project separate from this repository.

1. Give the agent a realistic UI task with multiple distinct controls, such as filters, a favorite button, a card, and an input. Record the exact prompt, chosen style slug, and spec source or content hash.
2. Let the agent inspect the consumer project and implement the task. Confirm it uses the saved spec for both generation and checks.
3. Compile the project's actual CSS. Run `eval-check.py --component ... --strict` on isolated component snippets or files; do not use one full-page strict result as proof for every component because required classes are matched across the input file as a whole.
4. Open the compiled page at desktop and narrow mobile widths. Exercise default, hover, focus, disabled, and other task-relevant states. Inspect computed foreground/background colors for actions and small text, and check the text contrast. With Tailwind v4, generic CSS that should yield to utilities may need `@layer base` or deliberate scoping.
5. Record compile output, per-component evaluator results, browser observations, and any fixes. A successful run is evidence for that task and environment, not a general quality guarantee.

## Failure modes this catches

In one forward test, the whole-page strict check passed, while isolated filter and favorite buttons lacked required shadow, hover, transition, and cursor classes. Browser inspection also found an unlayered `a { color: inherit; }` rule overriding a Tailwind text utility on a CTA, plus small pink text with poor contrast. These are examples of why class checks, compiled CSS, and browser review provide different evidence; the Skill does not automatically prevent these failures.
