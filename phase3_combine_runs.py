"""合并多个 scan run dir 成一个统一的多设备 dir。
用于:
  - 加新设备到老的批扫数据(避免重新扫 27 台)
  - 单独重扫某台设备后,replace 老数据(用于验证修改)

输入:
  --base <dir>:基础 multi-device run dir(必须有 all_devices_result.json)
  --add <dir>:单设备 run dir(必须有 traverse_result.json),可重复
                如果 device_name 已存在于 base → **替换**(用于复查重扫)
                否则 → 追加
  --out <dir>:输出目录

输出 dir 结构:
  - all_devices_result.json:合并后的 N 设备 entry
  - <device_safe>_main.png/.xml + <device_safe>_settings.png/.xml(新设备 + 复查设备)
  - <device_safe>_<path>.png/.xml(新设备的 sub-page captures,prefix 防冲突)
  - 老 base 的 PNG/XML 原样保留

用法:
  python phase3_combine_runs.py \
    --base output/traverse_v8_20260514_124723/ \
    --add output/traverse_v8_20260520_125403/ \
    --add output/traverse_v8_20260520_161245/ \
    --out output/combined_20260521/

下一步:
  python phase3_audit_proto.py output/combined_20260521/ \
    --reuse-findings output/traverse_v8_20260514_124723/findings.json
  python phase3_build_viewer.py output/combined_20260521/
"""
import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


def safe_name(s):
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s)
    return re.sub(r"_+", "_", s).strip("_")[:60] or "unnamed"


def _extract_device_name(single_data, add_dir):
    """从 single-device traverse_result.json 抽 device_name(phase2 single 不主动写这字段)。
    fallback:device_main tree 的 page_texts 第一条非数字非空文本。"""
    if single_data.get("device_name"):
        return single_data["device_name"]
    for tree in single_data.get("trees", []):
        if tree.get("label") == "device_main":
            for pt in tree.get("page_texts", [])[:5]:
                t = (pt.get("text") or "").strip()
                if t and len(t) > 2 and not t.replace(":", "").replace(".", "").isdigit():
                    return t
            break
    return add_dir.name


