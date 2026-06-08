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

# ★ 2026-05-21:当前正在扫描的设备名称。在 traverse_one_device / run_single_device_flow 入口设置。
# 用途:traverse_related_items 在 장치 관련 항목 页扫 자동실행/동시실행 时,需匹配设备清单中
# 自己设备名 + '현재' 标记。匹配不上就 skip,防止误点其他设备 → 设备切换 → 无限循环。
CURRENT_DEVICE_NAME = None

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
    "삭제", "제거", "초기화", "재설정", "재시작", "교체", "탈퇴", "로그아웃", "끄기", "공장",
    "删除", "移除", "重置", "重启", "解绑", "退出", "注销", "关机", "恢复出厂", "更换",
    "Delete", "Remove", "Reset", "Restart", "Reboot", "Unbind", "Logout", "Sign out", "Factory", "Replace",
    # ★ 2026-05-26(case #57):재시작 / 重启 / Restart 加入 — Aqara 摄像头等 L2 '장치 재시작' click
    # 会弹 RN Modal "다시 시작하시겠습니까?" 对话框,但 RN Modal 是独立 Android Window,uiautomator
    # dump_hierarchy 抓不到 → BOTTOM-SHEET / DIALOG 检测全部失效 → 点击会被误判 NO-OP-SCROLL →
    # dialog 滞留 → 阻断后续 하위 기기 / 네트워크 정보 等 items 的点击。
    # 根治:把 재시작 列入危险词,根本不点击 → 没 dialog → scan 顺畅继续。
    # 跟 '재설정' / '교체' / '삭제' 同类处理(破坏性硬件操作)。
]
DANGER_KEYWORDS_END_ONLY = [
    "종료", "켜기",                                       # 韩
    "退出", "结束", "打开", "开启", "启用",                # 中
    "Exit", "End", "Terminate", "Turn on", "Enable",     # 英
    # ★ 2026-05-21:BLE / 多步交互向 wizard — 自动化无法走完(需用户实物操作 + BLE 在线),
    # 进了 wizard BACK 会触发 종료하시겠습니까? 对话框,有时即使按 확인 也退不出去(BLE 卡住)。
    # 精确匹配,不会误中含相同子串的其它 title。
    "도어락 동작 확인", "门锁动作确认", "Lock Action Test",
]
DANGER_CLASSES = ["Switch", "CheckBox"]
NAVIGATION_JUMP_KEYWORDS = [
    "연결된 허브", 
    # "허브",
    "连接的网关", 
    # "网关",
    "Connected Hub", 
    # "Hub", "Gateway",
    "하위장치", "하위 장치","하위 기기",
    "子设备", "子裝置", "下属设备",
    "Sub-device", "Sub Device", "Subdevice", "Child Device",
]
SAVE_PROMPT_KEYWORDS = [
    # 韩
    "수정 사항이 저장되지 않았",
    "저장되지 않은 변경",
    "변경사항이 저장되지",
    "변경 내용을 저장",
    "변경내용이 저장되지",           # ★ 2026-05-21:Aqara 当前 wording(LED T2 / 도어락)
    "그래도 나가시겠습니까",           # ★ "你想退出吗"
    "종료하시겠습니까",                # ★ 2026-05-21:도어락 동작 확인 wizard 退出确认
    # 中
    "未保存的更改", "未保存", "保存修改", "仍要退出",
    # 英
    "Unsaved changes", "Discard changes", "save changes", "Save your changes",
    "Exit anyway", "Leave anyway",
]
# ★ 2026-05-21:Save-prompt 弹窗中"放弃修改并退出"按钮的 label
# 旧 dialog 用 "확인" = 放弃,新 dialog 用 "나가기"(取消 vs 离开)
# 单独 set,避免污染 CONFIRM_LABELS / CANCEL_LABELS 的语义
SAVE_PROMPT_DISCARD_LABELS = {
    "확인", "OK", "Confirm", "알겠습니다",            # 旧 case
    "나가기", "退出", "Exit", "Leave", "Discard",     # 新 case
    "포기", "放弃", "不保存",
}
# （绝不点击，只抓文本）
ACTION_BUTTON_EXACT = {
    # 韩
    "추가", "확인", "저장", "시작", "적용", "다음", "완료", "등록", "검색",
    "동의", "허용", "업데이트 확인", "업데이트",
    "기기 개인정보 보호 계약 승인 취소",
    "철회 확인", "더 많은 AQARA 제품 보러가기",
    # 中
    "添加", "确认", "保存", "开始", "应用", "下一步", "完成", "注册", "搜索",
    "同意", "允许", "检查更新", "更新", "了解更多Aqara产品",
    # 英
    "Add", "Confirm", "Save", "Start", "Apply", "Next", "Done", "OK", "Register",
    "Search", "Agree", "Allow", "Check for updates", "Update", "Learn more about Aqara products",
    # 韩 — 付款/订阅(危险,只看不点)
    # "결제",
    "지금 결제", "결제하기", "구매", "구매하기", "구독", "구독하기",
    "업그레이드", "업그레이드하기", "계속",
    # 中 — 付款/订阅
    "支付", "立即支付", "立即购买", "购买", "订阅", "立即订阅", "升级", "继续",
    # 英 — 付款/订阅
    "Pay", "Pay Now", "Buy", "Buy Now", "Purchase", "Subscribe", "Upgrade",
    "Get Plus", "Continue",
    # ★ 2026-05-27(case #64):客户服务按钮(FAQ 页面底部常见)— click 会跳外部客服页面
    # 中断当前 device 的 traversal。M3 hub `자주 묻는 질문 및 피드백` 页面有 '스마트 고객 서비스'
    # 按钮在 FAQ 列表下方,FAQ-PROBE 完成后 L1 discover 把它当 menu item → click → 飘走。
    # 加进 SKIP-ACTION 防误点。
    "스마트 고객 서비스", "고객 서비스", "Customer Service", "Smart Customer Service",
    "客户服务", "智能客户服务", "客戶服務",
    # ★ 2026-05-28(case #71):G3 카메라 허브 Phase A 控制中心的 'PTZ' 按钮 — click 会切换
    # 控制面板模式(从方向键 pad 切到其他模式),direction keys 消失 → 后续 items 位置变 →
    # find_item_by_title 找不到 → VANISH。MENU label 'PTZ' 已在 page_texts 抓到,不需要 click。
    # 精确匹配 "PTZ" 不影响 "PTZ 교정"/"PTZ 设置"/"PTZ menu" 等长 string。
    "PTZ","PTZ 교정","관심구역","관심구역 순환",
    "연결된 장치",
    "장치 검색",
    "허브",
    # ★ 2026-06-01(case #74):H2 조명 스위치 통신 프로토콜 click 弹底部 popup → 확인 click
    # 副作用把页面飘 → 接下来 3-4 个 items VANISH(包含 장치 관련 항목 / 장치 교체 / 장치 로그)
    # VANISH-RECOVERY 救得回 settings 但 vanished items 永久丢失。case #69 IME retry / case #70
    # aggressive BACK 当前 timing 没 catch 住(sig 暂时 match 通过)。
    # 修:精确匹配 SKIP-ACTION → 完全不 click → 无 dialog → 无 drift → 后续 items 全扫到。
    # 损失:通信协议 page 内 ~34 texts(Zigbee/MAC/IP 等技术显示)— 但 신호 강도 / 네트워크
    # 정보 已扫过类似数据,翻译价值低。换回 장치 관련 항목(자동/동시실행)+ 장치 교체 + 장치 로그。
    "통신 프로토콜",
}
# 选择类列表页（进入页面抓全部文本，但不点击任何选项）
CAPTURE_NO_RECURSE_KEYWORDS = [
    # === Add-* (添加类) ===
    "리모컨 추가", "장치 추가", "기기 추가", "액세서리 추가",
    "자동화 추가", "장면 추가", "동시실행 추가",
    "새 녹음 추가", "mp3 파일 가져오기", "장치 그룹 추가",
    "위치 지정", "방 추가","네트워크 정보","연결된 생태계","장치 언어",
    "添加遥控器", "添加设备", "添加配件", "添加自动化", "添加场景",
    "添加同步执行", "新录音", "导入MP3", "导入 MP3", "添加设备组",
    "指定位置", "选择位置", "添加房间","网络信息","已连接的生态",
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
    "指定位置", "设备位置", "选择位置","分配位置",        # 中
    "Set Location", "Device Location", "Specify Location",  # 英
    "방 추가", "添加房间", "Add Room",
    # === 空调匹配/品牌选择 ===
    "에어컨 매칭", "브랜드 선택", "에어컨 모드 설정",
    "空调匹配", "匹配空调", "选择品牌", "空调模式", "空调模式设置",
    "AC Matching", "Match AC", "Select Brand", "Brand Selection",
    "AC Mode", "AC Mode Setting", "Set AC Mode",
    # === 固件版本(子页 — 别递归) ===
    "펌웨어 버전", "固件版本", "Firmware Version",
    # === 信息显示类子页(2026-05-21 加 — click 后展开 inline 值 + 含 "장치 관련 항목"
    #     link → 容易误判 CHOOSER-REVEALED) ===
    "신호 강도", "信号强度", "Signal Strength",
    # === 道어락 L100 RN 子页(2026-05-20 加 — Fix #33 误判为 mode-toggle,
    #     这些 RN overlay 子页 items_preserved=100% 但其实是真子页) ===
    "자주하는 질문", "사용자 매뉴얼", "개인정보 보호 정책",
    "常见问题", "用户手册", "隐私政策",
    "FAQ", "User Manual", "Privacy Policy",
    "음성 및 사운드", "도어락 동작 확인", "인증 중단 설정",
    "声音和音效", "门锁动作确认", "认证暂停设置",
    "Sound", "Lock Action", "Auth Pause",
    "배터리 및 소모품", "공식 장치 이름",
    "电池和耗材", "设备名称",
    "Battery", "Device Name",
    "상시 열림 모드",  # always-open mode (방해 금지 모드 已经在 COMMON_SETTINGS_MENU_TITLES)
    "常开模式",
    "Always Open Mode",
    # === 设备"自身名"卡片(2026-05-20 加) — RN 设置页顶部"设备名 + 房间"卡片,
    #     click 进 "Device Info" sub-page。新 text 数随 RN 渲染时机 5-20 不等,
    #     Fix #33 偶尔会误判 mode-toggle。强制 captured。 ===
    # 道어락(锁):
    "스마트 도어락", "Smart Lock", "智能门锁", "智能锁",
    # 摄像头:
    "스마트 카메라", "Smart Camera",
    # 网关 / Hub: (主体名经常用作 title click,Smart Hub / Hub 已在 NAV_JUMP,这里不重复)
    # 设备型号字符串通常在 title 里(L100/G4/P2 等)— 简单覆盖只用首词

    # === LED 전구 T2 等灯泡子页(2026-05-21 加 — Fix #33 误判 + save prompt 卡死) ===
    # click 这些 → 进真子页(有 toggle),后续 BACK 触发"변경내용이 저장되지" save prompt。
    # 强制 captured + no recurse → 让脚本知道navigated,触发 save prompt 自动 dismiss(나가기)。
    "전환 설정", "디밍 범위", "장치 검색",
    "切换设置", "调光范围", "搜索设备",
    "Transition Settings", "Dimming Range", "Device Search",
    # 通信协议 / 子页信息
    "통신 프로토콜", "通信协议", "Communication Protocol",
    # "마스테크","릴레이 잠금",
    "스위치 그룹",
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

# ★ 2026-05-21:房间名 exact-match 黑名单(LED 전구 T2 触发的 bug 修)
# 触发场景:device card / 设置页里"当前房间"显示为可点 link(eg "스터디룸"),
# 或 chooser 漏过守卫时 room 名作为 list item 出现。click → device location 永久变更!
# 严格 exact match,防止误伤含房间字的设置项(e.g. "거실 모드" 不算)。
ROOM_NAMES_EXACT = {
    # 韩
    "거실", "침실", "주방", "부엌", "욕실", "화장실", "발코니", "복도", "현관",
    "출입구", "스터디룸", "휴대품 보관소", "보관실", "바 카운터", "추천 객실",
    "식당", "지하실", "마스터 베드룸", "나의 방", "다용도실", "베란다", "옷장", "옷방",
    "서재", "사무실", "아이방", "드레스룸", "다이닝룸",
    # 中
    "客厅", "卧室", "主卧", "厨房", "餐厅", "卫生间", "浴室", "洗手间", "阳台",
    "玄关", "走廊", "书房", "储物间", "储物室", "衣帽间", "地下室", "餐桌",
    "默认房间", "我的房间", "主卧室", "次卧",
    # 英 + 通用
    "Default Room", "Living Room", "Bedroom", "Master Bedroom", "Kitchen",
    "Dining Room", "Bathroom", "Toilet", "Balcony", "Hallway", "Foyer",
    "Study", "Office", "Storage Room", "Storage", "Wardrobe", "Basement",
    "My Room", "Entrance", "Corridor", "Doorway", "Other",
}
PAGE_CONTENT_NO_RECURSE_MARKERS = [
    # 韩
    "브랜드 선택", "브랜드 검색",
    "국가 선택", "지역 선택", "언어 선택", 
    # "장치 관련 항목", "장치 연관 항목",
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
LOADING_KEYWORDS = [
    "로딩 중", "로딩중", "잠시만",            # 韩 - 通用加载
    "처리 중", "처리중",                       # ★ 2026-05-21 加 — P2 네트워크 정보 page Thread 数据加载
    "Loading", "Processing",                   # 英
    "加载中", "处理中",                         # 中
]
PROGRESS_PATTERN = re.compile(r"^\d{1,3}%$")

# ===========================================================================
# ★★★ 设备性能模式配置(2026-05-21 加) ★★★
# 测试机性能差(三星 S8 / 2017 / 老安卓)→ SLOW_DEVICE_MODE = True
# 测试机性能好(新机)→ SLOW_DEVICE_MODE = False
# 切换时只改这一个 flag,下方所有 WAIT_* 常量自动 scale。
# 想完全 disable,直接把 SLOW_DEVICE_MODE 改成 False 即可(无需改其它代码)。
# ---------------------------------------------------------------------------
SLOW_DEVICE_MODE = True       # ★ S8 用 True;高性能手机用 False
_SLOW_MULT = 2.0 if SLOW_DEVICE_MODE else 1.0
# ===========================================================================

WAIT_POLL_INTERVAL = 0.5
WAIT_STABLE_THRESHOLD = 1.0 * _SLOW_MULT     # 慢机:2s 才算稳定(原 1s 易抓到 loading 中间态)
WAIT_MAX_NATIVE = 10.0 * _SLOW_MULT          # Native 页最大等待
WAIT_MAX_RN = 25.0 * _SLOW_MULT              # RN 页最大等待
WAIT_AFTER_BACK = 1.0 * _SLOW_MULT           # BACK 后 sleep
WAIT_AFTER_DEVICE_CLICK = 2.5 * _SLOW_MULT   # 进设备主页等待
WAIT_AFTER_CLICK_EXTRA = 1.0 if SLOW_DEVICE_MODE else 0.0   # ★ click 后额外 sleep(给 RN bundle 反应时间)
ACTIVITY_DETECT_DELAY = 0.8 * _SLOW_MULT
BACK_MAX_ATTEMPTS = 5
MAX_DEPTH = 4
NOOP_OVERLAP_THRESHOLD = 0.9

# ★ 2026-05-26 修(case #49):HEURISTIC_* 改成屏幕比例,适配不同尺寸 Android 手机
# 旧:绝对像素阈值(50/300/200)针对 1080×2220 — 同事大屏手机(QHD+ 1440×3120)上 item 高 > 300px → 全 fitler 掉 → 0 items → 静默失败
# 新:ratio 比例 — 同 1080×2220 上仍计算出 ~50/300/200(向后兼容);更大屏自动放大
#
# 实际像素值由 _heuristic_pixel_thresholds() 在运行时基于 get_screen_size() 计算
# (get_screen_size 在 main() 连接 device 后已经 cache 真实尺寸,所以无 stale 风险)
HEURISTIC_MIN_HEIGHT_RATIO = 0.0225   # 50 / 2220 ≈ 0.0225
HEURISTIC_MAX_HEIGHT_RATIO = 0.135    # 300 / 2220 ≈ 0.135
HEURISTIC_MIN_WIDTH_RATIO = 0.185     # 200 / 1080 ≈ 0.185
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

def wait_until_rn_page_stable(device, timeout=5.0, check_interval=0.5):
    """
    智能等待 RN/Matter 页面稳定:连续 2 次 dump 签名一致 → 已稳定。
    专治 RN 异步双重渲染:dump 与 screenshot 抓到不同 render 阶段的 bug。

    ★ 2026-05-26(case #50)bug fix:原版返回的 current_xml 是 sleep(0.3) 之前 dump 的,
    所以 0.3s "视觉稳定缓冲" 完全无意义 — 缓冲期内可能渲染新内容,但返回的 xml 不反映。
    修:sleep 后**重新 dump**一次,返回最新 xml。这样后续 screenshot 也是同步状态。

    成功稳定时静默;只在 timeout 触发时打印日志(避免每 click 1500+ 行噪音)。
    """
    start_time = time.time()
    last_sig = ""

    while time.time() - start_time < timeout:
        try:
            current_xml = device.dump_hierarchy()
            current_sig = get_text_signature(current_xml)

            if current_sig and current_sig == last_sig:
                # 视觉缓冲 + 重新 dump(防 stale)
                time.sleep(0.3)
                try:
                    return device.dump_hierarchy()
                except Exception:
                    return current_xml

            last_sig = current_sig
        except Exception:
            pass
        time.sleep(check_interval)

    print(f"[RN_GUARD] timeout after {timeout}s, force proceeding", flush=True)
    try:
        return device.dump_hierarchy()
    except Exception:
        return ""


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
    识别"未保存修改"弹窗。返回该弹窗里要点击的"放弃修改并退出"按钮 label,否则 None。
    Aqara 新版用 "나가기"(leave),旧版用 "확인"(confirm-discard)— SAVE_PROMPT_DISCARD_LABELS 都覆盖。
    ★ 2026-05-21:之前只查 CONFIRM_LABELS,漏 "나가기" → LED T2 / 도어락 卡死。
    """
    sig = get_text_signature(xml_str)
    has_prompt = any(any(kw in t for kw in SAVE_PROMPT_KEYWORDS) for t in sig)
    if not has_prompt:
        return None
    # 优先 nav/leave 类(更明确的"放弃并退出"语义)
    leave_labels = {"나가기", "退出", "Exit", "Leave", "Discard", "포기", "放弃", "不保存"}
    for t in sig:
        if t.strip() in leave_labels:
            return t.strip()
    # fallback:旧 dialog 用 확인 = discard
    for t in sig:
        if t.strip() in SAVE_PROMPT_DISCARD_LABELS:
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
        ts = t.strip()
        if ts in ACTION_BUTTON_EXACT:
            return True, f"action: '{t}'"
        # ★ 2026-05-26(case #58):Aqara nav-link 末尾常带 '>' 箭头(navigation indicator)。
        # 例如 '더 많은 AQARA 제품 보러가기>' — 加进 ACTION_BUTTON_EXACT 但精确匹配 miss(set 里
        # 无 '>')→ 不被识别为 action → 被点击。剥掉末尾 '>' 再 match。
        # 守卫 `ts_stripped != ts` 确保只有"原本带 >"的 text 才走这条路 → 不影响干净 text 行为。
        ts_stripped = ts.rstrip('>').rstrip()
        if ts_stripped and ts_stripped != ts and ts_stripped in ACTION_BUTTON_EXACT:
            return True, f"action: '{t}' (arrow-stripped)"
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


def _heuristic_pixel_thresholds():
    """★ 2026-05-26(case #49):基于实际屏幕尺寸计算 menu item 像素阈值。
    main() 连接 device 后 get_screen_size(device) 已 cache 真实尺寸,这里不会拿到 default fallback。
    返回 (min_h, max_h, min_w) 全部 int。"""
    screen_w, screen_h = get_screen_size()
    return (
        int(screen_h * HEURISTIC_MIN_HEIGHT_RATIO),
        int(screen_h * HEURISTIC_MAX_HEIGHT_RATIO),
        int(screen_w * HEURISTIC_MIN_WIDTH_RATIO),
    )


def parse_menu_items_heuristic(xml_str):
    root = etree.fromstring(xml_str.encode("utf-8"))
    _, screen_h = get_screen_size()
    bottom_cutoff = screen_h * BOTTOM_NAV_THRESHOLD_RATIO  # ★ 排除底部
    min_h, max_h, min_w = _heuristic_pixel_thresholds()    # ★ case #49 屏幕比例
    items = []
    for node in root.iter("node"):
        if node.get("clickable") != "true": continue
        if node.get("package") != APP_PACKAGE: continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m: continue
        x1, y1, x2, y2 = map(int, m.groups())
        h, w = y2 - y1, x2 - x1
        if h < min_h or h > max_h: continue
        if w < min_w: continue
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
    # if items:
    #     print(f"      [HEURISTIC] {len(items)} items", flush=True)
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
    # ★ 2026-05-20 Fix A:Phase B 入口前先等 RN 页面稳定
    # 触发设备:도어락 L100 — Phase A 完成后到 Phase B 之间 RN 还在 reflow,
    # 此刻 dump 缺真"..."按钮 → S4 0 candidates → S5 错点 status 图标 → 跳错页
    # 修:nav 前 wait_for_page_ready(2-5s),让 RN bundle 稳定 + ProgressBar 消失再 dump
    try:
        wait_for_page_ready(device, max_total=8.0)
    except Exception as e:
        print(f"  [NAV] wait_for_page_ready warning: {e}", flush=True)
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
    # ★ 2026-05-20 Fix D':S4 用 5 次 dump 取 UNION(进化自原 retry-on-empty)
    # RN devices(LumiRN)dump 极不稳定 — 同 page 多次 dump,button 时有时无。
    # 原 retry 思路:0 就再 dump。但有时连 3-5 次 dump 都 0 candidates(竟然!),
    # 即便 XML 里在 Phase A / failure save 时都有 button。
    # 改成 UNION:5 次 dump 合并所有 top-right 候选,只要任一次 catch 到就用。
    xml = None
    candidates_by_bounds = {}
    for _attempt in range(5):
        if _attempt > 0:
            time.sleep(0.8)
        try:
            xml = device.dump_hierarchy()
        except Exception:
            continue
        for cand in find_top_right_clickables(xml, screen_w, screen_h):
            candidates_by_bounds[cand[4]] = cand   # bounds string as key
    candidates = sorted(candidates_by_bounds.values(), key=lambda c: c[0], reverse=False)
    # 重新按 cx desc 排序(原 find_top_right_clickables 已 sort,这里保证一下)
    candidates.sort(key=lambda c: -(c[0] + c[2]))   # cx desc
    sig_anchor = get_text_signature(xml) if xml else set()
    print(f"  [NAV] S4: {len(candidates)} candidates (after 5-dump union)", flush=True)
    for x1, y1, x2, y2, bounds in candidates[:3]:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        print(f"  [NAV] S4: tap {bounds}", flush=True)
        device.click(cx, cy)
        # ★ 2026-05-26(case #52):原 time.sleep(2.0) 在 5/26 app 更新后不够。
        # G2H Pro 等重 RN bundle 设备点 "..." 后会先出现 1-3 秒白屏 loading,settings 才渲染。
        # 2 秒就 check → 还在白屏 → is_on_settings_page(lenient=True) 找不到 ≥3 menu items → 误判 False
        # → 试下一个 S4 候选 → 在 loading 期间错点别处 → 最终飘回 device main。
        # 改用 wait_until_rn_page_stable 等真正稳定(连续 2 次 dump sig 一致)。
        wait_until_rn_page_stable(device, timeout=8.0)
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
        device.click(cx, cy)
        wait_until_rn_page_stable(device, timeout=8.0)   # ★ case #52: 等 RN 渲染稳定
        # ★ 2026-05-20 Fix B:S5 几何启发式可能命中错误图标(status icon),
        # 用 strict 校验(≥3 anchor)防止跳错页还被误判为"已到达设置"
        # 触发设备:도어락 L100 — S5 错点 cx=699 跳到 일회용 비밀번호 子页(1 anchor),
        # 旧 lenient 接受 → "arrived via S5" 假报喜 → settings tree 0 items
        if is_on_settings_page(device, lenient=False):
            print(f"  [NAV] arrived via S5", flush=True)
            return True
        for label in ["설정", "设置", "Settings", "기기 설정"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device, lenient=False):
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
        device.click(cx, cy)
        wait_until_rn_page_stable(device, timeout=8.0)   # ★ case #52: 等 RN 渲染稳定(WebView 也适用)
        # ★ 2026-05-20 Fix B:S6 也是几何启发式(且不检 clickable),同样需 strict 校验
        if is_on_settings_page(device, lenient=False):
            print(f"  [NAV] arrived via S6", flush=True)
            return True
        for label in ["설정", "设置", "Settings", "기기 설정"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device, lenient=False): return True
        sig_after = get_text_signature(device.dump_hierarchy())
        if not signatures_match(sig_after, sig_anchor, threshold=0.9):
            device.press("back"); time.sleep(1.0)

    # ★ 2026-05-20 S7:RN-only 坐标硬 fallback
    # 触发场景:RN 设备(LumiRN/.arn.)dump 不稳定,S4 5 次 union 都 0,S5/S6 也错点。
    # Aqara 的 RN 设备 "..." 几乎恒在 cx≈95% 屏宽,cy≈6% 屏高(标准 action bar 右上)。
    # 直接坐标点击,UIAutomator2 发 raw touch event,不依赖 dump。
    # 后接 strict is_on_settings_page 校验,跳错页就不算 success。
    if "LumiRN" in activity or ".arn." in activity:
        cx_fb = int(screen_w * 0.95)
        cy_fb = int(screen_h * 0.06)
        print(f"  [NAV] S7: RN coord fallback at ({cx_fb},{cy_fb})", flush=True)
        device.click(cx_fb, cy_fb)
        wait_until_rn_page_stable(device, timeout=8.0)   # ★ case #52: 等 RN 渲染稳定
        if is_on_settings_page(device, lenient=False):
            print(f"  [NAV] arrived via S7", flush=True)
            return True
        # 也试 sub-label 点击
        for label in ["설정", "设置", "Settings", "기기 설정"]:
            item = device(text=label)
            if item.exists:
                item.click(); time.sleep(2.0)
                if is_on_settings_page(device, lenient=False):
                    return True
        # 没成功 → BACK 收尾,fall through 存诊断
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
    """向上滚动一屏(用 0.2→0.8 大行程,duration 0.3 加 fling)+ 分屏布局兜底。

    ★ 2026-05-28(case #68):分屏布局兼容 — 摄像头类设备(G3/G4/G2H Pro 等)主页上半
    是视频画面**不响应滚动手势**(touch 触发 video controls),下半才是可滚菜单。
    标准 swipe(起点 y=0.20=444px / 2220)落在视频区 → 整个 swipe 无效 →
    `scroll_page_to_top` 觉得"稳定 = 已到顶"提前 break → discover 后菜单卡在下方,
    initial top items 找不到 → VANISHED 漏抓。

    修:加一次 "low-region" swipe(0.65→0.95,起点终点都在下半 menu 区),保证至少
    一次 swipe 落在可滚区域。对正常全屏可滚页面:第二 swipe 多滚 ~30%(可能越过 top,
    无副作用因为滚到顶后 swipe 是 no-op);对分屏页面:第一 swipe 无效,第二 swipe
    生效 ✓。整体 scroll_page_to_top 最多多耗 ~0.4s × 6 attempts ≈ 2.4s,可接受。
    """
    screen_w, screen_h = get_screen_size(device)
    sx = screen_w // 2
    # 标准 swipe(大行程)
    device.swipe(sx, int(screen_h * 0.20),
                 sx, int(screen_h * 0.80), 0.3)
    time.sleep(0.4)
    # ★ split-pane fallback:起点终点都在下半,保证分屏设备菜单区被 swipe 到
    device.swipe(sx, int(screen_h * 0.65),
                 sx, int(screen_h * 0.95), 0.3)
    time.sleep(0.4)


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


def _detect_floating_button_y_top(xml_str):
    """★ case #65:检测页面是否有 '스마트 고객 서비스' / 'Customer Service' 类 floating button。
    返回该按钮的 y_top 坐标(用于设置防误点的 y 上限),没找到返回 None。
    Aqara FAQ 页底部常有这种悬浮客服按钮,会覆盖在下方问题之上,点击下方问题时实际命中它。"""
    floating_labels = ("스마트 고객 서비스", "고객 서비스", "Customer Service",
                       "Smart Customer Service", "客户服务", "智能客户服务", "客戶服務")
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
    except Exception:
        return None
    candidates = []
    for node in root.iter("node"):
        t = (node.get("text") or "").strip()
        if t not in floating_labels:
            continue
        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m:
            continue
        y1 = int(m.group(2))
        candidates.append(y1)
    return min(candidates) if candidates else None


_FAQ_PAREN_RE = re.compile(r"[?？]\s*[\(（][^)）]+[\)）]\s*$")

def _is_faq_question_text(t):
    """判断 text 是否为 FAQ question。

    ★ 2026-05-28(case #72):原版只要求 endswith '?' 或 '?'。但 Aqara G3 일반적인 질문
    有一题 `현재 프록시 허브로 지원되는 기기는 무엇입니까? (다음 제품 중 일부는...)` —
    `?` 后跟括号补充说明,末尾是 `)` 不是 `?` → 漏检 → 漏抓 answer。
    扩展:也接受 `? (...)` / `? （...）` 结尾的 pattern。括号内不能再有 `?`(避免误抓含问号的答案文本)。
    """
    if t.endswith("?") or t.endswith("？"):
        return True
    if _FAQ_PAREN_RE.search(t):
        return True
    return False


def _detect_webview_faq_questions(xml_str):
    """检测是否为 WebView FAQ-like 页面,返回每个问题 TextView 的 (text, bounds_center) list。

    判定:
    - 页面含 WebView class
    - 有 ≥3 个 TextView 的 text 以问号结尾(? 或 ?,或 `?(...)` 括号补充)
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
        if not _is_faq_question_text(t): continue
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
    """WebView FAQ 页面专用:依次点击每个 question 让答案展开,保存 expanded 状态截图 + dump。
    **滚动遍历**:每屏 detect → probe → scroll-down → re-detect → ... 直到连续 2 屏没新问题。

    用途:FAQ 详细答案是 HTML 内容,UIAutomator dump 部分可见(取决于实现):
      - WebView 渲染:dump 看不到 HTML 内部文本 → 截图 + Phase 3 Vision OCR
      - Native TextView 渲染:dump 能拿到答案文本 → extract_app_texts 取出

    返回:(question_count, expanded_texts) — count 用于日志,expanded_texts 是去重后展开的 native 答案文本
    (调用方 merge 进 app_texts)。Native 抓不到时 expanded_texts 为空 list。

    ★ 2026-05-27(case #60 v1):原版只截图 → 加 dump + extract,捞 native 答案文本。
    ★ 2026-05-27(case #63 v2):只检测当前屏 questions → 加滚动遍历,捞下方更多 questions。
                               触发设备:M3 hub FAQ 有 8+ 问题,初始屏只看到 7 个,下面还有
                               'M3는 어떤 설치 모드를 지원하나요?' 等漏抓。
    """
    # 初屏 detect
    initial_questions = _detect_webview_faq_questions(sub_xml)
    if not initial_questions:
        return 0, []

    base_texts, _ = extract_app_texts(sub_xml)
    base_text_set = {(t.get("text") or "").strip() for t in base_texts}
    expanded_texts = []
    seen_expanded = set()           # 答案文本跨 question 去重
    probed_question_texts = set()   # question 去重 by text(防滚动后重复 probe)
    total_probed = 0
    no_new_screens = 0              # 连续多少屏没新 question
    max_screens = 15                # 硬上限
    MAX_PROBES_PER_SCREEN = 20      # ★ case #67(2026-05-27 修):软上限,典型 FAQ 5-7 题/屏

    screen_w, screen_h = get_screen_size(device)
    current_xml = sub_xml
    screen_idx = 0
    while screen_idx < max_screens:
        screen_idx += 1
        questions = _detect_webview_faq_questions(current_xml)

        # ★ case #65 防御:检测 floating button,设 y 上限 = button 上方留 100px 安全余量
        # 没 floating button → 用默认 y_max = 70% 屏高(底部还是不点,防其它 floating)
        fb_y = _detect_floating_button_y_top(current_xml)
        if fb_y is not None:
            y_max = fb_y - 100
        else:
            y_max = int(screen_h * 0.70)

        # 过滤:仅 top 区域 + 未 probed
        eligible = [(q, c) for (q, c) in questions
                    if q not in probed_question_texts and c[1] < y_max]
        # ★ case #67(2026-05-27 修):probe **所有** eligible,不再 top-2 截断。
        # 原 SAFE_PROBE_PER_SCREEN=2 + scroll_page_down(~4 题距)→ 中间 2-3 题被
        # 推到屏幕外永远不再 probe(用户报告 M3 FAQ 中间 Q3/Q4/Q7-Q11 漏抓)。
        # 安全性:y_max 已防 floating button overlay(cy < fb_y-100);每题之间的
        # collapse-click+0.6s sleep 已让 layout 复位;原 cap 没有实际防御价值。
        to_probe = eligible[:MAX_PROBES_PER_SCREEN]

        if to_probe:
            no_new_screens = 0
            label = f"screen {screen_idx}" + (f" (fb_y={fb_y})" if fb_y else "")
            deferred_n = max(0, len(eligible) - len(to_probe))
            print(f"      [FAQ-PROBE] {label}: {len(to_probe)} questions to probe (y<{y_max}), {deferred_n} deferred", flush=True)
            for qtext, (cx, cy) in to_probe:
                probed_question_texts.add(qtext)
                total_probed += 1
                idx = total_probed
                try:
                    device.click(cx, cy)
                    time.sleep(1.2)
                    shot_path = output_dir / f"{sname_base}__q{idx:02d}.png"
                    device.screenshot(str(shot_path))
                    try:
                        exp_xml = device.dump_hierarchy()
                        (output_dir / f"{sname_base}__q{idx:02d}.xml").write_text(exp_xml, encoding="utf-8")
                        exp_app_texts, _ = extract_app_texts(exp_xml)
                        new_count = 0
                        for tx in exp_app_texts:
                            t_val = (tx.get("text") or "").strip()
                            if not t_val: continue
                            if t_val in base_text_set: continue
                            if t_val in seen_expanded: continue
                            seen_expanded.add(t_val)
                            expanded_texts.append(tx)
                            new_count += 1
                        if new_count > 0:
                            print(f"      [FAQ-PROBE] q{idx}: +{new_count} new texts from expanded answer", flush=True)
                    except Exception as e:
                        print(f"      [FAQ-PROBE] q{idx} dump/extract failed: {e}", flush=True)
                    # collapse
                    device.click(cx, cy)
                    time.sleep(0.6)
                except Exception as e:
                    print(f"      [FAQ-PROBE] q{idx} ({qtext[:30]}...) failed: {e}", flush=True)
        else:
            no_new_screens += 1
            if no_new_screens >= 2:
                break

        # scroll-down 一屏看是否还有新 questions
        try:
            scroll_page_down(device)
            time.sleep(1.0)
            current_xml = device.dump_hierarchy()
            # 累积 baseline texts(滚动后新出现的 base 文本也算 base,防止误认为 expanded)
            new_base_texts, _ = extract_app_texts(current_xml)
            for tx in new_base_texts:
                base_text_set.add((tx.get("text") or "").strip())
        except Exception:
            break

    # ★ 2026-05-27(case #66):最后一轮 — fling-to-bottom 后扫底部漏的 question。
    # case #65 防御性 top-region 点击可能漏掉最底部的几个 question(scroll 提前到底,
    # 但 bottom 的 question 没机会进入下一屏的 top)。所以最后做一次额外滚到底再扫一遍。
    try:
        scroll_page_down(device); time.sleep(0.8)
        scroll_page_down(device); time.sleep(0.8)  # 滚到底 (FAQ 不长,2 次足够)
        final_xml = device.dump_hierarchy()
        final_qs = _detect_webview_faq_questions(final_xml)
        final_fb = _detect_floating_button_y_top(final_xml)
        final_y_max = (final_fb - 100) if final_fb is not None else int(screen_h * 0.70)
        new_at_bottom = [(q, c) for (q, c) in final_qs
                          if q not in probed_question_texts and c[1] < final_y_max]
        if new_at_bottom:
            print(f"      [FAQ-PROBE] final scan: {len(new_at_bottom)} unprobed question(s) at bottom", flush=True)
            new_base_texts, _ = extract_app_texts(final_xml)
            for tx in new_base_texts:
                base_text_set.add((tx.get("text") or "").strip())
            for qtext, (cx, cy) in new_at_bottom:
                probed_question_texts.add(qtext)
                total_probed += 1
                idx = total_probed
                try:
                    device.click(cx, cy); time.sleep(1.2)
                    shot_path = output_dir / f"{sname_base}__q{idx:02d}.png"
                    device.screenshot(str(shot_path))
                    try:
                        exp_xml = device.dump_hierarchy()
                        (output_dir / f"{sname_base}__q{idx:02d}.xml").write_text(exp_xml, encoding="utf-8")
                        exp_app_texts, _ = extract_app_texts(exp_xml)
                        new_count = 0
                        for tx in exp_app_texts:
                            t_val = (tx.get("text") or "").strip()
                            if not t_val: continue
                            if t_val in base_text_set: continue
                            if t_val in seen_expanded: continue
                            seen_expanded.add(t_val)
                            expanded_texts.append(tx)
                            new_count += 1
                        if new_count > 0:
                            print(f"      [FAQ-PROBE] q{idx}: +{new_count} new texts (final scan)", flush=True)
                    except Exception as e:
                        print(f"      [FAQ-PROBE] q{idx} (final) dump/extract failed: {e}", flush=True)
                    device.click(cx, cy); time.sleep(0.6)
                except Exception as e:
                    print(f"      [FAQ-PROBE] q{idx} (final) ({qtext[:30]}...) failed: {e}", flush=True)
    except Exception:
        pass

    if total_probed > 0:
        print(f"      [FAQ-PROBE] total {total_probed} questions probed, {len(expanded_texts)} new native answer texts captured", flush=True)
    # 滚回顶部,便于后续 BACK 操作识别页面
    try:
        scroll_page_to_top(device)
    except Exception:
        pass
    return total_probed, expanded_texts


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
    # ★ 2026-05-20:no_change 阈值 3 → 5
    # 触发设备:도어락 L100 — RN 虚拟化 + 异步加载,3 次连续无新增可能只是 RN 慢,
    # 不是真到底。放宽到 5 给 RN 更多机会渲染剩余 items。
    for _ in range(max_scrolls):
        scroll_page_down(device)
        try:
            xml = device.dump_hierarchy()
        except Exception:
            break
        added = _absorb(xml)
        if added == 0:
            no_change += 1
            if no_change >= 5:
                break
        else:
            no_change = 0

    # ★ 兜底:uiautomator2 原生 fling-to-end(对 RN ScrollView 比 swipe 更可靠)
    try:
        sc = device(scrollable=True)
        if sc.exists:
            sc.fling.toEnd(max_swipes=5)
            time.sleep(1.5)  # ★ RN 渲染时间预留
            _absorb(device.dump_hierarchy())
            # 再 fling 一次确认到了真底端
            sc.fling.toEnd(max_swipes=3)
            time.sleep(1.5)
            _absorb(device.dump_hierarchy())
            # ★ 2026-05-20 加:再 fling toBeginning 然后 toEnd 一次,触发 RN 重新渲染懒加载 items
            # 触发设备:도어락 L100 — settings 26 items 但首次 discover 只发现 16,
            # 缺下面 자주하는 질문/사용자 매뉴얼/Aqara/이름/모델 等 10 个 RN 懒加载项。
            sc.fling.toBeginning(max_swipes=5)
            time.sleep(1.0)
            sc.fling.toEnd(max_swipes=8)
            time.sleep(1.5)
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
        # ★ 2026-05-21:先尝试 auto_navigate_to_settings(找右上 "..." 重进设置)。
        # 触发场景:LED T2 통신 프로토콜 click 后 [DIALOG] '확인' 按完不止关 dialog 还把脚本顶到
        # device main(3 items 显示)。原代码先 BACK loop 再 auto_nav,但 device main 上 BACK 必出
        # device → device list → return False,等于不给 auto_nav 一次机会。
        # 改:先 try auto_nav — 在 device main / settings 内部 / 中间页 都能找到右上 "..." 重新进
        # settings。失败再走 BACK loop。
        if auto_navigate_to_settings(device):
            try:
                cur_sig = get_text_signature(device.dump_hierarchy())
                if signatures_match(cur_sig, expected_sig, threshold=0.5):
                    return True
            except Exception:
                pass
        # 3. BACK 几次试着退到 device main(注意:Native device main 上 BACK 必出设备,
        #    所以每按一次都要检查 device_list)
        # ★ lenient=True(原 False):RN 设备 settings 没 cl_root_layout/item_layout anchor → 严格模式
        # 永远 False → BACK loop 把脚本顶出 device。lenient 看 looks_like_menu_page 能识别 RN settings。
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
            # 如果已经在 settings(lenient=True 兼容 RN) → break,直接 nav 检查
            if is_on_settings_page(device, lenient=True):
                break
            device.press("back")
            time.sleep(1.2)
        # 4. 用 auto_navigate_to_settings 找右上 "..." 重进设置
        if not is_on_settings_page(device, lenient=True):
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


# ========================================================================
# ★ 2026-05-21:장치 관련 항목 专项扫描 (자동실행 + 동시실행 추가流程)
# ========================================================================
# 流程(用户指定):
#   장치 관련 항목 页 → for each [자동실행, 동시실행]:
#     → click section 下的 추가
#     → conditions 页(3 个 button:트리거 조건 추가 / 상태 조건 추가 / 작업 추가)
#     → for each button: click → 选项页(장치/...)→ click 장치 → 设备清单
#       → 找有 '현재' 标记 且 名称 == CURRENT_DEVICE_NAME 的项 → click → capture
#       → BACK x3 回 conditions 页(若 own 未找到,BACK x2)
#     → BACK 回 장치 관련 항목 页
#
# 安全策略:
#   - 没有 CURRENT_DEVICE_NAME(extract 失败)→ 只 capture 页面文本,不深入
#   - 严格双要件(name match + '현재' 标记)才点击 → 防误点别人设备造成无限循环
#   - 任何 step 失败 → 多 BACK 几次安全退,不影响外层 traversal


def extract_device_name_from_main(main_xml):
    """从 Phase A device main XML 提取设备名称(顶部 header 第一条像设备名的文本)。
    单设备 flow 用。返回 None 表示提取失败 → 后续 traverse_related_items 将 skip 深入。"""
    try:
        root = etree.fromstring(main_xml.encode("utf-8"))
        _, screen_h = get_screen_size()
        cutoff_y = screen_h * 0.22  # 顶部 22% 内
        candidates = []  # (y, text)
        for node in root.iter("node"):
            t = (node.get("text") or "").strip()
            if not t or len(t) < 3 or len(t) > 50:
                continue
            # 排除状态/时间/电量/数值
            if re.match(r"^\d+([:.\-]\d+)*$", t):
                continue
            if "%" in t or t.lower().endswith(("dbm", "kb", "mb", "gb")):
                continue
            if t in {"잠김", "잠금 해제됨", "오프라인", "온라인", "켜짐", "꺼짐"}:
                continue
            bounds = node.get("bounds", "")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not m:
                continue
            y1 = int(m.group(2))
            if y1 > cutoff_y:
                continue
            candidates.append((y1, t))
        candidates.sort()  # by y, top first
        for _, t in candidates:
            # 跳过单字符 emoji / 装饰
            if any(c.isalpha() or '가' <= c <= '힯' or '一' <= c <= '鿿' for c in t):
                return t
        return None
    except Exception:
        return None


# def _find_clickable_ancestor_bounds(node, max_hops=5):
#     """向上找 max_hops 级 clickable 祖先,返回 bounds 或 None。"""
#     cur = node
#     hops = 0
#     while cur is not None and hops < max_hops:
#         if cur.get("clickable") == "true":
#             b = cur.get("bounds", "")
#             if re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b):
#                 return b
#         cur = cur.getparent()
#         hops += 1
#     return None
def _find_clickable_ancestor_bounds(node, max_hops=15):
    """向上找 max_hops 级 clickable 祖先，找不到则返回节点自身的 bounds 作为保底。"""
    cur = node
    hops = 0
    while cur is not None and hops < max_hops:
        if cur.get("clickable") == "true":
            b = cur.get("bounds", "")
            if re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b):
                return b
        cur = cur.getparent()
        hops += 1
    
    # 💡 核心保底优化：如果多设备适配时层级太深或没写 clickable，直接返回文本节点自身的坐标，确保绝对能点到
    b = node.get("bounds", "")
    if re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b):
        return b
    return None


def find_text_clickable(xml_str, target_text, exact=True):
    """在 XML 找文本匹配 target_text 的节点,返回最近 clickable 祖先的 bounds。"""
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
        for node in root.iter("node"):
            t = (node.get("text") or "").strip()
            if (exact and t == target_text) or (not exact and t and target_text in t):
                b = _find_clickable_ancestor_bounds(node)
                if b:
                    return b
        return None
    except Exception:
        return None


# def find_add_button_after_section(xml_str, section_text):
#     """找 section_text header 下方最接近的 '추가' clickable bounds。"""
#     try:
#         root = etree.fromstring(xml_str.encode("utf-8"))
#         section_y = None
#         for node in root.iter("node"):
#             if (node.get("text") or "").strip() == section_text:
#                 m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
#                 if m:
#                     section_y = int(m.group(2))
#                     break
#         if section_y is None:
#             return None
#         best, best_dy = None, 10**9
#         for node in root.iter("node"):
#             if (node.get("text") or "").strip() != "추가":
#                 continue
#             m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
#             if not m:
#                 continue
#             y1 = int(m.group(2))
#             if y1 <= section_y:
#                 continue
#             b = _find_clickable_ancestor_bounds(node)
#             if not b:
#                 continue
#             dy = y1 - section_y
#             if dy < best_dy:
#                 best_dy = dy
#                 best = b
#         return best
#     except Exception:
#         return None
def find_add_button_after_section(xml_str, section_text):
    """找 section_text header 下方最接近的 '추가' clickable bounds。"""
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
        section_y = None
        for node in root.iter("node"):
            node_text = (node.get("text") or "").strip()
            # 💡 修改点 1：将 == 改为 startswith，以兼容 "자동실행 (0)" 或 "자동실행 (1)" 等多设备动态数量
            if node_text.startswith(section_text):
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
                if m:
                    section_y = int(m.group(2))
                    break
        if section_y is None:
            return None
            
        best, best_dy = None, 10**9
        for node in root.iter("node"):
            if (node.get("text") or "").strip() != "추가":
                continue
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
            if not m:
                continue
            y1 = int(m.group(2))
            if y1 <= section_y:
                continue
            b = _find_clickable_ancestor_bounds(node)
            if not b:
                continue
            dy = y1 - section_y
            if dy < best_dy:
                best_dy = dy
                best = b
        return best
    except Exception:
        return None


def find_own_device_with_marker(xml_str, own_name, marker="현재"):
    """在设备清单页找 clickable container,同时包含 own_name(exact)和 marker(substr)文本。
    返回 (bounds, texts_list) 或 None。
    严格双要件,防误点。"""
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
        for node in root.iter("node"):
            if node.get("clickable") != "true":
                continue
            texts = []
            has_name, has_marker = False, False
            for c in node.iter("node"):
                t = (c.get("text") or "").strip()
                if t:
                    texts.append(t)
                    if t == own_name:
                        has_name = True
                    if marker in t:
                        has_marker = True
            if has_name and has_marker:
                b = node.get("bounds", "")
                if re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b):
                    return b, texts
        return None
    except Exception:
        return None


def traverse_related_items(device, own_device_name, breadcrumb, results, indent=""):
    """장치 관련 항목 页的专项扫描(자동실행 + 동시실행 → 추가 → 条件 → 장치 → 自己设备)。

    调用前提:已经 click 进了 장치 관련 항목 页(由 traverse_recursive 钩入)。
    返回时:期望停在 장치 관련 항목 页(由外层 BACK 回 settings)。

    所有 step 包 try,任何意外 → 多 BACK 几次安全退。
    """
    print(f"{indent}  [RELATED] entering special traversal (own='{own_device_name}')", flush=True)

    # ---- 1. 抓取 장치 관련 항목 页本身 ----
    try:
        page_xml = device.dump_hierarchy()
        page_sig = get_text_signature(page_xml)
        page_texts, _ = extract_app_texts(page_xml)
        sname = safe_name(" > ".join(breadcrumb)) or "related_items"
        try:
            device.screenshot(str(OUTPUT_DIR / f"{sname}.png"))
            (OUTPUT_DIR / f"{sname}.xml").write_text(page_xml, encoding="utf-8")
        except Exception:
            pass
        results.append({
            "path": " > ".join(breadcrumb),
            "depth": len(breadcrumb),
            "status": "captured_related_items",
            "app_text_count": len(page_texts),
            "app_texts": page_texts,
        })
        print(f"{indent}    [OK] {len(page_texts)} (related-items page)", flush=True)
    except Exception as e:
        print(f"{indent}  [RELATED] capture related-items page failed: {e}", flush=True)
        return

    # ---- 2. 没有自身设备名 → graceful skip 深入 ----
    if not own_device_name:
        print(f"{indent}  [RELATED] CURRENT_DEVICE_NAME unset, skipping deep scan (safe mode)", flush=True)
        return

    # ---- 3. 对每个 section 子遍历 ----
    for section in ["자동실행", "동시실행","장치 연결"]:
        print(f"{indent}  [RELATED] === section: {section} ===", flush=True)
        try:
            cur_xml = device.dump_hierarchy()
            add_bounds = find_add_button_after_section(cur_xml, section)
            if not add_bounds:
                print(f"{indent}    [RELATED] no '추가' under '{section}',skipping section", flush=True)
                continue

            # 点击 추가 → 进入 conditions 页
            print(f"{indent}    [RELATED] click '추가' under '{section}' @ {add_bounds}", flush=True)
            if not click_by_bounds(device, add_bounds):
                continue
            
            # ✨ 升级为智能等待
            cond_xml = wait_until_rn_page_stable(device, timeout=6.0)
            cond_texts, _ = extract_app_texts(cond_xml)
            cond_sname = safe_name(" > ".join(breadcrumb + [section, "추가"]))
            try:
                device.screenshot(str(OUTPUT_DIR / f"{cond_sname}.png"))
                (OUTPUT_DIR / f"{cond_sname}.xml").write_text(cond_xml, encoding="utf-8")
            except Exception:
                pass
            results.append({
                "path": " > ".join(breadcrumb + [section, "추가"]),
                "depth": len(breadcrumb) + 1,
                "status": "captured_conditions",
                "app_text_count": len(cond_texts),
                "app_texts": cond_texts,
            })
            print(f"{indent}    [OK] {len(cond_texts)} ({section} conditions)", flush=True)

            # 对每个 cond button 子流程
            for cond_btn in ["트리거 조건 추가", "상태 조건 추가", "작업 추가", "동작 추가"]:
                try:
                    # 重新 dump conditions 页 + find button (防止 state 变了)
                    check_xml = device.dump_hierarchy()
                    btn_bounds = find_text_clickable(check_xml, cond_btn, exact=True)
                    if not btn_bounds:
                        print(f"{indent}      [RELATED] '{cond_btn}' not found,skip", flush=True)
                        continue
                    print(f"{indent}      [RELATED] click '{cond_btn}' @ {btn_bounds}", flush=True)
                    if not click_by_bounds(device, btn_bounds):
                        continue
                    
                    # ✨ 升级为智能等待
                    opt_xml = wait_until_rn_page_stable(device, timeout=6.0)
                    opt_texts, _ = extract_app_texts(opt_xml)
                    opt_sname = safe_name(" > ".join(breadcrumb + [section, cond_btn]))
                    try:
                        device.screenshot(str(OUTPUT_DIR / f"{opt_sname}.png"))
                        (OUTPUT_DIR / f"{opt_sname}.xml").write_text(opt_xml, encoding="utf-8")
                    except Exception:
                        pass
                    results.append({
                        "path": " > ".join(breadcrumb + [section, cond_btn]),
                        "depth": len(breadcrumb) + 2,
                        "status": "captured_options",
                        "app_text_count": len(opt_texts),
                        "app_texts": opt_texts,
                    })
                    print(f"{indent}      [OK] {len(opt_texts)} ({cond_btn} options)", flush=True)

                    # 点击 장치
                    jangchi_bounds = find_text_clickable(opt_xml, "장치", exact=True)
                    if not jangchi_bounds:
                        print(f"{indent}      [RELATED] no '장치' option,BACK", flush=True)
                        device.press("back"); time.sleep(1.5)
                        continue
                    print(f"{indent}      [RELATED] click '장치' @ {jangchi_bounds}", flush=True)
                    if not click_by_bounds(device, jangchi_bounds):
                        device.press("back"); time.sleep(1.5)
                        continue
                    time.sleep(2.5)

                    # 现在在设备清单页 — 找自己 + '현재'
                    list_xml = device.dump_hierarchy()
                    found = find_own_device_with_marker(list_xml, own_device_name, "현재")
                    if not found:
                        print(f"{indent}      [RELATED] own device not in list with '현재',skipping deeper", flush=True)
                        device.press("back"); time.sleep(1.5)   # → options
                        device.press("back"); time.sleep(1.5)   # → conditions
                        continue

                    own_bounds, _ = found
                    print(f"{indent}      [RELATED] ✓ own device matched ('현재' present),click @ {own_bounds}", flush=True)
                    if not click_by_bounds(device, own_bounds):
                        device.press("back"); time.sleep(1.5)
                        device.press("back"); time.sleep(1.5)
                        continue
                    
                    # === 【结合：智能等待 + 长清单滚动抓取去重逻辑】 ===
                    print(f"{indent}      [SCROLL] start scrolling capture for own device sub-page...", flush=True)
                    
                    all_sub_texts = []
                    seen_text_contents = set()  
                    scroll_xmls = []            
                    
                    max_scrolls = 4             
                    has_scrolled_any = False    
                    
                    for scroll_idx in range(max_scrolls):
                        # ✨ 第一帧或滚动后的新帧，使用智能等待确保 RN 组件彻底加载定型后再提数据
                        current_sub_xml = wait_until_rn_page_stable(device, timeout=5.0)
                        current_texts, _ = extract_app_texts(current_sub_xml)
                        
                        new_added_in_frame = 0
                        for tx_obj in current_texts:
                            t_val = tx_obj.get("text", "").strip()
                            t_key = (t_val, tx_obj.get("type"), tx_obj.get("class"))
                            if t_val and t_key not in seen_text_contents:
                                seen_text_contents.add(t_key)
                                all_sub_texts.append(tx_obj)
                                new_added_in_frame += 1
                        
                        scroll_xmls.append(current_sub_xml)
                        print(f"{indent}      [SCROLL] frame {scroll_idx+1}: found {len(current_texts)} texts, ({new_added_in_frame} new added)", flush=True)
                        
                        # 尝试下滑
                        scroll_success = device.swipe(0.5, 0.7, 0.5, 0.3, duration=0.25)
                        time.sleep(1.0) 
                        
                        post_scroll_xml = device.dump_hierarchy()
                        if get_text_signature(current_sub_xml) == get_text_signature(post_scroll_xml):
                            print(f"{indent}      [SCROLL] reached list bottom, stop.", flush=True)
                            break
                        has_scrolled_any = True

                    sub_sname = safe_name(" > ".join(breadcrumb + [section, cond_btn, own_device_name]))
                    try:
                        device.screenshot(str(OUTPUT_DIR / f"{sub_sname}.png"))
                        final_save_xml = scroll_xmls[-1] if scroll_xmls else device.dump_hierarchy()
                        (OUTPUT_DIR / f"{sub_sname}.xml").write_text(final_save_xml, encoding="utf-8")
                        
                        if has_scrolled_any:
                            for idx, s_xml in enumerate(scroll_xmls):
                                try:
                                    (OUTPUT_DIR / f"{sub_sname}__scroll_f{idx+1}.xml").write_text(s_xml, encoding="utf-8")
                                    device.screenshot(str(OUTPUT_DIR / f"{sub_sname}__scroll_f{idx+1}.png"))
                                except Exception: pass
                    except Exception:
                        pass

                    results.append({
                        "path": " > ".join(breadcrumb + [section, cond_btn, own_device_name]),
                        "depth": len(breadcrumb) + 3,
                        "status": "captured_own_in_related",
                        "app_text_count": len(all_sub_texts),
                        "app_texts": all_sub_texts,
                    })
                    print(f"{indent}      [OK] Total {len(all_sub_texts)} texts merged across scrolling ({section})", flush=True)

                    # 3 次 BACK 回 conditions 页(own → list → options → conditions)
                    device.press("back"); time.sleep(1.5)
                    device.press("back"); time.sleep(1.5)
                    device.press("back"); time.sleep(1.5)

                except Exception as e:
                    print(f"{indent}      [RELATED] '{cond_btn}' exception: {e}", flush=True)
                    # 兜底 BACK 几次回 conditions
                    for _ in range(3):
                        try: device.press("back"); time.sleep(1.0)
                        except Exception: break
                    continue

            # section 完毕 → BACK 1 次回 장치 관련 항목 页
            device.press("back"); time.sleep(1.8)
            # 验证(用 page_sig 宽松匹配)— 若不在,extra BACK
            try:
                cur_sig = get_text_signature(device.dump_hierarchy())
                if not signatures_match(cur_sig, page_sig, threshold=0.5):
                    print(f"{indent}  [RELATED] drifted after section '{section}',extra BACK", flush=True)
                    device.press("back"); time.sleep(1.5)
            except Exception:
                pass

        except Exception as e:
            print(f"{indent}  [RELATED] section '{section}' exception: {e}", flush=True)
            # 兜底 BACK 几次试图回 장치 관련 항목
            for _ in range(4):
                try: device.press("back"); time.sleep(1.0)
                except Exception: break
            # 检查是否还在 장치 관련 항목,不在就尝试 nav 回 settings(让外层处理)
            try:
                cur_sig = get_text_signature(device.dump_hierarchy())
                if not signatures_match(cur_sig, page_sig, threshold=0.4):
                    print(f"{indent}  [RELATED] lost related-items page after exception,early return", flush=True)
                    return
            except Exception:
                return

    print(f"{indent}  [RELATED] === all sections done ===", flush=True)


def traverse_recursive(device, breadcrumb, results, visited_sigs, depth=0, ancestor_sigs=None):
    if ancestor_sigs is None:
        ancestor_sigs = []

    indent = "  " * depth
    if depth > MAX_DEPTH:
        print(f"{indent}[DEPTH] hit MAX_DEPTH={MAX_DEPTH}", flush=True)
        return

    # ★ 2026-05-21:장치 관련 항목 / 장치 연관 항목 专项扫描(자동실행 + 동시실행 추가流程)
    # 优先于 CAPTURE_NO_RECURSE_KEYWORDS / PAGE_CONTENT_NO_RECURSE_MARKERS,因为这是
    # 用户明确要求的 deep scan,不能被 capture-only 短路。
    # 钩子条件:刚 click 进 related-items 子页。
    # 没有 CURRENT_DEVICE_NAME 时 traverse_related_items 内部 graceful skip(只 capture 页面)。
    #
    # ★ 2026-05-26(case #56)扩展匹配:G2H Pro 摄像头 L0 入口标题是 content-desc 形式的长句
    # `[desc]장치 연결 연관된 자동 실행, 동시 실행 등`(不是 T1/T2 的简短 `장치 관련 항목`)。
    # 实际页面布局完全一样(자동실행 + 동시실행 sections + 추가 按钮)。
    # 加 substring 匹配:标题同时含 `자동 실행/실행` 和 `동시 실행/실행` → 触发(强信号,专属 related-items 入口)。
    if breadcrumb:
        last = breadcrumb[-1]
        clean = last[6:] if last.startswith("[desc]") else last
        is_related_entry = (
            clean in ("장치 관련 항목", "장치 연관 항목")  # T1/T2 精确匹配(向后兼容)
            or ("자동 실행" in clean and "동시 실행" in clean)  # G2H Pro 风格(带空格)
            or ("자동실행" in clean and "동시실행" in clean)    # 无空格变体
        )
        if is_related_entry:
            try:
                traverse_related_items(device, CURRENT_DEVICE_NAME, breadcrumb, results, indent)
            except Exception as e:
                print(f"{indent}  [RELATED] top-level exception: {e}", flush=True)
            return

    # ★ 2026-05-21:设备自身名称卡片 = capture-only,不递归
    # 触发场景:P2 settings 顶部 '열림 감지 센서 P2' 卡片 click → 进 '장치 정보' 子页
    # (含 장치 이름 / 장치 위치 / 사용자 매뉴얼 等 10 个子项)。
    # 原本递归 → L1 discovery 误混 L0 items(过渡 dump 状态)→ L1 处理 15 items 后无法干净 BACK
    # → L0 剩余 items VANISHED → ABORT
    # 修:精确匹配 CURRENT_DEVICE_NAME 时直接 capture-only return。
    # 父级 click 时已经 capture 了 38 条 sub-page 文本(包含所有子项 label + value),够翻译审计用;
    # 单 sub-item 的 WebView (사용자 매뉴얼 / 자주하는 질문) probe 在父级 click 时已经触发 FAQ probe,
    # 实际不丢内容。CURRENT_DEVICE_NAME 提取失败时不触发,走原逻辑(安全 fallback)。
    if breadcrumb and CURRENT_DEVICE_NAME and breadcrumb[-1] == CURRENT_DEVICE_NAME:
        print(f"{indent}[CAPTURE-ONLY-PARENT] '{breadcrumb[-1]}' (device-info card,matches CURRENT_DEVICE_NAME)", flush=True)
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
    # ★ 2026-05-26(case #59):snapshot upfront 发现的 "真" titles。
    # 后续 _record_items 添加的 items 可能含 sub-page leak(RN overlay 关闭后 view tree 残留),
    # 不应该被主循环作为"L0 待处理 title" 追踪。
    initial_discovered_set = set(discovered_order)
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
        # ★ 从 discovered_order 取下一个未处理 title(保持首见顺序,决定遍历顺序)
        # ★ 2026-05-27(case #59 二修): 撤销初版"只追 initial"限制。
        # 原因:M3 hub 主页 click `192.168.50.213` 会 inline 展开网络信息 section,
        # 展开后的 items(지그비 채널/Wi-Fi 채널/Thread/MAC 等)是 LEGIT 的 click-revealed
        # L0 内容,需要扫描("宁可多也不要少")。初版误把这些也算 pollution。
        # 改成:追 discovered_order 全部 items (含 click-revealed 和潜在 leak),
        # 但在 VANISHED handler 区分:initial items VANISHED → 真问题,计入 consecutive;
        # 后期 _record_items 加进来的 VANISHED → 静默 seen,不计 consecutive(避免假 ABORT)。
        next_title = next((t for t in discovered_order if t not in seen_titles), None)

        if next_title is None:
            # 全部 title 都处理过了。最后机会:dump 一次 + fling-top 各 record 一次,
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
            # ★ 2026-05-27(case #59 二修):区分 initial item VANISHED vs 后期 _record_items 加进来的
            # item VANISHED。后者大概率是 sub-page leak(M3 hub Matter Controller L1 items 漏到 L0
            # discovered_order)— find 不到是正常的,**不应该计入 consecutive_vanished** 触发 ABORT。
            # initial items VANISHED 才是真问题(device drift)。
            is_initial_item = next_title in initial_discovered_set
            if is_initial_item:
                print(f"{indent}  [VANISHED] '{next_title}' no longer findable on screen", flush=True)
            else:
                print(f"{indent}  [SKIP-LEAK] '{next_title}' not found (likely sub-page leak,not initial L0)", flush=True)
            seen_titles.add(next_title)
            results.append({
                "path": " > ".join(breadcrumb + [next_title]),
                "depth": depth + 1,
                "status": "vanished" if is_initial_item else "skipped_leak",
            })
            if not is_initial_item:
                continue   # 不计入 consecutive_vanished,直接处理下一项
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
        # ★ 2026-05-21:房间名 click 守卫 — exact match,防止 commit 设备位置变更
        # 触发设备:LED 전구 T2(E26, CCT) — 通过 device card 绕到 room chooser,
        # 每点一个房间名都会永久改变设备的 location 字段。
        if title.strip() in ROOM_NAMES_EXACT and len(breadcrumb) >= 1:
            print(f"{indent}  [SKIP-ROOM] {title}: room name click would commit device location change", flush=True)
            results.append({"path": path_str, "depth": depth+1, "status": "skipped_room",
                           "reason": "room name (location change destructive)",
                           "all_texts_on_card": item["texts"]})
            continue

        print(f"{indent}  [CLICK L{depth+1}] {title}", flush=True)
        if not click_by_bounds(device, item["bounds"]):
            results.append({"path": path_str, "depth": depth+1, "status": "click_failed"})
            continue

        time.sleep(ACTIVITY_DETECT_DELAY)
        # ★ 2026-05-26(case #50)REMOVED: wait_until_rn_page_stable(device, timeout=5.0)
        # 原本在这里多调一次 RN smart wait,但 wait_for_page_ready 本身就 poll sig 稳定 + WebView + loading-keyword
        # 检测 — 重复调用每 click 多花 3-5 秒,且 wait_for_page_ready 更全面。
        # 真正修复 RN 双重渲染的 bug 在 wait_until_rn_page_stable 内部(sleep 后 re-dump)— 不需要主 loop 调用。
        # wait_until_rn_page_stable 现在只在 traverse_related_items 子流程里用(没有 wait_for_page_ready 覆盖的地方)。

        # ★ SLOW_DEVICE_MODE 额外等待 click → 页面响应的延迟(老手机 / 慢 RN bundle)
        if WAIT_AFTER_CLICK_EXTRA > 0:
            time.sleep(WAIT_AFTER_CLICK_EXTRA)
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
        # ★ 2026-05-21:加 discovered_order 守卫。父页菜单 items 可能 scroll 出视野
        # 没在 page_sig 里(典型:LED T2 신호 강도 / 도어락 동작 확인 → 子页含 "장치 관련 항목"
        # 但这其实是父设置页的菜单项,只是初始 dump 时滚到屏幕下方了)。如果 marker 文本
        # 已经出现在 discovered_order 的 title 里 → 不是真 chooser,skip。
        new_markers = [
            marker for marker in PAGE_CONTENT_NO_RECURSE_MARKERS
            if any(marker in t for t in sub_sig)
            and not any(marker in t for t in page_sig)
            and not any(marker in dt for dt in discovered_order)
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
                # ★ 2026-05-21 Fix:在 L0 (depth==0) 且仍有 ≥2 个未处理 items 时,先尝试一次
                # _try_recover_to_settings(同 case #34 VANISH-RECOVERY 模式)。LED 전구 T2 신호 강도
                # click → CHOOSER-REVEALED 后 BACK off-parent → return → 后面 5 个 settings items
                # (펌웨어 업데이트 / 통신 프로토콜 / 장치 관련 항목 / 장치 로그 / 장치 그룹 생성)全跳过。
                # 恢复成功 → continue 处理剩余 items;失败 → 原 return 行为。
                remaining = [t for t in discovered_order if t not in seen_titles]
                if depth == 0 and len(remaining) >= 2:
                    print(f"{indent}    [CHOOSER-RECOVERY] BACK off parent, {len(remaining)} titles unprocessed, attempting re-nav...", flush=True)
                    if _try_recover_to_settings(device, page_sig, indent):
                        print(f"{indent}    [CHOOSER-RECOVERY] re-nav OK, resuming with {len(remaining)} unprocessed titles", flush=True)
                        continue
                    else:
                        print(f"{indent}    [CHOOSER-RECOVERY] re-nav failed, returning", flush=True)
                print(f"{indent}    [CHOOSER] BACK landed off parent — return to let caller recover", flush=True)
                return
            continue

        # ★ 如果点击对象在 CAPTURE_NO_RECURSE_KEYWORDS 里 ...
        # ★ 2026-05-21:title 命中 CAPTURE_NO_RECURSE_KEYWORDS,或精确匹配 CURRENT_DEVICE_NAME
        # (设备自身名称卡片)→ 都强制 BACK(跳过 Case A signature 匹配),保证 BACK 回父页。
        # ★ 2026-05-21 加:장치 관련 항목 / 장치 연관 항목 也强制 — 防 NO-OP-SCROLL mode-toggle 误判
        # 拦截后 hook 没机会进 recursion 触发 traverse_related_items。
        # ★ 2026-05-26(case #56)扩展:加 G2H Pro 风格(标题含 자동 실행 + 동시 실행)
        _title_clean = title[6:] if title.startswith("[desc]") else title
        title_forces_navigation = (
            any(kw in title for kw in CAPTURE_NO_RECURSE_KEYWORDS)
            or (CURRENT_DEVICE_NAME is not None and title == CURRENT_DEVICE_NAME)
            or _title_clean in ("장치 관련 항목", "장치 연관 항목")
            or ("자동 실행" in _title_clean and "동시 실행" in _title_clean)
            or ("자동실행" in _title_clean and "동시실행" in _title_clean)
        )

        # ★ 新文本量：真正的导航通常会引入大量新文本(页头/列表/按钮)，
        # 而内嵌展开/滚动 即使损失了一些 items，新文本通常 ≤ 3 条。
        new_texts_in_sub = sub_sig - page_sig
        new_text_count = len(new_texts_in_sub)

        # NO-OP check 2: 真正的滚动/展开（不是弹窗 / 不是导航）
        # 三条任一满足都算 scroll-only:
        #   A 经典严格：preservation>=0.9 且 items_preserved>=0.7
        #   B 兜底（M3 hub 类长设置页）：preservation>=0.8 且新文本 ≤3 条
        #     —— "几乎没有新内容" 是 inline-expansion 的强信号，即使 items 重排得多。
        #   C 同 items 矩阵(2026-05-13): items_preserved>=0.95
        #     —— "items 几乎完全一样" 说明这是 mode toggle 按钮矩阵或状态切换,
        #     即使文字大变(状态详情更新)也不是真子页 — 治浴霸/T1-1 类的递归爆炸
        #     ★ 2026-05-20:之前临时加 new_text<=8 守卫(为门锁 FAQ 漏抓),会导致
        #     浴배 낮음/중간(new=9)和 모션 P2 menu items(new=9-23)误翻成 captured →
        #     可能重现 case #33 的递归炸弹。还原 + 改用 keyword override(下方
        #     CAPTURE_NO_RECURSE_KEYWORDS 加门锁子页关键字)。
        is_strong_scroll = (preservation >= 0.9 and items_preserved >= 0.7)
        # ★ 2026-06-01(case #73):condition B 加 items_preserved>=0.7 守卫,
        # 防 H2 switch 类"简单 toggle 子页"误判 NO-OP-SCROLL。
        # 触发场景:릴레이 잠금 / 설치 방향 click → 真子页(items 58%,2 个 new texts)
        # 原 B 只看 text + new → 误判 scroll → 不递归 → 后续 items VANISH 链。
        # 修:加 items_preserved>=0.7 — inline 展开 items 几乎全在(>=0.7),真子页 items 大量消失(<0.7)。
        # 影响:历史 27 scans 里只 M3 hub `적외선 리모컨`(items 69%)borderline,
        # 即使变成真递归也有 CYCLE 守卫接住。其他设备零影响(items 都>=0.7 或 condition A/C 已命中)。
        # 回退:把下行恢复成 `is_minor_change = (preservation >= 0.8 and new_text_count <= 3)`。
        # is_minor_change = (preservation >= 0.8 and new_text_count <= 3)  # ★ 旧版,保留以备回退
        is_minor_change = (preservation >= 0.8 and new_text_count <= 3 and items_preserved >= 0.7)
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
        # ★ 2026-05-26(case #50)RN 同步 fix:screenshot 之前 re-dump 一次,确保 sub_xml 与 PNG 完全同时刻
        # 旧:sub_xml 是 wait_for_page_ready 几秒前 dump 的,期间 RN 可能继续渲染 → screenshot 与 xml 错位
        # 新:先 dump 再 screenshot,两者间隔 < 50ms,基本不可能错位
        try:
            sub_xml = device.dump_hierarchy()
        except Exception:
            pass  # 保留旧 sub_xml
        device.screenshot(str(OUTPUT_DIR / f"{sname}.png"))
        (OUTPUT_DIR / f"{sname}.xml").write_text(sub_xml, encoding="utf-8")

        # ★ WebView FAQ 类页面探测:如有 ≥3 个 "?" 结尾的 TextView → 依次 tap 各问题,保存展开后截图 + dump。
        # ★ 2026-05-27(case #60):probe_faq_expansions 现在也 dump + extract native 答案文本,merge 进 app_texts。
        # WebView 内的 HTML 答案 dump 抓不到 → Phase 3 Vision OCR 兜底(截图已保存)。
        # Native TextView 渲染的答案 dump 能拿到 → 这里 merge 进 app_texts,翻译审计也覆盖。
        faq_probed, faq_expanded_texts = probe_faq_expansions(device, sub_xml, sname, OUTPUT_DIR)
        if faq_expanded_texts:
            app_texts = app_texts + faq_expanded_texts  # merge,保持顺序(原页面 → FAQ 答案)

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
            "faq_expanded_text_count": len(faq_expanded_texts) if faq_expanded_texts else None,
        })
        loading_marker = " [STILL_LOADING]" if captured_loading else ""
        faq_marker = f" [FAQ:{faq_probed}q+{len(faq_expanded_texts)}t]" if faq_probed else ""
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
                # ★ 2026-05-28(case #69):dialog 含 text input + IME 弹出时(典型: G3
                # 摄像机 L1 장치 정보 → 장치 이름 click → 이름 변경 dialog + 韩文键盘),
                # 취소 click 后 dialog 关 + 键盘 dismiss 动画 ~500ms。原 sleep(1.0)
                # 不够,sig check 时键盘还在 dismiss,导致 sig <85% match → 走 BACK 一次
                # → depth>0 时从 L1 越界回 L0 → L1 后续 items 全 VANISH → ABORT。
                # 修:sig 不匹配时多等 1.5s 让动画完成 + re-dump 再 check,真正稳定才走
                # recovery / BACK。命中场景 ~5% click,extra 1.5s + 1 dump 可接受。
                time.sleep(1.5)
                current_sig = get_text_signature(device.dump_hierarchy())
            if not signatures_match(current_sig, page_sig, threshold=0.85):
                # ★ 2026-05-21:dialog 확인 click 的副作用可能把脚本顶到 device main
                # (典型:LED T2 통신 프로토콜 → "Zigbee" info dialog → 按 확인 → 跳 device main)。
                # 原代码 BACK 一次 — 在 device main 上 BACK 会越界到 device list,后面 items 全 VANISHED。
                # 改:L0 (depth==0) 时分情况处理:
                #   - 在 device list → 停(BACK 会出 app)
                #   - 不在 settings → 用 _try_recover_to_settings(内部 sig 已匹配 → 立即 OK / auto_nav 找 "..." 重进)
                #   - 在 settings(轻微 mismatch) → 走原 BACK 一次(不动)
                # depth > 0(子页 dialog)走原 BACK,不改行为(避免回归)。
                # ★ 用 sig overlap 区分"轻微 mismatch"vs"明显飘走":
                # is_on_settings_page(lenient=True) 对 device main 也返回 True(只要 ≥3 个菜单 item),
                # 所以不能靠它区分。改用 sig overlap < 0.3 (clearly different page) 触发 recovery,
                # 0.3-0.85 之间(state 略 drift / scroll diff)走原 BACK。
                if depth == 0:
                    if is_on_device_list(device):
                        print(f"{indent}    [DIALOG] drifted to device list,stopping iteration", flush=True)
                        return
                    if not signatures_match(current_sig, page_sig, threshold=0.3):
                        # 明显飘到不同页(< 30% overlap),典型:通신 프로토콜 'Zigbee' dialog 按确认 → device main
                        print(f"{indent}    [DIALOG] drifted off settings (sig <30%),attempting recovery", flush=True)
                        if _try_recover_to_settings(device, page_sig, indent):
                            print(f"{indent}    [DIALOG-RECOVERY] back on settings,resuming", flush=True)
                        else:
                            # ★ 2026-05-28(case #70):_try_recover_to_settings 设计针对 Phase B
                            # (找 "..." 重进 settings)。Phase A 调用时,如果 "확인" click 进了
                            # 真子页(典型:G3 摄像头 관심구역 → tutorial modal 확인 → 真 관심구역
                            # 子页),子页没 "..." → S4/S5/S6 全 0 candidates → recovery 失败 →
                            # 原代码 return 中止 Phase A → Phase B nav 也找不到 settings → 脚本"中断"。
                            # 修:recovery 失败前再做一轮 aggressive BACK(5 次 × sleep 2s 给 RN
                            # 充分反应)+ sig check。RN 子页 BACK 偶尔被 RN 拦截需要多按几下。
                            print(f"{indent}    [DIALOG-RECOVERY] try aggressive BACK fallback", flush=True)
                            aggressive_recovered = False
                            for back_i in range(5):
                                try:
                                    device.press("back"); time.sleep(2.0)
                                    if is_on_device_list(device):
                                        print(f"{indent}    [DIALOG-RECOVERY] hit device list at BACK #{back_i+1}, stopping", flush=True)
                                        return
                                    cur_sig = get_text_signature(device.dump_hierarchy())
                                    if signatures_match(cur_sig, page_sig, threshold=0.5):
                                        print(f"{indent}    [DIALOG-RECOVERY] aggressive BACK #{back_i+1} succeeded", flush=True)
                                        aggressive_recovered = True
                                        break
                                except Exception:
                                    pass
                            if not aggressive_recovered:
                                print(f"{indent}    [DIALOG-RECOVERY] failed,stopping iteration", flush=True)
                                return
                    else:
                        # 0.3-0.85: 还在 settings 但 state/scroll 略 drift,原 BACK 兼容行为
                        device.press("back"); time.sleep(1.0)
                else:
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
        try:
            current_xml = device.dump_hierarchy()
        except Exception:
            current_xml = ""
        current = get_text_signature(current_xml)

        # Case A: 我们已经在自己这一层的页（子层 drift 回来 / CYCLE-UP 后停在这）
        # 用宽松阈值 0.7(原 0.85):chooser-back-drift / 选项被选中导致 sig 细微变化时仍认为已恢复
        # ★ 2026-05-21:title_forces_navigation 强制跳过 Case A,直接走 Case C (BACK)。
        # 原因:CAPTURE_NO_RECURSE_KEYWORDS 命中(如 "전환 설정")时,递归会立即 CAPTURE-ONLY-PARENT
        # return 而**没有 BACK**,此时仍停留在 sub-page。sub-page 常常保留父页菜单 items
        # (items_preserved 高) → sig overlap >= 0.7 → Case A 误判已回父页 → continue 跳过 BACK
        # → 下一次点击落到 sub-page 的某项上,触发 [VANISHED]/[CYCLE-UP] 死循环(LED 전구 T2
        # 전환 설정 bug)。强制 BACK 才能脱离 sub-page。
        if not title_forces_navigation and signatures_match(current, page_sig, threshold=0.7):
            # ★ 2026-05-26(case #58):sig overlap 过 0.7 但可能在 sub-page。
            # 触发场景:P2 摄像头 장비 진단 sub-page 跟 L0 settings 共享 18/21 文本(85% overlap)
            # → Case A 误判已回 L0 → silent continue 不 BACK → 下次 click 落 sub-page → 全错
            # 根因:RN sub-page 是 overlay panel,L0 menu items 仍在底层 view hierarchy,大量重叠。
            # 守卫(只 L0 启用,L1/L2 不动避免回归):cur 的 menu items 中至少 70% initial top items 仍在
            # → 真回 L0;否则 → 在 sub-page,fall through 走 BACK。
            if depth == 0 and current_xml:
                try:
                    cur_titles = {i["primary_text"] for i in parse_menu_items(current_xml)}
                    init_titles = {i["primary_text"] for i in items}
                    if init_titles and len(init_titles) >= 3:
                        in_cur_ratio = len(cur_titles & init_titles) / len(init_titles)
                        if in_cur_ratio < 0.7:
                            print(f"{indent}  [CASE-A-OVERRIDE] sig match but only {in_cur_ratio:.0%} initial items in cur — likely on sub-page,force BACK", flush=True)
                            pass  # fall through to Case C BACK
                        else:
                            continue
                    else:
                        continue
                except Exception:
                    continue
            else:
                continue   # L1/L2/etc:走原逻辑(避免回归)

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
                cur_xml = device.dump_hierarchy()
                cur = get_text_signature(cur_xml)
            except Exception:
                cur_xml = ""
                cur = frozenset()
            if signatures_match(cur, page_sig, threshold=0.7):
                if back_attempt > 0:
                    print(f"{indent}  [RECOVER] settled at parent after {back_attempt+1} extra BACK(s)", flush=True)
                recovered = True
                break
            # ★ 2026-05-21:严格 sig 不匹配,但其实可能在 settings 页(scroll 位置不同 / state 略变)。
            # depth==0 时:如果 is_on_settings_page(lenient=True) 说在 settings 上,scroll-to-top
            # 再 retry sig match。触发场景:LED T2 신호 강도 chart sub-page → BACK 后回到 settings,
            # 但 scroll 位置停在 신호 강도 附近(mid-scroll) → 不显示 page_sig 顶端 items → sig 不匹配
            # → 原本会 BACK 把我们顶出 device。
            # ★ lenient=True 必要(原 False 不行):RN 设备(LumiRNMainActivity)既无 activity hint 也无
            # cl_root_layout/item_layout anchor → 严格模式永远 false,scroll fix 从来不触发。
            # 用 lenient(看是否 looks_like_menu_page)能识别 RN settings 页。误识别 device main 也无害
            # (sig 仍不匹配 → fall through BACK)。
            if depth == 0 and is_on_settings_page(device, lenient=True):
                try:
                    scroll_page_to_top(device)
                    time.sleep(0.6)
                    cur_xml = device.dump_hierarchy()
                    cur = get_text_signature(cur_xml)
                    if signatures_match(cur, page_sig, threshold=0.7):
                        print(f"{indent}  [RECOVER] on settings (scroll-mismatch), scroll-top fixed sig", flush=True)
                        recovered = True
                        break
                    # ★ 2026-05-26(case #53 / #54 / #55)NEW FALLBACK:sig 不匹配但当前页 menu item 标题
                    # 跟 settings 顶端 items 高度重叠 → 还是认为在 settings 根
                    # 触发场景:G2H Pro 摄像头 settings 含 dynamic 文本(live preview / 网速 / 录制状态)
                    # → page_sig 与 cur 之间动态文本差异大 → sig 0.7 阈值不过。但 menu item titles 稳定。
                    #
                    # 演化:
                    #   #53(v1):用 item 数量 → 误中(13 items 刚好碰阈值)
                    #   #54(v2):用 cur ∩ discovered_order(19 items)重叠率 → 阈值难定(只 7 items 屏可见 / 19 总数)
                    #   #55(v3):用 cur ∩ items(top-scroll 初次 parse 的 7 个 visible titles)重叠率 ≥ 60%
                    #          → 真 settings 顶端 → ~100% 重叠;中间 scroll(不同 items)→ 几乎 0% → 安全
                    cur_items = parse_menu_items(cur_xml)
                    cur_titles = {i["primary_text"] for i in cur_items}
                    initial_titles = {i["primary_text"] for i in items}  # L0 初次 parse 的 top-scroll items
                    if initial_titles and len(initial_titles) >= 3:
                        top_overlap = len(cur_titles & initial_titles) / len(initial_titles)
                        if top_overlap >= 0.6:
                            print(f"{indent}  [RECOVER] on settings (top-items overlap: {top_overlap:.0%}, {len(cur_titles & initial_titles)}/{len(initial_titles)})", flush=True)
                            recovered = True
                            break
                except Exception:
                    pass
            # 检查飘到了祖先 → DRIFT-UP 安全返回(不再按 BACK 越界)
            if any(signatures_match(cur, anc, threshold=0.7) for anc in ancestor_sigs):
                print(f"{indent}  [DRIFT-UP] on ancestor during recovery, return", flush=True)
                return
            # ★ 检查 device list — 已经被 BACK 顶出 device,不要继续 BACK 越界出 app
            if is_on_device_list(device):
                print(f"{indent}  [RECOVERY] hit device list at attempt {back_attempt}, stopping further BACK", flush=True)
                break
            # ★ 2026-05-21:loop 内也检查 save-prompt 对话框。
            # 触发场景:wizard 类页面(도어락 동작 확인 5 步)BACK 触发 종료하시겠습니까 对话框,
            # loop 第一次 BACK 已被外层 save-prompt 处理了一次,但如果 BACK 又落到 wizard 内层
            # 或 dialog 反复弹出,loop 不识别就只会按 BACK = 취소 → 留在 wizard 死循环。
            # 加 detect_save_prompt_action 让 loop 也能按 확인 跳出。
            if cur_xml:
                try:
                    save_action = detect_save_prompt_action(cur_xml)
                    if save_action:
                        print(f"{indent}  [SAVE-PROMPT-LOOP] dialog detected during recovery, clicking '{save_action}'", flush=True)
                        btn = device(text=save_action)
                        if btn.exists:
                            btn.click(); time.sleep(1.5)
                            continue  # 跳过 BACK,下一轮重新 check
                except Exception:
                    pass
            try:
                device.press("back"); time.sleep(WAIT_AFTER_BACK)
            except Exception:
                break
        if not recovered:
            # ★ 2026-05-21:ABORT-LEVEL 前最后挽救 — 调 _try_recover_to_settings 重走 Phase B nav。
            # 触发场景:LED T2 신호 강도 fullscreen chart sub-page → BACK 后落到非 settings 中间页,
            # 5 次 BACK 后还没回去 → 后面 5 个 items(펌웨어 업데이트 / 통신 프로토콜 / 장치 관련 항목
            # / 장치 로그 / 장치 그룹 생성)全跳过。同 case #34/#38 的 RECOVERY 模式。
            remaining = [t for t in discovered_order if t not in seen_titles]
            if depth == 0 and len(remaining) >= 2:
                print(f"{indent}  [ABORT-RECOVERY] 5 BACKs failed, {len(remaining)} titles unprocessed, attempting re-nav...", flush=True)
                if _try_recover_to_settings(device, page_sig, indent):
                    print(f"{indent}  [ABORT-RECOVERY] re-nav OK, resuming with {len(remaining)} unprocessed titles", flush=True)
                    continue
                else:
                    print(f"{indent}  [ABORT-RECOVERY] re-nav failed, aborting", flush=True)
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
            # ★ 2026-05-21:确认在 list 后,强制 tap "전체/全部/All" 房间 tab
            # 触发场景:冷重启后默认 tab 可能是某个房间(e.g. 거실),只显示该房间设备 →
            # multi flow 找不到老路上的设备 → no_new_devices break → 漏扫。
            # 修:在 list 顶部找 "전체/全部/All" tab,tap 它确保全部设备可见。
            try:
                for label in ["전체", "All", "全部"]:
                    elem = device(text=label)
                    if elem.exists:
                        # 限制 y 位置 — 应在顶部 tab 栏(屏幕 15-25% 高度区域)
                        info = elem.info
                        bounds = info.get("bounds") or {}
                        top = bounds.get("top", 9999)
                        if 50 <= top <= 500:  # heuristic: top tab strip
                            print(f"    [RECOVERY] tapping '{label}' tab to ensure all devices visible", flush=True)
                            elem.click()
                            time.sleep(1.5)
                        break
            except Exception:
                pass
            return True
        print(f"    [RECOVERY] after restart, still not on device list", flush=True)
    except Exception as e:
        print(f"    [RECOVERY] app restart failed: {e}", flush=True)
    return False

def traverse_one_device(device, label):
    """对一台设备完整跑 Phase A + B"""
    global CURRENT_DEVICE_NAME
    CURRENT_DEVICE_NAME = label   # ★ 2026-05-21:供 traverse_related_items 匹配自己设备
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

    # ★ Fix C(2026-05-20):0-items 假完成红旗 — 多设备 flow 也加,文件名前缀 device_safe 防冲突
    if len(settings_items_list) == 0:
        warn_xml = OUTPUT_DIR / f"{device_safe}_phase_b_empty_settings.xml"
        warn_png = OUTPUT_DIR / f"{device_safe}_phase_b_empty_settings.png"
        try:
            warn_xml.write_text(settings_snap.get("xml") or device.dump_hierarchy(), encoding="utf-8")
            device.screenshot(str(warn_png))
        except Exception as e:
            print(f"  [PHASE B] warn dump failed: {e}", flush=True)
        print(f"  ⚠ [PHASE B] {label}: settings tree has 0 items — nav may have landed on wrong page. "
              f"Check {warn_xml.name}", flush=True)

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
    global CURRENT_DEVICE_NAME
    visited_sigs = set()
    results = {
        "captured_at": datetime.now().isoformat(),
        "plugin_version": None,                      # ★ 新增
        "trees": [],
    }
    main_snap = capture_page_snapshot(device, "device_main", "01_main_page")
    # ★ 2026-05-21:从主页 XML 提取设备名 → 供 traverse_related_items 使用。
    # 提取失败时 None,traverse_related_items 内部 graceful skip 深入。
    CURRENT_DEVICE_NAME = extract_device_name_from_main(main_snap["xml"])
    if CURRENT_DEVICE_NAME:
        print(f"[DEVICE] name='{CURRENT_DEVICE_NAME}' (for related-items matching)", flush=True)
    else:
        print(f"[DEVICE] name extraction failed,장치 관련 항목 will only capture top page", flush=True)
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

    # ★ 2026-05-20 Fix C:Phase B 抓到 0 items 是"假完成"红旗 — 即便 nav helper 报 arrived,
    # 实际可能跳到了错误页面(看起来像 menu 但其实不是)。保存诊断 + 警告。
    if len(settings_tree["items"]) == 0:
        warn_xml = OUTPUT_DIR / "phase_b_empty_settings.xml"
        warn_png = OUTPUT_DIR / "phase_b_empty_settings.png"
        try:
            warn_xml.write_text(settings_snap.get("xml") or device.dump_hierarchy(), encoding="utf-8")
            device.screenshot(str(warn_png))
        except Exception as e:
            print(f"  [PHASE B] warn dump failed: {e}", flush=True)
        print(f"  ⚠ [PHASE B] settings tree has 0 items — nav may have landed on wrong page. "
              f"Check {warn_xml.name}", flush=True)

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