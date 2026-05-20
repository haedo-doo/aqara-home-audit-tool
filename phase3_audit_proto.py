"""Phase 3 — AI-assisted Korean UI translation audit (prototype).

模式自动切换:
- 没设 ANTHROPIC_API_KEY → 跑 Tier 1 规则(真实检测 chinese_leak/english_leak/punctuation/duplicate_char)+ 几条 mock AI findings
- 设了 ANTHROPIC_API_KEY → 真调 Claude Haiku 4.5,带 prompt caching,审 typo/awkward/inconsistency 等需要语义理解的项

输出(放在被审计的 run 目录里):
- findings.json — 机读结构,Phase 3 后续聚合 / 跨设备一致性审计的输入
- findings.html — 自包含浏览器视图,priority filter + 搜索 + 原文/建议对照

用法:
    python phase3_audit_proto.py [output/traverse_v8_XXX/]    # 默认用最新 run

API key 设置(开启真 AI 审计模式):
    PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."
    Bash:        export ANTHROPIC_API_KEY="sk-ant-..."
    或.env 文件:   ANTHROPIC_API_KEY=sk-ant-...   (推 git 前 gitignore!)

依赖(仅真 AI 模式需要):
    pip install anthropic pydantic

Mock 模式 0 依赖,纯标准库就跑。
"""
import json
import os
import re
import traceback
from pathlib import Path
from datetime import datetime
from collections import Counter

REPO_ROOT = Path(__file__).parent
OUTPUT_ROOT = REPO_ROOT / "output"

HAIKU_MODEL = "claude-haiku-4-5"  # ★ 严格固定 — 不要改成猜的 date-suffix 变体

# Gemini model — 2026-05-15 起切付费层(billing enabled),不再受 free tier RPD=20 限
# 候选 + 27 设备 audit 实测成本(KRW):
#   gemini-2.5-flash-lite  最便宜但质量弱,审韩文 typo 漏判多 — 不推荐做 Korean translation audit
#   gemini-2.5-flash       中等。约 ₩1,500-2,500
#   gemini-2.5-pro         ★ 默认,质量最好,本次实测 ₩4,876(2026-05-15, 27 设备, BATCH=60)
# 价格(Pro,2026):input $1.25 / output $10 per M tokens — output 占主要成本
# 通过环境变量 GEMINI_MODEL 可覆盖默认
GEMINI_MODEL = "gemini-2.5-pro"

# ============================================================
# 文本抽取
# ============================================================

# ============================================================
# 不送审/不送 AI 的文本模式(避免噪声 + 省 token)
# ============================================================
# 这些都是"明显不是翻译问题"的内容(log entries / 默认值 / 时间戳),
# 直接在 extract_audit_units 里过滤掉,**rules 和 AI 都不会看到它们**。
SKIP_AUDIT_PATTERNS = [
    # 持续时间日志(`지속 시간: 1분10초`, `지속 시간: 25분59초` 等)
    re.compile(r'^지속\s*시간\s*[:：]'),
    # 相对时间日志("어제 09:32 ...", "오늘 13:47 ...", "그제 ...")
    re.compile(r'^(어제|오늘|그제|그저께|내일|모레)\s+\d{1,2}:\d{2}'),
    # 오전 / 오후 + 时间 起头(摄像头事件时间线 "오후 1:30:03 | Default Room | ...")
    re.compile(r'^(오전|오후)\s*\d{1,2}:\d{2}'),
    # YYYY-MM-DD HH:MM[:SS] 时间戳行
    re.compile(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}'),
    # MM/DD HH:MM 短日期
    re.compile(r'^\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}'),
    # 纯时间打头 + 状态(如 "08:47 373 Lux", "08:28 닫힘", "13:47 두 번 누름")
    re.compile(r'^\d{1,2}:\d{2}\s'),
    # "최근 상태", "현재 상태", "측정값" 等纯标签 — 不审
    re.compile(r'^(최근|현재|이전)\s+(상태|값|측정)$'),
]
SKIP_AUDIT_EXACT = {
    "Default Room",           # 房间默认名(用户/系统设置值,不是翻译漏洞)
    "Default",
    "default",
    "(no name)",
    "(none)",
}

def should_audit(text):
    """返回 True 表示这条文本要纳入 audit;False = 跳过"""
    if not text or len(text) < 2: return False
    if text in SKIP_AUDIT_EXACT: return False
    for pat in SKIP_AUDIT_PATTERNS:
        if pat.match(text): return False
    return True


def extract_audit_units(data):
    """从 traverse_result.json 抽出待审计 units:每个唯一文本 + 它出现过的 paths。

    覆盖三个来源:
    - `tree.page_texts`(page snapshot — 设备主页/设置页的所有可见 UI 文本)
    - `item.app_texts`(每个 captured 子页的全部文本)
    - `item.all_texts_on_card`(每个 item 自己的 row 内文本)

    自动过滤 SKIP_AUDIT_PATTERNS(log timestamps / 默认值)— rules 和 AI 都不会看到。
    """
    units = {}
    skipped = set()

    def _add(text, path, cls="?"):
        text = (text or "").strip()
        if not text or len(text) < 2:
            return
        if re.match(r'^[\d\s:.%/_-]+$', text):
            return
        if text.lower() in {"true", "false", "null"}:
            return
        if len(text) >= 50 and re.fullmatch(r'[a-zA-Z0-9+/=]+', text):
            return  # base64 残段
        if not should_audit(text):
            skipped.add(text)
            return
        if text not in units:
            units[text] = {"paths": [], "class": cls}
        if path and path not in units[text]["paths"]:
            units[text]["paths"].append(path)

    for tree in data.get("trees", []):
        tree_label = tree.get("label", "?")
        # page_texts(page snapshot)
        for pt in tree.get("page_texts", []):
            text = pt.get("text") or pt.get("content_desc") or ""
            _add(text, f"<{tree_label}_root>", pt.get("class", "?"))
        # items
        for item in tree.get("items", []):
            path = item.get("path", "")
            # all_texts_on_card(item 行内文本)
            for t in item.get("all_texts_on_card") or item.get("texts") or []:
                if isinstance(t, str):
                    _add(t, path, "item_label")
            # app_texts(captured 子页内容)
            for at in item.get("app_texts", []):
                text = at.get("text") or at.get("content_desc") or ""
                _add(text, path, at.get("class", "?"))
    return units, skipped


PLUGIN_VERSION_PATTERN = re.compile(r"플러그인\s*버전\s*[:\s]\s*([\d][\d._]*)")
FIRMWARE_VERSION_PATTERN = re.compile(r"펌웨어\s*버전\s*[:\s]\s*([\d][\d._]*)")


def _scan_file_for(pattern, path: Path):
    if not path.exists():
        return None
    try:
        m = pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
        return m.group(1) if m else None
    except Exception:
        return None


def _safe_name(s):
    """Mirror of phase2.safe_name."""
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s)
    return re.sub(r"_+", "_", s).strip("_")[:60] or "unnamed"


def extract_versions(data, run_dir, device_safe=None):
    """抽取 3 个版本号(都可能是 None):
      - plugin_version_main:     主页 XML 里 '플러그인 버전: X.X'
      - plugin_version_settings: 设置页 XML 里 '플러그인 버전: X.X'
      - firmware_version:        全 result 扫 '펌웨어 버전:'(主要来自 펌웨어 업데이트 子页)
    单设备 run:read 01_main_page.xml / 02_settings_page.xml
    多设备 run:device_safe 给定 → read <device_safe>_main.xml / <device_safe>_settings.xml
    """
    if not isinstance(run_dir, Path):
        run_dir = Path(run_dir)
    if device_safe:
        main_xml = run_dir / f"{device_safe}_main.xml"
        settings_xml = run_dir / f"{device_safe}_settings.xml"
    else:
        main_xml = run_dir / "01_main_page.xml"
        settings_xml = run_dir / "02_settings_page.xml"
    plugin_main = _scan_file_for(PLUGIN_VERSION_PATTERN, main_xml)
    plugin_settings = _scan_file_for(PLUGIN_VERSION_PATTERN, settings_xml)
    blob = json.dumps(data, ensure_ascii=False)
    m = FIRMWARE_VERSION_PATTERN.search(blob)
    firmware = m.group(1) if m else None
    return plugin_main, plugin_settings, firmware


# ============================================================
# Corrections tracking + glossary(2026-05-15 加)
# 用户在 corrections.json 维护"已提交修改"的 wrong→fix 对。
# 每次 audit:
#   1. 已批准的 fix 文本从 AI 输入里剔除(省 token + 不再被反向 flag)
#   2. 生成 verification 报告:wrong 还在不在?fix 出现没?regressed 没?
# ============================================================
CORRECTIONS_PATH = REPO_ROOT / "corrections.json"


def load_corrections():
    """读 corrections.json。不存在/解析失败返回空列表。"""
    if not CORRECTIONS_PATH.exists():
        return []
    try:
        data = json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))
        corrs = data.get("corrections", [])
        # validate basic schema
        valid = []
        for c in corrs:
            if c.get("wrong") and c.get("fix") and c.get("id"):
                valid.append(c)
            else:
                print(f"  [corrections] skip malformed entry: {c}", flush=True)
        return valid
    except Exception as e:
        print(f"  [corrections] failed to load: {e}", flush=True)
        return []


