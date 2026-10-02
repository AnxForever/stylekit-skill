import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


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
spec_input = load("spec_input")


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
        legacy = {"slug": "test", "components": {}, "recipes": {"recipes": {"button": {}}}, "tokens": {}, "aiRules": "rules"}
        with patch.object(fetch, "get_json", side_effect=[error, legacy]) as getter:
            self.assertIn("button", fetch.fetch_spec("test")["recipes"])
            self.assertEqual(getter.call_count, 2)
        error = urllib.error.HTTPError("url", 500, "server error", {}, None)
        with patch.object(fetch, "get_json", side_effect=error) as getter:
            with self.assertRaises(urllib.error.HTTPError):
                fetch.fetch_spec("test")
            self.assertEqual(getter.call_count, 1)

    def test_brief_slug_mismatch_does_not_fall_back(self):
        with patch.object(fetch, "get_json", return_value={"schemaVersion": "stylekit-brief-v1", "slug": "other-style"}) as getter:
            with self.assertRaisesRegex(ValueError, "slug mismatch"):
                fetch.fetch_spec("neo-brutalist")
            self.assertEqual(getter.call_count, 1)


class SpecInputTests(unittest.TestCase):
    def brief(self, slug="neo-brutalist"):
        return {
            "schemaVersion": "stylekit-brief-v1",
            "slug": slug,
            "name": "新粗野主义",
            "nameEn": "Neo-Brutalist",
            "category": "expressive",
            "styleType": "visual",
            "description": "A bold style.",
            "tags": ["bold"],
            "keywords": ["brutalist"],
            "philosophy": "Use bold shapes.",
            "aiRules": "Use hard shadows.",
            "doList": ["Use thick borders."],
            "dontList": ["Avoid soft shadows."],
            "colors": {"primary": "#ff006e", "secondary": "#fff", "accent": ["#ffe600"]},
            "globalCss": "",
            "components": {"button": {"code": '<button className="border-2" />'}},
            "variants": [],
            "recipes": {"styleSlug": slug, "recipes": {"button": {"classes": ["border-2"]}}},
            "readiness": {
                "styleSlug": slug,
                "source": "curated",
                "themeModes": ["light", "dark"],
                "darkMode": {"support": "complete", "strategy": "explicit-tokens", "guidance": []},
                "states": {"default": {"support": "complete", "guidance": []}},
                "components": {"button": {"states": ["default"], "guidance": []}},
                "motion": {"support": "complete", "guidance": [], "duration": "200ms", "easing": "ease-out", "reducedMotion": "disable nonessential motion"},
                "accessibility": {"support": "complete", "guidance": [], "focus": "visible", "targetSize": "comfortable", "aria": "label controls"},
                "performance": {"support": "complete", "guidance": [], "costs": []},
                "promptAddons": [],
                "coverage": {"darkMode": 1, "states": 1, "motion": 1, "accessibility": 1, "performance": 1, "overall": 1},
            },
            "tokens": {
                "border": {"width": "border-2", "color": "border-black", "radius": "rounded-none"},
                "shadow": {"sm": "shadow-sm", "md": "shadow-md", "lg": "shadow-lg", "none": "shadow-none", "hover": "shadow-md", "focus": "ring-2"},
                "interaction": {"transition": "transition-colors"},
                "typography": {"heading": "font-bold", "body": "font-normal", "sizes": {"hero": "text-5xl", "h1": "text-4xl", "h2": "text-3xl", "h3": "text-2xl", "body": "text-base", "small": "text-sm"}},
                "spacing": {"section": "py-12", "container": "px-4", "card": "p-4", "gap": {"sm": "gap-2", "md": "gap-4", "lg": "gap-8"}},
                "colors": {
                    "background": {"primary": "bg-white", "secondary": "bg-gray-100", "accent": ["bg-pink-500"]},
                    "text": {"primary": "text-black", "secondary": "text-gray-700", "muted": "text-gray-500"},
                    "button": {"primary": "bg-pink-500", "secondary": "bg-white"},
                },
                "forbidden": {"classes": [], "patterns": [], "reasons": {}},
                "required": {"button": ["border-2"], "card": ["border-2"], "input": ["border-2"]},
            },
            "lintRules": {
                "schemaVersion": "stylekit-lint-v1", "sources": ["fixture"],
                "forbiddenClasses": [], "forbiddenPatterns": [], "exempt": [],
                "required": {}, "unsupportedRules": [],
            },
            "provenance": {"source": "bundled", "contentHash": "test-hash", "url": "https://example.test/style"},
        }

    def write_json(self, path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_mcp_structured_and_text_envelopes_normalize_with_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            structured_path = Path(tmp) / "structured.json"
            self.write_json(structured_path, {
                "content": [{"type": "text", "text": "truncated summary"}],
                "structuredContent": self.brief(),
            })
            structured = spec_input.load_spec_file(structured_path, "neo-brutalist", from_mcp=True)
            self.assertEqual(structured["recipes"]["button"]["classes"], ["border-2"])
            self.assertEqual(structured["_stylekitSource"]["kind"], "mcp-structuredContent")
            self.assertFalse(structured["_stylekitSource"]["degraded"])

            text_path = Path(tmp) / "text.json"
            self.write_json(text_path, {"content": [{"type": "text", "text": json.dumps(self.brief())}]})
            text_result = spec_input.load_spec_file(text_path, "neo-brutalist", from_mcp=True)
            self.assertEqual(text_result["_stylekitSource"]["kind"], "mcp-text-content")
            self.assertFalse(text_result["_stylekitSource"]["degraded"])

    def test_slug_schema_and_read_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrong_slug = self.write_json(root / "wrong-slug.json", self.brief("glassmorphism"))
            with self.assertRaisesRegex(ValueError, "slug mismatch"):
                spec_input.load_spec_file(wrong_slug, "neo-brutalist")

            unsupported = self.brief()
            unsupported["schemaVersion"] = "stylekit-brief-v2"
            unsupported_path = self.write_json(root / "unsupported.json", unsupported)
            with self.assertRaisesRegex(ValueError, "unsupported StyleKit schemaVersion"):
                spec_input.load_spec_file(unsupported_path, "neo-brutalist")

            incomplete = self.brief()
            del incomplete["lintRules"]
            incomplete_path = self.write_json(root / "incomplete.json", incomplete)
            with self.assertRaisesRegex(ValueError, "lintRules must use stylekit-lint-v1"):
                spec_input.load_spec_file(incomplete_path, "neo-brutalist")

            incomplete_tokens = self.brief()
            incomplete_tokens["tokens"].pop("interaction")
            token_path = self.write_json(root / "incomplete-tokens.json", incomplete_tokens)
            with self.assertRaisesRegex(ValueError, "tokens.interaction"):
                spec_input.load_spec_file(token_path, "neo-brutalist")

            incomplete_readiness = self.brief()
            incomplete_readiness["readiness"].pop("coverage")
            readiness_path = self.write_json(root / "incomplete-readiness.json", incomplete_readiness)
            with self.assertRaisesRegex(ValueError, "readiness.coverage"):
                spec_input.load_spec_file(readiness_path, "neo-brutalist")

            with self.assertRaisesRegex(ValueError, "cannot read JSON spec"):
                spec_input.load_spec_file(root / "missing.json", "neo-brutalist")

    def test_legacy_null_capabilities_fetch_and_eval_as_inconclusive(self):
        missing_brief = urllib.error.HTTPError("url", 404, "missing", {}, None)
        legacy = {
            "slug": "test",
            "components": {"button": {"code": '<button className="px-4" />'}},
            "recipes": None,
            "tokens": None,
            "aiRules": "Legacy guidance.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "legacy.json"
            with patch.object(fetch, "get_json", side_effect=[missing_brief, legacy]):
                normalized = fetch.fetch_spec("test")
            self.assertEqual(normalized["recipes"], {})
            self.assertIsNone(normalized["tokens"])
            self.assertTrue(normalized["_stylekitSource"]["degraded"])
            self.write_json(spec_path, normalized)

            component = Path(tmp) / "button.tsx"
            component.write_text('<button className="px-4" />', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "eval-check.py"), "test", str(component), "--spec", str(spec_path), "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "inconclusive")
            self.assertTrue(report["files"][0]["report"]["specSource"]["degraded"])

        for field in ("recipes", "tokens"):
            invalid = dict(legacy, **{field: "not-an-object"})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "incomplete legacy style spec"):
                spec_input.validate_spec_object(invalid, "test")

    def test_mcp_error_envelope_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "error.json"
            valid_content = {
                "structuredContent": self.brief(),
                "content": [{"type": "text", "text": json.dumps(self.brief())}],
            }
            self.write_json(path, {
                "isError": True,
                **valid_content,
            })
            with self.assertRaisesRegex(ValueError, "isError=true"):
                spec_input.load_spec_file(path, "neo-brutalist", from_mcp=True)

            self.write_json(path, {
                "result": {"isError": True, **valid_content},
                "content": valid_content["content"],
            })
            with self.assertRaisesRegex(ValueError, "isError=true"):
                spec_input.load_spec_file(path, "neo-brutalist", from_mcp=True)

    def test_inherited_source_metadata_cannot_override_validated_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = self.brief()
            brief["_stylekitSource"] = {
                "kind": "http-api",
                "contract": "legacy-style-spec",
                "degraded": True,
                "reason": "stale legacy warning",
            }
            brief_path = self.write_json(root / "brief.json", brief)
            loaded_brief = spec_input.load_spec_file(brief_path, "neo-brutalist")
            self.assertEqual(loaded_brief["_stylekitSource"]["kind"], "http-api")
            self.assertEqual(loaded_brief["_stylekitSource"]["contract"], "stylekit-brief-v1")
            self.assertFalse(loaded_brief["_stylekitSource"]["degraded"])
            self.assertNotIn("reason", loaded_brief["_stylekitSource"])

            legacy = {
                "slug": "neo-brutalist",
                "components": {},
                "recipes": {},
                "tokens": {},
                "aiRules": "legacy rules",
                "_stylekitSource": {
                    "kind": "file",
                    "contract": "stylekit-brief-v1",
                    "degraded": False,
                },
            }
            legacy_path = self.write_json(root / "legacy.json", legacy)
            loaded_legacy = spec_input.load_spec_file(legacy_path, "neo-brutalist")
            self.assertEqual(loaded_legacy["_stylekitSource"]["contract"], "legacy-style-spec")
            self.assertTrue(loaded_legacy["_stylekitSource"]["degraded"])
            self.assertTrue(loaded_legacy["_stylekitSource"]["reason"])

    def test_local_api_base_url_forms(self):
        self.assertEqual(
            spec_input.normalize_base_url("http://127.0.0.1:3189/api/styles", fetch.BASE),
            "http://127.0.0.1:3189/api/styles",
        )
        self.assertEqual(
            spec_input.normalize_base_url("http://127.0.0.1:3189", fetch.BASE),
            "http://127.0.0.1:3189/api/styles",
        )
        self.assertEqual(
            spec_input.normalize_base_url("http://127.0.0.1:3189/api", fetch.BASE),
            "http://127.0.0.1:3189/api/styles",
        )
        with self.assertRaisesRegex(ValueError, "credentials"):
            spec_input.normalize_base_url("http://user:pass@127.0.0.1:3189", fetch.BASE)

    def test_installed_scripts_work_from_unrelated_consumer_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_root = root / "consumer" / ".agents" / "skills" / "stylekit"
            target = root / "consumer" / "sample-app"
            target.mkdir(parents=True)
            shutil.copytree(ROOT, skill_root, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "tests"))
            (target / "package.json").write_text(json.dumps({"dependencies": {"next": "^15.0.0", "react": "^19.0.0"}}), encoding="utf-8")

            spec_path = target / "style-spec.json"
            brief = self.brief()
            brief["lintRules"] = {
                "schemaVersion": "stylekit-lint-v1",
                "sources": ["fixture"],
                "forbiddenClasses": [],
                "forbiddenPatterns": [],
                "exempt": [],
                "unsupportedRules": [],
                "required": {"button": {"classes": ["font-black"], "source": "fixture"}},
            }
            self.write_json(spec_path, brief)
            component = target / "button.tsx"
            component.write_text('<button className="border-2 font-black" />', encoding="utf-8")

            detect = subprocess.run(
                [sys.executable, str(skill_root / "scripts" / "detect-project.py"), str(target)],
                cwd=target, capture_output=True, text=True, check=False,
            )
            self.assertEqual(detect.returncode, 0, detect.stderr)
            self.assertEqual(json.loads(detect.stdout)["framework"], "next")

            envelope_path = target / "mcp-result.json"
            self.write_json(envelope_path, {"structuredContent": brief, "content": [{"type": "text", "text": json.dumps(brief)}]})
            normalized_path = target / "normalized.json"
            normalize = subprocess.run(
                [sys.executable, str(skill_root / "scripts" / "fetch-style.py"), "neo-brutalist", "--from-file", str(envelope_path), "--json"],
                cwd=target, capture_output=True, text=True, check=False,
            )
            self.assertEqual(normalize.returncode, 0, normalize.stderr)
            normalized_path.write_text(normalize.stdout, encoding="utf-8")
            self.assertEqual(json.loads(normalize.stdout)["_stylekitSource"]["kind"], "mcp-structuredContent")

            lint = subprocess.run(
                [sys.executable, str(skill_root / "scripts" / "eval-check.py"), "neo-brutalist", str(component), "--spec", str(normalized_path), "--component", "button", "--strict"],
                cwd=target, capture_output=True, text=True, check=False,
            )
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

            asset_metadata = {
                "id": "grain-drift",
                "kind": "animation",
                "name": "Grain Drift",
                "description": "A subtle animated texture.",
                "tags": ["grain", "motion"],
                "availability": "bundled",
                "contentLevel": "source",
            }
            asset_list = {
                "schemaVersion": "1",
                "assets": [asset_metadata],
                "kindCounts": {"animation": 1},
                "total": 1,
                "offset": 0,
                "limit": 10,
                "hasMore": False,
            }
            asset_list_path = target / "asset-list-mcp.json"
            self.write_json(asset_list_path, {"structuredContent": asset_list})
            asset_search = subprocess.run(
                [sys.executable, str(skill_root / "scripts" / "fetch-asset.py"), "search", "grain", "--from-file", str(asset_list_path), "--json"],
                cwd=target, capture_output=True, text=True, check=False,
            )
            self.assertEqual(asset_search.returncode, 0, asset_search.stderr)
            self.assertEqual(json.loads(asset_search.stdout)["assets"][0]["id"], "grain-drift")

            asset_detail = {
                "schemaVersion": "1",
                "metadata": asset_metadata,
                "data": {"duration": "600ms"},
                "code": "@keyframes drift {}",
            }
            asset_detail_path = target / "asset-detail-mcp.json"
            self.write_json(asset_detail_path, {"content": [{"type": "text", "text": json.dumps(asset_detail)}]})
            asset_get = subprocess.run(
                [sys.executable, str(skill_root / "scripts" / "fetch-asset.py"), "get", "animation", "grain-drift", "--from-file", str(asset_detail_path), "--json"],
                cwd=target, capture_output=True, text=True, check=False,
            )
            self.assertEqual(asset_get.returncode, 0, asset_get.stderr)
            self.assertEqual(json.loads(asset_get.stdout)["_stylekitSource"]["kind"], "mcp-text-content")

    def test_cli_errors_exit_two_without_live_api_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "consumer"
            target.mkdir()
            source = target / "button.tsx"
            source.write_text('<button className="font-black" />', encoding="utf-8")
            good = self.brief()
            cases = []
            wrong_slug = dict(good, slug="glassmorphism")
            cases.append(("wrong-slug.json", wrong_slug, "slug mismatch"))
            unsupported = dict(good, schemaVersion="stylekit-brief-v2")
            cases.append(("unsupported.json", unsupported, "unsupported StyleKit schemaVersion"))
            incomplete = dict(good)
            incomplete.pop("lintRules")
            cases.append(("incomplete.json", incomplete, "lintRules must use stylekit-lint-v1"))
            for filename, payload, expected in cases:
                spec_path = self.write_json(target / filename, payload)
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "eval-check.py"), "neo-brutalist", str(source), "--spec", str(spec_path)],
                    cwd=target, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(expected, result.stderr)
            missing = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "eval-check.py"), "neo-brutalist", str(source), "--spec", str(target / "missing.json")],
                cwd=target, capture_output=True, text=True, check=False,
            )
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)


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
