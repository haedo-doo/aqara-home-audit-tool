# -*- coding: utf-8 -*-
"""
分析任意 dump XML，找出"可能的菜单项"模式
用法：python inspect_xml.py <path_to_xml>
"""
import sys
from pathlib import Path
from lxml import etree
from collections import Counter

APP_PACKAGE = "com.lumiunited.aqarahome.play"

if len(sys.argv) < 2:
    print("Usage: python inspect_xml.py <xml_file>")
    sys.exit(1)

xml = Path(sys.argv[1]).read_text(encoding="utf-8")
root = etree.fromstring(xml.encode("utf-8"))

# 1) 统计：所有"可点击 + 内含文本"的容器，按 resource-id 分组
rid_stats = Counter()
samples = {}

for node in root.iter("node"):
    if node.get("clickable") != "true":
        continue
    if node.get("package") != APP_PACKAGE:
        continue
    inner_texts = []
    for c in node.iter("node"):
        t = (c.get("text") or "").strip()
        d = (c.get("content-desc") or "").strip()
        if t: inner_texts.append(t)
        elif d: inner_texts.append(f"[d]{d}")
    if not inner_texts:
        continue

    rid = node.get("resource-id", "") or "(no-id)"
    rid_short = rid.split(":")[-1] if ":" in rid else rid
    cls = node.get("class", "").split(".")[-1]
    key = f"[{cls}] {rid_short}"
    rid_stats[key] += 1
    samples.setdefault(key, []).append(inner_texts)

print("=" * 70)
print("Clickable containers with text (count + resource-id pattern):")
print("=" * 70)
for key, count in rid_stats.most_common():
    print(f"\n  {count}x  {key}")
    for s in samples[key][:3]:
        print(f"      └─ {' | '.join(s[:4])}")