def collect_all_scan_texts(device_data_list):
    """从扫描数据收集所有可见韩文 — 用于 correction verification。
    包括 page_texts + app_texts + all_texts_on_card。"""
    seen = set()
    for dd in device_data_list:
        for tree in dd.get("trees", []):
            for pt in tree.get("page_texts", []):
                t = (pt.get("text") or pt.get("content_desc") or "").strip()
                if t: seen.add(t)
            for item in tree.get("items", []):
                for t in item.get("all_texts_on_card") or item.get("texts") or []:
                    if isinstance(t, str) and t.strip():
                        seen.add(t.strip())
                for at in item.get("app_texts", []):
                    t = (at.get("text") or at.get("content_desc") or "").strip()
                    if t: seen.add(t)
    return seen


def verify_corrections(corrections, all_scan_texts):
    """对每条 correction 计算 current state。不改 status — 用户手工 review。
    返回 list of dict with extra fields: current_state, wrong_seen, fix_seen."""
    report = []
    for c in corrections:
        wrong_seen = c["wrong"] in all_scan_texts
        fix_seen = c["fix"] in all_scan_texts
        prev = c.get("status", "pending")
        # 计算 observed_state(独立于 status 字段,纯客观)
        if not wrong_seen and fix_seen:
            observed = "fix_applied"
        elif not wrong_seen and not fix_seen:
            observed = "both_missing"
        elif wrong_seen and not fix_seen:
            observed = "not_yet_fixed"
        else:  # wrong_seen and fix_seen
            observed = "both_present"
        # regression alert
        regression = (prev == "verified" and wrong_seen)
        report.append({
            **c,
            "observed_state": observed,
            "wrong_seen": wrong_seen,
            "fix_seen": fix_seen,
            "regression": regression,
        })
    return report


def get_approved_fix_texts(corrections):
    """已 verified 的 fix 文本集合 — audit 前从 units 里剔除以省 token。"""
    return {c["fix"] for c in corrections if c.get("status") == "verified"}


def get_ignored_texts(corrections):
    """status='ignored' 的 wrong 文本集合 — "既成事实"译法,用户决定不改,永不审。
    跟 verified(已修)的区别:ignored 是 *本身就保留*,不送 AI 也不进 verification 报告。"""
    return {c["wrong"] for c in corrections if c.get("status") == "ignored"}


def extract_device_label(data, run_dir):
    """识别设备名。优先级:
    1. 从 02_settings_page.xml 的 action bar(top 50-220px 区域)抓 TextView
       (这是设备主页 + 设置页的标题栏,如 "모션/조도 센서 P2"、"면조명")
    2. fallback:从 device_main 的 page_texts 找含韩文的非数字字符串
    3. 都失败:返回 run_dir 名
    """
    # Priority 1: 02_settings_page.xml top-area TextView
    if isinstance(run_dir, Path):
        settings_xml = run_dir / "02_settings_page.xml"
        if settings_xml.exists():
            try:
                content = settings_xml.read_text(encoding="utf-8")
                for m in re.finditer(r'<node[^>]*?text="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]', content):
                    text, x1, y1, x2, y2 = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                    # action bar 范围:y1 ~50-220, 长度 2-50, 不是纯数字/时间
                    if not (50 <= y1 <= 220): continue
                    if len(text) < 2 or len(text) > 50: continue
                    if re.fullmatch(r'[\d\s:.%]+', text): continue   # 时间/电量等
                    if text in {"<", ">", "...", "Wi-Fi"}: continue
                    return text
            except Exception:
                pass
    # Priority 2: device_main page_texts
    for tree in data.get("trees", []):
        if tree.get("label") == "device_main":
            for pt in tree.get("page_texts", [])[:8]:
                t = (pt.get("text") or "").strip()
                if t and len(t) >= 2 and any('가' <= c <= '힯' for c in t):
                    if re.search(r'[\d%]', t):
                        continue
                    return t
    # Fallback
    return run_dir.name if isinstance(run_dir, Path) else str(run_dir)


# ============================================================
# Tier 1 规则检查(无 AI,免费,catches obvious bugs)
# ============================================================

def _has_korean(s):
    return any('가' <= c <= '힯' for c in s)

def _has_chinese(s):
    return any('一' <= c <= '鿿' for c in s)

# 允许的英文品牌/技术词 — 这些在 ko UI 里出现属正常,不算 leak
ALLOWED_ENGLISH = {
    # 品牌
    "Aqara", "Lumi", "Matter", "Zigbee", "Z-Wave", "HomeKit", "Alexa",
    "iOS", "Android", "App", "AI", "Wi-Fi", "Bluetooth",
    # 技术单位 / 协议
    "USB", "HD", "FHD", "UHD", "FAQ", "ID", "OK", "QR", "PIN", "GMT",
    "API", "MAC", "IP", "URL", "TV", "GPS", "AC", "DC", "IR",
    "GB", "MB", "KB", "TB", "Hz", "kHz", "MHz", "GHz",
    "kbps", "Mbps", "Gbps", "ms", "fps",
    "1080p", "1080P", "720p", "720P", "480p", "360p", "4K", "8K", "2K",
    "RGB", "HDMI", "OTA", "DHCP", "DNS", "VPN", "VLAN", "DDNS",
    # 网络/通信术语(韩文 UI 里普遍按英文显示)
    "SSID", "BSSID", "ESSID", "PAN", "LAN", "WAN", "VLAN",
    "IPv4", "IPv6", "TCP", "UDP", "HTTPS", "HTTP", "SSH", "FTP",
    "UUID", "GUID", "EUI", "EUI-64",
    "BLE", "NFC", "RFID", "SoC", "MCU", "PoE",
    # 常见 UI 值(语言名 / 房间默认名 — 这些是 user-set values 不是 labels)
    "Default", "Default Room", "English", "Latest",
    # ★ 语言 picker 里的 self-names(每种语言显示它自己的拼写 — 这是正确 UX,不该翻译)
    "Español", "Русский", "Deutsch", "Français", "Italiano", "Português",
    "Nederlands", "Polski", "Türkçe", "Magyar", "Čeština", "Svenska", "Norsk",
    "Suomi", "Dansk", "Română", "Ελληνικά", "العربية", "עברית", "Tiếng Việt",
    "ไทย", "Bahasa", "Filipino",
    # 设备名常用词(应该翻 — 但 rule 层不敢断言,所以放宽)
    "Room", "Hub", "Camera", "Doorbell",
    # 时间单位
    "AM", "PM",
}

# 整串就是"值"的模式 — 不算 leak
SENSOR_UNITS = r'(GB|MB|KB|TB|GHz|MHz|kHz|Hz|kbps|Mbps|Gbps|ms|fps|p|P|%|Lux|lux|°C|°F|hPa|kPa|psi|dB|kWh|Wh|kW·h|mAh|kW|mW|mA|mV|V|W|A|°|ppm|μg|mg|km|cm|mm|m)'
VALUE_LIKE_PATTERNS = [
    # 纯"数字+单位":29.60 GB / 100 Lux / 50%
    re.compile(rf'^\d+(\.\d+)?\s?{SENSOR_UNITS}/?(s|초)?$', re.IGNORECASE),
    # 时间:08:47 或 08:47:30 或 08:47 AM
    re.compile(r'^\d{1,2}:\d{2}(:\d{2})?\s?(AM|PM)?$', re.IGNORECASE),
    # MAC / hex ID(16+ hex chars)
    re.compile(r'^[a-fA-F0-9_.:-]{16,}$'),
    # 传感器读数:时间 + 数值 + 单位(如 "08:47 373 Lux" / "어제 14:32 25.5°C")
    re.compile(rf'^.*\d+:\d{{2}}.*\s\d+(\.\d+)?\s{SENSOR_UNITS}$', re.IGNORECASE),
    # 数值 + 单位 + 描述(如 "373 Lux" / "25.5°C")
    re.compile(rf'^\d+(\.\d+)?\s{SENSOR_UNITS}.*$', re.IGNORECASE),
    # 十六进制值(如 "0x5186" / "0xFF00")— Zigbee PAN ID / Network ID 之类
    re.compile(r'^0x[0-9a-fA-F]+$'),
    # SSID-like / snake_case identifier(如 "Doo_Aqara_2.4G" / "MyWiFi_5G")
    # 至少一个下划线,主体全是 ASCII 字母数字 + 点/连字符
    re.compile(r'^[A-Za-z][A-Za-z0-9.\-]*_[A-Za-z0-9_.\-]+$'),
    # 随机大写字母+数字组成的 token / 密码(如 "WQPUB4XU" / "ABC123XY")
    # 6-12 字符,全大写字母+数字,**且必须既含字母又含数字**(避免误判 PIN/CCTV 等正常缩写)
    re.compile(r'^(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6,12}$'),
    # 裸单位标签(如 "kPa" / "°C" / "Lux" 出现在列头里)— 不算 leak
    re.compile(rf'^{SENSOR_UNITS}$'),
    # 通用 identifier(8+ 字符,无空格,既含字母又含数字,可含 . _ - 分隔)
    # 例:"WIN-NM463EFD28V"(NAS 主机名)/ "abc-def-123" / "DEVICE_A1B2"
    # 字段无空格 → 通常是 user-data / machine-generated 标识符,非翻译候选
    re.compile(r'^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9._-]{8,}$'),
]

