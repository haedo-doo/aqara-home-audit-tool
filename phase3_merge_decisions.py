"""把 viewer 导出的 decisions JSON 合并到 corrections.json。
自动:
  - 按 `wrong` 文本去重(已存在的 entry 只更新 status,不重复添加)
  - 自动分配下一个 c001/i001 ID(prefix=c if status='pending', i if 'ignored')
  - 写入前备份 corrections.json → corrections.json.bak

用法:
  python phase3_merge_decisions.py decisions.json
  # 或粘贴 stdin:
  python phase3_merge_decisions.py -
"""
import json
import sys
import datetime
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).parent
CORRECTIONS_PATH = REPO_ROOT / "corrections.json"


def _next_id(prefix, existing_entries):
    """从已有 entries 找出 prefix 开头的最大编号 + 1。"""
    nums = []
    for c in existing_entries:
        cid = c.get("id", "")
        if cid.startswith(prefix) and cid[len(prefix):].isdigit():
            nums.append(int(cid[len(prefix):]))
    n = max(nums) + 1 if nums else 1
    return f"{prefix}{n:03d}"


def merge(decisions_data, dry_run=False):
    """主合并逻辑。decisions_data: list[dict] 或 dict with 'decisions' key。"""
    if isinstance(decisions_data, dict):
        new_decisions = decisions_data.get("decisions", [])
    else:
        new_decisions = decisions_data
    if not isinstance(new_decisions, list):
        raise SystemExit(f"Invalid decisions format — expected list, got {type(new_decisions).__name__}")

    # Load existing corrections.json(保留 _doc / _schema / _status_meaning 等顶层 metadata)
    if CORRECTIONS_PATH.exists():
        existing = json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))
    else:
        existing = {"corrections": []}
    if "corrections" not in existing:
        existing["corrections"] = []

    existing_by_wrong = {c["wrong"]: c for c in existing["corrections"] if c.get("wrong")}

    added, updated, skipped = 0, 0, 0
    for d in new_decisions:
        wrong = d.get("wrong")
        status = d.get("status", "pending")
        if not wrong:
            skipped += 1
            continue
        if status not in ("pending", "ignored", "verified", "regressed", "removed"):
            print(f"  ⚠ skip invalid status={status!r}: {wrong[:30]!r}", flush=True)
            skipped += 1
            continue

        if wrong in existing_by_wrong:
            ex = existing_by_wrong[wrong]
            old_status = ex.get("status")
            if old_status == status:
                # 完全一样 — 跳过
                skipped += 1
                continue
            # 只允许某些状态升级(防止意外覆盖已 verified 的)
            if old_status == "verified" and status in ("pending", "ignored"):
                print(f"  ⚠ refuse to downgrade '{wrong[:30]}' from verified → {status}", flush=True)
                skipped += 1
                continue
            ex["status"] = status
            if d.get("fix"):
                ex["fix"] = d["fix"]
            ex["updated_at"] = datetime.date.today().isoformat()
            updated += 1
        else:
            prefix = "i" if status == "ignored" else "c"
            new = {
                "id": _next_id(prefix, existing["corrections"]),
                "wrong": wrong,
                "fix": d.get("fix") or ("(legacy: keep as-is)" if status == "ignored" else "(no fix proposed)"),
                "device_hint": d.get("device_hint"),
                "path_hint": d.get("path_hint"),
                "submitted_at": d.get("submitted_at", datetime.date.today().isoformat()),
                "status": status,
            }
            existing["corrections"].append(new)
            existing_by_wrong[wrong] = new
            added += 1

    if dry_run:
        print(f"DRY-RUN: would add {added}, update {updated}, skip {skipped}")
        return existing

    # Backup
    if CORRECTIONS_PATH.exists():
        backup = CORRECTIONS_PATH.with_suffix(".json.bak")
        backup.write_text(CORRECTIONS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  Backup → {backup}")

    CORRECTIONS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ Merged into {CORRECTIONS_PATH.name}: +{added} added, {updated} updated, {skipped} skipped")
    print(f"  Total entries: {len(existing['corrections'])}")
    statuses = Counter(c.get("status", "?") for c in existing["corrections"])
    print(f"  By status: {dict(statuses)}")
    return existing


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args = [a for a in args if a != "--dry-run"]
    if not args:
        raise SystemExit("Usage: python phase3_merge_decisions.py <decisions.json> [--dry-run]\n"
                         "       python phase3_merge_decisions.py - [--dry-run]   # stdin")

    src = args[0]
    if src == "-":
        raw = sys.stdin.read()
    else:
        p = Path(src)
        if not p.exists():
            raise SystemExit(f"Not found: {p}")
        raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except Exception as e:
        raise SystemExit(f"Invalid JSON: {e}")
    merge(data, dry_run=dry_run)


if __name__ == "__main__":
    main()
