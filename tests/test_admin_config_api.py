import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import runtime_config
from app.api.endpoints import admin_config


class AdminConfigApiTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temporary_directory.name)
        self.root_config_path = self.base_path / "config.yaml"
        self.douyin_config_path = self.base_path / "douyin.yaml"
        self.runtime_config_path = self.base_path / "var" / "runtime_config.json"

        self.root_config_path.write_text(
            "Web:\n  Access_Password: api-password\n",
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

        app = FastAPI()
        app.include_router(admin_config.router, prefix="/api/admin/config")
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for path_patch in reversed(self.path_patches):
            path_patch.stop()
        self.temporary_directory.cleanup()

    def test_status_requires_password(self):
        response = self.client.get("/api/admin/config/douyin-cookie")
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/api/admin/config/douyin-cookie",
            headers={"X-Admin-Password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_update_status_and_clear_cookie(self):
        headers = {"X-Admin-Password": "api-password"}
        runtime_cookie = "abcd-runtime-cookie-wxyz"

        response = self.client.put(
            "/api/admin/config/douyin-cookie",
            headers=headers,
            json={"cookie": runtime_cookie},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "runtime")
        self.assertNotIn(runtime_cookie, response.text)

        response = self.client.get(
            "/api/admin/config/douyin-cookie",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["masked_preview"], "abcd...wxyz")
        self.assertNotIn(runtime_cookie, response.text)

        response = self.client.delete(
            "/api/admin/config/douyin-cookie",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "yaml")
        self.assertFalse(response.json()["runtime_override"])


if __name__ == "__main__":
    unittest.main()
