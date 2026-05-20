# -*- coding: utf-8 -*-
"""
探针脚本：传入一个 resource-id，自动点击并 dump 点击后的画面
用途：验证点击链路，并抓取弹出菜单/新页面的元素信息
"""
import uiautomator2 as u2
import json
import time
import sys
from datetime import datetime
from pathlib import Path
from lxml import etree

# ===== 修改这里：要点击的目标元素的 resource-id =====
TARGET_RESOURCE_ID = "com.lumiunited.aqarahome.play:id/layout_title_right"

OUTPUT_DIR = Path("./output") / ("probe_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_texts(xml_str):
    """从 XML 字符串提取所有有文本的元素"""
    root = etree.fromstring(xml_str.encode("utf-8"))
    items = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        if not text and not desc:
            continue
        items.append({
            "text": text,
            "content_desc": desc,
            "class": node.get("class", "").split(".")[-1],
            "resource_id": node.get("resource-id", ""),
            "bounds": node.get("bounds", ""),
            "clickable": node.get("clickable", "false"),
        })
    return items


def main():
    device = u2.connect()
    print(f"[INFO] 连接成功：{device.app_current()}")

    # 1) 点击前先截图存档（用于事后比对）
    device.screenshot(str(OUTPUT_DIR / "before.png"))
    print("[OK] 已保存点击前截图：before.png")

    # 2) 点击目标元素
    target = device(resourceId=TARGET_RESOURCE_ID)
    if not target.exists:
        print(f"[FAIL] 没找到 resource-id={TARGET_RESOURCE_ID} 的元素")
        print("       请确认手机上当前页面是否还停留在设备详情页")
        sys.exit(1)

    print(f"[INFO] 找到目标元素，准备点击...")
    target.click()

    # 3) 等待 UI 响应（弹窗动画/页面切换）
    time.sleep(1.5)

    # 4) 点击后截图 + dump
    device.screenshot(str(OUTPUT_DIR / "after.png"))
    print("[OK] 已保存点击后截图：after.png")

    xml_str = device.dump_hierarchy()
    (OUTPUT_DIR / "after_dump.xml").write_text(xml_str, encoding="utf-8")

    items = extract_texts(xml_str)
    (OUTPUT_DIR / "after_items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 5) 打印当前画面所有可点元素的概览（重点关注）
    print(f"\n[OK] 点击后 dump 到 {len(items)} 个含文本元素")
    print("=" * 70)
    print("可点击文本元素（最重要，包含菜单项）：")
    print("=" * 70)
    clickables = [x for x in items if x["clickable"] == "true"]
    for i, el in enumerate(clickables, 1):
        display = el["text"] if el["text"] else f"[desc] {el['content_desc']}"
        rid = el["resource_id"].split(":")[-1] if el["resource_id"] else "(no-id)"
        print(f"{i:2d}. [{el['class']}] [{rid}] {display}")

    print("=" * 70)
    print(f"完整结果：{OUTPUT_DIR.absolute()}")
    print("\n请检查 after.png 看弹窗是否如期出现，并把上面带 '설정' 字样")
    print("的那一行的完整信息告诉我（特别是 resource_id 和 class）")


if __name__ == "__main__":
    main()