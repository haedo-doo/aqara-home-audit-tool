# -*- coding: utf-8 -*-
"""
设置页结构分析脚本：列出所有"可点击容器 + 容器内文本"的组合
这是 Phase 1 遍历的基础，可点击容器才是真正能 click 进入下一级的入口
"""
import uiautomator2 as u2
import json
from datetime import datetime
from pathlib import Path
from lxml import etree

OUTPUT_DIR = Path("./output") / ("settings_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    device = u2.connect()
    print(f"[INFO] 当前页面：{device.app_current()}")

    # 截图 + dump（在设置页操作前请确保手机已停留在设置页）
    device.screenshot(str(OUTPUT_DIR / "settings.png"))
    xml_str = device.dump_hierarchy()
    (OUTPUT_DIR / "settings_dump.xml").write_text(xml_str, encoding="utf-8")

    root = etree.fromstring(xml_str.encode("utf-8"))

    # 关键策略：找所有 clickable=true 的容器，并提取它们子树里的所有文本
    # 这模拟了一个"菜单项"的真实结构：可点容器 + 内部一个或多个 TextView
    menu_items = []
    for node in root.iter("node"):
        if node.get("clickable") != "true":
            continue

        # 收集该容器子树内所有有文本的节点
        inner_texts = []
        for child in node.iter("node"):
            text = (child.get("text") or "").strip()
            desc = (child.get("content-desc") or "").strip()
            if text:
                inner_texts.append(text)
            elif desc:
                inner_texts.append(f"[desc]{desc}")

        # 跳过完全没文字的可点元素（图标按钮先不管）
        if not inner_texts:
            continue

        menu_items.append({
            "container_class": node.get("class", "").split(".")[-1],
            "container_resource_id": node.get("resource-id", ""),
            "bounds": node.get("bounds", ""),
            "texts_inside": inner_texts,
            # 检查是否包含"开关"类危险元素，提前标记
            "has_switch_inside": any(
                "Switch" in (c.get("class") or "") or "CheckBox" in (c.get("class") or "")
                for c in node.iter("node")
            ),
        })

    (OUTPUT_DIR / "menu_items.json").write_text(
        json.dumps(menu_items, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 控制台展示
    print(f"\n[OK] 共发现 {len(menu_items)} 个可点击的菜单容器")
    print("=" * 70)
    for i, item in enumerate(menu_items, 1):
        rid = item["container_resource_id"].split(":")[-1] if item["container_resource_id"] else "(no-id)"
        switch_mark = " ⚠[含开关]" if item["has_switch_inside"] else ""
        texts_preview = " | ".join(item["texts_inside"][:3])
        print(f"{i:2d}. [{item['container_class']}] [{rid}] {texts_preview}{switch_mark}")
    print("=" * 70)
    print(f"\n详细结果：{OUTPUT_DIR.absolute()}\\menu_items.json")


if __name__ == "__main__":
    main()