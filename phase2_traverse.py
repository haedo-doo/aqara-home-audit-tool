# -*- coding: utf-8 -*-
"""Phase 2 v8：多设备流程 + 设备列表枚举 + 滚动 + 底部 Tab 过滤"""
import uiautomator2 as u2
import json, time, sys, traceback, re, argparse
from datetime import datetime
from pathlib import Path
from lxml import etree

print("[BOOT] script started", flush=True)

APP_PACKAGE = "com.lumiunited.aqarahome.play"
MENU_ITEM_ANCHORS = ["cl_root_layout", "item_layout"]
SETTINGS_ACTIVITY_HINT = "SettingPageListView"
RN_ACTIVITY_HINTS = ["LumiRN", ".arn."]

# ★ 设备列表页相关锚点
DEVICE_LIST_SCROLLER_ID = "rv_device_list"
DEVICE_CARD_ID = "container"
DEVICE_NAME_TEXT_ID = "tv_cell_left"

COMMON_SETTINGS_MENU_TITLES = [
    # 韩
    "장치 카드", "장치 설정", "신호 강도", "펌웨어 업데이트",
    "장치 로그", "장치 교체", "장치 검색", "장치 진단", "장비 진단",
    "기능 설정", "일반 설정", "Matter", "Matter 컨트롤러",
    "네트워크 정보", "장치 볼륨", "장치 언어", "방해 금지 모드",
    "맞춤 벨소리", "장치 오프라인 알림",
    # 中(2026-05-18 三语扫描加)
    "设备卡片", "设备设置", "信号强度", "固件升级", "固件更新",
    "设备日志", "更换设备", "搜索设备", "设备诊断", "装备诊断",
    "功能设置", "通用设置", "Matter控制器",
    "网络信息", "设备音量", "设备语言", "勿扰模式", "免打扰",
    "自定义铃声", "设备离线通知",
    # 英
    "Device Card", "Device Settings", "Signal Strength", "Firmware Update", "Firmware",
    "Device Log", "Replace Device", "Search Device", "Device Diagnosis", "Diagnostics",
    "Function Settings", "General Settings", "Matter Controller",
    "Network Info", "Network Information", "Device Volume", "Device Language",
    "Do Not Disturb", "DND", "Custom Ringtone", "Device Offline Notification",
]
DANGER_KEYWORDS = [
    "삭제", "제거", "초기화", "재설정", "교체", "탈퇴", "로그아웃", "끄기", "공장",
    "删除", "移除", "重置", "解绑", "退出", "注销", "关机", "恢复出厂", "更换",
    "Delete", "Remove", "Reset", "Unbind", "Logout", "Sign out", "Factory", "Replace",
]
DANGER_KEYWORDS_END_ONLY = [
    "종료", "켜기",                                       # 韩
    "退出", "结束", "打开", "开启", "启用",                # 中
    "Exit", "End", "Terminate", "Turn on", "Enable",     # 英
]
DANGER_CLASSES = ["Switch", "CheckBox"]
NAVIGATION_JUMP_KEYWORDS = [
    "연결된 허브", "허브",
    "连接的网关", "网关",
    "Connected Hub", "Hub", "Gateway",
    "하위장치", "하위 장치",
    "子设备", "子裝置", "下属设备",
    "Sub-device", "Sub Device", "Subdevice", "Child Device",
]
SAVE_PROMPT_KEYWORDS = [
    # 韩
    "수정 사항이 저장되지 않았",
    "저장되지 않은 변경",
    "변경사항이 저장되지",
    "변경 내용을 저장",
    # 中
    "未保存的更改", "未保存", "保存修改",
    # 英
    "Unsaved changes", "Discard changes", "save changes", "Save your changes",
]
# （绝不点击，只抓文本）
ACTION_BUTTON_EXACT = {
    # 韩
    "추가", "확인", "저장", "시작", "적용", "다음", "완료", "등록", "검색",
    "동의", "허용", "업데이트 확인", "업데이트",
    "기기 개인정보 보호 계약 승인 취소",
    "철회 확인",
    # 中
    "添加", "确认", "保存", "开始", "应用", "下一步", "完成", "注册", "搜索",
    "同意", "允许", "检查更新", "更新",
    # 英
    "Add", "Confirm", "Save", "Start", "Apply", "Next", "Done", "OK", "Register",
    "Search", "Agree", "Allow", "Check for updates", "Update",
    # 韩 — 付款/订阅(危险,只看不点)
    # "결제",
    "지금 결제", "결제하기", "구매", "구매하기", "구독", "구독하기",
    "업그레이드", "업그레이드하기", "계속",
    # 中 — 付款/订阅
    "支付", "立即支付", "立即购买", "购买", "订阅", "立即订阅", "升级", "继续",
    # 英 — 付款/订阅
    "Pay", "Pay Now", "Buy", "Buy Now", "Purchase", "Subscribe", "Upgrade",
    "Get Plus", "Continue",
}
# 选择类列表页（进入页面抓全部文本，但不点击任何选项）
CAPTURE_NO_RECURSE_KEYWORDS = [
    # === Add-* (添加类) ===
    "리모컨 추가", "장치 추가", "기기 추가", "액세서리 추가",
    "자동화 추가", "장면 추가", "동시실행 추가",
    "새 녹음 추가", "mp3 파일 가져오기", "장치 그룹 추가",
    "위치 지정", "방 추가",
    "添加遥控器", "添加设备", "添加配件", "添加自动化", "添加场景",
    "添加同步执行", "新录音", "导入MP3", "导入 MP3", "添加设备组",
    "指定位置", "选择位置", "添加房间",
    "Add Remote", "Add Device", "Add Accessory", "Add Automation",
    "Add Scene", "Add Sub-device", "Add Group", "Add Recording",
    "Import MP3", "Set Location", "Specify Location", "Add Room",
    # === 密码/PIN ===
    "비밀번호", "PIN", "암호", "password", "passcode", "Password",
    "密码", "口令",
    # === 语言/区域/国家 (选择列表) ===
    "언어", "지역", "국가",                # 韩
    "语言", "地区", "国家",                # 中
    "Language", "Region", "Country",       # 英
    # === 铃声/电源频率/红外/全屋监控 ===
    "벨소리", "전원 주파수", "야간 적외선",
    "铃声", "电源频率", "夜间红外", "夜视",
    "Ringtone", "Power Frequency", "Night IR", "Night Vision", "Infrared",
    "집 전체 감시", "전체 집 감시",
    "全屋监控", "整屋监控", "全屋监视",
    "Whole House Monitor", "Whole House Monitoring", "Home Monitoring",
    # === 位置/房间 ===
    "위치 지정", "장치 위치",                  # 韩 (★ P2 sensor 等子页是 room 选择器,每点 commit location)
    "指定位置", "设备位置", "选择位置",        # 中
    "Set Location", "Device Location", "Specify Location",  # 英
    "방 추가", "添加房间", "Add Room",
    # === 空调匹配/品牌选择 ===
    "에어컨 매칭", "브랜드 선택", "에어컨 모드 설정",
    "空调匹配", "匹配空调", "选择品牌", "空调模式", "空调模式设置",
    "AC Matching", "Match AC", "Select Brand", "Brand Selection",
    "AC Mode", "AC Mode Setting", "Set AC Mode",
    # === 固件版本(子页 — 别递归) ===
    "펌웨어 버전", "固件版本", "Firmware Version",
]
# === 选择器分支：path 命中以下关键字且不在末尾时，不再点击当前页子项 ===
# 这些菜单的二级子页是"动作选择页"（켜기/끄기/사람이 감지된 순간/...），
# 点击会立刻 commit 自动化规则；后续 BACK 弹"未保存"对话框，
# 即使我们点 확인 放弃，Aqara 也会直接踢回到设备列表，破坏整个遍历。
NO_CLICK_CHILDREN_UNDER_PATH = [
    # 韩
    "연관이벤트", "연관 이벤트",
    # 中(2026-05-18 三语扫描加)
    "关联事件", "关联的事件",
    # 英
    "Linked Events", "Related Events", "Associated Events",
]
PAGE_CONTENT_NO_RECURSE_MARKERS = [
    # 韩
    "브랜드 선택", "브랜드 검색",
    "국가 선택", "지역 선택", "언어 선택", "장치 관련 항목",
    "에어컨 매칭", "리모컨 매칭",
    # 中
    "选择品牌", "搜索品牌", "选择国家", "选择地区", "选择语言",
    "设备相关项目", "关联项目",
    "空调匹配", "匹配空调", "遥控器匹配",
    # 英
    "Select Brand", "Choose Brand", "Pick a Brand", "Search Brand",
    "Select Country", "Select Region", "Select Language",
    "Device-related Items", "Related Items",
    "AC Matching", "Match AC", "Remote Matching",
]
DIALOG_INFO_KEYWORDS = [
    # 韩 - 状态/错误
    "오프라인", "오프라인 상태", "찾을 수 없", "찾지 못했", "연결 실패",
    "에러", "오류", "실패", "알림", "주의", "안내",
    # ★ 韩 - 信息提示常见模式
    "할 수 있습니다", "할 수 있어요",     # "you can do X"
    "이용하실 수", "사용하실 수",
    "지원하지 않", "사용할 수 없",
    "에서 설정을", "페이지에서",          # ★ 命中"추가 설정 - 관련 장치 제어 페이지에서..."
    "추가 설정", "확인하세요",
    # 中
    "离线", "未找到", "连接失败", "错误", "失败", "提示",
    "可以在", "请在", "请前往",
    # 英
    "offline", "not found", "failed", "error", "notice", "alert", "unable",
    "you can", "please go to", "please tap",
]
CONFIRM_LABELS = {"확인", "OK", "Confirm", "알겠습니다", "确定", "确认"}
CANCEL_LABELS = {
    "취소", "닫기", "무시",        # 韩
    "Cancel", "Close", "Ignore", "Skip", "Later", "나중에",  # 英 + 韩混用
    "取消", "关闭", "忽略", "稍后",   # 中
}
DIALOG_DESTRUCTIVE_KEYWORDS = [
    "삭제", "리셋", "초기화", "제거", "교체", "포맷",
    "변경", "수정", "저장", "업데이트", "업그레이드",
    "재설정", "재시작", "복원", "복구",
    "delete", "reset", "remove", "replace", "format",
    "change", "save", "update", "upgrade", "restart", "restore",
    "删除", "重置", "更换", "保存", "更新",
]
LOADING_KEYWORDS = ["로딩 중", "로딩중", "Loading", "加载中", "잠시만"]
PROGRESS_PATTERN = re.compile(r"^\d{1,3}%$")

WAIT_POLL_INTERVAL = 0.5
WAIT_STABLE_THRESHOLD = 1.0
WAIT_MAX_NATIVE = 10.0
WAIT_MAX_RN = 25.0
WAIT_AFTER_BACK = 1.0
WAIT_AFTER_DEVICE_CLICK = 2.5  # 进入设备主页后等待时间
ACTIVITY_DETECT_DELAY = 0.8
BACK_MAX_ATTEMPTS = 5
MAX_DEPTH = 4
NOOP_OVERLAP_THRESHOLD = 0.9

# TODO(future-screen-portability): 下面 3 个常量是针对 1080×2220 标定的绝对像素阈值。
# 换大屏平板(item 渲染可能 > 300 高)或小屏手机(item 宽可能 < 200)时会漏抓。
# 改法:换成 screen size 比例,如 min_h = int(screen_h * 0.025), max_h = int(screen_h * 0.15),
# min_w = int(screen_w * 0.2)。详见 CLAUDE.md "未来计划 #3"。
HEURISTIC_MIN_HEIGHT = 50
HEURISTIC_MAX_HEIGHT = 300
HEURISTIC_MIN_WIDTH = 200
HEURISTIC_MIN_ITEMS_FOR_MENU = 3
BOTTOM_NAV_THRESHOLD_RATIO = 0.85   # 旧值 0.90 → 新值 0.85

# 多设备流程
SCROLL_NO_CHANGE_LIMIT = 2  # 连续 N 次滚动 sig 不变 → 视为见底

