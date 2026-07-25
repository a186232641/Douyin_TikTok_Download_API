import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import runtime_config


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temporary_directory.name)
        self.root_config_path = self.base_path / "config.yaml"
        self.douyin_config_path = self.base_path / "douyin.yaml"
        self.runtime_config_path = self.base_path / "var" / "runtime_config.json"

        self.root_config_path.write_text(
            "Web:\n  Access_Password: yaml-password\n",
            encoding="utf-8",
        )
        self.douyin_config_path.write_text(
            "TokenManager:\n"
            "  douyin:\n"
            "    headers:\n"
            "      Cookie: yaml-cookie\n",
            encoding="utf-8",
        )

        self.path_patches = [
            patch.object(runtime_config, "ROOT_CONFIG_PATH", self.root_config_path),
            patch.object(runtime_config, "DOUYIN_CONFIG_PATH", self.douyin_config_path),
            patch.object(runtime_config, "RUNTIME_CONFIG_PATH", self.runtime_config_path),
        ]
        for path_patch in self.path_patches:
            path_patch.start()

    def tearDown(self):
        for path_patch in reversed(self.path_patches):
            path_patch.stop()
        self.temporary_directory.cleanup()

    def test_runtime_cookie_overrides_yaml_and_clear_restores_fallback(self):
        self.assertEqual(runtime_config.get_douyin_cookie(), "yaml-cookie")

        status = runtime_config.set_douyin_cookie("runtime-cookie")
        self.assertEqual(runtime_config.get_douyin_cookie(), "runtime-cookie")
        self.assertEqual(status["source"], "runtime")
        self.assertTrue(status["runtime_override"])

        status = runtime_config.clear_douyin_cookie()
        self.assertEqual(runtime_config.get_douyin_cookie(), "yaml-cookie")
        self.assertEqual(status["source"], "yaml")
        self.assertFalse(status["runtime_override"])

    def test_status_never_returns_complete_cookie(self):
        status = runtime_config.set_douyin_cookie("abcd-sensitive-cookie-wxyz")

        self.assertEqual(status["masked_preview"], "abcd...wxyz")
        self.assertNotIn("cookie", json.dumps(status))

    def test_password_uses_environment_before_yaml(self):
        with patch.dict(os.environ, {"WEB_ACCESS_PASSWORD": "environment-password"}):
            self.assertTrue(runtime_config.verify_access_password("environment-password"))
            self.assertFalse(runtime_config.verify_access_password("yaml-password"))

    def test_missing_password_fails_closed(self):
        self.root_config_path.write_text("Web:\n  Access_Password: ''\n", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WEB_ACCESS_PASSWORD", None)
            self.assertFalse(runtime_config.is_access_password_configured())
            self.assertFalse(runtime_config.verify_access_password(""))

    def test_cookie_rejects_empty_and_multiline_values(self):
        with self.assertRaises(ValueError):
            runtime_config.set_douyin_cookie(" ")
        with self.assertRaises(ValueError):
            runtime_config.set_douyin_cookie("first\nsecond")

    def test_invalid_runtime_cookie_structure_is_rejected(self):
        self.runtime_config_path.parent.mkdir(parents=True)
        self.runtime_config_path.write_text(
            '{"douyin": "invalid"}\n',
            encoding="utf-8",
        )

        with self.assertRaises(runtime_config.RuntimeConfigError):
            runtime_config.get_douyin_cookie()


if __name__ == "__main__":
    unittest.main()
