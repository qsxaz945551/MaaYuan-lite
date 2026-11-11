from __future__ import annotations

import json
import unittest
from pathlib import Path

from lite.apply_scope import apply_scope


ROOT = Path(__file__).resolve().parents[2]


class ScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = json.loads((ROOT / "lite" / "scope.json").read_text(encoding="utf-8"))
        cls.interface = json.loads(
            (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig")
        )
        cls.overrides = json.loads(
            (ROOT / "lite" / "pipeline-overrides.json").read_text(encoding="utf-8")
        )

    def test_excluded_tasks_are_absent(self):
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        names = {task["name"] for task in lite["task"]}
        for item in self.scope["tasks"]["exclude"]:
            self.assertNotIn(item["name"], names)
        self.assertEqual(report["source_task_count"] - report["excluded_task_count"], len(names))

    def test_removed_tasks_stay_out(self):
        """2026-11-08 用户要求把这几项从其他任务里彻底删掉。"""
        lite, _report = apply_scope(self.interface, self.scope, self.overrides)
        names = {task["name"] for task in lite["task"]}
        self.assertNotIn("🏰 邺城之战V3", names)
        self.assertNotIn("💤 关闭游戏", names)
        self.assertNotIn("🏴 朝歌之战V2", names)

    def test_orphan_options_are_pruned(self):
        """任务删掉后，只被它引用的选项组也不该留在生成物里。"""
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        self.assertNotIn("邺城-刷哪层", lite["option"])
        self.assertNotIn("选择要购买的商品", lite["option"])
        self.assertFalse([key for key in lite["option"] if key.startswith("朝歌-")])
        self.assertGreater(report["pruned_option_count"], 0)
        # 保留任务的选项必须还在
        self.assertIn("修为历练级别", lite["option"])

    def test_no_zhaoge_left_in_lite_config(self):
        """2026-11-08 精简：朝歌相关的默认配置、隐藏项也不能留。"""
        for relative in (
            "lite/task-options.json",
            "lite/daily-profile.json",
            "runtime/task-options.json",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("朝歌", text, relative)

    def test_en_guard_only_runs_rec(self):
        """en 模型没有 det.onnx，据点的「无行囊check」必须只跑 rec，否则 ocrer_ 为空。

        2026-11-10：该节点是唯一未开 only_rec 的 en 节点，守卫因此永久失效。
        覆盖写在 pipeline-overrides.json，上游 assets 保持原样。
        """
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        task = next(t for t in lite["task"] if t["name"] == "🏯 据点日常")
        node = task["pipeline_override"]["无行囊check"]
        self.assertTrue(node["recognition"]["param"]["only_rec"])

        # 上游资源不能改：base 节点仍是 det+rec
        raw = json.loads(
            (ROOT / "assets/resource/base/pipeline/daily/base-events.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("only_rec", raw["无行囊check"]["recognition"]["param"])

        # 覆盖要在报告里留痕，便于审计
        self.assertTrue(
            any(
                item["task"] == "🏯 据点日常" and "无行囊check" in item["nodes"]
                for item in report["pipeline_overrides"]
            )
        )

    def test_house_interact_clicks_cabinet(self):
        """家具互动：上游点 [538,505]（床）会落在躺床的心纸君身上，改点矮柜 (360,404)。

        2026-11-10 实测：点矮柜后 interact.png 命中 0.9892；点床命中 0.9431 但角色躺床上时失效。
        覆盖只改 action.target，Click 类型与其余参数由框架继承原节点。
        """
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        task = next(t for t in lite["task"] if t["name"] == "🔶 日常收尾")
        node = task["pipeline_override"]["开始家具互动"]
        self.assertEqual(node["action"]["param"]["target"], [344, 388, 32, 32])
        self.assertNotIn("recognition", node)

        # 上游资源不能改：base 节点仍是点床
        raw = json.loads(
            (ROOT / "assets/resource/base/pipeline/daily/house.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            raw["开始家具互动"]["action"]["param"]["target"], [538, 505, 58, 57]
        )

        self.assertTrue(
            any(
                item["task"] == "🔶 日常收尾" and "开始家具互动" in item["nodes"]
                for item in report["pipeline_overrides"]
            )
        )

    def test_monthly_shop_clicks_tab_body(self):
        """月卡商店 20 体：模板自带红点，随机取点会落到角标上，需固定点标签本体。

        2026-11-11：模板命中 [480,227,68,58]，随机点落在 (531,232) 的红点，
        标签页没切换，随后「免费」按钮识别到的是商城价格「6元40元」。
        """
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        task = next(t for t in lite["task"] if t["name"] == "💰 领月卡福利")
        node = task["pipeline_override"]["领月卡商店20体"]
        self.assertEqual(node["action"]["param"]["target"], [500, 250, 30, 24])
        self.assertNotIn("recognition", node)

        # 红点在 y 220–242，覆盖区必须完全避开
        _, y, _, h = node["action"]["param"]["target"]
        self.assertGreaterEqual(y, 243)
        self.assertGreater(h, 0)

        # 上游资源不能改：base 节点仍是空 param（随机点）
        raw = json.loads(
            (ROOT / "assets/resource/base/pipeline/daily/subscription.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(raw["领月卡商店20体"]["action"]["param"], {})

        self.assertTrue(
            any(
                item["task"] == "💰 领月卡福利" and "领月卡商店20体" in item["nodes"]
                for item in report["pipeline_overrides"]
            )
        )

    def test_ocr_quantization_is_forbidden(self):
        self.assertEqual(
            self.scope["constraints"]["ocr_model_quantization"], "forbidden"
        )


if __name__ == "__main__":
    unittest.main()