# ★ Locale 后缀(2026-05-15 加)— 支持三语扫描(中/英/韩对比)
# 模块级提前 peek argv,因为 argparse 在 main() 才跑但 OUTPUT_DIR 在 import 时建
# 用法:python phase2_traverse.py --locale zh   → dir 末尾加 _zh
#       python phase2_traverse.py              → 无后缀(韩文默认)
_LOCALE_SUFFIX = ""
if "--locale" in sys.argv:
    try:
        _LOCALE_SUFFIX = "_" + sys.argv[sys.argv.index("--locale") + 1]
    except (IndexError, ValueError):
        _LOCALE_SUFFIX = ""

OUTPUT_DIR = Path("./output") / ("traverse_v8_" + datetime.now().strftime("%Y%m%d_%H%M%S") + _LOCALE_SUFFIX)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ★ tee 所有 stdout 到 OUTPUT_DIR/run.log，方便事后/Claude 直接读日志
class _Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
    def flush(self):
        for st in self.streams:
            try: st.flush()
            except Exception: pass
_RUN_LOG_FH = open(OUTPUT_DIR / "run.log", "w", encoding="utf-8", buffering=1)
sys.stdout = _Tee(sys.__stdout__, _RUN_LOG_FH)
sys.stderr = _Tee(sys.__stderr__, _RUN_LOG_FH)

print(f"[BOOT] output dir: {OUTPUT_DIR.absolute()}", flush=True)

_SCREEN_SIZE = None

def is_under_chooser_action_branch(breadcrumb):
    """
    检查当前页是否处于'选择器分支'的动作层。
    breadcrumb = [..., '연관이벤트']           → False（设备列表，正常点）
    breadcrumb = [..., '연관이벤트', '면조명']  → True（动作选择，不点）
    """
    if not breadcrumb:
        return False
    for i, part in enumerate(breadcrumb):
        for kw in NO_CLICK_CHILDREN_UNDER_PATH:
            if kw in part:
                # 命中节点不在末尾 → 我们已经在它的子层了
                return i < len(breadcrumb) - 1
    return False

def detect_save_prompt_action(xml_str):
    """
    识别"未保存修改"弹窗。这种弹窗里 '확인' = 放弃修改并退出（=我们想要的）
    返回该弹窗里要点击的按钮，否则 None
    """
    sig = get_text_signature(xml_str)
    has_prompt = any(any(kw in t for kw in SAVE_PROMPT_KEYWORDS) for t in sig)
    if not has_prompt:
        return None
    for t in sig:
        if t.strip() in CONFIRM_LABELS:
            return t.strip()
    return None

# 在 device_main 树的元数据里新增字段
def extract_plugin_version(page_xml):
    """从主页/设置页 XML 中提取 '플러그인 버전: X.Y' 字样"""
    import re
    match = re.search(r"플러그인\s*버전[:\s]*([\d._]+)", page_xml)
    if match:
        return match.group(1)
    return None

def is_settings_page(sig):
    """页面是否像设备设置页：包含 ≥ 3 个标准设置菜单 → 不再触发 CAPTURE-ONLY-PAGE"""
    matches = sum(
        1 for t in sig 
        if any(menu in t for menu in COMMON_SETTINGS_MENU_TITLES)
    )
    return matches >= 3

def get_screen_size(device=None):
    global _SCREEN_SIZE
    if _SCREEN_SIZE is None and device is not None:
        try: _SCREEN_SIZE = device.window_size()
        except Exception: _SCREEN_SIZE = (1080, 2220)
    return _SCREEN_SIZE or (1080, 2220)


def safe_name(s):
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s)
    return re.sub(r"_+", "_", s).strip("_")[:60] or "unnamed"


def is_loading_text(t):
    if not t: return False
    if any(kw in t for kw in LOADING_KEYWORDS): return True
    if PROGRESS_PATTERN.match(t.strip()): return True
    return False


def has_loading_marker(xml):
    for node in etree.fromstring(xml.encode("utf-8")).iter("node"):
        if node.get("package") != APP_PACKAGE: continue
        if is_loading_text((node.get("text") or "").strip()): return True
    return False


def get_text_signature(xml):
    texts = set()
    for node in etree.fromstring(xml.encode("utf-8")).iter("node"):
        if node.get("package") != APP_PACKAGE: continue
        t = (node.get("text") or "").strip()
        if t and not is_loading_text(t):
            texts.add(t)
    return frozenset(texts)


def is_on_main_page(current_sig, main_sig, overlap_threshold=0.75, max_new_texts=2):
    """
    主页判定：
    - 主页文本大部分必须在当前页（forward overlap）
    - 当前页相对主页新增文本不能超过 max_new_texts
      子页/wizard 通常会引入 ≥2 条新文本（标题、新按钮等）
      主页自身动态变化（计数、时间戳）一般 ≤1 条
    """
    if not main_sig:
        return len(current_sig) == 0
    if not current_sig:
        return False
    forward = len(current_sig & main_sig) / len(main_sig)
    if forward < overlap_threshold:
        return False
    new_texts = current_sig - main_sig
    if len(new_texts) > max_new_texts:
        return False
    return True

def signatures_match(current, expected, threshold=0.8):
    if expected == current: return True
    if not expected: return False
    return len(current & expected) / len(expected) >= threshold


def signature_overlap(a, b):
    if not a or not b: return 0.0
    return len(a & b) / max(len(a), len(b))


def _has_webview(xml_str):
    """页面里是否含 WebView 节点(FAQ/用户 매뉴얼/사용약관 等远程加载页)"""
    return 'class="android.webkit.WebView"' in xml_str

def _has_active_progressbar(xml_str):
    """页面里是否有还在转/加载的 ProgressBar(progress < 100 或者无 progress 属性的 indeterminate)"""
    # 简单粗暴:含 ProgressBar 节点 → 视为加载中。
    # (有些应用的 ProgressBar 是常驻装饰品,但 Aqara 这套不是,所以这个判断对我们 OK)
    return 'class="android.widget.ProgressBar"' in xml_str

def wait_for_page_ready(device, max_total):
    """等页面稳定 + 不在加载状态。

    新增 WebView 特殊处理:
    - 如果页面有 WebView,sig 稳定不够(WebView 渲染 HTML 不会改 sig)
    - 必须等 ProgressBar 消失 OR 多等 5 秒,才认为 WebView 加载完
    """
    start = time.time()
    last_sig, stable_since, last_xml = None, None, ""
    webview_extra_wait = None  # 检测到 WebView 后开始的额外等待计时

    while time.time() - start < max_total:
        time.sleep(WAIT_POLL_INTERVAL)
        try: xml_str = device.dump_hierarchy()
        except Exception: continue
        last_xml = xml_str
        loading = has_loading_marker(xml_str)
        sig = get_text_signature(xml_str)
        is_webview = _has_webview(xml_str)
        has_progress = _has_active_progressbar(xml_str)

        if sig == last_sig and sig:
            if stable_since is None: stable_since = time.time()
            if not loading and time.time() - stable_since >= WAIT_STABLE_THRESHOLD:
                # ★ WebView 特殊处理:sig 稳定但页面是 WebView → 必须再等 ProgressBar 消失或额外 5 秒
                if is_webview and has_progress:
                    if webview_extra_wait is None:
                        webview_extra_wait = time.time()
                        print(f"      [WAIT] WebView+ProgressBar detected, waiting for content load...", flush=True)
                    elif time.time() - webview_extra_wait < 8.0:
                        # 继续等 ProgressBar 消失,最多 8 秒
                        continue
                    # 8 秒过了 ProgressBar 还在 → 放弃等,按 still_loading 返回
                    return xml_str, "still_loading_webview", time.time() - start
                elif is_webview and webview_extra_wait is None:
                    # WebView 已加载完(progress 不见了)→ 再多等 1 秒让 HTML 稳定
                    webview_extra_wait = time.time()
                    continue
                elif is_webview and time.time() - webview_extra_wait < 1.0:
                    continue
                return xml_str, "ready", time.time() - start
        else:
            last_sig, stable_since = sig, None
            webview_extra_wait = None  # sig 变了重置 WebView 额外等待

    elapsed = time.time() - start
    if _has_webview(last_xml) and _has_active_progressbar(last_xml):
        status = "still_loading_webview"
    elif has_loading_marker(last_xml):
        status = "still_loading"
    else:
        status = "unstable"
    return last_xml, status, elapsed


def is_dangerous(texts, classes):
    for t in texts:
        ts = t.strip()
        for kw in DANGER_KEYWORDS:
            if kw in ts: return True, f"keyword '{kw}' in '{t}'"
        for kw in DANGER_KEYWORDS_END_ONLY:
            if ts == kw or ts.endswith(" " + kw): return True, f"end-keyword '{kw}'"
    for c in classes:
        for d in DANGER_CLASSES:
            if d in c: return True, f"control class: {c}"
    return False, None


def is_navigation_jump(texts):
    for t in texts:
        for kw in NAVIGATION_JUMP_KEYWORDS:
            if kw in t: return True, f"jump '{kw}'"
    return False, None

def detect_dismissable_dialog(xml_str):
    """三层判断：取消优先 → 信息关键词 → 小页面+无破坏性 兜底"""
    sig = get_text_signature(xml_str)

    # 第一层：有 취소/무시/닫기 类按钮 → 永远首选（绝对安全）
    for t in sig:
        if t.strip() in CANCEL_LABELS:
            return t.strip()

    # 找确认按钮
    confirm_label = next(
        (t.strip() for t in sig if t.strip() in CONFIRM_LABELS), None
    )
    if not confirm_label:
        return None

    # 第二层：含信息类关键词 → 安全
    if any(any(kw in t for kw in DIALOG_INFO_KEYWORDS) for t in sig):
        return confirm_label

    # ★ 第三层：页面文本 ≤ 4 条 + 不含任何破坏性关键词 → 大概率是纯信息浮层
    if len(sig) <= 4:
        has_destructive = any(
            any(kw in t for kw in DIALOG_DESTRUCTIVE_KEYWORDS) for t in sig
        )
        if not has_destructive:
            return confirm_label

    return None


def is_action_button(texts):
    for t in texts:
        if t.strip() in ACTION_BUTTON_EXACT: return True, f"action: '{t}'"
    return False, None


# ★ 状态值/计数值的黑名单 — 这些不应该当 menu 的 primary_text。
# 用途:RN 的一行 item(如 "Matter | 연결됨 >")子节点 dump 顺序可能让"연결됨"排首位,
# 导致 primary_text 误成"연결됨",discovered_order 出现假项,click 后导航到意外页 → 重复抓取。
STATUS_VALUE_PATTERNS = {
    # 韩 - 连接/匹配/开关状态
    "연결됨", "연결 안됨", "연결되지 않음", "연결 안 됨",
    "꺼짐", "켜짐",
    "매칭됨", "매칭되지 않음", "매칭 안됨",
    "사용 중", "사용 안 함",
    "온라인", "오프라인",
    "정상", "비정상",
    # 中
    "已连接", "未连接", "已匹配", "未匹配", "在线", "离线",
    "开", "关", "正常", "异常",
    # 英
    "Connected", "Disconnected", "Matched", "Unmatched",
    "On", "Off", "Online", "Offline",
}

def _has_cjk(s):
    """是否含韩文/中文/日文字符 — 韩文 menu 通常是 CJK,'값'(value)常是英文/数字"""
    return any(
        '가' <= c <= '힯'    # 韩
        or '一' <= c <= '鿿' # 中
        or '぀' <= c <= 'ヿ' # 日
        for c in s
    )

