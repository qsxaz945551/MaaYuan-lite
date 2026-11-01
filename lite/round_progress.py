"""Progress markers for tasks that loop until stopped.

These tasks never "finish" in the usual sense, so the console logs one line
per completed round instead.  A round is marked by a pipeline node that the
upstream pipeline already reaches once per iteration:

* 6-24 farming  -> 战斗结束 (one battle)
* 邺城之战       -> 邺城事件-结算 (one run settled)
* 鸢报四合一     -> the per-category end node (four categories)

Add an entry here if another loop task should report progress; the runner
only watches node names, so no pipeline change is needed.
"""

from __future__ import annotations


ROUND_MARKERS: dict[str, dict[str, str]] = {
    "start_6-24": {
        "战斗结束": "战斗",
    },
    "邺城刷取": {
        "邺城事件-结算": "攻取结算",
    },
    "鸟食大礼包启动": {
        "end_当前没有突发情报": "突发情况",
        "end_小道消息循环开关": "小道消息",
        "end_是否继续他的传闻": "他的传闻",
        "end_当前没有可办公务": "待办公务",
    },
}


def marker_labels(entry: str) -> dict[str, str]:
    return ROUND_MARKERS.get(entry, {})