# 全角标点(Unicode 全角形式,U+FF01-FF5E 区段 + U+3002 中文句号)
# 注意:之前误写成 ASCII 半角 — 这里要确保是 fullwidth codepoints
FULLWIDTH_PUNCT_PATTERN = re.compile(r'[：，。；！？]')

# Matter device ID 模式(matt. 开头 + 一串 hex)— 不当 english_leak
MATTER_DEVICE_ID = re.compile(r'^matt\.[0-9a-f]+$', re.IGNORECASE)

# 用户自设的"设备名"白名单 — 由 audit_run() 在跑前从 baselines 填充。
# 这些名字是用户输入(可能含中文/英文/韩文),不算翻译错误,所有规则都跳过。
ALLOWED_DEVICE_NAMES = set()


def rule_chinese_leak(text, paths):
    if text in ALLOWED_DEVICE_NAMES:
        return None
    if not _has_chinese(text):
        return None
    return {
        "issue_type": "chinese_leak",
        "suggested_translation": "(한국어 번역 필요)",
        "priority": "high",
        "rationale": "한국어 UI에 중국어 문자가 남아 있습니다. 개발자의 중국어 식별자가 번역되지 않은 채로 노출된 것으로 보입니다.",
    }

def rule_english_leak(text, paths):
    if text in ALLOWED_DEVICE_NAMES:
        return None
    if _has_korean(text) or _has_chinese(text):
        return None
    if not any(c.isalpha() for c in text):
        return None  # 纯标点/数字,不是 leak
    # ★ 跳过设备 ID(matt.41635...)— 这类是 hardware identifier 不该翻
    if MATTER_DEVICE_ID.fullmatch(text):
        return None
    # ★ 跳过看起来像 hex/MAC/version 的字符串(>= 8 chars 全是 [a-f0-9_.:-])
    if len(text) >= 8 and re.fullmatch(r'[a-fA-F0-9_.:\s-]+', text):
        return None
    # ★ 跳过"值"类(数字+单位、时间、IP、MAC 等)
    for vp in VALUE_LIKE_PATTERNS:
        if vp.fullmatch(text):
            return None
    # 拆词,看是否所有词都在白名单里(或是版本号/数字)
    words = re.split(r'[\s()._/-]+', text)
    words = [w for w in words if w]
    if not words:
        return None
    is_all_safe = True
    for w in words:
        if w in ALLOWED_ENGLISH:
            continue
        if re.fullmatch(r'[\d.]+', w):  # 版本号
            continue
        is_all_safe = False
        break
    if is_all_safe:
        return None
    return {
        "issue_type": "english_leak",
        "suggested_translation": "(한국어 번역 필요)",
        "priority": "high" if len(text) >= 5 else "medium",
        "rationale": "한국어 UI인데 영어 문자열만 있습니다. 한국어로 번역되어야 합니다. (Wi-Fi · Matter · Aqara 등 브랜드/기술 용어는 예외로 허용)",
    }

def rule_punctuation(text, paths):
    m = FULLWIDTH_PUNCT_PATTERN.search(text)
    if not m:
        return None
    # 全角 → 半角(只替换我们 regex 命中的几类)
    half = (text
            .replace("：", ": ")     # 全角冒号 → ': '(常见韩文写法)
            .replace("，", ", ")
            .replace("。", ". ")
            .replace("；", "; ")
            .replace("！", "!")
            .replace("？", "?"))
    # 收一下多余空格
    half = re.sub(r' +', ' ', half).strip()
    return {
        "issue_type": "punctuation",
        "suggested_translation": half,
        "priority": "low",
        "rationale": f"전각 부호 '{m.group()}'가 포함되어 있습니다. 한국어 UI는 보통 반각 부호 + 띄어쓰기를 사용합니다.",
    }

def rule_duplicate_char(text, paths):
    # 2 字符以上的紧接重复(추가추가, 데이터데이터)
    m = re.search(r'([가-힯]{2,})\1', text)
    if not m:
        return None
    return {
        "issue_type": "duplicate_char",
        "suggested_translation": text[:m.start()] + m.group(1) + text[m.end():],
        "priority": "medium",
        "rationale": f"중복된 문자열 '{m.group(1)}'이(가) 감지되었습니다. 오타(typo)일 가능성이 높습니다.",
    }

# ★ rule_punctuation 暂时禁用(2026-05-13):
#   App 内全角/半角符号在视觉上差别极小,AI 又频繁误判半角 '|' 为全角、对 ':' 后空格过度敏感,
#   findings 噪声大且耗 token。若以后想恢复,把 `rule_punctuation` 加回 list 并解除 SYSTEM_PROMPT 中的禁用条款。
TIER1_RULES = [rule_chinese_leak, rule_english_leak, rule_duplicate_char]

def run_tier1_rules(text, paths):
    findings = []
    for rule in TIER1_RULES:
        f = rule(text, paths)
        if f:
            findings.append({
                **f,
                "path": paths[0] if paths else "(unknown)",
                "all_paths": paths,
                "original": text,
                "source": f"rule:{f['issue_type']}",
            })
    return findings


# ============================================================
# Mock AI findings(用真文本造几条示例 — 没 API key 时跑)
# ============================================================

# 这些是 CLAUDE.md 里已记录的真实 bug 模式,mock 模式模拟 AI 能识别它们
MOCK_AI_PATTERNS = [
]

def run_mock_ai(text, paths):
    out = []
    for p in MOCK_AI_PATTERNS:
        if p["predicate"](text):
            out.append({
                "path": paths[0] if paths else "(unknown)",
                "all_paths": paths,
                "original": text,
                "issue_type": p["issue_type"],
                "suggested_translation": p["suggest"](text),
                "priority": p["priority"],
                "rationale": p["rationale"],
                "source": f"mock:{HAIKU_MODEL}",
            })
    return out


# ============================================================
# 真 Anthropic API 审计(Haiku 4.5 + prompt caching)
# ============================================================

