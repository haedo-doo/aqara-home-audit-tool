"""Phase 3 — Glossary generator (跨设备韩文术语聚合).

扫所有 output/traverse_v8_*/traverse_result.json,提取每个韩文 text:
- 出现在哪些设备
- 出现在哪些 path
- 出现频次

同时找"近似变体"(edit distance <= 2 OR word-Jaccard >= 0.7)— 即同义但不一致的翻译,
这是 Phase 3 Tier 3 "一致性审计"最关键的信号。

输出:
- output/glossary.json   — 机读结构(后续 phase3_audit 喂 AI)
- output/glossary.html   — 浏览器可视(同 phase3_build_viewer 风格)

用法:
    python phase3_glossary_gen.py
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent
OUTPUT_ROOT = REPO_ROOT / "output"


# ---------------- 文本提取 ----------------

CJK_RANGE = lambda c: '가' <= c <= '힯' or '一' <= c <= '鿿' or '぀' <= c <= 'ヿ'

def has_cjk(s):
    return any(CJK_RANGE(c) for c in s)

def is_term_candidate(text):
    """是否值得收进 glossary 的术语。
    过滤:纯数字/IP/单字符/状态栏时间/电量/带 base64 等噪声。
    """
    if not text or len(text) < 2: return False
    t = text.strip()
    if not t: return False
    if re.match(r'^[\d\s:.%/_-]+$', t): return False     # 时间/数字/小数
    if re.match(r'^\d+(\.\d+)+$', t): return False        # IP / 版本号
    if t.lower() in {"true","false","null","on","off"}: return False
    if "base64" in t.lower(): return False
    if len(t) > 200: return False                         # 大段文字不当术语
    return True


# ---------------- 文本相似度 ----------------

def edit_distance(a, b, max_d=3):
    """编辑距离;超过 max_d 提早返回 max_d+1(节省时间)"""
    if abs(len(a) - len(b)) > max_d: return max_d + 1
    if a == b: return 0
    if len(a) < len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        row_min = curr[0]
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j-1] + 1, prev[j-1] + (ca != cb))
            row_min = min(row_min, curr[j])
        if row_min > max_d: return max_d + 1
        prev = curr
    return prev[-1]


def word_jaccard(a, b):
    """词级 Jaccard 相似度(空格分词)"""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)


def cluster_variants(terms, threshold_edit=2, threshold_jaccard=0.7):
    """把"近似但不完全相同"的 texts 聚一起。

    粗筛优化:只对长度在 4-50 且含 CJK 的 term 做两两比较,O(N²) 但 N 通常 < 500 可接受。
    返回:list of clusters,每个 cluster 是一组相互"相似"的 texts(>=2 个)。
    """
    candidates = [t for t in terms if 4 <= len(t) <= 50 and has_cjk(t)]
    n = len(candidates)

    # Union-Find
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry: parent[rx] = ry

    # 粗剪枝:按首字分桶,只在同一首字桶内两两比
    buckets = defaultdict(list)
    for i, t in enumerate(candidates):
        buckets[t[0]].append(i)

    for bucket in buckets.values():
        if len(bucket) < 2: continue
        for ii in range(len(bucket)):
            i = bucket[ii]
            for jj in range(ii + 1, len(bucket)):
                j = bucket[jj]
                a, b = candidates[i], candidates[j]
                if a == b: continue
                if abs(len(a) - len(b)) > 3: continue
                ed = edit_distance(a, b, max_d=threshold_edit)
                if ed <= threshold_edit:
                    union(i, j); continue
                if word_jaccard(a, b) >= threshold_jaccard:
                    union(i, j)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(candidates[i])
    return [sorted(set(g), key=lambda x: -len(x)) for g in groups.values() if len(set(g)) > 1]


# ---------------- 主流程 ----------------

def extract_device_label(data, run_name):
    """从 device_main 的 page_texts 头部猜设备名"""
    for tree in data.get("trees", []):
        if tree.get("label") == "device_main":
            for pt in tree.get("page_texts", [])[:5]:
                t = (pt.get("text") or "").strip()
                if t and len(t) > 3 and has_cjk(t) and is_term_candidate(t):
                    return t
    return run_name


def collect_from_run(run_dir):
    """从单个 run 提取 (text, source_kind, path) 三元组列表"""
    json_path = run_dir / "traverse_result.json"
    if not json_path.exists(): return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    device_label = extract_device_label(data, run_dir.name)

    triples = []
    for tree in data.get("trees", []):
        tree_label = tree.get("label", "?")
        # page_texts (page-level snapshot)
        for pt in tree.get("page_texts", []):
            t = (pt.get("text") or pt.get("content_desc") or "").strip()
            if is_term_candidate(t):
                triples.append((t, f"page_texts:{tree_label}", f"<root:{tree_label}>", device_label))
        # items + app_texts
        for it in tree.get("items", []):
            path = it.get("path", "")
            # primary label of item
            for raw in it.get("all_texts_on_card") or it.get("texts") or []:
                t = raw.strip() if isinstance(raw, str) else ""
                if is_term_candidate(t):
                    triples.append((t, "item_label", path, device_label))
            # captured page contents
            for at in it.get("app_texts", []):
                t = (at.get("text") or at.get("content_desc") or "").strip()
                if is_term_candidate(t):
                    triples.append((t, f"app_text:{at.get('class','?')}", path, device_label))
    return triples


def build_glossary():
    runs = sorted(OUTPUT_ROOT.glob("traverse_v8_*"))
    runs = [r for r in runs if (r / "traverse_result.json").exists()]
    if not runs:
        raise SystemExit("No scans found")

    # text → {device: set(paths), source_kinds: set}
    agg = defaultdict(lambda: {"devices": defaultdict(set), "sources": set()})

    for run in runs:
        for text, kind, path, device in collect_from_run(run):
            agg[text]["devices"][device].add(path)
            agg[text]["sources"].add(kind)

    # Build sortable list
    terms = []
    for text, info in agg.items():
        device_count = len(info["devices"])
        occurrence = sum(len(p) for p in info["devices"].values())
        terms.append({
            "text": text,
            "device_count": device_count,
            "occurrence_count": occurrence,
            "devices": sorted(info["devices"].keys()),
            "sample_paths": sorted({p for paths in info["devices"].values() for p in paths})[:8],
            "is_cjk": has_cjk(text),
            "len": len(text),
        })
    terms.sort(key=lambda t: (-t["device_count"], -t["occurrence_count"], t["text"]))

    # Find variants
    all_texts = [t["text"] for t in terms]
    variant_clusters = cluster_variants(all_texts)
    # decorate each term with its cluster
    text_to_cluster = {}
    for ci, cluster in enumerate(variant_clusters):
        for t in cluster:
            text_to_cluster[t] = ci
    for t in terms:
        if t["text"] in text_to_cluster:
            t["variant_cluster_id"] = text_to_cluster[t["text"]]

    glossary = {
        "generated_at": datetime.now().isoformat(),
        "scans_count": len(runs),
        "scans": [r.name for r in runs],
        "term_count": len(terms),
        "variant_clusters": [
            {
                "id": i,
                "variants": cluster,
                "device_coverage": sorted({d for t in cluster for d in agg[t]["devices"]}),
            }
            for i, cluster in enumerate(variant_clusters)
        ],
        "terms": terms,
    }
    return glossary


# ---------------- HTML 输出 ----------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8"><title>Aqara Glossary — __SCANS_COUNT__ scans</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
         margin: 0; background: #f5f5f7; color: #222; }
  header { background: #1d1d1f; color: #fff; padding: 16px 24px; position: sticky; top: 0; z-index: 10; }
  header h1 { margin: 0 0 6px 0; font-size: 18px; }
  header .meta { font-size: 12px; opacity: 0.7; }
  .controls { background: #fff; padding: 12px 24px; border-bottom: 1px solid #ddd;
              position: sticky; top: 62px; z-index: 9; display: flex; gap: 12px; flex-wrap: wrap;
              align-items: center; }
  .controls input[type=search] { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px;
                                  width: 280px; font-size: 13px; }
  .controls label { font-size: 12px; cursor: pointer; user-select: none; }
  main { padding: 16px 24px 64px; max-width: 1400px; margin: 0 auto; }
  .section { background: #fff; border-radius: 8px; margin-bottom: 16px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }
  .section h2 { background: #fafafa; padding: 12px 16px; margin: 0;
                border-bottom: 1px solid #eee; font-size: 14px; }
  .section .body { padding: 0; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { background: #f8f8fa; text-align: left; padding: 8px 12px; font-weight: 600;
       border-bottom: 1px solid #eee; position: sticky; top: 108px; z-index: 5; }
  td { padding: 6px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
  tr:hover { background: #fafaff; }
  .ko-text { font-weight: 500; }
  .pill { display: inline-block; background: #eef; color: #336; padding: 1px 6px;
          border-radius: 3px; font-size: 11px; margin-right: 4px; }
  .variant-cluster { background: #fff3e6; padding: 10px 14px; border-bottom: 1px solid #ffd9b3; }
  .variant-cluster .vc-id { font-size: 11px; color: #aa5a00; font-weight: 600; }
  .variant-cluster .variants { margin: 4px 0; }
  .variant-cluster .variant { display: inline-block; background: #fff; padding: 2px 8px;
                              margin: 2px 4px 2px 0; border: 1px solid #ffb366; border-radius: 3px;
                              font-weight: 500; font-size: 13px; }
  .variant-cluster .devices { font-size: 11px; color: #666; }
  .small { font-size: 11px; color: #888; }
  .paths { font-size: 11px; color: #555; }
  .paths .path-item { display: block; margin: 1px 0; }
  .col-num { text-align: right; width: 60px; font-variant-numeric: tabular-nums; }
  .col-text { width: 30%; }
  .col-devices { width: 25%; }
  .col-paths { }
  .hidden { display: none !important; }
  .empty { padding: 20px; text-align: center; color: #999; font-style: italic; }
</style>
</head><body>
<header>
  <h1>Aqara Korean Glossary</h1>
  <div class="meta">__SCANS_COUNT__ scans · __TERM_COUNT__ unique terms · __CLUSTER_COUNT__ variant clusters · generated __GENERATED_AT__</div>
</header>
<div class="controls">
  <input type="search" id="search" placeholder="Filter by text / path / device...">
  <label><input type="checkbox" id="only-multi"> only multi-device terms (≥2)</label>
  <label><input type="checkbox" id="only-clusters"> only terms in variant clusters</label>
  <span class="small" id="visible-count"></span>
</div>
<main id="content"></main>

<script>
const DATA = __DATA__;

function renderClusters(container) {
  if (!DATA.variant_clusters.length) return;
  const sec = document.createElement("section");
  sec.className = "section";
  const h = document.createElement("h2");
  h.textContent = `★ Variant Clusters (${DATA.variant_clusters.length}) — 同义但不一致的翻译,候选审计对象`;
  sec.appendChild(h);
  const body = document.createElement("div"); body.className = "body";
  DATA.variant_clusters.forEach(c => {
    const div = document.createElement("div"); div.className = "variant-cluster";
    div.innerHTML = `<div class="vc-id">cluster #${c.id}</div>
                     <div class="variants">${c.variants.map(v => `<span class="variant">${escapeHTML(v)}</span>`).join("")}</div>
                     <div class="devices">covered in: ${c.device_coverage.map(d => escapeHTML(d)).join(", ")}</div>`;
    body.appendChild(div);
  });
  sec.appendChild(body);
  container.appendChild(sec);
}

function renderTerms(container) {
  const sec = document.createElement("section");
  sec.className = "section";
  const h = document.createElement("h2");
  h.textContent = `All terms (${DATA.terms.length})`;
  sec.appendChild(h);
  const body = document.createElement("div"); body.className = "body";
  const tbl = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>
    <th class="col-num">devs</th>
    <th class="col-num">occ</th>
    <th class="col-text">text</th>
    <th class="col-devices">devices</th>
    <th class="col-paths">sample paths</th></tr>`;
  tbl.appendChild(thead);
  const tbody = document.createElement("tbody");
  DATA.terms.forEach(t => {
    const tr = document.createElement("tr");
    tr.dataset.text = t.text.toLowerCase();
    tr.dataset.devices = t.devices.join(" ").toLowerCase();
    tr.dataset.paths = t.sample_paths.join(" ").toLowerCase();
    tr.dataset.deviceCount = t.device_count;
    tr.dataset.cluster = t.variant_cluster_id !== undefined ? "1" : "0";
    tr.innerHTML = `
      <td class="col-num">${t.device_count}</td>
      <td class="col-num">${t.occurrence_count}</td>
      <td class="col-text ko-text">${escapeHTML(t.text)}${t.variant_cluster_id!==undefined ? ` <span class="pill">VAR#${t.variant_cluster_id}</span>` : ""}</td>
      <td class="col-devices small">${t.devices.map(d => escapeHTML(d)).join("<br>")}</td>
      <td class="col-paths paths">${t.sample_paths.slice(0,5).map(p => `<span class="path-item">${escapeHTML(p)}</span>`).join("")}${t.sample_paths.length>5 ? `<span class="small">... +${t.sample_paths.length-5} more</span>` : ""}</td>`;
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  body.appendChild(tbl);
  sec.appendChild(body);
  container.appendChild(sec);
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
}

function applyFilters() {
  const q = document.getElementById("search").value.toLowerCase();
  const onlyMulti = document.getElementById("only-multi").checked;
  const onlyCluster = document.getElementById("only-clusters").checked;
  let visible = 0;
  document.querySelectorAll("tbody tr").forEach(tr => {
    let show = true;
    if (onlyMulti && +tr.dataset.deviceCount < 2) show = false;
    if (onlyCluster && tr.dataset.cluster !== "1") show = false;
    if (show && q) {
      show = tr.dataset.text.includes(q) || tr.dataset.devices.includes(q) || tr.dataset.paths.includes(q);
    }
    tr.classList.toggle("hidden", !show);
    if (show) visible++;
  });
  document.getElementById("visible-count").textContent = `(${visible} visible)`;
}

const content = document.getElementById("content");
renderClusters(content);
renderTerms(content);
document.getElementById("search").addEventListener("input", applyFilters);
document.getElementById("only-multi").addEventListener("change", applyFilters);
document.getElementById("only-clusters").addEventListener("change", applyFilters);
applyFilters();
</script>
</body></html>
"""


def write_outputs(glossary):
    json_path = OUTPUT_ROOT / "glossary.json"
    json_path.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
    html = (HTML_TEMPLATE
            .replace("__SCANS_COUNT__", str(glossary["scans_count"]))
            .replace("__TERM_COUNT__", str(glossary["term_count"]))
            .replace("__CLUSTER_COUNT__", str(len(glossary["variant_clusters"])))
            .replace("__GENERATED_AT__", glossary["generated_at"][:19])
            .replace("__DATA__", json.dumps(glossary, ensure_ascii=False)))
    html_path = OUTPUT_ROOT / "glossary.html"
    html_path.write_text(html, encoding="utf-8")
    return json_path, html_path


if __name__ == "__main__":
    glossary = build_glossary()
    json_path, html_path = write_outputs(glossary)
    print(f"Scans aggregated: {glossary['scans_count']}")
    print(f"Unique terms: {glossary['term_count']}")
    print(f"Variant clusters: {len(glossary['variant_clusters'])}")
    print(f"\nOutputs:")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print(f"\nOpen: file:///{html_path.as_posix().replace('c:/', 'C:/')}")
