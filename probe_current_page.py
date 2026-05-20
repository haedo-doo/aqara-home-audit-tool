# -*- coding: utf-8 -*-
"""探针：dump 当前页面所有可点击元素 + 含 settings 类关键词的任意元素"""
import uiautomator2 as u2
import json
from datetime import datetime
from pathlib import Path
from lxml import etree

APP_PACKAGE = "com.lumiunited.aqarahome.play"
OUTPUT = Path("./output") / ("probe_page_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
OUTPUT.mkdir(parents=True, exist_ok=True)

device = u2.connect()
print(f"[INFO] activity: {device.app_current()}", flush=True)

xml = device.dump_hierarchy()
(OUTPUT / "page.xml").write_text(xml, encoding="utf-8")
device.screenshot(str(OUTPUT / "page.png"))

root = etree.fromstring(xml.encode("utf-8"))
clickables, settings_hints = [], []

for node in root.iter("node"):
    if node.get("package") != APP_PACKAGE:
        continue
    text = (node.get("text") or "").strip()
    desc = (node.get("content-desc") or "").strip()
    rid = node.get("resource-id", "") or ""
    cls = (node.get("class") or "").split(".")[-1]
    bounds = node.get("bounds", "")
    clickable = node.get("clickable", "false") == "true"

    info = {
        "class": cls,
        "rid": rid.split(":")[-1] if rid else "",
        "text": text, "desc": desc,
        "bounds": bounds, "clickable": clickable,
    }
    if clickable:
        clickables.append(info)
    # 顺手扫含 settings 类关键词的任意元素（哪怕不可点）
    blob = (text + " " + desc + " " + rid).lower()
    for kw in ["설정", "setting", "더보기", "more", "menu", "메뉴", "옵션", "option"]:
        if kw in blob.lower() or kw in (text + desc):
            settings_hints.append(info)
            break

(OUTPUT / "clickables.json").write_text(
    json.dumps(clickables, ensure_ascii=False, indent=2), encoding="utf-8")
(OUTPUT / "settings_hints.json").write_text(
    json.dumps(settings_hints, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n[OK] {len(clickables)} clickables, {len(settings_hints)} settings-like hints", flush=True)
print("\n=== TOP-AREA CLICKABLES (likely header buttons) ===", flush=True)
# 顶部区域（y < 250）的可点元素，最可能是标题栏按钮
import re
for c in clickables:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", c["bounds"])
    if not m: continue
    y1 = int(m.group(2))
    if y1 < 250:
        rid_s = f" id={c['rid']}" if c['rid'] else ""
        text_s = f" text='{c['text']}'" if c['text'] else ""
        desc_s = f" desc='{c['desc']}'" if c['desc'] else ""
        print(f"  [{c['class']}]{rid_s}{text_s}{desc_s} bounds={c['bounds']}", flush=True)

print("\n=== SETTINGS-LIKE HINTS ===", flush=True)
for h in settings_hints[:10]:
    rid_s = f" id={h['rid']}" if h['rid'] else ""
    text_s = f" text='{h['text']}'" if h['text'] else ""
    desc_s = f" desc='{h['desc']}'" if h['desc'] else ""
    print(f"  [{h['class']}]{rid_s}{text_s}{desc_s} clickable={h['clickable']}", flush=True)