def _pick_primary_text(texts):
    """从一行 item 多个 texts 里挑最能代表"菜单名"的:
    - 过滤明显的 filler:单字符/纯数字/状态值(연결됨,Connected 等)
    - 韩文 App 里 menu 名通常含 CJK 字符,value 多为英文/数字(Default Room/English/Aqara 等)
      → 候选中**优先返回含 CJK 的第一个**
    - 没含 CJK 的候选 → 返回候选中第一个(保留 DOM 顺序)
    - **全部都是 filler → 返回空串**(parse_menu_items 会把 primary='' 的 item 整个 SKIP,
       因为这种 clickable 容器只装了状态值/数字,不是真菜单 — 典型场景:RN 导航后 L0 stale 容器
       残留在 L1 hierarchy 里,Matter TextView 被 unmount 但容器还有 '연결됨' 子节点)
    """
    if not texts: return ""
    def _is_filler(s):
        s = s.strip()
        if not s or len(s) <= 1: return True
        if s.isdigit(): return True
        if s in STATUS_VALUE_PATTERNS: return True
        return False
    candidates = [t for t in texts if not _is_filler(t)]
    if not candidates:
        return ""  # 整个 item 没有有意义的 label → 让 parse_menu_items 跳过
    cjk = [t for t in candidates if _has_cjk(t)]
    if cjk:
        return cjk[0]
    return candidates[0]


def parse_menu_items_known(xml_str):
    root = etree.fromstring(xml_str.encode("utf-8"))
    items = []
    for node in root.iter("node"):
        rid = node.get("resource-id", "") or ""
        if not any(rid.endswith(a) for a in MENU_ITEM_ANCHORS): continue
        if node.get("clickable") != "true": continue
        texts, classes = [], []
        for c in node.iter("node"):
            t = (c.get("text") or "").strip()
            d = (c.get("content-desc") or "").strip()
            if t: texts.append(t)
            elif d: texts.append(f"[desc]{d}")
            cls = c.get("class") or ""
            if cls: classes.append(cls)
        if texts:
            primary = _pick_primary_text(texts)
            if not primary:
                # primary 为空 = 所有 texts 都是 filler(状态值/数字/单字符)→ 跳过这种 ghost 容器
                continue
            items.append({"texts": texts, "primary_text": primary,
                         "bounds": node.get("bounds", ""),
                         "classes_inside": classes, "anchor": "known"})
    return items


def parse_menu_items_heuristic(xml_str):
    root = etree.fromstring(xml_str.encode("utf-8"))
    _, screen_h = get_screen_size()
    bottom_cutoff = screen_h * BOTTOM_NAV_THRESHOLD_RATIO  # ★ 排除底部
    items = []
    for node in root.iter("node"):
        if node.get("clickable") != "true": continue
        if node.get("package") != APP_PACKAGE: continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        h, w = y2 - y1, x2 - x1
        if h < HEURISTIC_MIN_HEIGHT or h > HEURISTIC_MAX_HEIGHT: continue
        if w < HEURISTIC_MIN_WIDTH: continue
        if y1 > bottom_cutoff: continue  # ★ 底部 nav bar 排除
        texts, classes = [], []
        for c in node.iter("node"):
            t = (c.get("text") or "").strip()
            d = (c.get("content-desc") or "").strip()
            if t: texts.append(t)
            elif d: texts.append(f"[desc]{d}")
            cls = c.get("class") or ""
            if cls: classes.append(cls)
        if texts:
            primary = _pick_primary_text(texts)
            if not primary:
                continue
            items.append({"texts": texts, "primary_text": primary,
                         "bounds": bounds, "classes_inside": classes, "anchor": "heuristic"})
    return items


def parse_menu_items(xml_str):
    items = parse_menu_items_known(xml_str)
    if items: return items
    items = parse_menu_items_heuristic(xml_str)
    if items:
        print(f"      [HEURISTIC] {len(items)} items", flush=True)
    return items

# 加过滤
def extract_app_texts(xml_str):
    root = etree.fromstring(xml_str.encode("utf-8"))
    app_texts, sys_texts = [], []
    for node in root.iter("node"):
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        if not t and not d: continue
        cls = node.get("class", "").split(".")[-1]
        text_value = t if t else d
        
        # ★ Image class 节点的 text 几乎全是 base64/资源名/装饰字符 —— 跳过
        if cls == "Image":
            continue
        # ★ 排除明显是 base64 / data URI 编码的内容
        if "base64," in text_value or text_value.startswith(("svg+xml;", "png;", "jpeg;", "data:")):
            continue
        # ★ 排除 CSS-style 资源名（kebab-case 含数字后缀）
        if re.match(r"^[a-z0-9]+(-[a-z0-9]+){2,}$", text_value):
            continue
        # ★ 排除单字符（除了真正会用的标点）
        if len(text_value) == 1 and text_value not in {"·", "•", "/"}:
            continue
        # ★ 排除疑似纯 base64 残段（≥20 字符，全部是 base64 字符集）
        if len(text_value) >= 20 and re.match(r"^[A-Za-z0-9+/=]+$", text_value):
            continue
        
        item = {"text": text_value, "type": "text" if t else "content_desc", "class": cls}
        if node.get("package") == APP_PACKAGE: app_texts.append(item)
        else: sys_texts.append(item)
    return app_texts, sys_texts


