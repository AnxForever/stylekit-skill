import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "detect_project",
    ROOT / "scripts" / "detect-project.py",
)
detect_project = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detect_project)


class DetectProjectTests(unittest.TestCase):
    def write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_expo_and_react_native_are_not_misreported_as_web_react(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_json(root / "package.json", {
                "dependencies": {
                    "expo": "~54.0.0",
                    "react": "19.1.0",
                    "react-native": "0.81.0",
                    "react-native-paper": "^5.14.0",
                },
                "devDependencies": {"@gorhom/bottom-sheet": "^5.0.0"},
            })

            result = detect_project.detect(tmp)

            self.assertEqual(result["framework"], "expo")
            self.assertEqual(result["platforms"], ["react-native"])
            self.assertEqual(result["componentLibraries"], ["@gorhom/bottom-sheet", "react-native-paper"])
            self.assertEqual(result["projects"], [{
                "path": ".",
                "framework": "expo",
                "platforms": ["react-native"],
                "componentLibraries": ["@gorhom/bottom-sheet", "react-native-paper"],
            }])

    def test_bare_react_native_ignores_react_dependency_as_web_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_json(Path(tmp) / "package.json", {
                "dependencies": {"react": "19.1.0", "react-native": "0.81.0", "@rneui/themed": "^4.0.0"},
            })

            result = detect_project.detect(tmp)

            self.assertEqual(result["framework"], "react-native")
            self.assertEqual(result["platforms"], ["react-native"])
            self.assertEqual(result["componentLibraries"], ["@rneui/themed"])

    def test_next_keeps_framework_priority_in_a_react_native_web_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_json(Path(tmp) / "package.json", {
                "dependencies": {
                    "next": "16.0.0",
                    "react": "19.0.0",
                    "react-dom": "19.0.0",
                    "react-native": "0.81.0",
                    "react-native-web": "0.20.0",
                },
            })

            result = detect_project.detect(tmp)

            self.assertEqual(result["framework"], "next")
            self.assertEqual(result["platforms"], ["react-native", "web"])
            self.assertEqual(result["componentLibraries"], ["react-native-web"])

    def test_web_frameworks_keep_legacy_detection_and_report_web_platform(self):
        cases = (
            ({"next": "16.0.0", "react": "19.0.0", "@radix-ui/react-dialog": "^1.0.0"}, "next", ["@radix-ui/react-dialog"]),
            ({"react": "19.0.0"}, "react", []),
            ({"vue": "3.5.0", "vant": "^4.0.0"}, "vue", ["vant"]),
        )
        for deps, expected_framework, expected_libraries in cases:
            with self.subTest(framework=expected_framework), tempfile.TemporaryDirectory() as tmp:
                self.write_json(Path(tmp) / "package.json", {"dependencies": deps})

                result = detect_project.detect(tmp)

                self.assertEqual(result["framework"], expected_framework)
                self.assertEqual(result["platforms"], ["web"])
                self.assertEqual(result["componentLibraries"], expected_libraries)
                for legacy_key in (
                    "framework", "reactVersion", "tailwind", "shadcn",
                    "styleKitInstalled", "hasGlobalCss", "cssFiles",
                ):
                    self.assertIn(legacy_key, result)

    def test_swift_package_requires_an_actual_swiftui_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Package.swift").write_text("// package manifest only\n", encoding="utf-8")
            source = root / "Sources" / "App" / "App.swift"
            source.parent.mkdir(parents=True)
            source.write_text("import Foundation\n/*\nimport SwiftUI\n*/\n", encoding="utf-8")

            generic = detect_project.detect(tmp)
            self.assertIsNone(generic["framework"])
            self.assertEqual(generic["platforms"], [])
            self.assertEqual(generic["projects"], [])

            source.write_text("@preconcurrency import SwiftUI\n", encoding="utf-8")
            swiftui = detect_project.detect(tmp)
            self.assertEqual(swiftui["framework"], "swiftui")
            self.assertEqual(swiftui["platforms"], ["swiftui"])

    def test_xcode_project_detects_swiftui_without_package_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Sample.xcodeproj").mkdir()
            source = root / "SampleApp" / "App.swift"
            source.parent.mkdir()
            source.write_text("import Foundation\n", encoding="utf-8")

            generic = detect_project.detect(tmp)
            self.assertIsNone(generic["framework"])
            self.assertEqual(generic["platforms"], [])

            source.write_text("import SwiftUI\n", encoding="utf-8")
            swiftui = detect_project.detect(tmp)
            self.assertEqual(swiftui["framework"], "swiftui")
            self.assertEqual(swiftui["platforms"], ["swiftui"])

    def test_pubspec_needs_flutter_sdk_under_a_dependency_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pubspec = root / "pubspec.yaml"
            pubspec.write_text(
                "name: sample\ndescription: mentions Flutter in documentation\ndependencies:\n  http: ^1.0.0\n",
                encoding="utf-8",
            )
            generic = detect_project.detect(tmp)
            self.assertIsNone(generic["framework"])
            self.assertEqual(generic["platforms"], [])

            pubspec.write_text(
                "name: sample\ndependencies:\n  http: ^1.0.0\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n",
                encoding="utf-8",
            )
            flutter = detect_project.detect(tmp)
            self.assertEqual(flutter["framework"], "flutter")
            self.assertEqual(flutter["platforms"], ["flutter"])

    def test_workspace_keeps_manifest_candidates_and_nested_project_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_json(root / "package.json", {
                "private": True,
                "workspaces": ["apps/*"],
                "devDependencies": {"typescript": "^5.0.0", "react": "19.0.0"},
            })
            self.write_json(root / "apps" / "web" / "package.json", {
                "dependencies": {"next": "16.0.0", "react": "19.0.0", "antd-mobile": "^5.0.0"},
            })
            self.write_json(root / "apps" / "mobile" / "package.json", {
                "dependencies": {"expo": "~54.0.0", "react": "19.1.0", "react-native": "0.81.0"},
            })
            ios = root / "apps" / "ios"
            (ios / "Package.swift").parent.mkdir(parents=True)
            (ios / "Package.swift").write_text("// Swift package\n", encoding="utf-8")
            (ios / "App.swift").write_text("import SwiftUI\n", encoding="utf-8")

            # These declarations are generated/vendor content and must not leak into the inventory.
            self.write_json(root / "node_modules" / "fake" / "package.json", {"dependencies": {"react-native": "1.0"}})
            self.write_json(root / "apps" / "web" / ".next" / "package.json", {"dependencies": {"vue": "1.0"}})
            self.write_json(root / "build" / "fake" / "package.json", {"dependencies": {"expo": "1.0"}})
            try:
                (root / "linked-mobile").symlink_to(root / "apps" / "mobile", target_is_directory=True)
            except OSError:
                pass  # Some Windows test environments do not permit creating directory symlinks.

            result = detect_project.detect(tmp)

            self.assertEqual(result["framework"], "react")
            self.assertEqual(result["platforms"], ["react-native", "swiftui", "web"])
            self.assertEqual(result["componentLibraries"], ["antd-mobile"])
            self.assertEqual([project["path"] for project in result["projects"]], [
                ".", "apps/ios", "apps/mobile", "apps/web",
            ])
            self.assertEqual([project["framework"] for project in result["projects"]], [
                "react", "swiftui", "expo", "next",
            ])

    def test_nonexistent_directory_raises_a_clear_filesystem_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-project"
            with self.assertRaises(FileNotFoundError):
                detect_project.detect(str(missing))


if __name__ == "__main__":
    unittest.main()
