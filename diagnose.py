# -*- coding: utf-8 -*-
import sys
print("[1] Python 版本:", sys.version, flush=True)
print("[2] 开始 import uiautomator2...", flush=True)
import uiautomator2 as u2
print("[3] uiautomator2 导入成功", flush=True)

print("[4] 开始连接设备...", flush=True)
d = u2.connect()
print("[5] 设备连接成功:", d.app_current(), flush=True)

print("[6] 开始 dump_hierarchy...", flush=True)
xml = d.dump_hierarchy()
print(f"[7] dump 成功，XML 长度: {len(xml)}", flush=True)

print("[OK] 全部正常", flush=True)