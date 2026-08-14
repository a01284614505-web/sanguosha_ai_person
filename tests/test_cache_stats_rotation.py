#!/usr/bin/env python3
"""缓存统计日志轮转测试（R8）。

覆盖 AIDecision._rotate_cache_stats_if_needed：
- 低于阈值不轮转
- 达到阈值时归档为带可排序时间戳的同名文件，并返回主文件状态
"""

import os
import tempfile
import unittest


from game_engine.ai_decision import AIDecision


def make_ai(stats_dir: str):
    ai = object.__new__(AIDecision)
    ai.cache_stats_path = os.path.join(stats_dir, "ai_cache_stats.jsonl")
    ai.CACHE_STATS_MAX_BYTES = 128
    return ai


def write_main_content(path: str, n: int):
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n):
            f.write("0123456789" + "\n")


class CacheStatsRotationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ai = make_ai(self._tmp.name)
        self.main = self.ai.cache_stats_path

    def test_below_threshold_does_not_rotate(self):
        write_main_content(self.main, 10)  # ~110 字节 < 128
        self.ai._rotate_cache_stats_if_needed()
        self.assertTrue(os.path.exists(self.main))
        self.assertEqual(
            [p for p in os.listdir(self._tmp.name) if p.startswith("ai_cache_stats")],
            ["ai_cache_stats.jsonl"],
            "低于阈值时不得生成归档，只能有主文件",
        )
        print("R8: 低于阈值不轮转 OK")

    def test_at_threshold_rotates_to_timestamped_archive(self):
        write_main_content(self.main, 13)  # ~143 字节 >= 128
        self.ai._rotate_cache_stats_if_needed()
        self.assertFalse(
            os.path.exists(self.main), "达到阈值后主文件应被归档走，原路径不再存在"
        )
        archives = sorted(
            p for p in os.listdir(self._tmp.name)
            if p.startswith("ai_cache_stats") and p != "ai_cache_stats.jsonl"
        )
        self.assertEqual(len(archives), 1)
        # 归档名必须可排序（YYYYMMDD_HHMMSS 伪时间戳），且整体按名字排序稳定。
        stamped = archives[0][len("ai_cache_stats."):len("ai_cache_stats.") + 15]
        self.assertTrue(stamped.replace("_", "").isdigit(), f"归档名时间戳部分不可排序: {archives[0]}")
        self.assertEqual(sorted(archives), archives)
        print(f"R8: 达到阈值轮转，归档 {archives[0]} OK")

    def test_after_rotation_record_goes_to_new_main_file(self):
        write_main_content(self.main, 13)
        self.ai._rotate_cache_stats_if_needed()
        content = "{\"kind\":\"decision\"}\n"
        with open(self.main, "a", encoding="utf-8") as f:
            f.write(content)
        self.assertTrue(os.path.exists(self.main))
        self.assertRegex(
            open(self.main, encoding="utf-8").read(), r"\{\"kind\":\"decision\"\}",
            "轮转后本次记录应写入新的主文件，而非归档",
        )
        print("R8: 轮转后新主文件可继续追加 OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
