"""Phase 3 三语对齐:把 ko / zh / en 三个 scan run 按 device_name + 菜单 path 位置对齐,
产出"每个韩文 text 的中英基线"映射,供 phase3_audit_proto.py 在 AI prompt 里塞 context。

策略 A — 按 device_name 匹配设备,按 (tree_index, item_index, text_index) 对齐文本:
  - 适用前提:3 语言下同设备的菜单**顺序一致**(用户已确认)
  - 对齐失败时(item 数量不匹配 / device 缺失) → baseline=None,fallback ko-only

不实施模糊匹配 — 简单优先,出问题再加。

用法(作为模块):
    from phase3_align_locales import build_baselines, collect_user_device_names
    bl = build_baselines("output/.../ko_run", "output/.../zh_run", "output/.../en_run")
    # bl["재실 센서 FP2"]["AI 사람 감지"]["zh"] = ["AI 人形检测"]
    # bl["재실 센서 FP2"]["AI 사람 감지"]["en"] = ["AI Person Detection"]

用法(独立 debug):
    python phase3_align_locales.py <ko_run> <zh_run> <en_run>
    → 打印对齐摘要 + 写 aligned_baselines.json 到 ko_run 目录
"""
import json
import sys
from pathlib import Path
from datetime import datetime


def _load_run(run_dir: Path):
    """读 run dir 的 all_devices_result.json 或 traverse_result.json,返回 devices list。"""
    if run_dir is None:
        return []
    if not isinstance(run_dir, Path):
        run_dir = Path(run_dir)
    multi = run_dir / "all_devices_result.json"
    single = run_dir / "traverse_result.json"
    if multi.exists():
        data = json.loads(multi.read_text(encoding="utf-8"))
        return data.get("devices", [])
    if single.exists():
        return [json.loads(single.read_text(encoding="utf-8"))]
    print(f"[align] WARN: no traverse JSON in {run_dir}", flush=True)
    return []


def _gather_positions(device):
    """遍历 device 的 trees,产 (position_key, text) 列表。
    position_key 形如 ('tree', N, 'pt', M) 或 ('tree', N, 'item', I, 'app', K)。"""
    out = []
    for ti, tree in enumerate(device.get("trees", [])):
        for pti, pt in enumerate(tree.get("page_texts", [])):
            t = (pt.get("text") or pt.get("content_desc") or "").strip()
            if t:
                out.append((("tree", ti, "pt", pti), t))
        for ii, item in enumerate(tree.get("items", [])):
            for ci, c in enumerate(item.get("all_texts_on_card") or item.get("texts") or []):
                if isinstance(c, str) and c.strip():
                    out.append((("tree", ti, "item", ii, "card", ci), c.strip()))
            for ai, at in enumerate(item.get("app_texts", [])):
                t = (at.get("text") or at.get("content_desc") or "").strip()
                if t:
                    out.append((("tree", ti, "item", ii, "app", ai), t))
    return out


def _get_at(device, pos):
    """按 position key 在另一 locale 的 device 查同位置 text。失败返 None。"""
    if not device:
        return None
    try:
        if pos[0] != "tree":
            return None
        ti = pos[1]
        trees = device.get("trees", [])
        if ti >= len(trees):
            return None
        tree = trees[ti]
        if pos[2] == "pt":
            pti = pos[3]
            pts = tree.get("page_texts", [])
            if pti >= len(pts):
                return None
            return (pts[pti].get("text") or pts[pti].get("content_desc") or "").strip() or None
        if pos[2] == "item":
            ii, kind, si = pos[3], pos[4], pos[5]
            items = tree.get("items", [])
            if ii >= len(items):
                return None
            item = items[ii]
            if kind == "card":
                cards = item.get("all_texts_on_card") or item.get("texts") or []
                if si >= len(cards):
                    return None
                t = cards[si]
                return t.strip() if isinstance(t, str) and t.strip() else None
            if kind == "app":
                apps = item.get("app_texts", [])
                if si >= len(apps):
                    return None
                return (apps[si].get("text") or apps[si].get("content_desc") or "").strip() or None
    except Exception:
        pass
    return None


def _build_device_baselines(ko_dev, zh_dev, en_dev):
    """单设备:返回 {ko_text -> {zh: [str,...], en: [str,...]}}。
    same-as-ko 的 baseline 不记(无信息量)。"""
    bl = {}
    for pos, ko_text in _gather_positions(ko_dev):
        zh_text = _get_at(zh_dev, pos)
        en_text = _get_at(en_dev, pos)
        if ko_text not in bl:
            bl[ko_text] = {"zh": [], "en": []}
        if zh_text and zh_text != ko_text and zh_text not in bl[ko_text]["zh"]:
            bl[ko_text]["zh"].append(zh_text)
        if en_text and en_text != ko_text and en_text not in bl[ko_text]["en"]:
            bl[ko_text]["en"].append(en_text)
    # 去掉 zh/en 都空的(没意义,等于 ko_only)
    return {k: v for k, v in bl.items() if v["zh"] or v["en"]}