def click_by_bounds(device, bounds):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not m: return False
    x1, y1, x2, y2 = map(int, m.groups())
    device.click((x1 + x2) // 2, (y1 + y2) // 2)
    return True


def looks_like_menu_page(xml_str):
    return len(parse_menu_items_heuristic(xml_str)) >= HEURISTIC_MIN_ITEMS_FOR_MENU


def is_on_settings_page(device, lenient=True):
    """
    lenient=True(默认,nav helper 点完后用):宽松判定 — 1 个 anchor 或 menu-like 页面就算
    lenient=False(Phase B 入口用):严格判定 — 要求 activity hint 或 ≥3 个 anchor
        (修复 M2 hub bug:它主页只有 1 个 "리모컨 추가" item_layout,被误判已在设置页,
         导致 Phase B 静默跳过 nav)
    """
    try:
        if SETTINGS_ACTIVITY_HINT in device.app_current().get("activity", ""):
            return True
        xml = device.dump_hierarchy()
        anchor_count = sum(
            1 for node in etree.fromstring(xml.encode("utf-8")).iter("node")
            if any((node.get("resource-id", "") or "").endswith(a) for a in MENU_ITEM_ANCHORS)
        )
        if lenient:
            if anchor_count >= 1: return True
            if looks_like_menu_page(xml): return True
        else:
            # 严格模式:真设置页一般 ≥3 items;只有 1 个 anchor 多半是设备主页的 "추가" 行
            if anchor_count >= 3: return True
    except Exception: pass
    return False


def find_top_right_clickables(xml_str, screen_w, screen_h):
    root = etree.fromstring(xml_str.encode("utf-8"))
    candidates = []
    for node in root.iter("node"):
        if node.get("package") != APP_PACKAGE: continue
        if node.get("clickable") != "true": continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        w, h = x2 - x1, y2 - y1
        if w > screen_w * 0.5 or h > 300: continue
        cx = (x1 + x2) / 2
        if cx > screen_w * 0.75 and y1 < screen_h * 0.15:
            candidates.append((cx - y1, x1, y1, x2, y2, bounds))
    candidates.sort(reverse=True)
    return [(x1, y1, x2, y2, b) for (_, x1, y1, x2, y2, b) in candidates]


def auto_navigate_to_settings(device):
    activity = device.app_current().get("activity", "")
    print(f"  [NAV] current: {activity.split('.')[-1]}", flush=True)
    btn = device(resourceId=f"{APP_PACKAGE}:id/layout_title_right")
    if btn.exists:
        print(f"  [NAV] S1", flush=True)
        btn.click(); time.sleep(2.0)
        if is_on_settings_page(device): return True
        for label in ["설정", "设置", "Settings"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device): return True
    for kw in ["설정", "더보기", "메뉴", "옵션", "Settings", "More", "Menu"]:
        elem = device(descriptionContains=kw)
        if elem.exists:
            print(f"  [NAV] S2: '{kw}'", flush=True)
            elem.click(); time.sleep(2.0)
            if is_on_settings_page(device): return True
    for kw in ["설정", "设置", "Settings"]:
        elem = device(text=kw)
        if elem.exists:
            print(f"  [NAV] S3: '{kw}'", flush=True)
            elem.click(); time.sleep(2.0)
            if is_on_settings_page(device): return True

    screen_w, screen_h = get_screen_size(device)
    xml = device.dump_hierarchy()
    sig_anchor = get_text_signature(xml)
    candidates = find_top_right_clickables(xml, screen_w, screen_h)
    print(f"  [NAV] S4: {len(candidates)} candidates", flush=True)
    for x1, y1, x2, y2, bounds in candidates[:3]:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        print(f"  [NAV] S4: tap {bounds}", flush=True)
        device.click(cx, cy); time.sleep(2.0)
        if is_on_settings_page(device):
            print(f"  [NAV] arrived via S4", flush=True)
            return True
        for label in ["설정", "设置", "Settings", "기기 설정"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device): return True
        sig_after = get_text_signature(device.dump_hierarchy())
        if not signatures_match(sig_after, sig_anchor, threshold=0.9):
            device.press("back"); time.sleep(1.0)
            sig_check = get_text_signature(device.dump_hierarchy())
            if not signatures_match(sig_check, sig_anchor, threshold=0.9):
                return False
    # S5: 窄面板 RN 设备（如 M3 hub，内容面板 < 屏幕宽度）
    # 把 cx 阈值从 0.75 放宽到 0.55，但加严尺寸约束（只找小图标按钮）
    # 同时排除左边缘（避免点到返回按钮）
    xml = device.dump_hierarchy()
    s5_candidates = []
    for node in etree.fromstring(xml.encode("utf-8")).iter("node"):
        if node.get("package") != APP_PACKAGE: continue
        if node.get("clickable") != "true": continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        w, h = x2 - x1, y2 - y1
        if w > 200 or h > 120: continue           # 小图标尺寸
        if y1 >= int(screen_h * 0.10): continue   # 顶部
        if x1 < screen_w * 0.10: continue         # 排除左边缘（避免返回按钮）
        cx = (x1 + x2) / 2
        if cx <= screen_w * 0.55: continue        # 中心至少在右半屏
        # 必须没有 text 后代
        if any((c.get("text") or "").strip() for c in node.iter("node")):
            continue
        s5_candidates.append((x1, y1, x2, y2, bounds))

    s5_candidates.sort(key=lambda c: -c[0])  # 最右优先
    print(f"  [NAV] S5: {len(s5_candidates)} narrow-panel icon candidates", flush=True)
    for x1, y1, x2, y2, bounds in s5_candidates[:3]:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        print(f"  [NAV] S5: tap {bounds}", flush=True)
        device.click(cx, cy); time.sleep(2.0)
        if is_on_settings_page(device):
            print(f"  [NAV] arrived via S5", flush=True)
            return True
        for label in ["설정", "设置", "Settings", "기기 설정"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device):
                    return True
        device.press("back"); time.sleep(1.0)

    # S6: WebView 内 top-right icon(2026-05-13 加)
    # 触发设备:FP2 region sensing 模式 — 整个主页是个 WebView,"..." 按钮
    # class=android.widget.Image,clickable=false(JS 侧捕获 tap),S4/S5 都过滤掉。
    # 思路:不要求 clickable,只看几何 + class/text hint,坐标点击。
    xml = device.dump_hierarchy()
    s6_candidates = []
    for node in etree.fromstring(xml.encode("utf-8")).iter("node"):
        if node.get("package") != APP_PACKAGE: continue
        cls = node.get("class", "")
        # 只看 Image 或裸 View(WebView 内的图标节点常是这两类)
        if cls not in ("android.widget.Image", "android.view.View"): continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        w, h = x2 - x1, y2 - y1
        # 图标尺寸(不要点中整页 WebView 容器)
        if w == 0 or h == 0 or w > 200 or h > 200: continue
        cx = (x1 + x2) / 2
        # 顶部右侧区
        if cx <= screen_w * 0.75: continue
        if y1 >= int(screen_h * 0.15): continue
        # text 含 base64(WebView 中嵌的 PNG 图标)是强信号,优先
        text = (node.get("text") or "").strip()
        priority = 1 if ("base64" in text or "data:image" in text) else 0
        # 排除"返回按钮"区:返回箭头通常 x1 < 200 — 但 cx>0.75*w 已经排除了左半
        # 排除整页容器:已经过 size 检查
        s6_candidates.append((priority, -x1, x1, y1, x2, y2, bounds))

    s6_candidates.sort(reverse=True)  # priority desc,然后最右优先
    print(f"  [NAV] S6: {len(s6_candidates)} webview icon candidates", flush=True)
    for _, _, x1, y1, x2, y2, bounds in s6_candidates[:3]:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        print(f"  [NAV] S6: tap {bounds} (coord-only, WebView)", flush=True)
        device.click(cx, cy); time.sleep(2.5)
        if is_on_settings_page(device):
            print(f"  [NAV] arrived via S6", flush=True)
            return True
        for label in ["설정", "设置", "Settings", "기기 설정"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device): return True
        sig_after = get_text_signature(device.dump_hierarchy())
        if not signatures_match(sig_after, sig_anchor, threshold=0.9):
            device.press("back"); time.sleep(1.0)

    # 全部 fallback 失败 → 存证据
    try:
        xml = device.dump_hierarchy()
        (OUTPUT_DIR / "phase_b_nav_failed.xml").write_text(xml, encoding="utf-8")
        device.screenshot(str(OUTPUT_DIR / "phase_b_nav_failed.png"))
        print(f"  [NAV] all strategies failed, saved phase_b_nav_failed.xml + .png for diagnosis", flush=True)
    except Exception as e:
        print(f"  [NAV] dump failed: {e}", flush=True)
    return False


def navigate_back_to_signature(device, expected_sig, max_attempts=2):
    """最多 2 次 BACK 找到匹配父页 —— 多了就放弃，避免按穿"""
    for attempt in range(max_attempts + 1):
        try:
            current_sig = get_text_signature(device.dump_hierarchy())
            if signatures_match(current_sig, expected_sig):
                if attempt > 0:
                    print(f"      [BACK] settled after {attempt}", flush=True)
                return True
        except Exception: pass
        if attempt < max_attempts:
            device.press("back"); time.sleep(1.0)
    return False


def safe_print(msg):
    try: print(msg, flush=True)
    except Exception: print(repr(msg), flush=True)

def scroll_page_up(device):
    """向上滚动一屏 60%(用 0.2→0.8 大行程,duration 0.3 加 fling)"""
    screen_w, screen_h = get_screen_size(device)
    device.swipe(screen_w // 2, int(screen_h * 0.20),
                 screen_w // 2, int(screen_h * 0.80), 0.3)
    time.sleep(0.8)


def scroll_capture_full_page(device, initial_xml, max_scrolls=15):   # ★ 4 → 15
    """
    长内容页面用：从顶部往下滚动，累积所有唯一文本，最后滚回顶。
    """
    all_texts = []
    seen_keys = set()

    def merge(xml):
        texts, _ = extract_app_texts(xml)
        added = 0
        for t in texts:
            tx = (t.get("text") or "").strip()
            if not tx:
                continue
            key = (tx, t.get("class", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                all_texts.append(t)
                added += 1
        return added

    merge(initial_xml)

    no_change = 0
    scrolls_done = 0
    for _ in range(max_scrolls):
        scroll_page_down(device)
        time.sleep(0.7)               # ★ 0.4 → 0.7（WebView 渲染慢一点）
        scrolls_done += 1
        try:
            xml = device.dump_hierarchy()
        except Exception:
            break
        added = merge(xml)
        if added == 0:
            no_change += 1
            if no_change >= 3:        # ★ 2 → 3（更严格的"见底"判定）
                break
        else:
            no_change = 0

    # 滚回顶
    for _ in range(scrolls_done + 1):
        scroll_page_up(device)

    try:
        final_xml = device.dump_hierarchy()
    except Exception:
        final_xml = initial_xml
    return all_texts, final_xml


def scroll_page_down(device):
    """通用向下滚动一屏 60%(用 0.8→0.2 大行程,duration 0.3 加 fling)。
    M3 hub 之前用 0.7→0.3 + duration 0.5 跑不动 RN ScrollView,改大。"""
    screen_w, screen_h = get_screen_size(device)
    sx = screen_w // 2
    device.swipe(sx, int(screen_h * 0.80),
                 sx, int(screen_h * 0.20), 0.3)
    time.sleep(0.8)

def scroll_page_to_top(device, max_attempts=6):
    """连续 swipe up 直到 sig 不再变化（fling-to-top）"""
    last_sig = None
    stable_count = 0
    for _ in range(max_attempts):
        try:
            cur_sig = get_text_signature(device.dump_hierarchy())
        except Exception:
            break
        if cur_sig == last_sig:
            stable_count += 1
            if stable_count >= 2:
                break
        else:
            stable_count = 0
            last_sig = cur_sig
        scroll_page_up(device)


def _detect_webview_faq_questions(xml_str):
    """检测是否为 WebView FAQ-like 页面,返回每个问题 TextView 的 (text, bounds_center) list。

    判定:
    - 页面含 WebView class
    - 有 ≥3 个 TextView 的 text 以问号结尾(? 或 ?)
    返回:[(question_text, (cx, cy)), ...],按 y 坐标升序
    """
    if 'class="android.webkit.WebView"' not in xml_str:
        return []
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
    except Exception:
        return []
    questions = []
    for node in root.iter("node"):
        if node.get("class") != "android.widget.TextView":
            continue
        t = (node.get("text") or "").strip()
        if not t: continue
        if not (t.endswith("?") or t.endswith("?")): continue
        if len(t) < 5: continue  # 太短不太可能是问题
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        questions.append((t, (cx, cy), y1))
    questions.sort(key=lambda q: q[2])  # 按 y 升序
    return [(q[0], q[1]) for q in questions]


def probe_faq_expansions(device, sub_xml, sname_base, output_dir):
    """WebView FAQ 页面专用:依次点击每个 question 让答案展开,保存 expanded 状态截图。

    用途:FAQ 详细答案是 HTML 内容,UIAutomator dump 看不到,但截图能完整记录。
    给 Phase 3 Vision OCR 用。

    返回:抓到的问题数(0 表示这页不是 FAQ 类型)。
    """
    questions = _detect_webview_faq_questions(sub_xml)
    if not questions:
        return 0
    print(f"      [FAQ-PROBE] {len(questions)} questions detected; tapping each + screenshot", flush=True)
    for idx, (qtext, (cx, cy)) in enumerate(questions, 1):
        try:
            device.click(cx, cy)
            time.sleep(1.0)  # 等展开动画
            shot_path = output_dir / f"{sname_base}__q{idx:02d}.png"
            device.screenshot(str(shot_path))
            # collapse 试图把当前 question 再点一下,让下一次循环不受叠加影响
            device.click(cx, cy)
            time.sleep(0.6)
        except Exception as e:
            print(f"      [FAQ-PROBE] q{idx} ({qtext[:30]}...) failed: {e}", flush=True)
    return len(questions)


def discover_all_titles(device, max_scrolls=20):
    """L0 进入时调用：在点击任何 item 之前，先 fling-top + 反复 scroll-down 把整个页面
    扫一遍，把所有 item primary_text 按首见顺序收集起来。

    Why upfront：M3 hub 类 RN 页面，点击会触发"内嵌展开/重排"，事后 fling-top 也回不到
    最初的视图状态 —— 顶部一些 item 会永远丢失。在任何 click 前完成扫描可以避免这种丢失。

    完成后会 scroll-to-top，把页面留在顶端给主循环使用。

    多重兜底:
    1. swipe scroll(0.8→0.2,duration 0.3) × max_scrolls 次,no_change>=3 break
    2. 若 swipe 没收到任何新 item,尝试 uiautomator2 原生 scrollable.fling.toEnd 兜底
    3. 再做一次 fling.toEnd 后 dump 一次,补漏底部
    """
    scroll_page_to_top(device)
    discovered_order = []
    discovered_set = set()

    def _absorb(xml):
        items = parse_menu_items(xml)
        added = 0
        for it in items:
            pt = it["primary_text"]
            if pt not in discovered_set:
                discovered_set.add(pt)
                discovered_order.append(pt)
                added += 1
        return added

    # 首屏 absorb
    try:
        _absorb(device.dump_hierarchy())
    except Exception:
        pass

    no_change = 0
    for _ in range(max_scrolls):
        scroll_page_down(device)
        try:
            xml = device.dump_hierarchy()
        except Exception:
            break
        added = _absorb(xml)
        if added == 0:
            no_change += 1
            if no_change >= 3:
                break
        else:
            no_change = 0

    # ★ 兜底:uiautomator2 原生 fling-to-end(对 RN ScrollView 比 swipe 更可靠)
    try:
        sc = device(scrollable=True)
        if sc.exists:
            sc.fling.toEnd(max_swipes=5)
            time.sleep(1.0)
            _absorb(device.dump_hierarchy())
            # 再 fling 一次确认到了真底端
            sc.fling.toEnd(max_swipes=3)
            time.sleep(1.0)
            _absorb(device.dump_hierarchy())
    except Exception as e:
        print(f"      [DISCOVER] fling.toEnd fallback failed: {e}", flush=True)

    # 把页面留在顶端
    scroll_page_to_top(device)
    return discovered_order


def find_item_by_title(device, title):
    """多层兜底:在当前页找 primary_text==title 的 item。
    返回 (item_dict | None, xml_at_find)。

    Layer 1: 当前 dump 直接找
    Layer 2: scroll-up 2 次重试
    Layer 3: fling-top + 反复 scroll-down 找
    Layer 4: device(text=title) 走 uiautomator2 的 accessibility 查找(对虚化列表特别有用)
    """
    # Layer 1
    xml = device.dump_hierarchy()
    items = parse_menu_items(xml)
    for it in items:
        if it["primary_text"] == title:
            return it, xml
    # Layer 2
    for _ in range(2):
        scroll_page_up(device)
        xml = device.dump_hierarchy()
        items = parse_menu_items(xml)
        for it in items:
            if it["primary_text"] == title:
                return it, xml
    # Layer 3
    scroll_page_to_top(device)
    for _ in range(8):
        xml = device.dump_hierarchy()
        items = parse_menu_items(xml)
        for it in items:
            if it["primary_text"] == title:
                return it, xml
        scroll_page_down(device)
    # Layer 4
    try:
        ele = device(text=title)
        if ele.exists:
            info = ele.info
            bb = info.get("bounds") or {}
            if all(k in bb for k in ("left", "top", "right", "bottom")):
                bs = f"[{bb['left']},{bb['top']}][{bb['right']},{bb['bottom']}]"
                item = {
                    "texts": [title], "primary_text": title,
                    "bounds": bs, "classes_inside": [info.get("className", "") or ""],
                    "anchor": "ui2-fallback",
                }
                return item, device.dump_hierarchy()
    except Exception:
        pass
    return None, xml


def new_dismiss_buttons(parent_sig, sub_sig):
    """返回 sub 中新出现而 parent 中没有的 취소/확인 类按钮"""
    parent_btns = {t.strip() for t in parent_sig 
                   if t.strip() in CANCEL_LABELS or t.strip() in CONFIRM_LABELS}
    sub_btns = {t.strip() for t in sub_sig 
                if t.strip() in CANCEL_LABELS or t.strip() in CONFIRM_LABELS}
    return sub_btns - parent_btns

def parent_content_preserved(parent_sig, sub_sig):
    """父页文本中有多少比例仍在 sub 里。1.0 = 父页完全被包含 → 大概率没跳页"""
    parent_set = set(parent_sig)
    sub_set = set(sub_sig)
    if not parent_set:
        return 0.0
    return len(parent_set & sub_set) / len(parent_set)


def _try_recover_to_settings(device, expected_sig, indent=""):
    """[Fix B,2026-05-13] L0 ABORT-LEVEL-VANISHED 前的恢复尝试。

    场景:RN 类设备(M3 hub / P2 / G4 摄像机 等)L0 末尾几个 title VANISHED,
    其实不是真没那个 menu,只是 device 被前面的 click 顶到了某个未知中间页。
    重新走 Phase B nav("..." 按钮)往往能回到 settings 页继续点剩下的 title。

    返回 True = 已恢复到 settings 页(sig 跟 expected_sig 大致匹配);False = 救不回来。
    """
    try:
        # 1. 如果已经被弹回设备列表 → 救不了
        if is_on_device_list(device):
            return False
        # 2. 已经在 settings 页(或 sig 近似)→ 直接 OK
        try:
            cur_sig = get_text_signature(device.dump_hierarchy())
            if signatures_match(cur_sig, expected_sig, threshold=0.7):
                return True
        except Exception:
            pass
        # 3. BACK 几次试着退到 device main(注意:Native device main 上 BACK 必出设备,
        #    所以每按一次都要检查 device_list)
        for _ in range(3):
            if is_on_device_list(device):
                return False
            # 如果当前页 sig 跟 expected_sig 匹配,直接 OK 不再 BACK
            try:
                cur_sig = get_text_signature(device.dump_hierarchy())
                if signatures_match(cur_sig, expected_sig, threshold=0.7):
                    return True
            except Exception:
                pass
            # 如果已经在 settings(用 lenient=False 严格判定) → break,直接 nav 检查
            if is_on_settings_page(device, lenient=False):
                break
            device.press("back")
            time.sleep(1.2)
        # 4. 用 auto_navigate_to_settings 找右上 "..." 重进设置
        if not is_on_settings_page(device, lenient=False):
            if not auto_navigate_to_settings(device):
                return False
        # 5. 最终 sig check(用更宽松 0.5 阈值 — 设置页可能因状态变化与原 sig 有些 drift)
        try:
            cur_sig = get_text_signature(device.dump_hierarchy())
            return signatures_match(cur_sig, expected_sig, threshold=0.5)
        except Exception:
            return False
    except Exception as e:
        print(f"{indent}  [VANISH-RECOVERY] exception: {e}", flush=True)
        return False


def traverse_recursive(device, breadcrumb, results, visited_sigs, depth=0, ancestor_sigs=None):
    if ancestor_sigs is None:
        ancestor_sigs = []

    indent = "  " * depth
    if depth > MAX_DEPTH:
        print(f"{indent}[DEPTH] hit MAX_DEPTH={MAX_DEPTH}", flush=True)
        return

    if breadcrumb:
        for kw in CAPTURE_NO_RECURSE_KEYWORDS:
            if kw in breadcrumb[-1]:
                print(f"{indent}[CAPTURE-ONLY-PARENT] '{breadcrumb[-1]}'", flush=True)
                return
    # ★ NEW: 选择器分支下不再迭代子项（防 commit 自动化规则）
    if is_under_chooser_action_branch(breadcrumb):
        print(f"{indent}[SKIP-CHOOSER-BRANCH] under chooser action page, not clicking children", flush=True)
        return

    # ★★★ 新增：进入此层前先关闭可能存在的拦截浮层（最多连续关 3 个）
    for _ in range(3):
        entry_xml = device.dump_hierarchy()
        entry_sig = get_text_signature(entry_xml)
        # 文本 > 5 条已经像真页面，不再尝试关闭
        if len(entry_sig) > 5:
            break
        dismiss_label = detect_dismissable_dialog(entry_xml)
        if not dismiss_label:
            break
        print(f"{indent}[ENTRY-DIALOG] dismissing '{dismiss_label}'", flush=True)
        try:
            btn = device(text=dismiss_label)
            if btn.exists:
                btn.click()
                time.sleep(1.5)
            else:
                break
        except Exception:
            break

    page_xml = device.dump_hierarchy()
    page_sig = get_text_signature(page_xml)
    parent_act = device.app_current().get("activity", "")
    new_ancestors = ancestor_sigs + [page_sig]   # ★ 给子层用
    # ★ 先判断这是不是个设置页
    is_settings = is_settings_page(page_sig)

    for marker in PAGE_CONTENT_NO_RECURSE_MARKERS:
        if any(marker in t for t in page_sig):
            # ★ 设置页里出现 marker 关键词 = 仅仅是某个菜单项标签，不是真的"内容专属页"
            if is_settings:
                continue
            print(f"{indent}[CAPTURE-ONLY-PAGE] '{marker}'", flush=True)
            return

    items = parse_menu_items(page_xml)
    if not items:
        return

    bc = " > ".join(breadcrumb) if breadcrumb else "(root)"
    print(f"{indent}[L{depth}] {len(items)} items visible at: {bc}", flush=True)

    seen_titles = set()
    consecutive_sheets = 0
    consecutive_dialogs = 0   # 连续 [DIALOG] auto-dismiss 计数
    consecutive_vanished = 0  # ★ 连续 VANISHED 计数 — 防止 CHOOSER drift 后空跑整个 discovered_order

    # ★★ Upfront discovery —— 在任何 click 前先 fling-top + 反复 scroll-down 扫一遍，
    # 拿到全量 item 列表。这样后续点击即便改变页面状态（M3 hub 类 RN 页常见），
    # 我们仍知道还有哪些 title 没处理。每个 title 用 find_item_by_title 定位 bounds。
    discovered_order = discover_all_titles(device)
    discovered_set = set(discovered_order)
    print(f"{indent}[L{depth}] upfront discovery: {len(discovered_order)} items total", flush=True)
    # ★ 打印发现的 title 列表(方便核对漏抓),长度太多就分行
    for idx, t in enumerate(discovered_order, 1):
        print(f"{indent}    #{idx:02d} {t!r}", flush=True)

    # discover_all_titles 末尾会 scroll-to-top；这里刷新 page_sig + new_ancestors 给下游 NO-OP/CYCLE 检测用
    page_xml = device.dump_hierarchy()
    page_sig = get_text_signature(page_xml)
    new_ancestors[-1] = page_sig

    def _record_items(items_list):
        """累计记录在迭代过程中新出现的 item title(防止 click 触发的新内容漏过)"""
        added = 0
        for it in items_list:
            pt = it["primary_text"]
            if pt not in discovered_set:
                discovered_set.add(pt)
                discovered_order.append(pt)
                added += 1
        return added

    while True:
        # ★ 从 discovered_order 取下一个未处理 title（保持首见顺序，决定遍历顺序）
        next_title = next((t for t in discovered_order if t not in seen_titles), None)

        if next_title is None:
            # 全部 title 都处理过了。最后机会:dump 一次 + fling-top 各 record 一次，
            # 看看有没有 click 中新冒出来还没记进 discovered 的 item
            try:
                cur_items = parse_menu_items(device.dump_hierarchy())
                if _record_items(cur_items) > 0:
                    continue
            except Exception:
                pass
            scroll_page_to_top(device)
            try:
                top_items = parse_menu_items(device.dump_hierarchy())
                if _record_items(top_items) > 0:
                    continue
            except Exception:
                pass
            print(f"{indent}  [DONE-LEVEL] {len(seen_titles)} processed, {len(discovered_order)} discovered", flush=True)
            return

        # ★ 多层兜底找当前 title 对应的 item:scroll-up → fling-top + scroll-down → ui2 text 查找
        item, page_xml = find_item_by_title(device, next_title)
        items = parse_menu_items(page_xml) if page_xml else []
        _record_items(items)

        if item is None:
            print(f"{indent}  [VANISHED] '{next_title}' no longer findable on screen", flush=True)
            seen_titles.add(next_title)
            results.append({
                "path": " > ".join(breadcrumb + [next_title]),
                "depth": depth + 1,
                "status": "vanished",
            })
            consecutive_vanished += 1
            # ★ 连续 3 个 VANISHED → 说明 device 已经 drift 到未知页(典型场景:CHOOSER 后 BACK 落在中间页),
            # 继续按 discovered_order 找剩下的 title 全会 VANISHED + 浪费 12+ 次 dump/项。
            if consecutive_vanished >= 3:
                # ★ 2026-05-13 Fix B: 在 abort 前尝试一次 re-nav 回 settings 续扫
                # (针对 RN drift 场景:M3 hub / P2 / 摄像机 等末尾几项 VANISHED 是因为 device 状态被点击顶飞,
                # 不是真的没那项;重新走 Phase B nav 回设置页通常能恢复)
                remaining = [t for t in discovered_order if t not in seen_titles]
                if depth == 0 and remaining and len(remaining) >= 2:
                    print(f"{indent}  [VANISH-RECOVERY] {len(remaining)} titles still unprocessed, attempting re-nav...", flush=True)
                    if _try_recover_to_settings(device, page_sig, indent):
                        consecutive_vanished = 0
                        # 重置 page_xml + items 等下一轮 loop 用新 dump
                        print(f"{indent}  [VANISH-RECOVERY] re-nav OK, resuming with {len(remaining)} unprocessed titles", flush=True)
                        continue
                    else:
                        print(f"{indent}  [VANISH-RECOVERY] re-nav failed, aborting level", flush=True)
                print(f"{indent}  [ABORT-LEVEL-VANISHED] {consecutive_vanished} consecutive VANISHEDs, device likely drifted; return", flush=True)
                return
            continue

        title = item["primary_text"]
        seen_titles.add(title)
        consecutive_vanished = 0  # 成功找到一个 item,重置连续 VANISHED 计数
        full_path = breadcrumb + [title]
        path_str = " > ".join(full_path)

        # === 安全过滤（与原版相同）===
        is_d, dr = is_dangerous(item["texts"], item["classes_inside"])
        if is_d:
            print(f"{indent}  [SKIP-DANGER] {title}: {dr}", flush=True)
            results.append({"path": path_str, "depth": depth+1, "status": "skipped_danger",
                           "reason": dr, "all_texts_on_card": item["texts"]})
            continue
        is_j, jr = is_navigation_jump(item["texts"])
        if is_j:
            print(f"{indent}  [SKIP-JUMP] {title}: {jr}", flush=True)
            results.append({"path": path_str, "depth": depth+1, "status": "skipped_jump",
                           "reason": jr, "all_texts_on_card": item["texts"]})
            continue
        is_a, ar = is_action_button(item["texts"])
        if is_a:
            print(f"{indent}  [SKIP-ACTION] {title}: {ar}", flush=True)
            results.append({"path": path_str, "depth": depth+1, "status": "skipped_action",
                           "reason": ar, "all_texts_on_card": item["texts"]})
            continue

        print(f"{indent}  [CLICK L{depth+1}] {title}", flush=True)
        if not click_by_bounds(device, item["bounds"]):
            results.append({"path": path_str, "depth": depth+1, "status": "click_failed"})
            continue

        time.sleep(ACTIVITY_DETECT_DELAY)
        sub_act = device.app_current().get("activity", "")
        is_rn = any(h in sub_act for h in RN_ACTIVITY_HINTS)
        max_wait = WAIT_MAX_RN if is_rn else WAIT_MAX_NATIVE
        sub_xml, ready_status, elapsed = wait_for_page_ready(device, max_total=max_wait)
        sub_sig = get_text_signature(sub_xml)

        # NO-OP check 1: 传统重叠（页面几乎完全相同）
        if signature_overlap(sub_sig, page_sig) >= NOOP_OVERLAP_THRESHOLD:
            print(f"{indent}    [NO-OP]", flush=True)
            results.append({"path": path_str, "depth": depth+1, "status": "no_navigation",
                        "all_texts_on_card": item["texts"]})
            continue

        preservation = parent_content_preserved(page_sig, sub_sig)
        new_btns = new_dismiss_buttons(page_sig, sub_sig)

        # ★ NEW: items-based 二次确认（防 RN 容器 shell 文本占多导致误判 NO-OP-SCROLL）
        parent_item_titles = {i["primary_text"] for i in items}
        sub_item_titles = {i["primary_text"] for i in parse_menu_items(sub_xml)}
        if parent_item_titles:
            items_preserved = len(parent_item_titles & sub_item_titles) / len(parent_item_titles)
        else:
            items_preserved = 1.0

        # ★ 第三种检测：底部弹窗（同 activity + 父页保留 + 新 취소/확인 按钮）
        is_bottom_sheet = (
            sub_act == parent_act 
            and preservation >= 0.9 
            and len(new_btns) > 0
        )

        if is_bottom_sheet:
            print(f"{indent}    [BOTTOM-SHEET] detected, new buttons: {new_btns}", flush=True)

            # 抓取弹窗内容
            app_texts, _ = extract_app_texts(sub_xml)
            sname = safe_name(path_str) or f"d{depth}_{len(seen_titles)}"
            device.screenshot(str(OUTPUT_DIR / f"{sname}.png"))
            (OUTPUT_DIR / f"{sname}.xml").write_text(sub_xml, encoding="utf-8")
            
            results.append({
                "path": path_str, "depth": depth+1, "status": "captured",
                "all_texts_on_card": item["texts"],
                "sub_page_activity": sub_act, "is_rn_plugin": is_rn,
                "ready_status": ready_status, "wait_elapsed_sec": round(elapsed, 1),
                "app_text_count": len(app_texts), "app_texts": app_texts,
                "is_bottom_sheet": True,                         # ★ 标记类型
                "new_dialog_buttons": list(new_btns),
                "anchor_used": item.get("anchor", "?"),
            })
            print(f"{indent}    [OK] {len(app_texts)} ({elapsed:.1f}s) [SHEET]", flush=True)

            # ★ 必须用 취소 关闭，绝不 BACK（BACK 会跨级退出）
            cancel_label = None
            for label in new_btns:
                if label in CANCEL_LABELS:
                    cancel_label = label
                    break
            
            if cancel_label:
                try:
                    print(f"{indent}    [SHEET] dismissing with '{cancel_label}'", flush=True)
                    btn = device(text=cancel_label)
                    if btn.exists:
                        btn.click(); time.sleep(1.0)
                except Exception as e:
                    print(f"{indent}    [SHEET] click failed: {e}", flush=True)
            else:
                # 弹窗里没有 취소，只有 확인 → 检查是否是信息类弹窗
                info_dismiss = detect_dismissable_dialog(sub_xml)
                if info_dismiss:
                    print(f"{indent}    [SHEET] info-only, dismissing with '{info_dismiss}'", flush=True)
                    try:
                        btn = device(text=info_dismiss)
                        if btn.exists:
                            btn.click(); time.sleep(1.0)
                    except Exception:
                        pass
                else:
                    # 无安全关闭路径 — 不递归不 BACK，留给下一轮自然处理
                    print(f"{indent}    [SHEET] no safe dismiss, leaving as-is", flush=True)
            
            # ★ 连续 BOTTOM-SHEET 计数：3 次以上判定为品牌/设备列表页
            consecutive_sheets += 1
            if consecutive_sheets >= 3:
                print(f"{indent}  [ABORT-LIST-PAGE] {consecutive_sheets} consecutive bottom-sheets, likely a brand/device list, stopping iteration", flush=True)
                return

            # 关键：跳过递归 + 跳过下面的标准 BACK 流程
            continue

        # ★ 这次点击不是 bottom-sheet → 重置连续计数
        consecutive_sheets = 0

        # ★ NEW: 检测点击是否揭示了一个 chooser/list 页面
        # （PAGE_CONTENT_NO_RECURSE_MARKERS 中的文本在 sub 出现，但 parent 没有 → 真的进了选择器）
        new_markers = [
            marker for marker in PAGE_CONTENT_NO_RECURSE_MARKERS
            if any(marker in t for t in sub_sig)
            and not any(marker in t for t in page_sig)
        ]
        if new_markers:
            print(f"{indent}    [CHOOSER-REVEALED] '{new_markers[0]}' appeared, capture-only", flush=True)
            # ★ 用 scroll_capture 累积抓取所有品牌/选项（chooser 页常 ≥100 条，单帧 dump 抓不全）
            #    scroll_capture_full_page 在最后会滚回顶，方便接下来 BACK 退出
            app_texts, full_xml = scroll_capture_full_page(device, sub_xml)
            sub_xml_for_save = full_xml or sub_xml
            sname = safe_name(path_str) or f"d{depth}_{len(seen_titles)}"
            try:
                device.screenshot(str(OUTPUT_DIR / f"{sname}.png"))
                (OUTPUT_DIR / f"{sname}.xml").write_text(sub_xml_for_save, encoding="utf-8")
            except Exception:
                pass
            results.append({
                "path": path_str, "depth": depth + 1, "status": "captured_chooser",
                "all_texts_on_card": item["texts"],
                "sub_page_activity": sub_act, "is_rn_plugin": is_rn,
                "ready_status": ready_status, "wait_elapsed_sec": round(elapsed, 1),
                "app_text_count": len(app_texts), "app_texts": app_texts,
                "chooser_markers": new_markers,
                "anchor_used": item.get("anchor", "?"),
            })
            print(f"{indent}    [OK] {len(app_texts)} chooser texts (scroll-captured)", flush=True)

            # ★ BACK 退出 chooser → 回父页 → 继续迭代下一项
            # 关键:这里**不能再用 navigate_back_to_signature 多按 BACK**——
            # 之前 max_attempts=2 会再多按 2 下 BACK,从 chooser 一路顶过 L2/L1/device main,
            # 导致 L1 后续 7+ items(包括 자주하는 질문/사용자 매뉴얼/펌웨어 버전 等)全部 abort。
            # 改:只按 1 下 BACK,然后用宽松阈值(0.7)查;如果没回到父页,**记录 'chooser_back_drift'
            # 但不 return**,让父循环的 post-recurse 处理来自行决定怎么回(或继续找下一个 title)。
            try:
                device.press("back"); time.sleep(1.5)
            except Exception:
                pass
            cur_sig_after_back = get_text_signature(device.dump_hierarchy())
            if not signatures_match(cur_sig_after_back, page_sig, threshold=0.7):
                # CHOOSER BACK 落到未知页(典型:Default Room → 장치 관련 항목 commit chooser → BACK 后到了一个 8-item 中间页,既不是 L2 也不是 L1)。
                # ★ 不能 continue 让本层主循环空跑(每个剩余 title 都会经历 12 次 dump 然后 VANISHED,慢 + 没意义);
                # 改:return 把控制权交给上层 post-recurse,上层有 5-BACK 渐进恢复,能更直接处理。
                print(f"{indent}    [CHOOSER] BACK landed off parent — return to let caller recover", flush=True)
                return
            continue

        # ★ 如果点击对象在 CAPTURE_NO_RECURSE_KEYWORDS 里 ...
        title_forces_navigation = any(kw in title for kw in CAPTURE_NO_RECURSE_KEYWORDS)

        # ★ 新文本量：真正的导航通常会引入大量新文本(页头/列表/按钮)，
        # 而内嵌展开/滚动 即使损失了一些 items，新文本通常 ≤ 3 条。
        new_texts_in_sub = sub_sig - page_sig
        new_text_count = len(new_texts_in_sub)

        # NO-OP check 2: 真正的滚动/展开（不是弹窗 / 不是导航）
        # 三条任一满足都算 scroll-only:
        #   A 经典严格：preservation>=0.9 且 items_preserved>=0.7
        #   B 兜底（M3 hub 类长设置页）：preservation>=0.8 且新文本 ≤3 条
        #     —— "几乎没有新内容" 是 inline-expansion 的强信号，即使 items 重排得多。
        #   C 同 items 矩阵(2026-05-13 修): items_preserved>=0.95
        #     —— "items 几乎完全一样" 说明这是 mode toggle 按钮矩阵或状态切换,
        #     即使文字大变(状态详情更新)也不是真子页 — 治浴霸/T1-1 这类设备的递归爆炸
        is_strong_scroll = (preservation >= 0.9 and items_preserved >= 0.7)
        is_minor_change = (preservation >= 0.8 and new_text_count <= 3)
        is_mode_toggle = (items_preserved >= 0.95)
        if (sub_act == parent_act
            and (is_strong_scroll or is_minor_change or is_mode_toggle)
            and not title_forces_navigation):
            reason = "mode-toggle" if (is_mode_toggle and not is_strong_scroll and not is_minor_change) else "scroll"
            print(f"{indent}    [NO-OP-SCROLL] text {preservation:.0%}, items {items_preserved:.0%}, new={new_text_count} ({reason})", flush=True)
            results.append({"path": path_str, "depth": depth+1, "status": "no_navigation_scroll",
                        "all_texts_on_card": item["texts"],
                        "parent_preservation": round(preservation, 2),
                        "items_preserved": round(items_preserved, 2),
                        "new_text_count": new_text_count,
                        "scroll_reason": reason})
            continue

        # ★ 长内容页面检测：少菜单 + 多文本 → 滚动累积抓取
        items_in_sub = parse_menu_items(sub_xml)
        initial_texts, _ = extract_app_texts(sub_xml)
        if len(initial_texts) >= 10 and len(items_in_sub) <= 2:
            print(f"{indent}    [SCROLL-CAPTURE] long-content page, accumulating...", flush=True)
            app_texts, sub_xml = scroll_capture_full_page(device, sub_xml)
            sub_sig = get_text_signature(sub_xml)
            print(f"{indent}    [SCROLL-CAPTURE] {len(initial_texts)} → {len(app_texts)} texts", flush=True)
        else:
            app_texts = initial_texts

        captured_loading = ready_status == "still_loading"
        sname = safe_name(path_str) or f"d{depth}_{len(seen_titles)}"
        device.screenshot(str(OUTPUT_DIR / f"{sname}.png"))
        (OUTPUT_DIR / f"{sname}.xml").write_text(sub_xml, encoding="utf-8")

        # ★ WebView FAQ 类页面探测:如有 ≥3 个 "?" 结尾的 TextView → 依次 tap 各问题,保存展开后截图。
        # 详细答案是 WebView HTML(dump 看不到),只能 Phase 3 用 Vision OCR 截图。
        faq_probed = probe_faq_expansions(device, sub_xml, sname, OUTPUT_DIR)

        results.append({
            "path": path_str, "depth": depth+1, "status": "captured",
            "all_texts_on_card": item["texts"],
            "sub_page_activity": sub_act, "is_rn_plugin": is_rn,
            "ready_status": ready_status, "wait_elapsed_sec": round(elapsed, 1),
            "app_text_count": len(app_texts), "app_texts": app_texts,
            "needs_recapture": captured_loading,
            "needs_ocr": is_rn and captured_loading,
            "anchor_used": item.get("anchor", "?"),
            "faq_expansions_probed": faq_probed if faq_probed else None,
        })
        loading_marker = " [STILL_LOADING]" if captured_loading else ""
        faq_marker = f" [FAQ:{faq_probed}q]" if faq_probed else ""
        print(f"{indent}    [OK] {len(app_texts)} ({elapsed:.1f}s){loading_marker}{faq_marker}", flush=True)

        # === 信息弹窗自动关闭（保留你之前的补丁）===
        dismiss_label = detect_dismissable_dialog(sub_xml)
        if dismiss_label:
            print(f"{indent}    [DIALOG] '{dismiss_label}', dismissing", flush=True)
            results[-1]["is_dismissable_dialog"] = True
            results[-1]["dismiss_label"] = dismiss_label
            try:
                btn = device(text=dismiss_label)
                if btn.exists:
                    btn.click(); time.sleep(1.0)
            except Exception:
                pass
            current_sig = get_text_signature(device.dump_hierarchy())
            if not signatures_match(current_sig, page_sig, threshold=0.85):
                device.press("back"); time.sleep(1.0)
            # ★ NEW: 连续 dialog 计数，5 次以上判定卡在 chooser 上
            consecutive_dialogs += 1
            if consecutive_dialogs >= 5:
                print(f"{indent}  [ABORT-DIALOG-LOOP] {consecutive_dialogs} consecutive dialogs, likely stuck on chooser/list page, stopping iteration", flush=True)
                return
            continue

        # ★ 走到这里说明是成功导航（没 dialog）→ 重置计数
        consecutive_dialogs = 0

        if sub_sig in visited_sigs:
            is_ancestor_cycle = any(
                signatures_match(sub_sig, anc, threshold=0.85) for anc in new_ancestors
            )
            if is_ancestor_cycle:
                print(f"{indent}    [CYCLE-UP] sub-page is an ancestor, drifted up", flush=True)
                results[-1]["status"] = "cycle_up"
                # 不递归，下面的统一回退检查会处理
            else:
                print(f"{indent}    [CYCLE]", flush=True)
        else:
            visited_sigs.add(sub_sig)
            traverse_recursive(device, full_path, results, visited_sigs,
                            depth=depth+1, ancestor_sigs=new_ancestors)

        # === 回退到父页前先确认当前位置 ===
        current = get_text_signature(device.dump_hierarchy())

        # Case A: 我们已经在自己这一层的页（子层 drift 回来 / CYCLE-UP 后停在这）
        # 用宽松阈值 0.7(原 0.85):chooser-back-drift / 选项被选中导致 sig 细微变化时仍认为已恢复
        if signatures_match(current, page_sig, threshold=0.7):
            continue   # 不需要 BACK，直接处理下一项

        # Case B: 我们已经飘到更上层的祖先页 → 不能再 BACK，会继续往上越界
        if any(signatures_match(current, anc, threshold=0.85) for anc in ancestor_sigs):
            print(f"{indent}  [DRIFT-UP] on ancestor page, return without BACK", flush=True)
            return

        # Case C: 正常情况，我们在子页 → BACK 回父页
        device.press("back"); time.sleep(WAIT_AFTER_BACK)

        # ★ 检查 BACK 是否触发了"未保存修改"对话框
        try:
            post_back_xml = device.dump_hierarchy()
            save_action = detect_save_prompt_action(post_back_xml)
            if save_action:
                print(f"{indent}  [SAVE-PROMPT] unsaved-changes dialog, clicking '{save_action}' to discard", flush=True)
                btn = device(text=save_action)
                if btn.exists:
                    btn.click(); time.sleep(1.5)
        except Exception as e:
            print(f"{indent}  [SAVE-PROMPT] check failed: {e}", flush=True)

        # ★ 渐进式恢复:不再轻易 ABORT-LEVEL。
        # 之前的 max_attempts=2(总 3 次 BACK) 一爆就 abort 整层 → 漏抓后面所有未处理 items。
        # 改为:依次按 BACK 最多 5 次,每次按完用**宽松阈值 0.7** 查;只要回到 page_sig 就 continue。
        # 完全恢复不了才 abort —— 而且 abort 前先 check 是不是已经飘到祖先(若是,DRIFT-UP 安全返回)。
        recovered = False
        for back_attempt in range(5):
            try:
                cur = get_text_signature(device.dump_hierarchy())
            except Exception:
                cur = frozenset()
            if signatures_match(cur, page_sig, threshold=0.7):
                if back_attempt > 0:
                    print(f"{indent}  [RECOVER] settled at parent after {back_attempt+1} extra BACK(s)", flush=True)
                recovered = True
                break
            # 检查飘到了祖先 → DRIFT-UP 安全返回(不再按 BACK 越界)
            if any(signatures_match(cur, anc, threshold=0.7) for anc in ancestor_sigs):
                print(f"{indent}  [DRIFT-UP] on ancestor during recovery, return", flush=True)
                return
            try:
                device.press("back"); time.sleep(WAIT_AFTER_BACK)
            except Exception:
                break
        if not recovered:
            print(f"{indent}  [ABORT-LEVEL] could not recover after 5 BACKs", flush=True)
            return

def capture_page_snapshot(device, label, file_prefix):
    xml = device.dump_hierarchy()
    sig = get_text_signature(xml)
    (OUTPUT_DIR / f"{file_prefix}.xml").write_text(xml, encoding="utf-8")
    device.screenshot(str(OUTPUT_DIR / f"{file_prefix}.png"))
    app_texts, _ = extract_app_texts(xml)
    return {"label": label, "activity": device.app_current().get("activity", ""),
            "sig": sig, "xml": xml, "page_app_texts": app_texts}


# ========== ★ Phase 1B：多设备流程 ==========

def is_on_device_list(device):
    """在设备清单页 + '장치' Tab 当前为选中状态"""
    try:
        xml = device.dump_hierarchy()
        # 必须有 RecyclerView
        if f":id/{DEVICE_LIST_SCROLLER_ID}" not in xml:
            return False
        # 且 장치 Tab 必须 checked=true
        for node in etree.fromstring(xml.encode("utf-8")).iter("node"):
            rid = node.get("resource-id", "") or ""
            if rid.endswith(":id/btn_device_list"):
                return node.get("checked", "false") == "true"
    except Exception: pass
    return False


def enumerate_device_cards(xml_str):
    """枚举设备卡片，跳过被底部 Tab 栏遮挡的"""
    root = etree.fromstring(xml_str.encode("utf-8"))
    _, screen_h = get_screen_size()
    safe_y_max = screen_h * 0.85  # ★ 中心点 y 必须 < 屏幕 85% 才安全
    
    cards = []
    for node in root.iter("node"):
        rid = node.get("resource-id", "") or ""
        if not rid.endswith(f":id/{DEVICE_CARD_ID}"): continue
        if node.get("clickable") != "true": continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        cy = (y1 + y2) // 2
        # ★ 跳过中心被 Tab 栏遮挡的卡片
        if cy >= safe_y_max:
            continue
        device_name = None
        for child in node.iter("node"):
            if child.get("resource-id", "").endswith(f":id/{DEVICE_NAME_TEXT_ID}"):
                t = (child.get("text") or "").strip()
                if t:
                    device_name = t
                    break
        if device_name:
            cards.append({"name": device_name, "bounds": bounds})
    return cards


def scroll_device_list_down(device):
    """向下滑设备列表"""
    screen_w, screen_h = get_screen_size(device)
    sx = screen_w // 2
    sy = int(screen_h * 0.7)
    ey = int(screen_h * 0.3)
    device.swipe(sx, sy, sx, ey, 0.5)
    time.sleep(1.2)


def return_to_device_list(device):
    """三层恢复：tab tap → 少量 BACK → app restart"""
    if is_on_device_list(device):
        return True

    # 第一层：直接点 장치 Tab（最可靠）
    try:
        tab = device(resourceId=f"{APP_PACKAGE}:id/btn_device_list")
        if tab.exists:
            print("    [RECOVERY] tapping 장치 tab", flush=True)
            tab.click()
            time.sleep(2.0)
            if is_on_device_list(device):
                return True
    except Exception:
        pass

    # 第二层：尝试少量 BACK（最多 2 次，避免按穿）
    for _ in range(2):
        device.press("back"); time.sleep(1.0)
        if is_on_device_list(device):
            return True
        # 每次 BACK 后再试一次 tab tap
        try:
            tab = device(resourceId=f"{APP_PACKAGE}:id/btn_device_list")
            if tab.exists:
                tab.click(); time.sleep(2.0)
                if is_on_device_list(device):
                    return True
        except Exception:
            pass

    # 第三层：核选项 —— **强制冷重启** App(stop + start;app_start 单独不会真重启)
    # 2026-05-14 修:之前只调 app_start 等价 "拉到前台",app 还在 P2 settings 子页 → tab 找不到 → 抛错
    print("    [RECOVERY] force-restarting app (stop + start)", flush=True)
    try:
        try:
            device.app_stop(APP_PACKAGE)
            time.sleep(1.5)
        except Exception as e:
            print(f"    [RECOVERY] app_stop warning: {e}", flush=True)
        device.app_start(APP_PACKAGE)
        # cold start 需要更久 — 等 RecyclerView 出现或 8s 超时
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if is_on_device_list(device):
                print(f"    [RECOVERY] app restarted, already on device list", flush=True)
                return True
            try:
                tab = device(resourceId=f"{APP_PACKAGE}:id/btn_device_list")
                if tab.exists:
                    print(f"    [RECOVERY] app restarted, tapping 장치 tab", flush=True)
                    tab.click()
                    time.sleep(2.5)
                    if is_on_device_list(device):
                        return True
                    break  # tap 了但还不在 list,跳出 wait 循环
            except Exception:
                pass
            time.sleep(0.5)
        # 最后再 dump 一次确认
        if is_on_device_list(device):
            return True
        print(f"    [RECOVERY] after restart, still not on device list", flush=True)
    except Exception as e:
        print(f"    [RECOVERY] app restart failed: {e}", flush=True)
    return False

def traverse_one_device(device, label):
    """对一台设备完整跑 Phase A + B"""
    visited_sigs = set()
    result = {
        "device_name": label,
        "scanned_at": datetime.now().isoformat(),   # ★ 新增
        "plugin_version": None,                      # ★ 新增（先占位）
        "trees": [],
    }
    device_safe = safe_name(label)

    # ====== Phase A: 设备主页 ======
    print(f"  [PHASE A] {label} main page", flush=True)
    main_snap = capture_page_snapshot(device, "device_main", f"{device_safe}_main")
    visited_sigs.add(main_snap["sig"])
    # ★ 从主页 XML 提取 plugin version
    pv = extract_plugin_version(main_snap["xml"])
    if pv:
        result["plugin_version"] = pv
        print(f"  [PLUGIN] version: {pv}", flush=True)

    # ★ 用 dict() 构造（不可能写成 set），并用独立的 list 变量
    main_items_list = []
    main_tree = dict(
        label="device_main",
        activity=main_snap["activity"],
        page_texts=main_snap["page_app_texts"],
        items=main_items_list,
    )
    print(f"  [PHASE A] main page texts: {len(main_snap['page_app_texts'])}", flush=True)
    if parse_menu_items(main_snap["xml"]):
        traverse_recursive(device, [], main_items_list, visited_sigs, depth=0)
    result["trees"].append(main_tree)

    # ★ Phase A 收尾：BACK 最多 5 次以确保回到主页
    main_sig = main_snap["sig"]
    # Phase A cleanup：BACK 回主页（最多 5 次）
    screen_w, screen_h = get_screen_size(device)
    main_activity = main_snap["activity"]
    is_rn_device = any(h in main_activity for h in RN_ACTIVITY_HINTS)
    for back_attempt in range(5):
        # ★ 守卫 1：activity 变了 → 已经 BACK 出当前设备 → 停（再 BACK 没意义）
        current_activity = device.app_current().get("activity", "")
        if current_activity != main_activity:
            print(f"  [PHASE A] cleanup: drifted to '{current_activity.split('.')[-1]}' (was '{main_activity.split('.')[-1]}'), stopping", flush=True)
            break
        # ★ 守卫 2：在主页 → 停
        current_sig = get_text_signature(device.dump_hierarchy())
        if is_on_main_page(current_sig, main_sig):
            if back_attempt > 0:
                print(f"  [PHASE A] cleanup: returned to main after {back_attempt} BACK(s)", flush=True)
            break
        # ★ 守卫 3(2026-05-13 新):Native 设备(activity 不含 LumiRN/.arn.)在 main activity 上 BACK 必然弹回设备列表 →
        # 即使 sig 略不匹配(state 刷新/动态计数)也不要再 BACK
        if not is_rn_device:
            forward = len(current_sig & main_sig) / max(len(main_sig), 1)
            new_count_check = len(current_sig - main_sig)
            print(f"  [PHASE A] cleanup: on Native device main activity (overlap {forward:.0%}, new={new_count_check}), BACK would exit device, stopping", flush=True)
            break
        new_count = len(current_sig - main_sig)
        print(f"  [PHASE A] cleanup: not on main (attempt {back_attempt+1}/5, |current|={len(current_sig)}, |main|={len(main_sig)}, new={new_count}), pressing BACK", flush=True)
        device.press("back"); time.sleep(1.5)
        try:
            save_action = detect_save_prompt_action(device.dump_hierarchy())
            if save_action:
                btn = device(text=save_action)
                if btn.exists:
                    print(f"  [PHASE A] cleanup: dismissing save-prompt with '{save_action}'", flush=True)
                    btn.click(); time.sleep(1.5)
        except Exception:
            pass
    else:
        print(f"  [PHASE A] cleanup: WARN failed to return to main after 5 BACKs", flush=True)
    # 安全检查：如果意外退回了设备清单，跳过 Phase B
    if is_on_device_list(device):
        print(f"  [PHASE B] WARNING: back on device list, skip Phase B for {label}", flush=True)
        return result

    # ====== Phase B: 设置页 ======
    print(f"  [PHASE B] {label} settings page", flush=True)
    if not is_on_settings_page(device, lenient=False):
        if not auto_navigate_to_settings(device):
            print(f"  [PHASE B] cannot reach settings, skip", flush=True)
            return result

    settings_snap = capture_page_snapshot(device, "settings", f"{device_safe}_settings")
    print(f"  [PHASE B] settings page texts: {len(settings_snap['page_app_texts'])}", flush=True)
    # ★ 主页没拿到的话，从设置页 XML 兜底
    if not result["plugin_version"]:
        pv = extract_plugin_version(settings_snap["xml"])
        if pv:
            result["plugin_version"] = pv
            print(f"  [PLUGIN] version (from settings): {pv}", flush=True)

    settings_items_list = []
    settings_tree = dict(
        label="settings",
        activity=settings_snap["activity"],
        page_texts=settings_snap["page_app_texts"],
        items=settings_items_list,
    )
    if settings_snap["sig"] not in visited_sigs:
        visited_sigs.add(settings_snap["sig"])
        traverse_recursive(device, [], settings_items_list, visited_sigs, depth=0)
    result["trees"].append(settings_tree)
    return result

def run_multi_device_flow(device, seed_visited=None, scan_only_first=False):
    """主多设备循环。
    - seed_visited: 已扫过(应跳过)的设备名集合(用于 single-then-continue 模式)
    - scan_only_first: --once 模式 — 处理 1 台就停
    """
    print("[FLOW] device list detected, starting multi-device traversal", flush=True)
    all_results = {"captured_at": datetime.now().isoformat(), "devices": []}
    visited_names = set(seed_visited) if seed_visited else set()
    if visited_names:
        print(f"[FLOW] pre-seeded visited (skip): {sorted(visited_names)}", flush=True)
    no_change_count = 0

    while True:
        # 安全网：每轮先确认在设备清单页
        if not is_on_device_list(device):
            print("[FLOW] not on device list, recovering...", flush=True)
            if not return_to_device_list(device):
                print("[FLOW] cannot recover, aborting", flush=True)
                break

        list_xml = device.dump_hierarchy()
        list_sig = get_text_signature(list_xml)
        cards = enumerate_device_cards(list_xml)
        new_cards = [c for c in cards if c["name"] not in visited_names]

        if not new_cards:
            print(f"\n[FLOW] no new devices visible, scrolling...", flush=True)
            scroll_device_list_down(device)
            new_sig = get_text_signature(device.dump_hierarchy())
            if signatures_match(new_sig, list_sig, threshold=0.95):
                no_change_count += 1
                if no_change_count >= SCROLL_NO_CHANGE_LIMIT:
                    print(f"[FLOW] reached end of device list", flush=True)
                    break
            else:
                no_change_count = 0
            continue

        no_change_count = 0
        card = new_cards[0]
        device_name = card["name"]
        idx = len(visited_names) + 1
        print(f"\n{'='*60}", flush=True)
        print(f"=== [{idx}] {device_name} ===", flush=True)
        print(f"{'='*60}", flush=True)

        try:
            click_by_bounds(device, card["bounds"])
            time.sleep(1.0)  # 让 Activity 切换开始
            # ★ 等设备主页稳定，再开始 traverse
            wait_for_page_ready(device, max_total=15.0)
            device_result = traverse_one_device(device, label=device_name)
        except Exception as e:
            print(f"  [ERROR] {device_name} crashed: {e}", flush=True)
            traceback.print_exc()
            device_result = {"device_name": device_name, "error": str(e), "trees": []}

        all_results["devices"].append(device_result)
        visited_names.add(device_name)

        # 返回设备清单（统一用强力恢复）
        if not return_to_device_list(device):
            print("[FLOW] cannot return to list, stopping", flush=True)
            break
        time.sleep(1.0)

        if scan_only_first:
            print("[FLOW] --once specified, stopping after first device", flush=True)
            break

    json_path = OUTPUT_DIR / "all_devices_result.json"
    json_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*60}", flush=True)
    print(f"[DONE] processed {len(all_results['devices'])} devices", flush=True)
    for d in all_results["devices"]:
        n_trees = len(d.get("trees", []))
        err = " (ERROR)" if "error" in d else ""
        print(f"  - {d['device_name']}: {n_trees} trees{err}", flush=True)
    print(f"  result: {json_path}", flush=True)
    print("="*60, flush=True)


def run_single_device_flow(device):
    """原有单设备流程（兼容旧用法）"""
    visited_sigs = set()
    results = {
        "captured_at": datetime.now().isoformat(),
        "plugin_version": None,                      # ★ 新增
        "trees": [],
    }
    main_snap = capture_page_snapshot(device, "device_main", "01_main_page")
    visited_sigs.add(main_snap["sig"])
    # ★ 从主页 XML 提取 plugin version
    pv = extract_plugin_version(main_snap["xml"])
    if pv:
        results["plugin_version"] = pv
        print(f"[PLUGIN] version: {pv}", flush=True)
    main_tree = dict(
        label="device_main",
        activity=main_snap["activity"],
        page_texts=main_snap["page_app_texts"],
        items=[],
    )
    print(f"[PHASE A] main page texts: {len(main_snap['page_app_texts'])}", flush=True)
    if parse_menu_items(main_snap["xml"]):
        traverse_recursive(device, [], main_tree["items"], visited_sigs, depth=0)
    results["trees"].append(main_tree)

    # ★ Phase A 收尾：BACK 最多 5 次以确保回到主页
    main_sig = main_snap["sig"]
    # Phase A cleanup：BACK 回主页（最多 5 次）
    screen_w, screen_h = get_screen_size(device)
    main_activity = main_snap["activity"]
    is_rn_device = any(h in main_activity for h in RN_ACTIVITY_HINTS)
    for back_attempt in range(5):
        # ★ 守卫 1：activity 变了 → 已经 BACK 出当前设备 → 停（再 BACK 没意义）
        current_activity = device.app_current().get("activity", "")
        if current_activity != main_activity:
            print(f"  [PHASE A] cleanup: drifted to '{current_activity.split('.')[-1]}' (was '{main_activity.split('.')[-1]}'), stopping", flush=True)
            break
        # ★ 守卫 2：在主页 → 停
        current_sig = get_text_signature(device.dump_hierarchy())
        if is_on_main_page(current_sig, main_sig):
            if back_attempt > 0:
                print(f"  [PHASE A] cleanup: returned to main after {back_attempt} BACK(s)", flush=True)
            break
        # ★ 守卫 3(2026-05-13 新):Native 设备(activity 不含 LumiRN/.arn.)在 main activity 上 BACK 必然弹回设备列表 →
        # 即使 sig 略不匹配(state 刷新/动态计数)也不要再 BACK
        if not is_rn_device:
            forward = len(current_sig & main_sig) / max(len(main_sig), 1)
            new_count_check = len(current_sig - main_sig)
            print(f"  [PHASE A] cleanup: on Native device main activity (overlap {forward:.0%}, new={new_count_check}), BACK would exit device, stopping", flush=True)
            break
        new_count = len(current_sig - main_sig)
        print(f"  [PHASE A] cleanup: not on main (attempt {back_attempt+1}/5, |current|={len(current_sig)}, |main|={len(main_sig)}, new={new_count}), pressing BACK", flush=True)
        device.press("back"); time.sleep(1.5)
        try:
            save_action = detect_save_prompt_action(device.dump_hierarchy())
            if save_action:
                btn = device(text=save_action)
                if btn.exists:
                    print(f"  [PHASE A] cleanup: dismissing save-prompt with '{save_action}'", flush=True)
                    btn.click(); time.sleep(1.5)
        except Exception:
            pass
    else:
        print(f"  [PHASE A] cleanup: WARN failed to return to main after 5 BACKs", flush=True)

    print("\n[PHASE B] navigating to settings page", flush=True)
    if not is_on_settings_page(device, lenient=False):
        if not auto_navigate_to_settings(device):
            json_path = OUTPUT_DIR / "traverse_result.json"
            json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            return

    settings_snap = capture_page_snapshot(device, "settings", "02_settings_page")
    # ★ 主页没拿到的话，从设置页 XML 兜底
    if not results["plugin_version"]:
        pv = extract_plugin_version(settings_snap["xml"])
        if pv:
            results["plugin_version"] = pv
            print(f"[PLUGIN] version (from settings): {pv}", flush=True)
    settings_tree = dict(
        label="settings",
        activity=settings_snap["activity"],
        page_texts=settings_snap["page_app_texts"],
        items=[],
    )
    if settings_snap["sig"] not in visited_sigs:
        visited_sigs.add(settings_snap["sig"])
        traverse_recursive(device, [], settings_tree["items"], visited_sigs, depth=0)
    results["trees"].append(settings_tree)

    json_path = OUTPUT_DIR / "traverse_result.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[DONE] result: {json_path}", flush=True)


def _get_device_label_from_main(device):
    """当前在设备主页时,从 action bar 顶部抓设备名(用于 single+continue 模式 dedup)。
    返回空字符串表示抓不到 — multi flow 会扫所有 cards 包含已扫的那个,造成重复但不影响正确性。"""
    try:
        xml = device.dump_hierarchy()
        root = etree.fromstring(xml.encode("utf-8"))
        screen_w, _ = get_screen_size(device)
        candidates = []
        for node in root.iter("node"):
            if node.get("package") != APP_PACKAGE: continue
            cls = node.get("class", "")
            if "TextView" not in cls: continue
            text = (node.get("text") or "").strip()
            if not text or len(text) < 2: continue
            # 跳过纯数字/纯标点
            if not any(c.isalpha() or '가' <= c <= '힣' or '一' <= c <= '鿿' for c in text): continue
            bounds = node.get("bounds", "")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not m: continue
            x1, y1, x2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # action bar 区:y 50-220
            if y1 < 50 or y1 > 220: continue
            # 排除满屏宽 banner / 左上 back / 右上 "..."
            cx = (x1 + x2) / 2
            if cx < screen_w * 0.2 or cx > screen_w * 0.85: continue
            candidates.append((y1, x1, text))
        if candidates:
            candidates.sort()  # 优先 y 小、x 小
            return candidates[0][2]
    except Exception as e:
        print(f"[FLOW] label extract failed: {e}", flush=True)
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 v8 — Aqara Home Korean translation traversal.")
    parser.add_argument(
        "--once", "-1", action="store_true",
        help="扫一台后立即停,不返回设备列表续扫(用于调试/单设备测试/FP2 多模式分别扫)")
    parser.add_argument(
        "--locale", choices=["ko", "zh", "en"], default=None,
        help="标记本次 scan 的 app 语言(zh/en/ko)— 影响 output dir 后缀,用于三语对比。"
             "默认不带后缀(隐式韩文)。你需要 *在 app 内手动切到对应语言再起脚本*。")
    args = parser.parse_args()
    if args.locale:
        print(f"[BOOT] locale={args.locale}; output dir suffix _{args.locale}", flush=True)

    print("[STEP] connecting...", flush=True)
    device = u2.connect()
    get_screen_size(device)
    print(f"[STEP] connected: {device.app_current()}", flush=True)

    # ★ 流程分流
    if is_on_device_list(device):
        # 已在设备列表:multi 流(--once 时只扫第一张卡片)
        run_multi_device_flow(device, scan_only_first=args.once)
        return

    # 在设备主页:先抓当前设备名(只在续扫模式下需要,用于 dedup 自己)
    first_name = ""
    if not args.once:
        first_name = _get_device_label_from_main(device)
        if first_name:
            print(f"[FLOW] current device label: {first_name!r}", flush=True)
        else:
            print(f"[FLOW] could not detect current device label (will scan list normally)", flush=True)

    print("[FLOW] not on device list, running single-device flow", flush=True)
    run_single_device_flow(device)

    if args.once:
        return

    # 续扫:返回设备列表,跑 multi flow,跳过刚扫过的那台
    print(f"\n{'='*60}", flush=True)
    print(f"[FLOW] single device done, returning to device list to scan others...", flush=True)
    print(f"{'='*60}", flush=True)
    if not return_to_device_list(device):
        print("[FLOW] cannot return to device list, stopping after one device", flush=True)
        return
    seed = {first_name} if first_name else set()
    run_multi_device_flow(device, seed_visited=seed)


if __name__ == "__main__":
    try: main()
    except Exception:
        print("\n[FATAL]", flush=True)
        traceback.print_exc()
        sys.exit(1)