import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from app.api.endpoints import download
from app.api.task_queue import RateLimiter, Task


class DownloadSweepTest(unittest.TestCase):
    """downloadAll 收尾重试：首轮失败的作品会再跑一轮，恢复后计数和 details 同步更新。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = {}

    def tearDown(self):
        self.tmp.cleanup()

    async def fake_download_one(self, aweme_id, limiter, headers, with_watermark, video_folder, image_folder):
        n = self.calls[aweme_id] = self.calls.get(aweme_id, 0) + 1
        if aweme_id == "always_fail":
            return {"aweme_id": aweme_id, "status": "failed", "error": "HTTP状态错误: 403"}
        if aweme_id == "fail_then_ok" and n == 1:
            return {"aweme_id": aweme_id, "status": "failed", "error": "HTTP状态错误: 403"}
        if aweme_id == "skipped":
            return {"aweme_id": aweme_id, "type": "video", "status": "skipped"}
        return {"aweme_id": aweme_id, "type": "image" if aweme_id.startswith("img") else "video", "status": "success"}

    def run_task(self, ids):
        async def fake_get_all(share_url, before_request=None):
            return {"success": True, "user_info": {"nickname": "tester"}, "new_aweme_ids": ids}

        async def fake_headers():
            return {"headers": {}}

        task = Task(id="t1", kind="download_user_all",
                    params={"share_url": "https://www.douyin.com/user/x", "base_folder": self.tmp.name})
        crawler = download.HybridCrawler.DouyinWebCrawler
        with patch.object(crawler, "get_all_user_videos", fake_get_all), \
                patch.object(crawler, "get_douyin_headers", fake_headers), \
                patch.object(download, "_download_one", self.fake_download_one):
            return asyncio.run(download._run_user_download(task, RateLimiter(interval=0)))

    def test_failed_items_are_retried_once_and_counters_reconciled(self):
        stats = self.run_task(["ok1", "fail_then_ok", "always_fail", "img1", "skipped"])

        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["processed"], 5)
        self.assertEqual(stats["success"], 3)   # ok1, img1, fail_then_ok(恢复)
        self.assertEqual(stats["failed"], 1)    # always_fail
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["video_count"], 2)
        self.assertEqual(stats["image_count"], 1)
        self.assertEqual(stats["sweep"], {"total": 2, "recovered": 1})
        # 只有失败的作品才会被第二次调用
        self.assertEqual(self.calls, {"ok1": 1, "fail_then_ok": 2, "always_fail": 2, "img1": 1, "skipped": 1})
        # details 里的记录被替换且标记 retried，顺序不变
        by_id = {d["aweme_id"]: d for d in stats["details"]}
        self.assertEqual([d["aweme_id"] for d in stats["details"]], ["ok1", "fail_then_ok", "always_fail", "img1", "skipped"])
        self.assertEqual(by_id["fail_then_ok"]["status"], "success")
        self.assertTrue(by_id["fail_then_ok"]["retried"])
        self.assertEqual(by_id["always_fail"]["status"], "failed")
        self.assertTrue(os.path.exists(stats["stats_file"]))

    def test_no_sweep_when_nothing_failed(self):
        stats = self.run_task(["ok1", "img1"])
        self.assertNotIn("sweep", stats)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(self.calls, {"ok1": 1, "img1": 1})


if __name__ == "__main__":
    unittest.main()
