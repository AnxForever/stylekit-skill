import importlib.util
import io
import json
import zipfile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("fetch_asset", ROOT / "scripts" / "fetch-asset.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def summary(kind="animation", asset_id="grain-drift", availability="bundled"):
    return {
        "id": asset_id,
        "kind": kind,
        "name": "Grain Drift",
        "description": "A subtle animated texture.",
        "tags": ["grain", "motion"],
        "availability": availability,
        "contentLevel": "remote" if kind == "template" else ("metadata" if kind == "experience-pack" else "source"),
    }


def detail(kind="animation", asset_id="grain-drift", availability="bundled"):
    return {
        "schemaVersion": "1",
        "metadata": summary(kind, asset_id, availability),
        "data": (
            {
                "downloadUrl": f"https://www.stylekit.top/api/templates/{asset_id}/download",
                "downloadMethod": "GET",
                "downloadFormat": "zip",
                "sourceFilesIncluded": False,
            }
            if kind == "template"
            else {"duration": "600ms", "reducedMotion": "static"}
        ),
        "code": "@keyframes drift { from { opacity: .7 } to { opacity: 1 } }",
        "dependencies": ["tailwindcss"],
        "license": {"name": "MIT", "url": "https://example.test/license"},
        "attribution": {"required": False},
        "sourceUrls": ["https://stylekit.top/animations/grain-drift"],
    }


class AssetUrlTests(unittest.TestCase):
    def test_base_url_accepts_origin_api_prefix_and_full_path(self):
        self.assertEqual(assets.normalize_base_url("http://127.0.0.1:3189"), "http://127.0.0.1:3189/api/assets")
        self.assertEqual(assets.normalize_base_url("http://127.0.0.1:3189/api"), "http://127.0.0.1:3189/api/assets")
        self.assertEqual(assets.normalize_base_url("http://127.0.0.1:3189/api/assets"), "http://127.0.0.1:3189/api/assets")
        self.assertEqual(assets.normalize_base_url("https://example.test/v1/api/assets/"), "https://example.test/v1/api/assets")

    def test_base_url_rejects_credentials_query_and_fragment(self):
        for url in (
            "http://user:pass@127.0.0.1:3189",
            "http://127.0.0.1:3189?token=x",
            "http://127.0.0.1:3189#section",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "credentials"):
                assets.normalize_base_url(url)


class AssetApiTests(unittest.TestCase):
    def test_search_validates_pagination_and_returns_request_url(self):
        response = {
            "schemaVersion": "1",
            "assets": [summary()],
            "kindCounts": {"animation": 5},
            "total": 5,
            "offset": 2,
            "limit": 3,
            "hasMore": True,
        }
        with patch.object(assets, "_read_json", return_value=response) as get_json:
            result, url = assets.search_assets("grain drift", "animation", 2, 3, "http://127.0.0.1:3189/api")
        self.assertEqual(result["assets"][0]["id"], "grain-drift")
        self.assertEqual(url.split("?")[0], "http://127.0.0.1:3189/api/assets")
        self.assertIn("q=grain+drift", url)
        self.assertIn("kind=animation", url)
        self.assertIn("offset=2", url)
        self.assertEqual(get_json.call_count, 1)

    def test_search_rejects_malformed_contract_and_page_metadata(self):
        with self.assertRaisesRegex(ValueError, "schemaVersion"):
            assets.validate_list({"schemaVersion": "2", "assets": []})
        malformed = {"schemaVersion": "1", "assets": [summary()], "kindCounts": {"animation": 1}, "total": 1, "offset": True, "limit": 1, "hasMore": False}
        with self.assertRaisesRegex(ValueError, "offset"):
            assets.validate_list(malformed)
        malformed = {"schemaVersion": "1", "assets": [summary()], "kindCounts": {"animation": 1}, "total": 0, "offset": 0, "limit": 1, "hasMore": False}
        with self.assertRaisesRegex(ValueError, "smaller"):
            assets.validate_list(malformed)
        malformed = {"schemaVersion": "1", "assets": [{**summary(), "availability": []}], "kindCounts": {"animation": 1}, "total": 1, "offset": 0, "limit": 1, "hasMore": False}
        with self.assertRaisesRegex(ValueError, "availability"):
            assets.validate_list(malformed)

    def test_detail_checks_identity_and_source_shapes(self):
        fetched = detail()
        with patch.object(assets, "_read_json", return_value=fetched) as get_json:
            result, url = assets.fetch_asset("animation", "grain-drift", "http://127.0.0.1:3189/api/assets")
        self.assertEqual(result["metadata"]["id"], "grain-drift")
        self.assertTrue(url.endswith("/animation/grain-drift"))
        self.assertEqual(get_json.call_count, 1)

        with self.assertRaisesRegex(ValueError, "kind mismatch"):
            assets.validate_detail(fetched, "background", "grain-drift")
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            assets.validate_detail(fetched, "animation", "different")
        invalid = detail()
        invalid["dependencies"] = "tailwindcss"
        with self.assertRaisesRegex(ValueError, "dependencies"):
            assets.validate_detail(invalid, "animation", "grain-drift")

    def test_restricted_asset_drops_reusable_source(self):
        restricted = detail(availability="restricted")
        result = assets.validate_detail(restricted, "animation", "grain-drift")
        self.assertEqual(result["metadata"]["availability"], "restricted")
        self.assertNotIn("data", result)
        self.assertNotIn("code", result)
        self.assertNotIn("dependencies", result)
        self.assertNotIn("code", result["metadata"])
        self.assertFalse(result["_stylekitAccess"]["usable"])
        self.assertIn("license", result)

    def test_external_asset_requires_review_without_following_source(self):
        external = detail(availability="external")
        with patch.object(assets, "_read_json", return_value=external):
            result, _ = assets.fetch_asset("animation", "grain-drift")
        self.assertEqual(result["_stylekitAccess"]["usable"], "review-required")
        self.assertNotIn("code", result)
        self.assertNotIn("data", result)
        self.assertIn("sourceUrls", result)

    def test_template_download_requires_exact_official_route_and_valid_zip(self):
        template = assets.validate_detail(detail("template", "brutal-landing", "remote"), "template", "brutal-landing")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("brutal-landing-template/app/page.tsx", "export default function Page() { return <main /> }")
        contents = buffer.getvalue()

        class Response:
            headers = {"Content-Type": "application/zip"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, count):
                return contents[:count]

        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response()

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "brutal-landing.zip"
            opener = Opener()
            with patch.object(assets.urllib.request, "build_opener", return_value=opener):
                record = assets.download_template(template, destination)
            self.assertTrue(zipfile.is_zipfile(destination))
            self.assertEqual(record["bytes"], len(contents))
            self.assertEqual(len(record["sha256"]), 64)
            self.assertEqual(opener.request.full_url, template["data"]["downloadUrl"])

            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                with patch.object(assets.urllib.request, "build_opener", return_value=opener):
                    assets.download_template(template, destination)

    def test_template_download_rejects_external_route_before_network(self):
        template = assets.validate_detail(detail("template", "brutal-landing", "remote"), "template", "brutal-landing")
        template["data"]["downloadUrl"] = "https://evil.example/api/templates/brutal-landing/download"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(assets.urllib.request, "build_opener") as build:
                with self.assertRaisesRegex(ValueError, "official HTTPS host"):
                    assets.download_template(template, Path(tmp) / "template.zip")
                build.assert_not_called()

    def test_template_source_files_materialize_with_binary_decode(self):
        template = assets.validate_detail(detail("template", "brutal-landing", "remote"), "template", "brutal-landing")
        template["data"].update({
            "sourceFilesIncluded": True,
            "files": {
                "app/page.tsx": "export default function Page() { return <main /> }",
                "public/logo.bin": "AAEC/w==",
            },
            "binaryFiles": ["public/logo.bin"],
            "fileEncoding": assets.BINARY_ENCODING,
            "dependencies": {"next": "^15.0.0"},
            "devDependencies": {"typescript": "^5.0.0"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new-template"
            result = assets.materialize_template(template, output)
            self.assertEqual(result["files"], 2)
            self.assertTrue((output / "app" / "page.tsx").read_text(encoding="utf-8").startswith("export default"))
            self.assertEqual((output / "public" / "logo.bin").read_bytes(), b"\x00\x01\x02\xff")

    def test_template_source_paths_are_validated_before_writing(self):
        template = assets.validate_detail(detail("template", "brutal-landing", "remote"), "template", "brutal-landing")
        template["data"].update({
            "sourceFilesIncluded": True,
            "files": {"../outside.txt": "no"},
            "binaryFiles": [],
            "fileEncoding": assets.BINARY_ENCODING,
        })
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new-template"
            with self.assertRaisesRegex(ValueError, "unsafe template file path"):
                assets.materialize_template(template, output)
            self.assertFalse(output.exists())

    def test_template_binary_list_must_match_files_and_decode_strictly(self):
        template = assets.validate_detail(detail("template", "brutal-landing", "remote"), "template", "brutal-landing")
        template["data"].update({
            "sourceFilesIncluded": True,
            "files": {"public/logo.bin": "not-base64"},
            "binaryFiles": ["public/logo.bin"],
            "fileEncoding": assets.BINARY_ENCODING,
        })
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new-template"
            with self.assertRaisesRegex(ValueError, "not valid base64"):
                assets.materialize_template(template, output)
            self.assertFalse(output.exists())

        template["data"]["binaryFiles"] = ["missing.bin"]
        with self.assertRaisesRegex(ValueError, "keys in data.files"):
            assets.validate_detail(template, "template", "brutal-landing")


class SavedAssetTests(unittest.TestCase):
    def write_json(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_structured_and_text_mcp_envelopes_normalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            self.write_json(path, {"structuredContent": detail()})
            payload, kind = assets._load_file(path, from_mcp=True)
            result = assets.validate_detail(payload, "animation", "grain-drift")
            self.assertEqual(kind, "mcp-structuredContent")
            self.assertEqual(result["metadata"]["kind"], "animation")

            self.write_json(path, {"content": [{"type": "text", "text": json.dumps({"schemaVersion": "1", "assets": [summary()], "kindCounts": {"animation": 1}, "total": 1, "offset": 0, "limit": 10, "hasMore": False})}]})
            payload, kind = assets._load_file(path, from_mcp=True)
            self.assertEqual(kind, "mcp-text-content")
            self.assertEqual(assets.validate_list(payload)["assets"][0]["id"], "grain-drift")

    def test_mcp_error_and_bad_text_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp-error.json"
            self.write_json(path, {"isError": True, "structuredContent": detail()})
            with self.assertRaisesRegex(ValueError, "isError=true"):
                assets._load_file(path, from_mcp=True)
            self.write_json(path, {"content": [{"type": "text", "text": "Searching the catalogue…"}]})
            with self.assertRaisesRegex(ValueError, "no usable"):
                assets._load_file(path, from_mcp=True)

    def test_saved_contract_source_is_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.json"
            payload = detail()
            payload["_stylekitSource"] = {"kind": "http-api", "degraded": True, "contract": "wrong"}
            self.write_json(path, payload)
            result = assets._read_local_asset(argparse_namespace(spec=path, from_file=None), "animation", "grain-drift")
            self.assertEqual(result["_stylekitSource"]["kind"], "json-file")
            self.assertFalse(result["_stylekitSource"]["degraded"])
            self.assertEqual(result["_stylekitSource"]["contract"], "stylekit-assets-v1")

    def test_cli_writes_machine_readable_detail_and_redacts_restricted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "restricted.json"
            self.write_json(path, detail(availability="restricted"))
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "fetch-asset.py"), "get", "animation", "grain-drift", "--spec", str(path), "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertNotIn("code", output)
            self.assertNotIn("data", output)
            self.assertFalse(output["_stylekitAccess"]["usable"])

    def test_local_list_search_is_explicitly_limited_to_saved_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            self.write_json(path, {"schemaVersion": "1", "assets": [summary(), summary("background", "linen")], "kindCounts": {"animation": 1, "background": 1}, "total": 2, "offset": 0, "limit": 20, "hasMore": False})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "fetch-asset.py"), "search", "linen", "--spec", str(path), "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual([item["id"] for item in output["assets"]], ["linen"])
            self.assertEqual(output["total"], 1)
            self.assertIn("saved response only", output["_stylekitSource"]["scope"])


def argparse_namespace(**kwargs):
    class Args:
        pass
    args = Args()
    for key, value in kwargs.items():
        setattr(args, key, value)
    return args


if __name__ == "__main__":
    unittest.main()