def build_baselines(ko_run, zh_run=None, en_run=None):
    """主入口:对齐 3 个 run,返回:
        {
          "user_device_names":     {name: locale_observed},  # 用于 ALLOWED_DEVICE_NAMES
          "devices": {
            device_name: {
              "baseline_status": "full|ko_zh|ko_en|ko_only",
              "baselines": {ko_text: {"zh": [...], "en": [...]}}
            },
            ...
          },
        }
    """
    ko_devs = _load_run(Path(ko_run)) if ko_run else []
    zh_devs = _load_run(Path(zh_run)) if zh_run else []
    en_devs = _load_run(Path(en_run)) if en_run else []

    by_name_zh = {d.get("device_name", ""): d for d in zh_devs if d.get("device_name") and not d.get("error")}
    by_name_en = {d.get("device_name", ""): d for d in en_devs if d.get("device_name") and not d.get("error")}

    out_devices = {}
    user_names = set()
    for d in ko_devs:
        name = d.get("device_name", "")
        if not name or d.get("error"):
            continue
        user_names.add(name)
        zh_d = by_name_zh.get(name)
        en_d = by_name_en.get(name)
        bl = _build_device_baselines(d, zh_d, en_d)
        has_zh = any(v["zh"] for v in bl.values())
        has_en = any(v["en"] for v in bl.values())
        if has_zh and has_en:
            status = "full"
        elif has_zh:
            status = "ko_zh"
        elif has_en:
            status = "ko_en"
        else:
            status = "ko_only"
        out_devices[name] = {
            "baseline_status": status,
            "zh_available": zh_d is not None,
            "en_available": en_d is not None,
            "baselines": bl,
        }

    # 用户设备名汇总(也含 zh/en run 里出现的,以防 ko 漏了某台)
    for d in zh_devs + en_devs:
        n = d.get("device_name", "")
        if n and not d.get("error"):
            user_names.add(n)

    return {
        "generated_at": datetime.now().isoformat(),
        "ko_run": str(ko_run) if ko_run else None,
        "zh_run": str(zh_run) if zh_run else None,
        "en_run": str(en_run) if en_run else None,
        "user_device_names": sorted(user_names),
        "devices": out_devices,
    }


def collect_user_device_names(*run_dirs):
    """便利函数:从 1+ 个 run dir 抓所有 device_name(用作 ALLOWED set)。"""
    names = set()
    for r in run_dirs:
        for d in _load_run(Path(r)):
            n = d.get("device_name", "")
            if n and not d.get("error"):
                names.add(n)
    return names


def baselines_for_text(aligned, device_name, text):
    """便利查询:某设备某 ko 文本的 baseline。返 {zh: [...], en: [...]} 或 None。"""
    if not aligned:
        return None
    dev = aligned.get("devices", {}).get(device_name)
    if not dev:
        return None
    return dev.get("baselines", {}).get(text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python phase3_align_locales.py <ko_run> [<zh_run>] [<en_run>]")
        sys.exit(1)
    ko, zh, en = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None), (sys.argv[3] if len(sys.argv) > 3 else None)
    result = build_baselines(ko, zh, en)
    # 写 aligned_baselines.json 到 ko run dir
    out_path = Path(ko) / "aligned_baselines.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written: {out_path}")
    print(f"\nSummary:")
    print(f"  ko_run: {ko}")
    print(f"  zh_run: {zh}")
    print(f"  en_run: {en}")
    print(f"  user_device_names: {len(result['user_device_names'])}")
    print(f"  devices aligned: {len(result['devices'])}")
    statuses = {"full": 0, "ko_zh": 0, "ko_en": 0, "ko_only": 0}
    for d in result["devices"].values():
        statuses[d["baseline_status"]] += 1
    print(f"  by status: {statuses}")
    # Sample
    print(f"\nSample (first 3 entries from first device):")
    for dn, dd in list(result["devices"].items())[:1]:
        print(f"  {dn} ({dd['baseline_status']})")
        for k, v in list(dd["baselines"].items())[:3]:
            print(f"    ko: '{k}'")
            print(f"      zh: {v['zh']}")
            print(f"      en: {v['en']}")