SYSTEM_PROMPT_TEMPLATE = """You are a Korean UI translation auditor for the Aqara Home smart-device Android app (com.lumiunited.aqarahome.play).

Your job: for each input string from the Korean-localized UI, identify translation quality issues. The app is auto-translated from Chinese, so common issues include typos, awkward phrasing, language mixing, and terminology inconsistency.

# Trilingual baselines (use WITH CAUTION)

Each input may include `zh` (Chinese) and/or `en` (English) baselines. These are **position-matched** (same item index in the menu tree), **NOT semantic-matched**. They can be **MISALIGNED** when menu structures differ between locales — this is common and you MUST detect it.

## How to use baselines

**Step 1 — Reliability check.** Before treating baseline as ground truth, ask: *is this baseline plausibly the same UI concept as ko?*
  - Same concept-category (both are signal levels / both are room types / both are buttons of similar purpose) AND length / character class roughly similar → RELIABLE, treat as ground truth.
  - Completely different concepts (ko='카메라' [camera] vs zh='风扇' [fan]; ko='보통' [normal/medium-level] vs zh='优秀' [excellent]; ko='발코니' [balcony] vs zh='玄关' [foyer]) → **MISALIGNED** — discard the baseline and judge ko alone.

**Step 2 — When reliable:**
  - ko deviates in meaning from zh/en → translation error (flag).
  - ko is faithful to zh/en but awkward Korean → awkward.
  - ko matches naturally → no finding (omit).

**Step 3 — When unreliable / missing:** judge ko on its own merits — does it look like idiomatic Korean UI text? If yes, no finding.

## Critical: do NOT flag misalignments as translation errors

If ko='보통' (signal level "normal/fair") and baseline says 'Excellent' / '优秀', that does NOT mean Korean is wrong. It means the **list orders differ** between locales and we sampled at the wrong index. **DO NOT** suggest changing '보통' to '우수' in this case — both are legitimate Korean UI terms for signal levels, you simply cannot use these baselines.

Other example sets where misalignment is common (always discard baseline in these cases unless ko is itself nonsensical):
  - Signal levels: 약함 / 보통 / 우수
  - Room types: 발코니 / 거실 / 침실 / 주방 / 현관 / 복도 / 화장실 / 서재 / 다용도실 ...
  - Modes/scenes lists
  - Country/region/language lists

## Examples

[reliable baseline — flag]
ko: "움직임명 인식됨"  zh: "检测到移动"  en: "Motion detected"
→ baselines ARE reliable (both about motion detection). ko is typo: '움직임명' → '움직임이', '인식됨' → '감지됨'. Flag as typo.

[misaligned baseline — DO NOT flag]
ko: "보통"  zh: "优秀"  en: "Excellent"
→ baselines look DIFFERENT in meaning but '보통' is a legitimate signal-strength level in Korean. This is misalignment (list ordering). Discard baseline. Korean text is fine → omit finding.

[misaligned baseline — DO NOT flag]
ko: "발코니"  zh: "玄关"  en: "Foyer"
→ baselines look different but '발코니' is a valid room type. Misaligned. Omit.

[no baseline]
ko: "추가추가하기"  (no zh/en)
→ judge alone: duplicate '추가'. Flag as duplicate_char.

# Issue categories

Use exactly one of these `issue_type` values:

- **typo**: Misspelled Korean (e.g., '서택' should be '선택'; '명' should be '이' for the subject marker)
- **chinese_leak**: Chinese characters appearing in supposedly Korean UI (e.g., '智能可视门铃G4'). This is a developer Chinese identifier that wasn't translated.
- **english_leak**: Pure English where Korean is expected. EXCLUDE brand/technical terms: Wi-Fi, Matter, Aqara, Lumi, Bluetooth, USB, HD, FAQ, GB/MB/KB, IP, URL, HomeKit, Alexa, Zigbee, Z-Wave, AI, API. EXCLUDE version numbers like "1.2.3" or "0.0.0_0018".
- **punctuation**: DISABLED. Do NOT use this category. Fullwidth/halfwidth punctuation, colon spacing, vertical bar `|`, and similar typography differences are visually negligible in this UI and not real translation defects. If you would have flagged a punctuation issue, use 'ok' instead. The enum value is retained only for schema compatibility.
- **awkward**: Grammatically valid Korean but unnatural phrasing — typical machine-translation tells like literal Chinese → Korean transliteration, incorrect particle usage, or non-idiomatic word order. This is the most useful AI judgment beyond rules.
- **untranslated**: Looks like a raw resource name or developer placeholder (e.g., 'cell_arrow', 'device_icon', 'btn_save_text'). Snake_case English fragments that shouldn't be visible.
- **duplicate_char**: Repeated Korean syllable or word sequence (e.g., '추가추가하기' should be '추가하기').
- **inconsistency**: Term that conflicts with a more common variant elsewhere in the app. (You don't have full app context here — only flag this when the same text appears as multiple slightly different variants in the input batch.)
- **ok**: DISABLED. Do NOT return any Finding with issue_type='ok'. If you would judge a text as fine, simply omit it from the response — no Finding emitted. The enum value is retained for schema compatibility only.

# Severity rules

- **high**: Clearly wrong, blocks user understanding or shows lack of localization. chinese_leak, untranslated, severe typo, duplicate_char.
- **medium**: Noticeable but not blocking. Awkward phrasing, mild typo, language-mixing in non-critical place.
- **low**: Minor — inconsistency that's still understandable, mild awkwardness.
- **info**: Use ONLY when issue_type='ok'.

# Output format

For each input string, output a Finding with:
- `path`: copy from input
- `original`: copy the input text verbatim
- `issue_type`: one of the categories above
- `suggested_translation`: corrected Korean (or "" if issue_type='ok')
- `priority`: one of {high, medium, low, info}
- `rationale`: **Write in Korean (한국어), ≤ 30 characters / one short phrase**. State the change concisely, no full sentences. Korean translator audience. Never write Chinese.
  - GOOD: "'서택' → '선택' 오타", "조사 '명' → '이' 자연스러움", "중국어 잔존"
  - BAD: "이 텍스트는 한국어 UI에 적합하지 않은 중국어 식별자가 그대로 남아 있어..."

Be CONSERVATIVE: when in doubt, mark as 'ok'. False positives are worse than false negatives for this audit — the user will manually review the high/medium findings, so over-reporting wastes their time.

# Examples (one per category)

Input: `서택`
Output: typo / high / suggested='선택' / rationale="'서택' → '선택' 오타"

Input: `智能可视门铃G4`
Output: chinese_leak / high / suggested="(한국어 번역 필요)" / rationale="중국어 잔존, '스마트 비디오 도어벨 G4'"

Input: `Lumi video doorbell face recognition authorization`
Output: english_leak / high / suggested="(한국어 번역 필요)" / rationale="설명문 전체 영어"

Input: `움직임명 인식됨`
Output: awkward / medium / suggested='움직임이 감지됨' / rationale="조사 '명'→'이', '인식됨'→'감지됨'"

Input: `cell_arrow`
Output: untranslated / high / suggested="(한국어 번역 필요)" / rationale="리소스 ID 노출"

Input: `추가추가하기`
Output: duplicate_char / high / suggested='추가하기' / rationale="'추가' 중복"

Input: `장치 카드`  → (no finding emitted — this is fine Korean)
Input: `Wi-Fi 연결` → (no finding emitted — brand term OK)
Input: `사용 중:29.60 GB` → (no finding emitted — punctuation disabled)

# Critical reminders

- DO NOT flag brand names (Aqara, Lumi, Matter, Wi-Fi, HomeKit etc.) as english_leak.
- DO NOT flag '0.0.0_0058' style version strings.
- **DO NOT flag any punctuation issue. Punctuation category disabled — simply omit those texts from findings.**
- For awkward findings, your suggested_translation should be a real improved Korean phrase, not just "improve this".
- **OUTPUT ONLY problematic texts. Skip texts judged as fine — do not emit issue_type='ok' findings (token waste). Empty findings array is acceptable.**
- **Keep `rationale` to ≤ 30 Korean characters / one phrase. Long sentences waste output tokens and cost.**
"""

def real_audit_with_haiku(units, device_label):
    """走真 Anthropic API。需要:
    1. 环境变量 ANTHROPIC_API_KEY
    2. pip install anthropic pydantic

    设计:
    - 用 Haiku 4.5(成本极低,Korean OK)
    - System prompt 含完整 audit 规则 + 示例(~4096 tokens 才能命中 Haiku 4.5 的 prompt cache 阈值)
    - 用 messages.parse() + pydantic schema 保证 JSON 输出
    - 每批 30 units,降 API 调用数
    """
    try:
        import anthropic
        from pydantic import BaseModel, Field
        from typing import Literal, List as _List
    except ImportError as e:
        raise SystemExit(
            f"Missing dependency for real API mode: {e}\n"
            "  pip install anthropic pydantic"
        )

    class Finding(BaseModel):
        path: str
        original: str
        issue_type: Literal[
            "typo", "chinese_leak", "english_leak", "punctuation",
            "awkward", "untranslated", "duplicate_char", "inconsistency", "ok"
        ]
        suggested_translation: str = ""
        priority: Literal["high", "medium", "low", "info"]
        rationale: str

    class AuditBatch(BaseModel):
        findings: _List[Finding]

    client = anthropic.Anthropic()  # auto-reads ANTHROPIC_API_KEY

    BATCH_SIZE = 30
    unit_list = list(units.items())
    all_findings = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read = 0
    total_cache_write = 0

    for i in range(0, len(unit_list), BATCH_SIZE):
        batch = unit_list[i:i + BATCH_SIZE]
        user_content = ("Audit each Korean UI text. zh/en baselines (when present) are the same UI position "
                        "in Chinese/English app — use them as ground truth.\n\n")
        for j, (text, info) in enumerate(batch, 1):
            sample_path = info["paths"][0] if info["paths"] else "(root)"
            text_safe = text.replace("\n", "\\n").replace('"', '\\"')
            user_content += f'{j}. ko: "{text_safe}"\n   path: "{sample_path}"\n'
            bl = info.get("baselines") or {}
            if bl.get("zh"):
                zh_safe = bl["zh"][0].replace("\n", "\\n").replace('"', '\\"')
                user_content += f'   zh: "{zh_safe}"\n'
            if bl.get("en"):
                en_safe = bl["en"][0].replace("\n", "\\n").replace('"', '\\"')
                user_content += f'   en: "{en_safe}"\n'
            user_content += "\n"

        # System prompt 带 cache_control(Haiku 4.5 需要 ≥4096 tokens 才会真缓存,
        # 我们的 system prompt 实测在阈值附近;不达标也不报错,只是没省钱)
        response = client.messages.parse(
            model=HAIKU_MODEL,
            max_tokens=16000,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT_TEMPLATE,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
            output_format=AuditBatch,
        )

        parsed = response.parsed_output
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        total_cache_write += getattr(response.usage, "cache_creation_input_tokens", 0) or 0

        batch_findings = 0
        for f in parsed.findings:
            if f.issue_type == "ok":
                continue
            d = f.model_dump()
            # 增加跨设备 path 信息
            d["all_paths"] = units.get(f.original, {}).get("paths", [d["path"]])
            d["source"] = f"ai:{HAIKU_MODEL}"
            all_findings.append(d)
            batch_findings += 1

        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(unit_list) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Batch {batch_num}/{total_batches}: +{batch_findings} findings "
              f"(in={response.usage.input_tokens}, out={response.usage.output_tokens}, "
              f"cache_read={getattr(response.usage,'cache_read_input_tokens',0)})", flush=True)

    # 估算成本(Haiku 4.5 定价:input $1.00/M, output $5.00/M, cache_write 1.25×, cache_read 0.1×)
    cost = (total_input_tokens * 1.00
            + total_output_tokens * 5.00
            + total_cache_write * 1.25
            + total_cache_read * 0.10) / 1_000_000
    print(f"  Total tokens: in={total_input_tokens}, out={total_output_tokens}, "
          f"cache_read={total_cache_read}, cache_write={total_cache_write}")
    print(f"  Estimated cost: ${cost:.4f}")

    return all_findings


# ============================================================
# 真 Google Gemini API 审计(2.5 Flash 免费层)
# ============================================================

