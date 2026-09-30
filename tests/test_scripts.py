import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load("fetch-style")
detect = load("detect-project")
evaluate = load("eval-check")
verify = load("verify-spec")
benchmark = load("benchmark")


class FetchTests(unittest.TestCase):
    def test_exact_slug_matches_without_keyword_or_tag_matches(self):
        with patch.object(fetch, "get_json", return_value={"styles": [{"slug": "glassmorphism", "nameEn": "Glass", "keywords": [], "tags": []}]}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(fetch.search("glassmorphism")), 1)

    def test_recipes_wrapper_prints_actual_implementation(self):
        spec = {"recipes": {"styleSlug": "glassmorphism", "recipes": {"button": {"skeleton": {"baseClasses": ["backdrop-blur-xl"]}, "states": {"disabled": {"classes": ["opacity-50"]}}}}}}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            fetch.print_recipes(spec)
        self.assertIn("button:", output.getvalue())
        self.assertIn("backdrop-blur-xl", output.getvalue())
        self.assertIn("disabled", output.getvalue())

    def test_complete_text_preserves_css_and_templates(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            fetch.print_spec("test", "all", {"slug": "test", "philosophy": "Purpose", "globalCss": "body {color:red}", "components": {"button": {"code": "<button>OK</button>"}}})
        self.assertIn("Purpose", output.getvalue())
        self.assertIn("body {color:red}", output.getvalue())
        self.assertIn("<button>OK</button>", output.getvalue())

    def test_legacy_fallback_only_on_404(self):
        error = urllib.error.HTTPError("url", 404, "missing", {}, None)
        with patch.object(fetch, "get_json", side_effect=[error, {"slug": "test", "recipes": {"recipes": {"button": {}}}}]) as getter:
            self.assertIn("button", fetch.fetch_spec("test")["recipes"])
            self.assertEqual(getter.call_count, 2)
        error = urllib.error.HTTPError("url", 500, "server error", {}, None)
        with patch.object(fetch, "get_json", side_effect=error) as getter:
            with self.assertRaises(urllib.error.HTTPError):
                fetch.fetch_spec("test")
            self.assertEqual(getter.call_count, 1)


class BenchmarkTests(unittest.TestCase):
    def test_evaluator_errors_never_count_as_a_baseline_pass(self):
        task = {"id": "sample", "slug": "test", "component": "button", "prompt": "Create a button"}
        spec = {"slug": "test", "components": {"button": {"code": '<button className="p-4" />'}}}
        with patch.object(benchmark, "fetch_spec", return_value=spec), patch.object(benchmark, "score", side_effect=[(2, []), (0, [])]) as scorer:
            result = benchmark.run_task(task)
        self.assertFalse(result["baseline"]["pass"])
        self.assertEqual(result["baseline_exit_code"], 2)
        self.assertIs(scorer.call_args_list[0].args[3], spec)
        self.assertIs(scorer.call_args_list[1].args[3], spec)


class DetectionTests(unittest.TestCase):
    def test_resolves_ui_alias_and_ignores_generated_css(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(json.dumps({"dependencies": {"next": "16.0.0", "tailwindcss": "^4.0", "stylekit-core": "1.0.0-beta.4"}}))
            (root / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}))
            (root / "components.json").write_text(json.dumps({"aliases": {"components": "@/components", "ui": "@/components/ui"}}))
            ui = root / "src/components/ui"
            ui.mkdir(parents=True)
            (ui / "button.tsx").write_text("export const Button = null;")
            (ui / "card.tsx").write_text("export const Card = null;")
            (ui / "readme.md").write_text("ignored")
            generated = root / "node_modules/irrelevant"
            generated.mkdir(parents=True)
            (generated / "theme.css").write_text('@import "tailwindcss";')
            result = detect.detect(tmp)
            self.assertEqual(result["framework"], "next")
            self.assertEqual(result["shadcn"]["installedComponents"], ["button", "card"])
            self.assertTrue(result["styleKitInstalled"])
            self.assertEqual(result["cssFiles"], [])
            self.assertFalse(result["tailwind"]["usesCssConfig"])


class LintContractTests(unittest.TestCase):
    def test_shared_contract_cases(self):
        fixture = json.loads((ROOT / "tests/fixtures/style-lint-contract.json").read_text())
        for sample in fixture["cases"]:
            with self.subTest(sample["name"]):
                report = evaluate.lint_code(fixture["specs"][sample["slug"]], sample["code"], sample.get("component"), sample.get("strict", False))
                self.assertEqual(report["status"], sample["status"])
                self.assertEqual(report["ok"], sample["status"] == "pass")

    def test_spec_checker_does_not_exempt_small_elements(self):
        spec = {"slug": "test", "doList": ["use rules"], "dontList": ["no rounding"], "aiRules": "no rounding",
                "tokens": {"forbidden": {"classes": ["rounded-xl"]}, "required": {}},
                "components": {"button": {"code": '<button className="w-2 h-2 rounded-xl" />'}}}
        issues, _ = verify.check_spec(spec)
        self.assertTrue(any("rounded-xl" in issue for issue in issues))

    def test_bad_pattern_and_unknown_rules_do_not_pass(self):
        spec = {"slug": "test", "lintRules": {"schemaVersion": "stylekit-lint-v1", "sources": ["tokens"], "forbiddenClasses": [], "forbiddenPatterns": [{"pattern": "[", "source": "tokens"}], "exempt": [], "required": {}}}
        self.assertEqual(evaluate.lint_code(spec, '<div class="p-4"/>')["status"], "inconclusive")
        self.assertEqual(evaluate.lint_code({"slug": "unknown"}, '<div class="p-4"/>')["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
