import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import runtime_config
from crawlers.douyin.web.web_crawler import DouyinWebCrawler


class DouyinCookiePrecedenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_web_cookie_takes_precedence_in_crawler_headers(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_path = Path(temporary_directory)
            douyin_config_path = base_path / "douyin.yaml"
            runtime_config_path = base_path / "var" / "runtime_config.json"
            douyin_config_path.write_text(
                "TokenManager:\n"
                "  douyin:\n"
                "    headers:\n"
                "      Cookie: yaml-cookie\n",
                encoding="utf-8",
            )

            with (
                patch.object(runtime_config, "DOUYIN_CONFIG_PATH", douyin_config_path),
                patch.object(runtime_config, "RUNTIME_CONFIG_PATH", runtime_config_path),
            ):
                crawler = DouyinWebCrawler()
                fallback_headers = await crawler.get_douyin_headers()
                self.assertEqual(fallback_headers["headers"]["Cookie"], "yaml-cookie")

                runtime_config.set_douyin_cookie("runtime-cookie")
                runtime_headers = await crawler.get_douyin_headers()
                self.assertEqual(runtime_headers["headers"]["Cookie"], "runtime-cookie")


if __name__ == "__main__":
    unittest.main()