class GeminiQuotaExhausted(Exception):
    """Gemini 免费层日配额(RPD)用完。当天内 retry 也救不了,应 fallback 到其它 provider。
    携带 partial findings 不丢已抓到的 batch 数据。"""
    def __init__(self, msg, partial_findings=None):
        super().__init__(msg)
        self.partial_findings = partial_findings or []


def _parse_gemini_429(exc_str):
    """从 429 错误信息里抠 (is_daily_quota, retry_delay_seconds, quota_id)。
    daily quota 唯一可靠特征:quotaId 严格匹配 GenerateRequestsPerDayPerProjectPerModel-*。
    ★ 2026-05-15 v2:之前用 'PerDay' in exc_str 太宽,文档链接/解释文本里也可能含 PerDay → 误报。
       改成严格 regex 抓 quotaId 字段,只在 quotaId 真含 PerDay 时算 daily。"""
    import re
    # 抓 quotaId 字段 — Google 错误格式标准
    m_qid = re.search(r"['\"]quotaId['\"]\s*:\s*['\"]([^'\"]+)['\"]", exc_str)
    quota_id = m_qid.group(1) if m_qid else ""
    # 严格判断:quotaId 含 "PerDay" 才算 daily
    is_daily = "PerDay" in quota_id
    # retryDelay 形如 "retryDelay': '41s'"
    delay = 30
    m = re.search(r"retryDelay['\"]?:\s*['\"](\d+)s", exc_str)
    if m:
        delay = int(m.group(1)) + 2
    return is_daily, delay, quota_id


def real_audit_with_gemini(units, device_label):
    """走 Google Gemini API(免费层,无需信用卡)。需要:
    1. 环境变量 GEMINI_API_KEY(从 https://aistudio.google.com/apikey 拿,不是 GCP)
    2. pip install google-genai pydantic

    错误处理:
    - 分钟级 429(quotaValue 较大,有 retryDelay 几十秒)→ 等 retryDelay 后重试,最多 2 次
    - 日级 429(quotaId 含 PerDay 或 quotaValue<=50)→ raise GeminiQuotaExhausted
      携带已抓到的 partial findings,让 audit_run fallback 到 Anthropic
    - 其它错误 → 直接 raise
    """
    import time
    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel
        from typing import Literal, List as _List
    except ImportError as e:
        raise SystemExit(
            f"Missing dependency for Gemini mode: {e}\n"
            "  pip install google-genai pydantic"
        )

    class Finding(BaseModel):
        path: str
        original: str
        issue_type: Literal[
            "typo", "chinese_leak", "english_leak", "punctuation",
            "awkward", "untranslated", "duplicate_char", "inconsistency", "ok"
        ]
        suggested_translation: str = ""
        priority: Literal["high", "medium", "low", "info"]
        rationale: str

    class AuditBatch(BaseModel):
        findings: _List[Finding]

    model_name = os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)

    # ★ 2026-05-15:Gemini 免费层 RPD 限 20(不是宣传的 1000)
    #   27 设备 ~1000-1500 units × BATCH=30 → 50 次请求 → 远超 20 RPD
    #   改成 BATCH=120,~10 次请求,稳进 RPD;单 batch token ~4-8K << 250K TPM 池子
    #   质量代价:batch>150 会有"中间漏审",120 是 Gemini Flash 系列实测安全上限
    # 2026-05-15:切付费层 + 升 Pro,BATCH 降回 60(小 batch 质量更稳;付费下不需要省 RPD)
    BATCH_SIZE = 60
    RATE_LIMIT_SLEEP = 1.0  # 付费 Pro 限 ~150 RPM,1s buffer 足够;留着是为应付突发 burst

    unit_list = list(units.items())
    all_findings = []
    total_in = 0
    total_out = 0
    total_thoughts = 0  # ★ 2026-05-19:Pro 隐藏的 thinking tokens,按 output 价计费
    total_batches = (len(unit_list) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(unit_list), BATCH_SIZE):
        batch = unit_list[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        # rate limit:除第一批外都先 sleep(paid Tier1 Pro ~150 RPM,1s 远超安全)
        if i > 0:
            time.sleep(RATE_LIMIT_SLEEP)

        user_content = ("Audit each Korean UI text. zh/en baselines (when present) are the same UI position "
                        "in Chinese/English app — use them as ground truth.\n\n")
        for j, (text, info) in enumerate(batch, 1):
            sample_path = info["paths"][0] if info["paths"] else "(root)"
            text_safe = text.replace("\n", "\\n").replace('"', '\\"')
            user_content += f'{j}. ko: "{text_safe}"\n   path: "{sample_path}"\n'
            bl = info.get("baselines") or {}
            if bl.get("zh"):
                zh_safe = bl["zh"][0].replace("\n", "\\n").replace('"', '\\"')
                user_content += f'   zh: "{zh_safe}"\n'
            if bl.get("en"):
                en_safe = bl["en"][0].replace("\n", "\\n").replace('"', '\\"')
                user_content += f'   en: "{en_safe}"\n'
            user_content += "\n"

        def _call_gemini():
            return client.models.generate_content(
                model=model_name,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TEMPLATE,
                    response_mime_type="application/json",
                    response_schema=AuditBatch,
                ),
            )

        response = None
        attempts = 0
        while True:
            attempts += 1
            try:
                response = _call_gemini()
                break
            except Exception as e:
                err = str(e)
                is_429 = "429" in err or "RESOURCE_EXHAUSTED" in err
                # ★ 2026-05-18:加 503 UNAVAILABLE / 504 处理 — Google server 过载,非 quota
                is_503 = ("503" in err or "UNAVAILABLE" in err
                          or "504" in err or "DEADLINE_EXCEEDED" in err)
                if not is_429 and not is_503:
                    raise
                if is_503:
                    if attempts >= 4:
                        print(f"  ★ Gemini 503 UNAVAILABLE — 4 retries failed, skipping batch.", flush=True)
                        response = None
                        break
                    backoff = [5, 15, 45, 120][min(attempts - 1, 3)]
                    print(f"  ★ Gemini 503 (server overload, attempt {attempts}/4). "
                          f"Sleeping {backoff}s with exponential backoff...", flush=True)
                    time.sleep(backoff)
                    continue
                # ── 以下 429 处理(原逻辑不变)──
                is_daily, retry_delay, quota_id = _parse_gemini_429(err)
                print(f"  ★ Gemini 429 — quotaId={quota_id!r}, retryDelay={retry_delay}s, is_daily={is_daily}", flush=True)
                if is_daily:
                    print(f"  ★ Daily quota exhausted (model={model_name}). "
                          f"Got {len(all_findings)} findings before hitting limit.",
                          flush=True)
                    raise GeminiQuotaExhausted(
                        f"Gemini {model_name} daily quota exhausted at batch {batch_num} (quotaId={quota_id})",
                        partial_findings=all_findings,
                    )
                if attempts >= 3:
                    print(f"  ★ Gemini rate-limited 3 times in a row, giving up on this batch.",
                          flush=True)
                    response = None
                    break
                print(f"  ★ Gemini rate-limited (batch {batch_num}, attempt {attempts}). "
                      f"Sleeping {retry_delay}s per retryDelay...", flush=True)
                time.sleep(retry_delay)

        if response is None:
            continue

        parsed = response.parsed  # AuditBatch instance
        if parsed is None:
            # response_schema 失效时 fallback 解析 text
            try:
                raw = json.loads(response.text)
                parsed = AuditBatch.model_validate(raw)
            except Exception:
                print(f"  ★ Could not parse Gemini response, skipping batch", flush=True)
                continue

        usage = getattr(response, "usage_metadata", None)
        if usage:
            total_in += getattr(usage, "prompt_token_count", 0) or 0
            total_out += getattr(usage, "candidates_token_count", 0) or 0
            total_thoughts += getattr(usage, "thoughts_token_count", 0) or 0  # ★ Pro 内部 reasoning

        batch_findings = 0
        for f in parsed.findings:
            if f.issue_type == "ok":
                continue
            d = f.model_dump()
            d["all_paths"] = units.get(f.original, {}).get("paths", [d["path"]])
            d["source"] = f"ai:{model_name}"
            all_findings.append(d)
            batch_findings += 1

        bth = getattr(usage, "thoughts_token_count", 0) or 0 if usage else 0
        print(f"  Batch {batch_num}/{total_batches}: +{batch_findings} findings "
              f"(in={getattr(usage,'prompt_token_count','?') if usage else '?'}, "
              f"out={getattr(usage,'candidates_token_count','?') if usage else '?'}"
              + (f", thoughts={bth}" if bth else "") + ")", flush=True)

    # 成本估算 — Gemini 2.5 Pro paid:input $1.25/M, output $10/M(≤200K context)
    # ★ thoughts_token_count 算 output 价(Pro 的隐藏 reasoning,按 $10/M 收费)
    if "pro" in model_name.lower():
        cost_usd = total_in * 1.25e-6 + (total_out + total_thoughts) * 10e-6
        krw = cost_usd * 1400
        print(f"  Total tokens: in={total_in}, out={total_out}, thoughts={total_thoughts} "
              f"(est cost ≈ ${cost_usd:.4f} ≈ ₩{krw:.0f}, model={model_name})", flush=True)
    else:
        print(f"  Total tokens: in={total_in}, out={total_out}  (model={model_name})", flush=True)
    return all_findings


