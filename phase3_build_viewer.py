"""Phase 3 viewer: 把单次扫描结果 + AI audit findings 渲染成自包含 split-view HTML。

支持两种 run dir 形态:
  - 单设备:traverse_result.json (+ findings.json 可选)
  - 多设备:all_devices_result.json (+ findings.json 可选,多设备 schema)

Layout:
  +---- header (overall: device count, summary) ----+
  | (multi only) tab bar: [P2] [M3] [浴霸] ...      |
  +-----------+--------------------------------------+
  | Findings  | Menu tree (per active device)        |
  | sidebar   | (with screenshots inline)            |
  +-----------+--------------------------------------+

用法:
  python phase3_build_viewer.py                       # 默认用最新 run
  python phase3_build_viewer.py output/traverse_v8_XXX/

输出:
  在 run 目录里生成 viewer.html(self-contained,直接 file:// 打开能用)。
"""
import json
import sys
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent
OUTPUT_ROOT = REPO_ROOT / "output"

PLUGIN_VERSION_PATTERN = re.compile(r"플러그인\s*버전\s*[:\s]\s*([\d][\d._]*)")
FIRMWARE_VERSION_PATTERN = re.compile(r"펌웨어\s*버전\s*[:\s]\s*([\d][\d._]*)")


def find_latest_run():
    runs = sorted(
        [p for p in OUTPUT_ROOT.glob("traverse_v8_*")
         if (p / "traverse_result.json").exists() or (p / "all_devices_result.json").exists()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not runs:
        raise SystemExit("No traverse_v8_* run found")
    return runs[0]


def safe_name(s):
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s)
    return re.sub(r"_+", "_", s).strip("_")[:60] or "unnamed"


def annotate_screenshots(device_data, run_dir, device_safe=None):
    """给 device_data["trees"][*]["items"][*] 加 _screenshot / _faq_screenshots 字段。
    多设备模式下,sub-page 截图可能多设备共享同一文件名(phase2 已知问题),取 disk 上存在的那个。"""
    available = {p.name for p in run_dir.glob("*.png")}

    def attach(item):
        if item.get("status") not in ("captured", "captured_chooser"):
            return
        path = item.get("path", "")
        # 候选文件名:多设备模式下优先 <device_safe>_<safename> 这种(将来 phase2 fix 后会出现),
        # 没有就 fallback <safename>(当前 phase2 行为)
        candidates = []
        last_seg = path.split(" > ")[-1] if " > " in path else path
        sn_path = safe_name(path)
        sn_last = safe_name(last_seg)
        if device_safe:
            candidates.append(f"{device_safe}_{sn_path}.png")
            candidates.append(f"{device_safe}_{sn_last}.png")
        candidates.append(f"{sn_path}.png")
        candidates.append(f"{sn_last}.png")
        for c in candidates:
            if c in available:
                item["_screenshot"] = c
                base = c[:-4]
                faq = sorted(p for p in available if p.startswith(f"{base}__q") and p.endswith(".png"))
                if faq:
                    item["_faq_screenshots"] = faq
                return

    for tree in device_data.get("trees", []):
        for it in tree.get("items", []):
            attach(it)


def _scan_file_for(pattern, path: Path):
    if not path.exists():
        return None
    try:
        m = pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
        return m.group(1) if m else None
    except Exception:
        return None


def extract_versions(device_data, run_dir, device_safe=None):
    if device_safe:
        main_xml = run_dir / f"{device_safe}_main.xml"
        settings_xml = run_dir / f"{device_safe}_settings.xml"
    else:
        main_xml = run_dir / "01_main_page.xml"
        settings_xml = run_dir / "02_settings_page.xml"
    plugin_main = _scan_file_for(PLUGIN_VERSION_PATTERN, main_xml)
    plugin_settings = _scan_file_for(PLUGIN_VERSION_PATTERN, settings_xml)
    blob = json.dumps(device_data, ensure_ascii=False)
    m = FIRMWARE_VERSION_PATTERN.search(blob)
    firmware = m.group(1) if m else None
    return plugin_main, plugin_settings, firmware


def extract_device_label_fallback(device_data, run_dir, device_safe=None):
    """device_data["device_name"] 是 phase2 多设备 flow 写的,优先用。否则 fallback 解析 XML / page_texts。"""
    if device_data.get("device_name"):
        return device_data["device_name"]
    # 单设备:从 02_settings_page.xml 上方 action bar 找
    xml = run_dir / (f"{device_safe}_settings.xml" if device_safe else "02_settings_page.xml")
    if xml.exists():
        try:
            txt = xml.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', txt):
                t = m.group(1).strip()
                x1, y1, x2 = int(m.group(2)), int(m.group(3)), int(m.group(4))
                if not t or len(t) < 2: continue
                if y1 < 50 or y1 > 220: continue
                cx = (x1 + x2) / 2
                if cx < 216 or cx > 920: continue
                if any(c.isalpha() or '가' <= c <= '힣' or '一' <= c <= '鿿' for c in t):
                    return t
        except Exception:
            pass
    for tree in device_data.get("trees", []):
        if tree.get("label") == "device_main":
            for pt in tree.get("page_texts", [])[:5]:
                t = (pt.get("text") or "").strip()
                if t and len(t) > 3 and not t.replace(":", "").replace(".", "").isdigit():
                    return t
            break
    return device_safe or run_dir.name


def collect_devices(run_dir):
    """返回 (is_multi, [device_payload, ...])。每个 payload 含:
        label, safe_name, plugin_main, plugin_settings, firmware, trees, findings (list).
    """
    multi_json = run_dir / "all_devices_result.json"
    single_json = run_dir / "traverse_result.json"
    findings_json = run_dir / "findings.json"

    findings_data = None
    if findings_json.exists():
        try:
            findings_data = json.loads(findings_json.read_text(encoding="utf-8"))
        except Exception:
            findings_data = None

    is_multi = multi_json.exists()
    if is_multi:
        scan = json.loads(multi_json.read_text(encoding="utf-8"))
        scan_devices = scan.get("devices", [])
    elif single_json.exists():
        scan_devices = [json.loads(single_json.read_text(encoding="utf-8"))]
    else:
        raise SystemExit(f"Neither traverse_result.json nor all_devices_result.json in {run_dir}")

    # findings 按 device 对齐:多设备 schema 在 findings_data["devices"] 数组里,单设备直接顶层
    if findings_data:
        if findings_data.get("is_multi_device"):
            f_devices = findings_data.get("devices", [])
        else:
            f_devices = [findings_data]
    else:
        f_devices = []

    payloads = []
    for idx, dd in enumerate(scan_devices):
        if dd.get("error"): continue
        if not dd.get("trees"): continue
        label = dd.get("device_name") or (f_devices[idx]["device_label"] if idx < len(f_devices) and f_devices[idx].get("device_label") else None)
        if not label:
            label = extract_device_label_fallback(dd, run_dir, safe_name(dd.get("device_name") or "") if is_multi else None)
        ds = safe_name(label) if is_multi else None
        annotate_screenshots(dd, run_dir, ds)
        plugin_main, plugin_settings, firmware = extract_versions(dd, run_dir, ds)

        device_findings = []
        if idx < len(f_devices) and f_devices[idx]:
            device_findings = f_devices[idx].get("findings", [])

        payloads.append({
            "label": label,
            "safe_name": ds or "",
            "plugin_main": plugin_main,
            "plugin_settings": plugin_settings,
            "firmware": firmware,
            "trees": dd.get("trees", []),
            "findings": device_findings,
            "scan_summary": {
                "tree_count": len(dd.get("trees", [])),
                "items_count": sum(len(t.get("items", [])) for t in dd.get("trees", [])),
                "findings_count": len(device_findings),
            },
        })
    return is_multi, payloads, findings_data


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Aqara Viewer — __TITLE__</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
         background: #f5f5f7; color: #222; display: flex; flex-direction: column; }
  header { background: #1d1d1f; color: #fff; padding: 10px 18px; flex-shrink: 0; }
  header h1 { margin: 0 0 3px 0; font-size: 16px; font-weight: 600; }
  header .meta { font-size: 11px; opacity: 0.55; font-family: monospace; }
  header .versions { font-size: 11px; margin-top: 5px; display: flex; gap: 8px; flex-wrap: wrap; }
  header .versions span { background: rgba(255,255,255,0.08); padding: 2px 8px; border-radius: 3px;
                           font-family: monospace; opacity: 0.85; }
  header .versions span.absent { opacity: 0.4; font-style: italic; }

  .device-tabs { background: #2a2a2c; border-bottom: 1px solid #444; display: flex; gap: 0;
                  overflow-x: auto; flex-shrink: 0; scrollbar-width: thin; }
  .device-tab { padding: 8px 14px; cursor: pointer; font-size: 12px; color: #ccc;
                 border-right: 1px solid #444; white-space: nowrap; flex-shrink: 0; display: flex;
                 align-items: center; gap: 6px; transition: background 0.15s; }
  .device-tab:hover { background: #3a3a3c; color: #fff; }
  .device-tab.active { background: #f5f5f7; color: #222; font-weight: 600; }
  .device-tab .count { background: rgba(0,0,0,0.15); padding: 1px 6px; border-radius: 8px;
                        font-size: 10px; font-weight: normal; }
  .device-tab.active .count { background: rgba(245,166,35,0.25); color: #aa5a00; }
  .device-tab.error { color: #f88; font-style: italic; }
  .device-tab .err-mark { color: #f55; font-weight: 600; }

  .controls { background: #fff; padding: 6px 14px; border-bottom: 1px solid #ddd;
              display: flex; gap: 10px; flex-wrap: wrap; align-items: center; flex-shrink: 0; font-size: 11px; }
  .controls input[type=search] { padding: 4px 8px; border: 1px solid #ccc; border-radius: 3px;
                                  font-size: 11px; width: 200px; }
  .controls label { cursor: pointer; user-select: none; }

  .workspace { flex: 1; display: flex; min-height: 0; overflow: hidden; }
  .sidebar { width: 340px; background: #fff; border-right: 1px solid #ddd;
             overflow-y: auto; flex-shrink: 0; }
  .sidebar-header { padding: 8px 12px; border-bottom: 1px solid #eee; background: #fafafa;
                    font-size: 11px; font-weight: 600; position: sticky; top: 0; z-index: 2; }
  .sidebar-header .nav-buttons { float: right; }
  .sidebar-header .nav-buttons button { padding: 2px 7px; border: 1px solid #ccc; background: #fff;
                                         border-radius: 3px; font-size: 10px; cursor: pointer; margin-left: 3px; }
  .sidebar-header .nav-buttons button:hover { background: #f0f0f0; }
  .sidebar-search { padding: 5px 10px; border-bottom: 1px solid #eee; }
  .sidebar-search input { width: 100%; padding: 3px 7px; border: 1px solid #ccc; border-radius: 3px; font-size: 11px; }
  .finding-group h4 { padding: 5px 12px; margin: 0; background: #f8f8f8; font-size: 10px;
                       text-transform: uppercase; letter-spacing: 0.5px; color: #777; border-top: 1px solid #eee; }
  .finding-group.pri-high h4 { color: #c62828; }
  .finding-group.pri-medium h4 { color: #b08800; }
  .finding-group.pri-low h4 { color: #555; }
  .finding-item { padding: 7px 12px; cursor: pointer; border-bottom: 1px solid #f0f0f0;
                  border-left: 3px solid transparent; }
  .finding-item:hover { background: #f8f8fc; }
  .finding-item.selected { background: #fff7d6; border-left-color: #f5a623; }
  .finding-item .issue-badge { display: inline-block; padding: 1px 5px; border-radius: 3px;
                                font-size: 9px; font-weight: 600; text-transform: uppercase; }
  .it-chinese_leak, .it-english_leak { background: #ffd6d6; color: #c62828; }
  .it-typo, .it-duplicate_char { background: #ffe6cc; color: #aa5a00; }
  .it-awkward, .it-inconsistency, .it-untranslated { background: #fff4cc; color: #b08800; }
  .finding-item .original { display: block; margin: 3px 0 1px 0; font-size: 12px; font-weight: 500; word-break: break-all; }
  .finding-item .suggestion { display: block; font-size: 11px; color: #1e6630; margin: 1px 0; }
  .finding-item .path-hint { display: block; font-size: 10px; color: #888; word-break: break-all; }
  .sidebar-empty { padding: 24px 14px; text-align: center; color: #888; font-style: italic; font-size: 11px; }
  /* --- Decision UI (2026-05-19) --- */
  .finding-actions { display: flex; gap: 4px; margin-top: 6px; }
  .finding-actions button { font-size: 10px; padding: 3px 8px; border: 1px solid #ccc;
                             background: #fff; border-radius: 3px; cursor: pointer; color: #333; }
  .finding-actions button:hover { background: #f0f0f0; }
  .finding-actions button.fix:hover { background: #e3f2fd; border-color: #1a73e8; color: #1a73e8; }
  .finding-actions button.ignore:hover { background: #f5f5f5; color: #555; }
  .decision-pill { display: inline-block; font-size: 9px; padding: 1px 6px; border-radius: 2px;
                    margin-left: 4px; vertical-align: middle; font-weight: 600; text-transform: uppercase; }
  .decision-pill.local-pending  { background: #e3f2fd; color: #1a73e8; }
  .decision-pill.local-ignored  { background: #eee; color: #666; }
  .decision-pill.canon-pending  { background: #fff4cc; color: #b08800; }
  .decision-pill.canon-ignored  { background: #e0e0e0; color: #555; }
  .decision-pill.canon-verified { background: #d4f4dd; color: #1e6630; }
  .decision-pill.canon-regressed{ background: #ffd6d6; color: #c62828; }
  .finding-item.decision-local-ignored, .finding-item.decision-canon-ignored { opacity: 0.55; }
  .finding-item.decision-canon-verified { opacity: 0.4; }
  /* Bottom export bar */
  .export-bar { position: sticky; bottom: 0; background: #fff; border-top: 1px solid #ddd;
                padding: 7px 12px; font-size: 11px; display: flex; gap: 8px; align-items: center; z-index: 2; }
  .export-bar button { padding: 4px 10px; border: 1px solid #ccc; background: #fff;
                       border-radius: 3px; cursor: pointer; font-size: 11px; }
  .export-bar button.primary { background: #1a73e8; color: #fff; border-color: #1a73e8; }
  .export-bar button:disabled { opacity: 0.4; cursor: not-allowed; }
  /* Modal */
  .modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none;
              align-items: center; justify-content: center; z-index: 100; }
  .modal-bg.open { display: flex; }
  .modal { background: #fff; max-width: 720px; width: 92%; max-height: 80vh;
           border-radius: 8px; padding: 18px; display: flex; flex-direction: column; }
  .modal h3 { margin: 0 0 6px 0; font-size: 16px; }
  .modal .hint { font-size: 11px; color: #666; margin-bottom: 10px; }
  .modal textarea { flex: 1; font-family: monospace; font-size: 11px; padding: 10px;
                     border: 1px solid #ccc; border-radius: 4px; min-height: 200px; resize: vertical; }
  .modal-actions { margin-top: 12px; display: flex; gap: 8px; justify-content: flex-end; align-items: center; }
  .modal-actions .status { margin-right: auto; font-size: 11px; color: #1e6630; }
  .modal-actions button { padding: 6px 12px; border: 1px solid #ccc; border-radius: 3px;
                          cursor: pointer; font-size: 12px; background: #fff; }
  .modal-actions button.primary { background: #1a73e8; color: #fff; border-color: #1a73e8; }

  .main { flex: 1; overflow-y: auto; padding: 10px 16px 30px; }
  .tree-section { background: #fff; border-radius: 8px; margin-bottom: 12px;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }
  .tree-header { background: #fafafa; padding: 8px 12px; border-bottom: 1px solid #eee;
                 font-weight: 600; font-size: 12px; }
  .tree-header .stats { font-weight: 400; font-size: 11px; color: #777; margin-left: 10px; }
  ul.items { list-style: none; padding: 0; margin: 0; }
  ul.items ul.items { padding-left: 20px; border-left: 2px solid #eef; }
  li.item { border-bottom: 1px solid #f0f0f0; transition: background 0.6s; }
  li.item:last-child { border-bottom: none; }
  li.item.flash-highlight > .row { background: #fff4cc; }
  .row { padding: 6px 12px; cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 12px; }
  .row:hover { background: #f8f8fc; }
  .row.expandable::before { content: "▶"; font-size: 9px; color: #888; transition: transform 0.15s;
                             display: inline-block; flex-shrink: 0; width: 9px; }
  .row.expanded::before { transform: rotate(90deg); }
  .row.leaf::before { content: "·"; color: #ccc; width: 9px; flex-shrink: 0; }
  .badge { padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600;
           text-transform: uppercase; flex-shrink: 0; }
  .b-captured { background: #d4f4dd; color: #1e6630; }
  .b-captured_chooser { background: #ffe6cc; color: #aa5a00; }
  .b-no_navigation, .b-no_navigation_scroll { background: #f0f0f0; color: #666; }
  .b-skipped_jump { background: #e8eaf6; color: #3949ab; }
  .b-skipped_danger { background: #ffd6d6; color: #c62828; }
  .b-skipped_action { background: #fff4cc; color: #b08800; }
  .b-vanished { background: #f3e5f5; color: #6a1b9a; }
  .b-cycle_up { background: #e0f7fa; color: #00695c; }
  .findings-marker { background: #fff4cc; color: #b08800; font-size: 10px; padding: 1px 6px;
                      border-radius: 3px; font-weight: 600; flex-shrink: 0; }
  .path { flex: 1; min-width: 0; }
  .path .last { font-weight: 500; }
  .path .parents { color: #999; font-size: 11px; }
  .meta-info { font-size: 11px; color: #888; flex-shrink: 0; }
  .details { padding: 9px 12px 12px; background: #fbfbfd; display: none; border-top: 1px solid #eef; }
  .details.open { display: grid; grid-template-columns: 1fr 300px; gap: 12px; }
  .texts-list { font-size: 12px; }
  .texts-list table { width: 100%; border-collapse: collapse; }
  .texts-list td { padding: 3px 6px; border-bottom: 1px solid #eee; vertical-align: top; }
  .texts-list .ko { font-weight: 500; }
  .texts-list .ko.has-finding { background: #fff4cc; border-left: 3px solid #f5a623; padding-left: 4px; }
  .texts-list .cls { color: #888; font-size: 10px; }
  .screenshots { font-size: 12px; }
  .screenshots img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px;
                     display: block; margin-bottom: 6px; cursor: zoom-in; }
  .faq-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px; }
  .faq-grid img { max-width: 100%; cursor: zoom-in; }
  .hidden { display: none !important; }
  .empty { color: #999; font-style: italic; font-size: 12px; padding: 12px; }
</style>
</head>
<body>
<header>
  <h1 id="title">__TITLE__</h1>
  <div class="meta" id="header-meta">__HEADER_META__</div>
  <div class="versions" id="versions-bar"></div>
</header>

__TABS_HTML__

<div class="controls">
  <input type="search" id="tree-search" placeholder="Filter menu tree...">
  <label><input type="checkbox" class="status-filter" value="all" checked> all</label>
  <span style="color:#aaa">|</span>
  <label><input type="checkbox" class="status-filter" value="captured"> captured</label>
  <label><input type="checkbox" class="status-filter" value="vanished"> vanished</label>
  <label><input type="checkbox" class="status-filter" value="skipped"> skipped</label>
  <label style="margin-left:auto"><input type="checkbox" id="only-with-findings"> only items with findings ⚠</label>
</div>

<div class="workspace">
  <aside class="sidebar">
    <div class="sidebar-header">
      <span id="findings-title">Findings</span>
      <span class="nav-buttons">
        <button onclick="prevFinding()">◀</button>
        <button onclick="nextFinding()">▶</button>
        <span id="finding-counter" style="font-size: 10px; margin-left:6px; color:#888;"></span>
      </span>
    </div>
    <div class="sidebar-search"><input type="search" id="finding-search" placeholder="search findings..."></div>
    <div id="findings-list"></div>
    <div class="export-bar">
      <span><span id="export-bar-count">0</span> local decisions</span>
      <button id="export-btn" class="primary" onclick="exportDecisions()" disabled>📋 Export</button>
      <button onclick="clearAllDecisions()" title="Clear all local decisions (does NOT touch canonical corrections.json)">↩ Clear</button>
    </div>
  </aside>
  <main class="main" id="content"></main>
</div>

<div id="export-modal" class="modal-bg">
  <div class="modal">
    <h3>Export <span id="export-count">0</span> local decisions</h3>
    <div class="hint">
      Copy this JSON or download as file, then send to the audit engineer.<br>
      Engineer runs: <code>python phase3_merge_decisions.py decisions.json</code> to merge into corrections.json.
    </div>
    <textarea id="export-textarea" spellcheck="false"></textarea>
    <div class="modal-actions">
      <span class="status" id="copy-status"></span>
      <button onclick="copyDecisions()">📋 Copy</button>
      <button onclick="downloadDecisions()">💾 Download .json</button>
      <button class="primary" onclick="document.getElementById('export-modal').classList.remove('open')">Close</button>
    </div>
  </div>
</div>

<script>
const DEVICES = __DEVICES__;
const RUN_NAME = "__RUN_NAME__";
const IS_MULTI = __IS_MULTI__;
const EXISTING_CORRECTIONS = __EXISTING_CORRECTIONS__;  // {wrong_text: status}

// --- Decision management (localStorage-based, 2026-05-19) ---
const STORAGE_KEY = "aqara-decisions-" + RUN_NAME;
function loadDecisions() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
  catch(e) { return {}; }
}
function saveDecisions(d) { localStorage.setItem(STORAGE_KEY, JSON.stringify(d)); }
function getDecision(originalText) {
  // canonical (already in corrections.json) takes priority
  if (EXISTING_CORRECTIONS[originalText]) {
    return {source: "canon", status: EXISTING_CORRECTIONS[originalText]};
  }
  const d = loadDecisions()[originalText];
  return d ? {source: "local", status: d.status} : null;
}
function setLocalDecision(orig, sug, status, pathHint, deviceLabel) {
  const decisions = loadDecisions();
  decisions[orig] = {
    wrong: orig,
    fix: status === "ignored" ? "(legacy: keep as-is)" : (sug || "(no fix proposed)"),
    status: status,
    device_hint: deviceLabel || null,
    path_hint: pathHint || null,
    submitted_at: new Date().toISOString().slice(0, 10),
  };
  saveDecisions(decisions);
  renderFindings();
  updateExportBar();
}
function clearLocalDecision(orig) {
  const decisions = loadDecisions();
  delete decisions[orig];
  saveDecisions(decisions);
  renderFindings();
  updateExportBar();
}
function clearAllDecisions() {
  const count = Object.keys(loadDecisions()).length;
  if (count === 0) return;
  if (!confirm(`Clear ${count} local decisions? Canonical corrections.json is unaffected.`)) return;
  localStorage.removeItem(STORAGE_KEY);
  renderFindings();
  updateExportBar();
}
function exportDecisions() {
  const items = Object.values(loadDecisions());
  if (!items.length) { alert("No local decisions to export."); return; }
  document.getElementById("export-textarea").value = JSON.stringify(items, null, 2);
  document.getElementById("export-count").textContent = items.length;
  document.getElementById("export-modal").classList.add("open");
}
function copyDecisions() {
  const t = document.getElementById("export-textarea");
  t.select();
  navigator.clipboard.writeText(t.value).then(() => {
    document.getElementById("copy-status").textContent = "✓ Copied!";
    setTimeout(() => document.getElementById("copy-status").textContent = "", 2000);
  });
}
function downloadDecisions() {
  const t = document.getElementById("export-textarea").value;
  const blob = new Blob([t], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `decisions_${RUN_NAME}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
function updateExportBar() {
  const count = Object.keys(loadDecisions()).length;
  document.getElementById("export-bar-count").textContent = count;
  document.getElementById("export-btn").disabled = count === 0;
}

let currentDevice = 0;
let ALL_FINDINGS = [];
let findingsByPath = {};
let currentIdx = -1;

// ---------- Sidebar rendering ----------
function renderFindings() {
  const root = document.getElementById("findings-list");
  root.innerHTML = "";
  if (!ALL_FINDINGS.length) {
    root.innerHTML = '<div class="sidebar-empty">No findings for this device.<br>(Run phase3_audit_proto.py first.)</div>';
    document.getElementById("findings-title").textContent = "Findings (0)";
    document.getElementById("finding-counter").textContent = "";
    return;
  }
  document.getElementById("findings-title").textContent = `Findings (${ALL_FINDINGS.length})`;
  const byPri = {high: [], medium: [], low: [], info: []};
  ALL_FINDINGS.forEach(f => { (byPri[f.priority] || byPri.info).push(f); });
  ["high", "medium", "low", "info"].forEach(pri => {
    if (!byPri[pri].length) return;
    const group = document.createElement("div");
    group.className = "finding-group pri-" + pri;
    const h = document.createElement("h4");
    h.textContent = `${pri} (${byPri[pri].length})`;
    group.appendChild(h);
    byPri[pri].forEach(f => {
      const item = document.createElement("div");
      item.className = "finding-item";
      item.dataset.idx = f._idx;
      item.dataset.path = f.path;
      const decision = getDecision(f.original);
      if (decision) {
        item.classList.add("decision-" + decision.source + "-" + decision.status);
      }
      const badge = document.createElement("span");
      badge.className = "issue-badge it-" + f.issue_type;
      badge.textContent = f.issue_type;
      item.appendChild(badge);
      // Decision badge if any
      if (decision) {
        const pill = document.createElement("span");
        pill.className = "decision-pill " + decision.source + "-" + decision.status;
        pill.textContent = (decision.source === "canon" ? "📌 " : "✎ ") + decision.status;
        item.appendChild(pill);
      }
      const orig = document.createElement("span");
      orig.className = "original";
      orig.textContent = f.original;
      item.appendChild(orig);
      if (f.suggested_translation) {
        const sug = document.createElement("span");
        sug.className = "suggestion";
        sug.textContent = "→ " + f.suggested_translation;
        item.appendChild(sug);
      }
      const ph = document.createElement("span");
      ph.className = "path-hint";
      ph.textContent = f.path;
      item.appendChild(ph);
      // Action buttons — only if NOT already in canonical corrections.json
      if (!decision || decision.source !== "canon") {
        const actions = document.createElement("div");
        actions.className = "finding-actions";
        const deviceLabel = DEVICES[currentDevice].label;
        if (decision && decision.source === "local") {
          // Already locally decided — show revoke
          const revoke = document.createElement("button");
          revoke.textContent = "↩ Undo";
          revoke.onclick = (e) => { e.stopPropagation(); clearLocalDecision(f.original); };
          actions.appendChild(revoke);
        } else {
          // No decision — show both
          const bFix = document.createElement("button");
          bFix.className = "fix";
          bFix.textContent = "📋 Add to fix list";
          bFix.title = "Mark this as a Korean translation issue to fix";
          bFix.onclick = (e) => {
            e.stopPropagation();
            setLocalDecision(f.original, f.suggested_translation, "pending", f.path, deviceLabel);
          };
          actions.appendChild(bFix);
          const bIg = document.createElement("button");
          bIg.className = "ignore";
          bIg.textContent = "✗ Ignore (legacy)";
          bIg.title = "Mark as 'won't fix' — used for legacy terms";
          bIg.onclick = (e) => {
            e.stopPropagation();
            setLocalDecision(f.original, f.suggested_translation, "ignored", f.path, deviceLabel);
          };
          actions.appendChild(bIg);
        }
        item.appendChild(actions);
      }
      item.onclick = () => selectFinding(f._idx);
      group.appendChild(item);
    });
    root.appendChild(group);
  });
}

function selectFinding(idx) {
  if (idx < 0 || idx >= ALL_FINDINGS.length) return;
  currentIdx = idx;
  document.querySelectorAll(".finding-item.selected").forEach(e => e.classList.remove("selected"));
  const el = document.querySelector(`.finding-item[data-idx="${idx}"]`);
  if (el) {
    el.classList.add("selected");
    el.scrollIntoView({block: "nearest", behavior: "smooth"});
  }
  document.getElementById("finding-counter").textContent = `${idx + 1} / ${ALL_FINDINGS.length}`;
  jumpToPath(ALL_FINDINGS[idx].path);
}

function prevFinding() {
  if (!ALL_FINDINGS.length) return;
  selectFinding(currentIdx <= 0 ? ALL_FINDINGS.length - 1 : currentIdx - 1);
}
function nextFinding() {
  if (!ALL_FINDINGS.length) return;
  selectFinding(currentIdx >= ALL_FINDINGS.length - 1 ? 0 : currentIdx + 1);
}

// ---------- Menu tree rendering ----------
function statusClass(s) { return "badge b-" + s; }

function renderItem(item) {
  const li = document.createElement("li");
  li.className = "item";
  li.dataset.status = item.status;
  li.dataset.path = item.path;
  const path = item.path;
  const last = path.includes(" > ") ? path.split(" > ").pop() : path;
  const parents = path.includes(" > ") ? path.substring(0, path.lastIndexOf(" > ") + 3) : "";

  const hasDetails = ["captured", "captured_chooser"].includes(item.status);
  const row = document.createElement("div");
  row.className = "row " + (hasDetails ? "expandable" : "leaf");

  const badge = document.createElement("span");
  badge.className = statusClass(item.status);
  badge.textContent = item.status;
  row.appendChild(badge);

  const pathFindings = findingsByPath[path] || [];
  if (pathFindings.length) {
    const marker = document.createElement("span");
    marker.className = "findings-marker";
    marker.textContent = `⚠ ${pathFindings.length}`;
    marker.title = pathFindings.map(f => `${f.priority}: ${f.original}`).join("\n");
    row.appendChild(marker);
    li.dataset.hasFindings = "1";
  }

  const pathEl = document.createElement("span");
  pathEl.className = "path";
  if (parents) {
    const p = document.createElement("span"); p.className = "parents"; p.textContent = parents;
    pathEl.appendChild(p);
  }
  const l = document.createElement("span"); l.className = "last"; l.textContent = last;
  pathEl.appendChild(l);
  row.appendChild(pathEl);

  const meta = document.createElement("span");
  meta.className = "meta-info";
  const metaParts = [];
  if (item.app_text_count) metaParts.push(`${item.app_text_count} texts`);
  if (item.faq_expansions_probed) metaParts.push(`FAQ:${item.faq_expansions_probed}q`);
  if (item.reason) metaParts.push(item.reason);
  meta.textContent = metaParts.join(" · ");
  row.appendChild(meta);

  li.appendChild(row);

  if (hasDetails) {
    const details = document.createElement("div");
    details.className = "details";

    const textsList = document.createElement("div");
    textsList.className = "texts-list";
    const table = document.createElement("table");
    const findingOriginals = new Set(pathFindings.map(f => f.original));
    (item.app_texts || []).forEach(t => {
      const tr = document.createElement("tr");
      const tdT = document.createElement("td");
      tdT.className = "ko";
      const text = t.text || t.content_desc || "(empty)";
      if (findingOriginals.has(text)) tdT.classList.add("has-finding");
      tdT.textContent = text;
      const tdC = document.createElement("td");
      tdC.className = "cls";
      tdC.textContent = (t.class || "") + (t.type === "content_desc" ? " [desc]" : "");
      tr.appendChild(tdT); tr.appendChild(tdC);
      table.appendChild(tr);
    });
    if (!(item.app_texts || []).length) {
      const em = document.createElement("div"); em.className = "empty";
      em.textContent = "(no app_texts captured)";
      textsList.appendChild(em);
    } else {
      textsList.appendChild(table);
    }
    details.appendChild(textsList);

    const shots = document.createElement("div");
    shots.className = "screenshots";
    if (item._screenshot) {
      const img = document.createElement("img");
      img.dataset.src = item._screenshot;
      img.loading = "lazy"; img.title = item._screenshot;
      img.onclick = () => window.open(item._screenshot, "_blank");
      shots.appendChild(img);
    }
    if (item._faq_screenshots) {
      const label = document.createElement("div");
      label.style.fontWeight = "600"; label.style.marginTop = "6px";
      label.textContent = `FAQ (${item._faq_screenshots.length}):`;
      shots.appendChild(label);
      const grid = document.createElement("div"); grid.className = "faq-grid";
      item._faq_screenshots.forEach(fn => {
        const img = document.createElement("img");
        img.dataset.src = fn; img.loading = "lazy"; img.title = fn;
        img.onclick = () => window.open(fn, "_blank");
        grid.appendChild(img);
      });
      shots.appendChild(grid);
    }
    if (!item._screenshot && !item._faq_screenshots) {
      const em = document.createElement("div"); em.className = "empty";
      em.textContent = "(no screenshot)";
      shots.appendChild(em);
    }
    details.appendChild(shots);

    li.appendChild(details);
    row.onclick = () => toggleItem(li);
  }
  return li;
}

function toggleItem(li) {
  const details = li.querySelector(":scope > .details");
  const row = li.querySelector(":scope > .row");
  if (!details) return;
  const open = details.classList.toggle("open");
  row.classList.toggle("expanded", open);
  if (open) loadLazyImages(details);
}

function loadLazyImages(scope) {
  scope.querySelectorAll("img[data-src]").forEach(img => {
    img.src = img.dataset.src; delete img.dataset.src;
  });
}

function renderTree(tree) {
  const section = document.createElement("section");
  section.className = "tree-section";
  const header = document.createElement("div");
  header.className = "tree-header";
  header.textContent = tree.label;
  const stats = document.createElement("span");
  stats.className = "stats";
  const counts = {};
  tree.items.forEach(it => { counts[it.status] = (counts[it.status] || 0) + 1; });
  stats.textContent = `${tree.items.length} items · ${Object.entries(counts).map(([k,v]) => `${k}:${v}`).join(", ")}`;
  header.appendChild(stats);
  section.appendChild(header);

  const ul = document.createElement("ul"); ul.className = "items";
  const itemsByPath = {};
  tree.items.forEach(it => { itemsByPath[it.path] = { item: it, children: [] }; });
  const roots = [];
  tree.items.forEach(it => {
    if (it.path.includes(" > ")) {
      const parent = it.path.substring(0, it.path.lastIndexOf(" > "));
      if (itemsByPath[parent]) itemsByPath[parent].children.push(itemsByPath[it.path]);
      else roots.push(itemsByPath[it.path]);
    } else {
      roots.push(itemsByPath[it.path]);
    }
  });

  function attachItem(parent, node) {
    const li = renderItem(node.item);
    if (node.children.length) {
      const childUl = document.createElement("ul"); childUl.className = "items";
      node.children.forEach(c => attachItem(childUl, c));
      li.appendChild(childUl);
    }
    parent.appendChild(li);
  }
  roots.forEach(r => attachItem(ul, r));
  section.appendChild(ul);
  return section;
}

// ---------- Finding → menu sync ----------
function jumpToPath(path) {
  const target = document.querySelector(`li.item[data-path="${CSS.escape(path)}"]`);
  if (!target) { console.warn("path not in tree:", path); return; }
  let p = target.parentElement;
  while (p) {
    if (p.tagName === "LI" && p.classList.contains("item")) {
      const det = p.querySelector(":scope > .details");
      const row = p.querySelector(":scope > .row");
      if (det && !det.classList.contains("open")) {
        det.classList.add("open"); row.classList.add("expanded"); loadLazyImages(det);
      }
    }
    p = p.parentElement;
  }
  const tDet = target.querySelector(":scope > .details");
  const tRow = target.querySelector(":scope > .row");
  if (tDet && !tDet.classList.contains("open")) {
    tDet.classList.add("open"); tRow.classList.add("expanded"); loadLazyImages(tDet);
  }
  target.scrollIntoView({behavior: "smooth", block: "center"});
  target.classList.add("flash-highlight");
  setTimeout(() => target.classList.remove("flash-highlight"), 2500);
}

// ---------- Filters ----------
function applyTreeFilters() {
  const q = document.getElementById("tree-search").value.toLowerCase();
  const checked = Array.from(document.querySelectorAll(".status-filter:checked")).map(c => c.value);
  const all = checked.includes("all");
  const onlyFindings = document.getElementById("only-with-findings").checked;
  document.querySelectorAll("li.item").forEach(li => {
    const status = li.dataset.status;
    let show = all
      || (checked.includes("captured") && status.startsWith("captured"))
      || (checked.includes("vanished") && status === "vanished")
      || (checked.includes("skipped") && status.startsWith("skipped"));
    if (show && onlyFindings) {
      // 自己有 findings 或子树里有 findings 都显示(否则父节点 display:none 会连带隐藏子项)
      show = li.dataset.hasFindings === "1" || li.dataset.hasFindingsSubtree === "1";
    }
    if (show && q) {
      const text = li.querySelector(".row").textContent.toLowerCase();
      show = text.includes(q);
    }
    li.classList.toggle("hidden", !show);
  });
}
function applyFindingsSearch() {
  const q = document.getElementById("finding-search").value.toLowerCase();
  document.querySelectorAll(".finding-item").forEach(it => {
    const t = it.textContent.toLowerCase();
    it.classList.toggle("hidden", q !== "" && !t.includes(q));
  });
  document.querySelectorAll(".finding-group").forEach(g => {
    const anyVisible = Array.from(g.querySelectorAll(".finding-item")).some(it => !it.classList.contains("hidden"));
    g.classList.toggle("hidden", !anyVisible);
  });
}

// ---------- Versions header ----------
function renderVersions(d) {
  const bar = document.getElementById("versions-bar");
  bar.innerHTML = "";
  function add(text, cls = "") {
    const s = document.createElement("span");
    if (cls) s.className = cls;
    s.textContent = text;
    bar.appendChild(s);
  }
  if (d.plugin_main) add(`플러그인 (홈) / Plugin (main): ${d.plugin_main}`);
  if (d.plugin_settings) add(`플러그인 (설정) / Plugin (settings): ${d.plugin_settings}`);
  if (!d.plugin_main && !d.plugin_settings) add("플러그인 / Plugin: (N/A)", "absent");
  add(`펌웨어 / Firmware: ${d.firmware || "(N/A)"}`, d.firmware ? "" : "absent");
}

// ---------- Switch device ----------
function switchDevice(idx) {
  if (idx < 0 || idx >= DEVICES.length) return;
  currentDevice = idx;
  const d = DEVICES[idx];

  // Tab active
  document.querySelectorAll(".device-tab").forEach((t, i) => t.classList.toggle("active", i === idx));

  // Title + meta
  document.getElementById("title").textContent = d.label;
  document.getElementById("header-meta").textContent =
    `run: ${RUN_NAME} · trees: ${d.scan_summary.tree_count} · items: ${d.scan_summary.items_count} · findings: ${d.scan_summary.findings_count}`;
  renderVersions(d);

  // Set per-device findings state
  ALL_FINDINGS = (d.findings || []).map((f, i) => ({...f, _idx: i}));
  findingsByPath = {};
  ALL_FINDINGS.forEach(f => {
    if (!findingsByPath[f.path]) findingsByPath[f.path] = [];
    findingsByPath[f.path].push(f);
  });
  currentIdx = -1;

  // Re-render content + sidebar
  const content = document.getElementById("content");
  content.innerHTML = "";
  d.trees.forEach(t => content.appendChild(renderTree(t)));

  // ★ 2026-05-15:propagate findings 标记给 ancestor li
  //   filter 用 display:none 隐藏父节点会把子树也连带隐藏 → finding 子项看不见
  //   每个有 findings 的 li,把祖先全标 data-has-findings-subtree="1"
  document.querySelectorAll('li.item[data-has-findings="1"]').forEach(li => {
    let p = li.parentElement;
    while (p) {
      if (p.tagName === "LI" && p.classList.contains("item")) {
        p.dataset.hasFindingsSubtree = "1";
      }
      p = p.parentElement;
    }
  });

  renderFindings();
  applyTreeFilters();

  // Auto-select first finding
  if (ALL_FINDINGS.length) setTimeout(() => selectFinding(0), 50);

  // URL fragment for deep-link
  if (IS_MULTI) location.hash = `#device-${idx}`;
}

// ---------- Init ----------
// Wire controls
document.getElementById("tree-search").addEventListener("input", applyTreeFilters);
document.getElementById("only-with-findings").addEventListener("change", applyTreeFilters);
document.querySelectorAll(".status-filter").forEach(cb => {
  cb.addEventListener("change", e => {
    if (e.target.value === "all" && e.target.checked) {
      document.querySelectorAll(".status-filter").forEach(c => { if (c !== e.target) c.checked = false; });
    } else if (e.target.value !== "all" && e.target.checked) {
      document.querySelector(".status-filter[value=all]").checked = false;
    }
    applyTreeFilters();
  });
});
document.getElementById("finding-search").addEventListener("input", applyFindingsSearch);

document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "j") nextFinding();
  if (e.key === "k") prevFinding();
  if (e.key === "[" && IS_MULTI) switchDevice(currentDevice > 0 ? currentDevice - 1 : DEVICES.length - 1);
  if (e.key === "]" && IS_MULTI) switchDevice(currentDevice < DEVICES.length - 1 ? currentDevice + 1 : 0);
});

// Tab clicks (handled via inline onclick in HTML, but bind here for safety)
document.querySelectorAll(".device-tab").forEach((tab, i) => {
  tab.addEventListener("click", () => switchDevice(i));
});

// Auto-select device from URL fragment or default 0
const m = location.hash.match(/#device-(\d+)/);
const initIdx = m ? Math.min(parseInt(m[1]), DEVICES.length - 1) : 0;
switchDevice(initIdx);
updateExportBar();
// Close modal when clicking outside
document.getElementById("export-modal").addEventListener("click", e => {
  if (e.target.id === "export-modal") e.currentTarget.classList.remove("open");
});
</script>
</body>
</html>
"""


def build(run_dir: Path) -> Path:
    is_multi, devices = collect_devices(run_dir)[:2]
    if not devices:
        raise SystemExit(f"No usable device data in {run_dir}")

    # Build tabs HTML (server-side, simpler than JS-built tabs)
    if is_multi:
        tab_pieces = ['<div class="device-tabs">']
        for i, d in enumerate(devices):
            count = d["scan_summary"]["findings_count"]
            tab_pieces.append(
                f'  <div class="device-tab" data-idx="{i}">{_html_escape(d["label"])}'
                + (f' <span class="count">⚠{count}</span>' if count else "")
                + '</div>'
            )
        tab_pieces.append('</div>')
        tabs_html = "\n".join(tab_pieces)
    else:
        tabs_html = ""

    title = devices[0]["label"] if not is_multi else f"{len(devices)} devices · {run_dir.name}"

    # Serialize devices (drop heavy stuff if any)
    devices_serializable = [
        {
            "label": d["label"],
            "safe_name": d["safe_name"],
            "plugin_main": d["plugin_main"],
            "plugin_settings": d["plugin_settings"],
            "firmware": d["firmware"],
            "trees": d["trees"],
            "findings": d["findings"],
            "scan_summary": d["scan_summary"],
        }
        for d in devices
    ]

    # ★ inline existing corrections.json status table — for finding cards to show "already in corrections" badge
    existing_corrections = {}
    corr_path = REPO_ROOT / "corrections.json"
    if corr_path.exists():
        try:
            cdata = json.loads(corr_path.read_text(encoding="utf-8"))
            for c in cdata.get("corrections", []):
                w = c.get("wrong")
                if w:
                    existing_corrections[w] = c.get("status", "pending")
        except Exception:
            pass

    html = (HTML_TEMPLATE
            .replace("__TITLE__", _html_escape(title))
            .replace("__HEADER_META__", "")  # populated by JS
            .replace("__TABS_HTML__", tabs_html)
            .replace("__RUN_NAME__", run_dir.name)
            .replace("__IS_MULTI__", "true" if is_multi else "false")
            .replace("__EXISTING_CORRECTIONS__", json.dumps(existing_corrections, ensure_ascii=False))
            .replace("__DEVICES__", json.dumps(devices_serializable, ensure_ascii=False)))
    out = run_dir / "viewer.html"
    out.write_text(html, encoding="utf-8")
    return out


def _html_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


if __name__ == "__main__":
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_run()
    print(f"Building viewer for: {run}")
    out = build(run)
    print(f"Done. Open in browser: {out}")