def combine(base_dir: Path, add_dirs: list, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # === 1. Read base ===
    base_json_path = base_dir / "all_devices_result.json"
    if not base_json_path.exists():
        raise SystemExit(f"--base must contain all_devices_result.json: {base_json_path}")
    base_data = json.loads(base_json_path.read_text(encoding="utf-8"))
    devices = list(base_data.get("devices", []))
    print(f"[base] {base_dir.name} — {len(devices)} devices")

    # === 2. Copy base PNG/XML files as-is ===
    print(f"[copy] base PNG/XML files...")
    copied_base = 0
    for f in base_dir.iterdir():
        if not f.is_file(): continue
        if f.suffix not in (".png", ".xml"): continue
        if f.name == "phase_b_nav_failed.xml" or f.name == "phase_b_nav_failed.png": continue
        if f.name.startswith("phase_b_empty"): continue
        shutil.copy2(f, out_dir / f.name)
        copied_base += 1
    print(f"  copied {copied_base} base files")

    # === 3. For each --add, integrate device data (single OR multi) ===
    add_device_entries = []  # list of (device_entry, source_dir, file_rename_map)
    for add_path in add_dirs:
        add_dir = Path(add_path)
        multi_json = add_dir / "all_devices_result.json"
        single_json = add_dir / "traverse_result.json"
        if multi_json.exists():
            # Multi-device source — extract each device + its files
            md = json.loads(multi_json.read_text(encoding="utf-8"))
            for dev in md.get("devices", []):
                if dev.get("error") or not dev.get("trees"):
                    continue
                add_device_entries.append((dev, add_dir, None))  # files already device_safe-prefixed
        elif single_json.exists():
            single_data = json.loads(single_json.read_text(encoding="utf-8"))
            device_name = _extract_device_name(single_data, add_dir)
            device_entry = {
                "device_name": device_name,
                "scanned_at": single_data.get("captured_at"),
                "plugin_version": single_data.get("plugin_version"),
                "trees": single_data.get("trees", []),
            }
            add_device_entries.append((device_entry, add_dir, "single"))
        else:
            print(f"  ⚠ SKIP {add_dir} — no traverse JSON")

    for device_entry, add_dir, source_type in add_device_entries:
        device_name = device_entry.get("device_name", "")
        if not device_name:
            print(f"  ⚠ SKIP entry with no device_name in {add_dir}")
            continue
        device_safe = safe_name(device_name)

        # Replace or append
        existing_idx = None
        for i, d in enumerate(devices):
            if d.get("device_name") == device_name:
                existing_idx = i
                break

        if existing_idx is not None:
            # Replace — first delete old files with this device_safe prefix from out_dir
            old_safe = safe_name(devices[existing_idx].get("device_name", ""))
            removed = 0
            for f in list(out_dir.iterdir()):
                if not f.is_file(): continue
                if f.name.startswith(f"{old_safe}_") and f.suffix in (".png", ".xml"):
                    f.unlink()
                    removed += 1
            devices[existing_idx] = device_entry
            print(f"[add] REPLACE: {device_name} (cleared {removed} old files)")
        else:
            devices.append(device_entry)
            print(f"[add] APPEND: {device_name}")

        if source_type == "single":
            # Single-device source: rename top-level + prefix subpages
            rename_map = {
                "01_main_page.png": f"{device_safe}_main.png",
                "01_main_page.xml": f"{device_safe}_main.xml",
                "02_settings_page.png": f"{device_safe}_settings.png",
                "02_settings_page.xml": f"{device_safe}_settings.xml",
            }
            copied = 0
            for f in add_dir.iterdir():
                if not f.is_file(): continue
                if f.suffix not in (".png", ".xml"): continue
                if f.name in ("phase_b_nav_failed.xml", "phase_b_nav_failed.png"): continue
                if f.name.startswith("phase_b_empty"): continue
                new_name = rename_map.get(f.name)
                if new_name is None:
                    new_name = f"{device_safe}_{f.name}"
                shutil.copy2(f, out_dir / new_name)
                copied += 1
            print(f"   copied {copied} files (renamed with prefix '{device_safe}_')")
        else:
            # Multi-device source: only files matching this device's safe_name prefix
            copied = 0
            for f in add_dir.iterdir():
                if not f.is_file(): continue
                if f.suffix not in (".png", ".xml"): continue
                if f.name in ("all_devices_result.json", "phase_b_nav_failed.xml",
                              "phase_b_nav_failed.png"): continue
                if f.name.startswith("phase_b_empty"): continue
                if f.name.startswith(f"{device_safe}_"):
                    shutil.copy2(f, out_dir / f.name)
                    copied += 1
            print(f"   copied {copied} files from multi-device source for '{device_name}'")

    # === 4. Write combined all_devices_result.json ===
    combined = {
        "captured_at": datetime.now().isoformat(),
        "_combined_from": [str(base_dir)] + [str(p) for p in add_dirs],
        "devices": devices,
    }
    out_json = out_dir / "all_devices_result.json"
    out_json.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Wrote {out_json} ({len(devices)} devices total)")

    return out_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="Base multi-device run dir")
    parser.add_argument("--add", action="append", default=[],
                        help="Single-device run dir (repeatable)")
    parser.add_argument("--out", required=True, help="Output combined dir")
    args = parser.parse_args()

    out_dir = combine(Path(args.base), args.add, Path(args.out))
    base_dir = Path(args.base)

    print(f"\n=== Next steps ===")
    print(f"1. Audit (reuse old findings, only AI on new devices):")
    print(f"   python phase3_audit_proto.py {out_dir} \\")
    print(f"     --reuse-findings {base_dir / 'findings.json'}")
    print(f"")
    print(f"2. Build viewer:")
    print(f"   python phase3_build_viewer.py {out_dir}")


if __name__ == "__main__":
    main()