# ============================================================
# 主流程
# ============================================================

class _ProviderState:
    """跨多设备共享的 AI provider 状态。Gemini 日配额是全局的,一旦撞了
    后续设备直接走 Haiku 或 mock,不要再 try Gemini。"""
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        self.gemini_exhausted = False
        self.gemini_model = os.environ.get("GEMINI_MODEL", GEMINI_MODEL)


def _audit_units_with_ai(units, ctx_label, state: _ProviderState):
    """Run Tier 1 rules + AI on a single device's units. Returns (findings, mode_str, model_str).
    Updates state.gemini_exhausted as side effect."""
    findings = []
    # Tier 1 — always
    for text, info in units.items():
        findings.extend(run_tier1_rules(text, info["paths"]))

    # AI: priority Gemini → Haiku → mock,respecting state
    audit_mode, ai_model = "rules_only", "(rules)"
    if state.gemini_key and not state.gemini_exhausted:
        try:
            ai = real_audit_with_gemini(units, ctx_label)
            findings.extend(ai)
            audit_mode, ai_model = f"ai_gemini ({state.gemini_model})", state.gemini_model
        except GeminiQuotaExhausted as e:
            state.gemini_exhausted = True
            partial = getattr(e, "partial_findings", []) or []
            findings.extend(partial)
            print(f"  → Preserved {len(partial)} partial Gemini findings; falling back for rest.")
            audited = {f["original"] for f in partial}
            remaining = {t: info for t, info in units.items() if t not in audited}
            if state.anthropic_key:
                ai = real_audit_with_haiku(remaining, ctx_label)
                findings.extend(ai)
                audit_mode = f"ai_gemini_partial+haiku ({state.gemini_model} → {HAIKU_MODEL})"
                ai_model = f"{state.gemini_model} + {HAIKU_MODEL}"
            else:
                for t, info in remaining.items():
                    findings.extend(run_mock_ai(t, info["paths"]))
                audit_mode = f"ai_gemini_partial+mock ({state.gemini_model})"
                ai_model = f"{state.gemini_model} (quota) + mock"
    elif state.anthropic_key:
        ai = real_audit_with_haiku(units, ctx_label)
        findings.extend(ai)
        audit_mode, ai_model = f"ai_haiku ({HAIKU_MODEL})", HAIKU_MODEL
    elif state.gemini_exhausted and state.anthropic_key:
        ai = real_audit_with_haiku(units, ctx_label)
        findings.extend(ai)
        audit_mode, ai_model = f"ai_haiku_after_gemini ({HAIKU_MODEL})", HAIKU_MODEL
    elif state.gemini_exhausted:
        for t, info in units.items():
            findings.extend(run_mock_ai(t, info["paths"]))
        audit_mode, ai_model = "mock_ai_after_gemini_quota", "(mock)"
    else:
        for t, info in units.items():
            findings.extend(run_mock_ai(t, info["paths"]))
        audit_mode, ai_model = "rules + mock_ai", "(rules + mock)"

    # Post-filter punctuation (defense-in-depth)
    before = len(findings)
    findings = [f for f in findings if f.get("issue_type") != "punctuation"]
    if before - len(findings):
        print(f"  [filter] dropped {before-len(findings)} punctuation findings")

    # Dedup
    seen, unique = set(), []
    for f in findings:
        k = (f["path"], f["original"], f["issue_type"])
        if k in seen: continue
        seen.add(k); unique.append(f)

    # Sort + number
    pri = {"high": 0, "medium": 1, "low": 2, "info": 3}
    unique.sort(key=lambda f: (pri.get(f["priority"], 9), f["issue_type"], f["path"]))
    for i, f in enumerate(unique, 1):
        f["id"] = f"f_{i:04d}"

    return unique, audit_mode, ai_model


def _audit_one_device(device_data, run_dir, device_index, total, state: _ProviderState, is_multi,
                       approved_fixes=None, ignored_texts=None, aligned=None):
    """对单台设备的数据跑完整 audit。返回 per-device output dict。
    approved_fixes: 已 verified 的 correction.fix 文本集合 — 跳过 AI 审计(省 token + 不被反向 flag)。
    aligned: 三语对齐字典(可选)— 给每个 unit 附 zh/en baseline,AI prompt 里塞进去。"""
    device_label = device_data.get("device_name") or extract_device_label(device_data, run_dir)
    device_safe = _safe_name(device_label) if is_multi else None

    print(f"\n{'='*60}\n=== [{device_index+1}/{total}] {device_label} ===\n{'='*60}", flush=True)

    units, skipped = extract_audit_units(device_data)
    # ★ 跳过用户设备名(白名单,Tier1 规则也会跳)— 同时省 AI token + 防误 flag
    if ALLOWED_DEVICE_NAMES:
        skipped_names = [t for t in units if t in ALLOWED_DEVICE_NAMES]
        for t in skipped_names:
            del units[t]
        if skipped_names:
            print(f"  [whitelist] skipped {len(skipped_names)} user device names", flush=True)
    # ★ 跳过 ignored 文本(用户决定保留的"既成事实"译法,永不审)
    if ignored_texts:
        skipped_ignored = [t for t in units if t in ignored_texts]
        for t in skipped_ignored:
            del units[t]
        if skipped_ignored:
            print(f"  [ignored] skipped {len(skipped_ignored)} legacy/won't-fix phrases", flush=True)
    # ★ 跳过已批准词典里的 fix(已确认正确的译法,不需再审)
    if approved_fixes:
        skipped_glossary = [t for t in units if t in approved_fixes]
        for t in skipped_glossary:
            del units[t]
        if skipped_glossary:
            print(f"  [glossary] skipped {len(skipped_glossary)} approved phrases", flush=True)

    # ★ 附 zh/en baselines 到每个 unit(若有)
    # 2026-05-19:加 reliability filter — 短 ko 文本(≤4 字)的 baseline 一律不要,
    # 因为 list 类菜单(信号강도 약함/보통/우수,房间名 발코니/현관/...)的 position 对齐特别容易错位。
    # 短词 ko UI 一般是按钮(확인/취소)或 list item,AI 单独也能判,无需 baseline help。
    # 长文本(≥5 字)的 baseline 保留 — 位置对齐对 distinctive text 更可靠,
    # 而且像 '움직임명 인식됨' 这种核心 typo 一定 ≥5 字,不会因这层过滤丢 baseline。
    n_with_bl = 0
    n_short_skipped = 0
    if aligned:
        device_bl = (aligned.get("devices", {}).get(device_label) or {}).get("baselines", {})
        for text, info in units.items():
            b = device_bl.get(text)
            if not b or not (b.get("zh") or b.get("en")):
                continue
            if len(text) <= 4:
                n_short_skipped += 1
                continue
            info["baselines"] = b
            n_with_bl += 1
        if n_short_skipped:
            print(f"  [align] {n_short_skipped} short ko texts have baseline but dropped (≤4 chars: list/btn,误对齐风险高)", flush=True)
        if n_with_bl:
            print(f"  [align] {n_with_bl}/{len(units)} units have zh/en baseline", flush=True)

    print(f"  units: {len(units)} (skipped {len(skipped)} log/default)")

    findings, audit_mode, ai_model = _audit_units_with_ai(units, device_label, state)

    plugin_main, plugin_settings, firmware_v = extract_versions(device_data, run_dir, device_safe)

    return {
        "device_label": device_label,
        "device_safe_name": device_safe or "",
        "plugin_version": plugin_main or plugin_settings,
        "plugin_version_main": plugin_main,
        "plugin_version_settings": plugin_settings,
        "firmware_version": firmware_v,
        "audit_mode": audit_mode,
        "model": ai_model,
        "summary": {
            "total_units_audited": len(units),
            "findings_count": len(findings),
            "by_priority": dict(Counter(f["priority"] for f in findings)),
            "by_issue_type": dict(Counter(f["issue_type"] for f in findings)),
            "by_source": dict(Counter(f.get("source", "?") for f in findings)),
        },
        "findings": findings,
    }


def audit_run(run_dir: Path, baseline_zh: Path = None, baseline_en: Path = None):
    """检测 run dir 是单设备还是多设备,跑相应的 audit。
    输出统一 schema:顶层 `devices` 数组,单设备就是长度 1。
    向后兼容:单设备 case 顶层也复制第一台的字段。
    baseline_zh / baseline_en:可选,中/英 scan run dir,用于三语对比 AI prompt。"""
    multi_json = run_dir / "all_devices_result.json"
    single_json = run_dir / "traverse_result.json"

    if multi_json.exists():
        all_data = json.loads(multi_json.read_text(encoding="utf-8"))
        device_list = all_data.get("devices", [])
        is_multi = True
        scan_captured_at = all_data.get("captured_at")
    elif single_json.exists():
        single_data = json.loads(single_json.read_text(encoding="utf-8"))
        device_list = [single_data]
        is_multi = False
        scan_captured_at = single_data.get("captured_at")
    else:
        raise SystemExit(f"Neither traverse_result.json nor all_devices_result.json in {run_dir}")

    # ★ 三语对齐 baselines + ALLOWED_DEVICE_NAMES 白名单
    aligned = None
    if baseline_zh or baseline_en:
        try:
            from phase3_align_locales import build_baselines
            aligned = build_baselines(run_dir, baseline_zh, baseline_en)
            statuses = Counter(d["baseline_status"] for d in aligned["devices"].values())
            print(f"[align] {len(aligned['devices'])} devices, status: {dict(statuses)}", flush=True)
            # 把 user_device_names 全部丢进白名单 — chinese_leak/english_leak 规则跳过这些
            global ALLOWED_DEVICE_NAMES
            ALLOWED_DEVICE_NAMES = set(aligned.get("user_device_names", []))
            print(f"[align] {len(ALLOWED_DEVICE_NAMES)} device names whitelisted (will skip chinese/english_leak rules)", flush=True)
        except Exception as e:
            print(f"[align] WARN: failed to build baselines: {e}", flush=True)
            aligned = None

    # ★ corrections / glossary
    corrections = load_corrections()
    approved_fixes = get_approved_fix_texts(corrections)
    ignored_texts = get_ignored_texts(corrections)
    if corrections:
        print(f"\n[corrections] loaded {len(corrections)} entries "
              f"({len(approved_fixes)} verified → 词典,"
              f"{len(ignored_texts)} ignored → 永不审)", flush=True)

    state = _ProviderState()
    device_outputs = []
    for idx, dd in enumerate(device_list):
        if dd.get("error"):
            print(f"\n[SKIP] device {idx+1} had scan error: {dd['error']!r}", flush=True)
            continue
        if not dd.get("trees"):
            print(f"\n[SKIP] device {idx+1} has no trees", flush=True)
            continue
        try:
            device_outputs.append(_audit_one_device(
                dd, run_dir, idx, len(device_list), state, is_multi,
                approved_fixes=approved_fixes,
                ignored_texts=ignored_texts,
                aligned=aligned,
            ))
        except Exception as e:
            print(f"  ★ device {idx+1} audit failed: {e}", flush=True)
            traceback.print_exc()
            device_outputs.append({
                "device_label": dd.get("device_name", f"device_{idx+1}"),
                "device_safe_name": "",
                "error": str(e),
                "findings": [],
                "summary": {"findings_count": 0, "by_priority": {}, "by_issue_type": {}, "by_source": {}},
            })

    # Aggregate summary
    total_findings = sum(d["summary"]["findings_count"] for d in device_outputs)
    agg_pri = Counter()
    agg_type = Counter()
    for d in device_outputs:
        agg_pri.update(d["summary"]["by_priority"])
        agg_type.update(d["summary"]["by_issue_type"])

    overall_mode = device_outputs[0].get("audit_mode") if device_outputs else "no_devices"
    overall_model = device_outputs[0].get("model") if device_outputs else "(none)"

    # ★ corrections verification — 跨所有设备扫文本,确认 wrong 还在不在 / fix 出现没
    corrections_report = []
    if corrections:
        all_texts = collect_all_scan_texts(device_list)
        corrections_report = verify_corrections(corrections, all_texts)
        print(f"\n[corrections] verification:", flush=True)
        for c in corrections_report:
            tag = "🔴" if c["regression"] else ({
                "fix_applied":   "✅",
                "not_yet_fixed": "⏳",
                "both_present":  "⚠",
                "both_missing":  "—",
            }.get(c["observed_state"], "?"))
            print(f"  {tag} [{c['id']}] {c['observed_state']:15s} wrong={c['wrong_seen']} fix={c['fix_seen']}  "
                  f"'{c['wrong'][:30]}' → '{c['fix'][:30]}'", flush=True)

    output = {
        "generated_at": datetime.now().isoformat(),
        "scan_run": run_dir.name,
        "scan_captured_at": scan_captured_at,
        "is_multi_device": is_multi,
        "audit_mode": overall_mode,
        "model": overall_model,
        "summary": {
            "total_devices": len(device_outputs),
            "findings_count": total_findings,
            "by_priority": dict(agg_pri),
            "by_issue_type": dict(agg_type),
        },
        "corrections_report": corrections_report,
        "devices": device_outputs,
    }

    # 向后兼容:单设备 case 也把第一台的字段复制到顶层
    if not is_multi and device_outputs:
        d0 = device_outputs[0]
        for k in ("device_label", "plugin_version", "plugin_version_main",
                  "plugin_version_settings", "firmware_version", "findings"):
            if k in d0:
                output[k] = d0[k]

    return output


# ============================================================
# HTML 输出
# ============================================================

HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Findings — __DEVICE__</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
         margin: 0; background: #f5f5f7; color: #222; }
  header { background: #1d1d1f; color: #fff; padding: 14px 24px; position: sticky; top: 0; z-index: 10; }
  header .label { font-size: 11px; opacity: 0.5; text-transform: uppercase; letter-spacing: 1px; }
  header h1 { margin: 2px 0 4px 0; font-size: 22px; font-weight: 600; }
  header h1 .pill-mode { display: inline-block; background: #355; color: #fff; font-size: 10px;
                         padding: 2px 8px; border-radius: 3px; margin-left: 8px; vertical-align: middle;
                         font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
  header .meta { font-size: 11px; opacity: 0.55; font-family: monospace; }
  header .versions { font-size: 11px; margin-top: 4px; display: flex; gap: 16px; flex-wrap: wrap; }
  header .versions span { background: rgba(255,255,255,0.08); padding: 2px 8px; border-radius: 3px;
                           font-family: monospace; opacity: 0.85; }
  header .versions span.absent { opacity: 0.4; font-style: italic; }
  .summary { padding: 12px 24px; background: #fff; border-bottom: 1px solid #ddd;
             display: flex; gap: 24px; font-size: 13px; flex-wrap: wrap;
             position: sticky; top: 60px; z-index: 9; }
  .stat strong { color: #000; font-size: 15px; margin-right: 4px; }
  .stat.high strong { color: #c62828; }
  .stat.medium strong { color: #ef6c00; }
  .stat.low strong { color: #c79900; }
  .controls { background: #fff; padding: 12px 24px; border-bottom: 1px solid #ddd;
              display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
              position: sticky; top: 113px; z-index: 8; }
  .controls input[type=search] { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px;
                                  font-size: 13px; width: 320px; }
  .controls label { font-size: 12px; cursor: pointer; user-select: none; }
  main { padding: 16px 24px 64px; max-width: 1400px; margin: 0 auto; }
  .finding { background: #fff; border-radius: 6px; padding: 12px 16px; margin-bottom: 8px;
             border-left: 4px solid #ccc; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
  .finding.high { border-left-color: #d32f2f; }
  .finding.medium { border-left-color: #f57c00; }
  .finding.low { border-left-color: #fbc02d; }
  .finding.info { border-left-color: #9e9e9e; opacity: 0.7; }
  .row1 { display: flex; gap: 8px; align-items: center; font-size: 12px; flex-wrap: wrap; }
  .pill { padding: 2px 8px; border-radius: 3px; font-weight: 600; font-size: 10px;
          text-transform: uppercase; }
  .pill.high { background: #ffebee; color: #c62828; }
  .pill.medium { background: #fff3e0; color: #ef6c00; }
  .pill.low { background: #fffde7; color: #c79900; }
  .pill.info { background: #f5f5f5; color: #666; }
  .pill.issue { background: #e3f2fd; color: #1565c0; }
  .pill.source { background: #f3e5f5; color: #6a1b9a; }
  /* 位置 / breadcrumb 行 — 醒目地告诉用户问题在哪 */
  .location { margin-top: 8px; padding: 6px 10px; background: #f0f4ff;
              border-radius: 4px; border-left: 3px solid #3949ab;
              font-size: 12px; line-height: 1.5; }
  .location-label { font-weight: 600; color: #3949ab; margin-right: 6px;
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  .crumb { color: #444; font-weight: 500; }
  .crumb-sep { color: #999; margin: 0 4px; }
  .crumb-root { color: #888; font-style: italic; }
  .extra-paths { display: block; margin-top: 4px; font-size: 11px; color: #777; }
  .extra-paths .more-count { color: #3949ab; font-weight: 600; cursor: pointer; user-select: none; }
  .extra-paths-list { display: none; margin-top: 4px; padding-left: 12px;
                      border-left: 2px solid #d0d8f0; }
  .extra-paths-list.open { display: block; }
  .extra-paths-list .crumb-row { padding: 2px 0; font-size: 11px; color: #555; }
  /* ★/★★ row2 = 原文 → 建议译文 */
  .row2 { margin-top: 10px; font-size: 13px; line-height: 1.6; }
  .original { padding: 3px 8px; background: #f5f5f5; border-radius: 3px;
              display: inline-block; font-weight: 500;
              border: 1px solid #ddd; }
  .arrow { color: #888; margin: 0 8px; }
  .suggested { padding: 3px 8px; background: #e8f5e9; border-radius: 3px;
               display: inline-block; border: 1px solid #a5d6a7; }
  .rationale { font-size: 11px; color: #555; margin-top: 6px; }
  .hidden { display: none; }
  .empty { padding: 40px; text-align: center; color: #999; font-style: italic; }
</style>
</head>
<body>
<header>
  <div class="label">장치 / Device</div>
  <h1>__DEVICE__ <span class="pill-mode">__MODE__</span></h1>
  <div class="meta">scan: __SCAN_RUN__ · generated __TIMESTAMP__</div>
  <div class="versions">__VERSIONS_HTML__</div>
</header>
<div class="summary">
  <div class="stat"><strong id="total-count">__TOTAL__</strong>발견 항목 / findings</div>
  <div class="stat high"><strong>__HIGH__</strong>high</div>
  <div class="stat medium"><strong>__MEDIUM__</strong>medium</div>
  <div class="stat low"><strong>__LOW__</strong>low</div>
  <div class="stat" style="margin-left:auto;color:#666;" id="visible-count"></div>
</div>
<div class="controls">
  <input type="search" id="search" placeholder="원문 · 경로 · 설명 검색 / Search original, path, rationale...">
  <label><input type="checkbox" class="pri" value="high" checked> high (높음)</label>
  <label><input type="checkbox" class="pri" value="medium" checked> medium (보통)</label>
  <label><input type="checkbox" class="pri" value="low" checked> low (낮음)</label>
  <label><input type="checkbox" class="pri" value="info"> info (ok)</label>
</div>
<main id="content"></main>
<script>
const DATA = __DATA__;

function escapeHTML(s) {
  const m = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  return String(s).replace(/[&<>"']/g, c => m[c]);
}

// 把 path("A > B > C" 或 "<device_main_root>")渲染成可读面包屑
function renderCrumb(path) {
  if (!path) return '<span class="crumb-root">(unknown location)</span>';
  // 替换抽象 root 标签为人话
  const ROOT_LABELS = {
    "<device_main_root>": "📱 Device main page",
    "<settings_root>": "⚙ Settings page",
  };
  if (ROOT_LABELS[path]) return `<span class="crumb-root">${ROOT_LABELS[path]}</span>`;
  // breadcrumb: "A > B > C" → A › B › C
  const parts = path.split(" > ");
  return parts.map((p, i) => {
    const rendered = ROOT_LABELS[p]
      ? `<span class="crumb-root">${ROOT_LABELS[p]}</span>`
      : `<span class="crumb">${escapeHTML(p)}</span>`;
    return i === 0 ? rendered : `<span class="crumb-sep">›</span>${rendered}`;
  }).join("");
}

function render() {
  const c = document.getElementById("content");
  if (!DATA.findings.length) {
    c.innerHTML = '<div class="empty">발견된 문제가 없습니다 / No findings.</div>';
    return;
  }
  DATA.findings.forEach((f, idx) => {
    const div = document.createElement("div");
    div.className = "finding " + f.priority;
    div.dataset.priority = f.priority;
    const allPaths = f.all_paths && f.all_paths.length ? f.all_paths : [f.path];
    div.dataset.search = (f.original + " " + allPaths.join(" ") + " " + (f.rationale||"") + " " + f.issue_type + " " + (f.source||"")).toLowerCase();
    const suggestedHTML = f.suggested_translation
      ? `<span class="arrow">→</span><span class="suggested">${escapeHTML(f.suggested_translation)}</span>`
      : "";
    // 多 path 展开:第一条主显示,其它折叠
    const primaryPath = allPaths[0];
    const extraCount = allPaths.length - 1;
    let extraHTML = "";
    if (extraCount > 0) {
      const moreId = `more-${idx}`;
      const extras = allPaths.slice(1).map(p => `<div class="crumb-row">${renderCrumb(p)}</div>`).join("");
      extraHTML = `
        <div class="extra-paths">
          <span class="more-count" onclick="document.getElementById('${moreId}').classList.toggle('open')">
            ▾ ${extraCount}개 다른 위치에도 나타남 / Also in ${extraCount} other location${extraCount>1?'s':''} (펼치기 / click to expand)
          </span>
          <div class="extra-paths-list" id="${moreId}">${extras}</div>
        </div>`;
    }
    div.innerHTML = `
      <div class="row1">
        <span class="pill ${f.priority}">${f.priority}</span>
        <span class="pill issue">${escapeHTML(f.issue_type)}</span>
        <span class="pill source">${escapeHTML(f.source||"?")}</span>
      </div>
      <div class="location">
        <span class="location-label">📍 위치 / Location</span>
        ${renderCrumb(primaryPath)}
        ${extraHTML}
      </div>
      <div class="row2">
        <span class="original">${escapeHTML(f.original)}</span>
        ${suggestedHTML}
      </div>
      <div class="rationale">${escapeHTML(f.rationale||"")}</div>
    `;
    c.appendChild(div);
  });
  applyFilter();
}

function applyFilter() {
  const q = document.getElementById("search").value.toLowerCase();
  const enabled = new Set(Array.from(document.querySelectorAll(".pri:checked")).map(c => c.value));
  let v = 0;
  document.querySelectorAll(".finding").forEach(el => {
    let show = enabled.has(el.dataset.priority);
    if (show && q) show = el.dataset.search.includes(q);
    el.classList.toggle("hidden", !show);
    if (show) v++;
  });
  document.getElementById("visible-count").textContent = `${v}개 표시 중 / ${v} visible`;
}

render();
document.getElementById("search").addEventListener("input", applyFilter);
document.querySelectorAll(".pri").forEach(c => c.addEventListener("change", applyFilter));
</script>
</body></html>
"""

def write_outputs(output, run_dir: Path):
    json_path = run_dir / "findings.json"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # 多设备 case 不写 findings.html(被 viewer.html 取代),只产 findings.json
    if output.get("is_multi_device"):
        return json_path, None

    counts = output["summary"]["by_priority"]
    parts = []
    pm = output.get("plugin_version_main")
    ps = output.get("plugin_version_settings")
    fw = output.get("firmware_version")
    if pm:
        parts.append(f'<span>플러그인 (홈) / Plugin (main): {pm}</span>')
    if ps:
        parts.append(f'<span>플러그인 (설정) / Plugin (settings): {ps}</span>')
    if not pm and not ps:
        parts.append('<span class="absent">플러그인 / Plugin: (N/A)</span>')
    fw_cls = "" if fw else "absent"
    parts.append(f'<span class="{fw_cls}">펌웨어 / Firmware: {fw or "(N/A)"}</span>')
    versions_html = "\n    ".join(parts)
    html = (HTML_TEMPLATE
            .replace("__DEVICE__", output["device_label"])
            .replace("__SCAN_RUN__", output["scan_run"])
            .replace("__MODE__", output["audit_mode"])
            .replace("__TIMESTAMP__", output["generated_at"][:19])
            .replace("__TOTAL__", str(output["summary"]["findings_count"]))
            .replace("__HIGH__", str(counts.get("high", 0)))
            .replace("__MEDIUM__", str(counts.get("medium", 0)))
            .replace("__LOW__", str(counts.get("low", 0)))
            .replace("__VERSIONS_HTML__", versions_html)
            .replace("__DATA__", json.dumps(output, ensure_ascii=False)))
    html_path = run_dir / "findings.html"
    html_path.write_text(html, encoding="utf-8")
    return json_path, html_path


def find_latest_run():
    """找最近的 run dir(单设备 traverse_result.json 或多设备 all_devices_result.json 都算)。"""
    runs = sorted(
        [p for p in OUTPUT_ROOT.glob("traverse_v8_*")
         if (p / "traverse_result.json").exists() or (p / "all_devices_result.json").exists()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not runs:
        raise SystemExit("No traverse_v8_* run found")
    return runs[0]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phase 3 AI audit. 默认 ko-only,加 baseline 三语对比更准.")
    parser.add_argument("run_dir", nargs="?", default=None,
                        help="韩文 scan run dir(不给就用最新)")
    parser.add_argument("--baseline-zh", default=None,
                        help="可选:中文 scan run dir(对齐基线)")
    parser.add_argument("--baseline-en", default=None,
                        help="可选:英文 scan run dir(对齐基线)")
    args = parser.parse_args()

    run = Path(args.run_dir) if args.run_dir else find_latest_run()
    zh_run = Path(args.baseline_zh) if args.baseline_zh else None
    en_run = Path(args.baseline_en) if args.baseline_en else None
    print(f"Auditing: {run}")
    if zh_run: print(f"  baseline zh: {zh_run}")
    if en_run: print(f"  baseline en: {en_run}")
    print()
    output = audit_run(run, baseline_zh=zh_run, baseline_en=en_run)
    json_path, html_path = write_outputs(output, run)

    print()
    print(f"Mode:        {output['audit_mode']}")
    print(f"Model:       {output['model']}")
    print(f"Findings:    {output['summary']['findings_count']} unique")
    for pri, n in sorted(output['summary']['by_priority'].items(),
                         key=lambda kv: ['high','medium','low','info'].index(kv[0])):
        print(f"  {pri:>7}: {n}")
    print(f"By type:")
    for t, n in sorted(output['summary']['by_issue_type'].items(), key=lambda kv: -kv[1]):
        print(f"  {t:>18}: {n}")
    print()
    print(f"Outputs:")
    print(f"  JSON: {json_path}")
    if html_path:
        print(f"  HTML: {html_path}")
    if output.get("is_multi_device"):
        print(f"  (multi-device: run `python phase3_build_viewer.py {run}/` to build viewer.html with tabs)")
