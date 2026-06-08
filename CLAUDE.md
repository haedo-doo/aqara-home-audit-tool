# Aqara Home Korean Translation Audit System

> 本文档是项目的完整上下文交接文件。Claude Code 在此项目目录工作时会自动读它。
> 最后更新：2026-05-11

---

## 项目背景与目标

**目标**：自动化审计 Aqara Home Android 应用的韩文翻译质量，替代手工截图比对。

**Pipeline**：
1. **Phase 1**（已完成）：XML 解析，定义如何从 UIAutomator dump 中提取所有文本
2. **Phase 2**（接近完成）：自动遍历整个 App 的所有菜单 → 抓取每个页面的韩文文本到 JSON
3. **Phase 3**（待启动）：Claude API 批量审计抓取的韩文 → 输出 findings JSON

**技术栈**：
- Windows + Python 3.13
- uiautomator2 + uiautodev
- Android 28, 屏幕 1080×2220
- 韩文版 Aqara Home（`com.lumiunited.aqarahome.play`）
- 环境变量：`PYTHONUTF8=1`

**当前 App 内已设备数**：27 台(2026-05-19 起;烟感 한때 缺过又添回)
- 摄像类:智能可视门铃 G4(国际版)、智能摄像机 G2H Pro(国际版)
- 传感器类:人체 P1 / T1-1、모션·조도 P2、고감도 모션、열림 감지 P2/T1、재실 FP1/FP2、누수 T1、조도 T1、연기 감지-1
- 开关类:무선 노브 H1、무선 리모트 H1 (1/2구)、무선 리모트 T1 (1구)、조명 스위치 H2 (2버튼,1채널)、무선 開關 T1(双键)
- Hub 类:M3-Doo、스마트 허브 E1、스마트 허브 M2-Doo
- 其他:스마트 플러그 EU、큐브 T1 Pro、면조명、Aqara智能浴霸 T1、Temperature and Humidity Sensor T1

---

## 文件位置

| 文件 | 路径 |
|---|---|
| 主代码 | `C:\doo\test_project1\aqara_home_app_audit\phase2_traverse.py` (v8) |
| 输出目录 | `C:\doo\test_project1\aqara_home_app_audit\output\traverse_v8_YYYYMMDD_HHMMSS\` |
| 单设备输出 | `traverse_result.json` |
| 多设备输出 | `all_devices_result.json` |
| 失败诊断 | `phase_b_nav_failed.xml` + `.png` |

---

## 架构关键发现

### 设备渲染类型
两种 activity：
1. **Native settings**：用 `cl_root_layout` / `item_layout` 作为菜单项 anchor
2. **RN plugin**（`LumiRNMainActivity`）：每个设备独立的 React Native 插件，
   activity 名包含 `.arn.`，`plugin_version` 各异。所有 settings **内嵌展开**，不真正导航到独立 sub-page。

### 关键 UI 锚点
- 设置菜单页：`cl_root_layout` / `item_layout`（或启发式 fallback）
- "..."（设置）按钮：`layout_title_right`（native）/ 顶部右侧启发式（RN）
- 设备列表 RecyclerView：`id/rv_device_list`
- 设备卡片：`id/container`
- 设备名：`id/tv_cell_left`
- 底部 Tab 栏：5 个 RadioButtons（`btn_home/btn_device_list/btn_automation/btn_explore/btn_mine`）

### M3 Hub 的特殊性（反自动化）
- **内容面板宽 = 屏幕 70%**（756/1080），右侧 30% 留白
- **"..." 按钮 cx ≈ 64% 屏宽**，落在标准 75% 阈值之外 → 需要 S5 策略
- **所有设置内嵌展开**：点 "방해 금지 모드" / "에어컨 모드" 等不会真正导航，sub_sig 几乎等于 page_sig
- **100+ 个 AC 品牌内嵌列表**：点 매칭된 에어컨 会展开 22+ 项品牌，每个品牌点击触发 bottom-sheet
- **多次 BACK 容易越界**：从子页 BACK 多了会退出 hub 到 App 的 MainActivity

---

## Phase 2 traversal 算法核心

`traverse_recursive` 是核心递归函数。每次调用代表一个层级：
- **L0** = 当前页根级（depth=0）
- **L1** = 点击 L0 某项进入的 sub-page
- 以此类推，最大 `MAX_DEPTH=4`

### Phase A vs Phase B
- **Phase A**：当前已经在某设备主页 → 遍历主页的 items
- **Phase B**：从主页找 "..." → 进入设置页 → 遍历设置项

### 关键判定逻辑
- `signatures_match(a, b, threshold)`：a 与 b 的文本签名交集占 b 的比例 ≥ threshold
- `is_on_main_page(current, main)`：双向匹配 + 新增文本 ≤ 2 条（用于 Phase A cleanup 判定）
- `signature_overlap`：双向最大重叠比例
- `parent_content_preserved`：父页文本在子页中的保留率
- `items_preserved`：父页 items 在子页 items 中的保留率

### 点击后的判定瀑布（按顺序）
1. NO-OP（signature_overlap ≥ 0.9）→ 不递归
2. BOTTOM-SHEET（同 activity + 父页保留 ≥ 0.9 + 新增 취소/확인 按钮）→ 抓取 + 用 취소 关闭
3. **CHOOSER-REVEALED**（新出现 `PAGE_CONTENT_NO_RECURSE_MARKERS` 关键词）→ 抓 + return
4. NO-OP-SCROLL（同 activity + 父页保留 ≥ 0.9 + items 保留 ≥ 0.7）→ 不递归
5. 长内容页（≥10 texts, ≤2 items）→ scroll_capture_full_page 累积抓取
6. 正常导航 → 抓 + 递归 + BACK

### Cleanup 机制
Phase A 结束后会执行 BACK cleanup，最多 5 次。守卫条件：
- activity 变了 → 已退出当前设备 → 停
- `is_on_main_page` 为 True → 已回主页 → 停

---

## 累计 74 项边界 case 修复（按发现顺序）

每一条都对应过去 30+ 轮迭代里某次真实失败。**改代码前先理解它在防什么**，否则容易回退。

1. **多 anchor 支持**：`cl_root_layout` + `item_layout` + 启发式 fallback
2. **三层安全过滤**：`DANGER_KEYWORDS` / `DANGER_KEYWORDS_END_ONLY`（含 종료/켜기）/ `DANGER_CLASSES`（Switch/CheckBox）
3. **`NAVIGATION_JUMP_KEYWORDS`**：跨设备跳转项（连接된 허브 / 하위 장치）→ SKIP-JUMP
4. **`ACTION_BUTTON_EXACT`**（抓取但不点击）：추가 / 확인 / 저장 / 지금 결제 / 구독 等。注意 결제 **不**在列表里（用户要审计付费页）
5. **`CAPTURE_NO_RECURSE_KEYWORDS`**：리모컨 추가、비밀번호/PIN/암호、언어/벨소리/지역/국가/전원 주파수、야간 적외선、집 전체 감시、위치 지정、방 추가、에어컨 매칭、브랜드 선택、에어컨 모드 설정 等
6. **`PAGE_CONTENT_NO_RECURSE_MARKERS`**（gated by `is_settings_page`）：브랜드 선택 / 국가 선택 等
7. **智能等待**（native 10s / RN 25s，指纹稳定 1s）
8. **系统 UI 过滤**（`BOTTOM_NAV_THRESHOLD_RATIO=0.85`）：排除底部 Tab 栏
9. **NO-OP 检测**（overlap ≥ 0.9）
10. **`parent_preservation` NO-OP-SCROLL 检测**：父页保留 → 子页是滚动展开，不递归
11. **父页签名回归检查**（`navigate_back_to_signature` max 2 次 BACK）：防按穿
12. **`visited_sigs` 循环防护**
13. **CYCLE-UP / DRIFT-UP 祖先检测**：drift 到祖先就 return，避免越级 BACK
14. **多策略自动找设置入口** S1-S5：
    - S1：`layout_title_right` resourceId
    - S2：content-desc 含 설정/더보기/메뉴/옵션/Settings/More/Menu
    - S3：text 含 설정/设置/Settings
    - S4：top-right 启发式（cx > 0.75 屏宽，y1 < 0.15 屏高）
    - S5：窄面板 RN 启发式（cx > 0.55 屏宽，w<200, h<120，排除左边缘）
15. **Phase A（设备主页）+ Phase B（设置页）两阶段**
16. **多设备流程 `run_multi_device_flow`**
17. **强力恢复 `return_to_device_list`**：tab tap → 少量 BACK → app restart
18. **`is_on_device_list`** 必须满足 `btn_device_list checked=true`
19. **Bottom-sheet 检测**：同 activity + 父页保留 + 新增按钮 → 抓取后用 취소 关闭（**绝不 BACK**）
20. **进入层时关闭拦截浮层**（entry dialog，最多连关 3 个）
21. **`CANCEL_LABELS` 含 무시/Ignore/Later/나중에**
22. **`scroll_capture_full_page`**（max_scrolls=15, sleep 0.7s, no_change=3）：长内容页累积抓取
23. **`plugin_version` 提取正则**：`플러그인\s*버전[:\s]*([\d._]+)`
24. **Save-prompt 弹窗处理**：BACK 触发"未保存修改" → 点 확인 = 放弃修改并退出
25. **켜기 加入 `DANGER_KEYWORDS_END_ONLY`**：防自动打开开关
26. **`NO_CLICK_CHILDREN_UNDER_PATH`**（연관이벤트）：自动化规则选择器分支不点子项，防 commit 规则
27. **`extract_app_texts` 过滤**：Image class / base64 / SVG / CSS resource name / 单字符 → 移除噪声
28. **集邮"브랜드 선택"+"매칭된 에어컨" 内嵌列表**：
    - **consecutive_sheets 计数器**：连续 3 次 BOTTOM-SHEET → return（解 L2 品牌列表卡死）
    - **consecutive_dialogs 计数器**：连续 5 次 [DIALOG] dismiss → return（解 L1 卡死）
    - **CHOOSER-REVEALED**：click 后 sub_sig 出现 marker 但 page_sig 没有 → capture + return（最彻底的防御）
29. **CHOOSER 后 BACK 不要过度按**(2026-05-12 修)
    - 原:CHOOSER 抓完按 1 下 BACK + `navigate_back_to_signature(max_attempts=2)` 又按 2 下 = 3 下 BACK
    - 后果:CHOOSER 通常是 L3 层。3 下 BACK 会顶过 L2/L1/设备主页 → L1 主循环找不回 page_sig → ABORT-LEVEL → **后面 7+ 个未处理 items 全跳过**(P2 设备的 자주하는 질문/사용자 매뉴얼/펌웨어 버전/제조업체/장치 ID 等)
    - 修:CHOOSER 只按 1 下 BACK,然后用 `signatures_match(threshold=0.7)` 单次 check;没回到也**不 return**,让外层主循环的渐进式 recovery 处理
30. **主循环 post-recurse 渐进式 recovery 替代一刀切 ABORT-LEVEL**(2026-05-12 修)
    - 原:`navigate_back_to_signature(max_attempts=2)` 失败 = `[ABORT-LEVEL]` return → 整层剩余 items 全跳过
    - 后果:任何一个 chooser 抓失败 → 整个 settings tree 后半截全漏
    - 修:循环 5 次 (BACK + 用 0.7 阈值 check + check 祖先);恢复就 continue;真的恢复不了再 abort
    - 副带:Case A 的 sig match 阈值从 0.85 → 0.7,允许"选项被选中导致细微 sig 变化"的情况仍判定为已回父页
31. **`is_on_settings_page(lenient=False)` 阈值修复**(2026-05-13 修)
    - 触发:M2 hub 主页只有 1 个 "리모컨 추가"(`item_layout` 锚)→ 原 1 个 anchor 就返回 True → Phase B 静默跳过 nav → 02_settings_page.xml 实际是 01_main_page.xml 副本
    - 修:`lenient=False`(Phase B 入口判定)改成要求 activity hint 或 **≥3 个 anchor**;`lenient=True`(nav helper 点完后)保持 1 个 anchor 也算的 loose 判断
    - 副作用:M2 hub / 其它"只有一个加号按钮"的极简设备主页现在会触发 Phase B nav 正常找右上 "..."
32. **Phase A cleanup 在 Native device main 上禁 BACK**(2026-05-13 修)
    - 触发:人体传感器 T1-1 Phase A 5 items 处理完,主页含 2 个 timestamp 动态文本(`11:11 움직임`/`11:12 움직임`)随新事件刷新进 sig,`is_on_main_page` overlap=0.714<0.75 判 false → cleanup 按 BACK → Native device main activity 上 BACK 直接弹回设备列表 → Phase B 找不到 "..." → S1/S4/S5 全失败,save phase_b_nav_failed.xml
    - 修:Phase A cleanup 加守卫 3 — 如果设备是 Native(activity 不含 LumiRN/.arn.)且仍在原 main_activity,**永不 BACK**;接受 sig 略不匹配为"已在主页"(state 动态刷新很正常)。RN 设备保持原 BACK 行为,因为它们 BACK 在同 activity 内部导航,不会弹出 device
    - 两个 Phase A cleanup 都修(单设备 + 多设备 flow)
33. **`items_preserved >= 0.95` 强制 NO-OP-SCROLL — mode toggle 矩阵防递归**(2026-05-13 修)
    - 触发:Aqara 智능 浴霸 T1 主页是 8 个 mode/level toggle 按钮(온풍/환기/건조/송풍/낮음/중간/높음/...),click 后页面**不导航**只改状态,但状态文字大变(显示 "현재: 온풍" 等)→ 现有守卫都不命中:text preservation 才 ~0.6(状态文字变了)、new_text_count ~5-8(超过 ≤3 阈值)→ 走 "captured + recurse" 分支 → sub-page items 跟 parent 完全一样 → 递归 4 层 → ABORT-LEVEL × 2 + 5-BACK cleanup → device 顶到 MainActivity → Phase B nav failed
    - 同根因:T1-1 也是状态变化重复递归(只是变化更轻微,sig overlap 微差),`배터리 > 배터리 > 배터리 > 배터리` 4 层
    - 修:NO-OP-SCROLL 检查加第三条短路 — `is_mode_toggle = (items_preserved >= 0.95)`。三条任一满足都算 scroll-only:
      - A 经典严格:preservation>=0.9 且 items_preserved>=0.7
      - B 兜底(M3 hub 类长设置页):preservation>=0.8 且 new_text_count<=3
      - C 同 items 矩阵(本次):items_preserved>=0.95
    - 影响面:只对 "click 后 items 完全保留" 的设备生效(浴霸 mode 矩阵 / T1-1 状态刷新)。真实子页 items 不会和 parent 几乎一致,不会误触
    - 日志:`[NO-OP-SCROLL] text X%, items Y%, new=N (mode-toggle)` (新增 scroll_reason 区分 mode-toggle vs scroll)
34. **ABORT-LEVEL-VANISHED 前 try re-nav 续扫 — RN 飘出 settings 后恢复**(2026-05-13 修)
    - 触发:M3 hub / P2 / H2 / 모션 P2 / G4 doorbell / G2H Pro 等 RN 设备 Phase B 末尾经常出现连续 3+ 个 VANISHED → ABORT-LEVEL-VANISHED → 后面剩余的 settings items(자주하는 질문 / 사용자 매뉴얼 / 펌웨어 / 제조업체 / 장치 ID 등)全跳过
    - 修:`_try_recover_to_settings(device, expected_sig)` 辅助函数 + 主循环改造。当 depth==0 且 unprocessed items >= 2 时,在 abort 前尝试一次恢复:
      - 先 dump 看是否已在 settings(sig match >= 0.7);否则最多 3 次 BACK 找回 settings;再不行调 `auto_navigate_to_settings`(S1-S5)
      - 恢复成功 → `consecutive_vanished = 0` + `continue` 继续处理剩余 items;失败 → 原 abort 行为
    - 影响面:RN 设备在 L0 settings 末尾飘出时多一次救命机会,数据完整性显著提升
    - 日志:`[VANISH-RECOVERY] N titles still unprocessed, attempting re-nav...` / `[VANISH-RECOVERY] re-nav OK, resuming` / `[VANISH-RECOVERY] re-nav failed, aborting level`
35. **S6 — WebView top-right icon 启发式(覆盖 FP2 region sensing 等纯 WebView 主页)**(2026-05-13 修)
    - 触发:FP2 切到 region sensing(grid 雷达图)模式 — 整页是 `android.webkit.WebView`,"..." 按钮在 `bounds=[960,162][1035,237]`,class `android.widget.Image`,**`clickable="false"`**(JS 侧捕获 tap)。S4/S5 都强制 `clickable="true"` → 0 candidates → all strategies failed,save phase_b_nav_failed.xml
    - 修:在 S5 之后加 S6 — 不要求 clickable,只看几何 + class hint:
      - class ∈ (Image, View)、w<200 且 h<200(图标尺寸)、cx > 0.75 屏宽、y1 < 0.15 屏高
      - text 含 `base64` 或 `data:image` 优先(WebView 内 PNG 图标常这样)
      - 坐标点击(uiautomator2.click 发 raw touch event,WebView 在 JS 侧处理,不依赖 clickable)
    - 影响面:FP2 region sensing / fall detection 等纯 WebView 主页能 nav 进 settings。Native/RN 设备已被 S1-S5 覆盖,S6 是最后兜底,误触概率低
    - 日志:`[NAV] S6: N webview icon candidates` / `[NAV] S6: tap [x,y][x,y] (coord-only, WebView)` / `[NAV] arrived via S6`
36. **`return_to_device_list` 第 3 层 recovery 真冷重启(stop+start,非纯 start)**(2026-05-14 修)
    - 触发:多设备 flow 扫完 P2 后,设备停在 P2 settings 子页(底部 Tab 栏被遮);第 1 层 tab tap 找不到 `btn_device_list` → 第 2 层 2 次 BACK 也没翻出来 → 第 3 层调 `device.app_start(APP_PACKAGE)` — **但 app_start 只是拉前台,app 仍在 P2 settings 子页** → tab 还是找不到 → 整个 multi flow 在第 1 台后 stop
    - 后果:用户以为 `python phase2_traverse.py` 起 multi 模式只扫了 1 台,实际是 return_to_list 失败一刀切
    - 修:第 3 层先 `device.app_stop(APP_PACKAGE)`(真正 kill),sleep 1.5s,再 `device.app_start(APP_PACKAGE)` 冷启;cold start 较慢,改成 8s deadline 内每 0.5s 轮询 `is_on_device_list` 或 btn_device_list,找到就 tap → 再 check;最后再 dump 一次确认
    - 日志:`[RECOVERY] force-restarting app (stop + start)` / `[RECOVERY] app restarted, tapping 장치 tab` / `[RECOVERY] after restart, still not on device list`

74. **`통신 프로토콜` 加 ACTION_BUTTON_EXACT — 防 dialog drift 引发 VANISH 链**(2026-06-01 修)
    - 触发场景:H2 조명 스위치 (2버튼, 1채널)第 17 项 `통신 프로토콜` click → 底部 popup(Zigbee/protocol info)→ script 检测 dismissable dialog → click `확인` → **확인 click 副作用把页面飘**(case #43 LED T2 同类)→ 主循环找接下来 3 个 items(`장치 관련 항목` / `장치 교체` / `장치 로그`)全 VANISH
    - VANISH-RECOVERY 救回 settings 后继续处理 `장치 그룹 생성`,但已 marked vanished+seen 的 3 个 items 永久丢失。case #69 IME retry / case #70 aggressive BACK 在这个 timing edge case 没接住(sig check 暂时通过)
    - 修:`통신 프로토콜` 加进 `ACTION_BUTTON_EXACT`(精确匹配)→ click 都不做 → 没 dialog → 没 drift → 后续 items 全扫到 ✓
    - 损失分析:`통신 프로토콜` 内容是 Zigbee version / MAC / network protocol info(~34 texts 技术显示)。**翻译价值低**(数字 / MAC 地址 / 版本号);同类技术内容在 `신호 강도` / `네트워크 정보` 已扫过
    - 换回:`장치 관련 항목`(자동실행/동시실행 deep scan)+ `장치 교체` + `장치 로그`(audit 关键的功能性内容)
    - 跨设备影响:精确匹配,只命中 title == `통신 프로토콜` 的 item。其他设备如果有 `통신 프로토콜 설정` 等长 string,**不受影响**(继续正常扫)
    - 影响范围(LED T2 / 其他可能):LED T2 通신 프로토콜 也曾触发 dialog drift(case #43)。该 case 现在 SKIP-ACTION 后,LED T2 通信协议 也不再 click → 一致行为 ✓

73. **NO-OP-SCROLL condition B 加 items_preserved 守卫 — 防简单 toggle 子页误判**(2026-06-01 修)
    - 触发场景:H2 조명 스위치 (2버튼, 1채널)`릴레이 잠금` / `설치 방향` click 进真子页(只显示一个 toggle + 一行说明),被 case #33 condition B 误判为 NO-OP-SCROLL → 不递归。后续 items(7-10 个)在子页 dump 找不到 → VANISH 链 → 即使 VANISH-RECOVERY 多轮"OK",已 mark vanished items 不重试 → 永久漏抓。用户反复扫 H2 多次都中途中断。
    - 关键 dump 数字:text 81% / **items 58%** / new=2 — case B `preservation>=0.8 AND new<=3` 命中,但 items 58% 是"真子页"强信号(parent items 大量消失)。case B 不看 items → bug。
    - 修:condition B 加 `items_preserved >= 0.7` 守卫。inline 展开 items 几乎全在(>=0.7),真子页 items 大量消失(<0.7)。匹配 case A 的 0.7 阈值。
    - 影响面分析(grep 历史 27 scans):**8 行触发新行为,7 行是 H2 switch(我们要 fix 的),1 行是 M3 hub `적외선 리모컨`(items 69% borderline)**。M3 hub 即使从 NO-OP-SCROLL 变成递归,有 CYCLE 守卫接住,不会爆。其他设备 NO-OP-SCROLL 都是 items>=80% 或 condition A/C 命中 → 0 影响。
    - 浴霸 mode toggle(case #33 原始 case):preservation 0.6 + new 5-8 + items 100% → 命中 C(items_preserved>=0.95)→ 不受 B 改动影响 ✓
    - M3 hub inline 展开:items 通常 80-100%(parent items 都还在,只是位置重排)→ 仍命中新 B → 行为不变 ✓
    - 回退方法:[phase2_traverse.py:2566](phase2_traverse.py#L2566) 下方的注释行 `is_minor_change = (preservation >= 0.8 and new_text_count <= 3)` 取消注释,删上面新行即可
    - 日志变化:之前误判 scroll 的 `text 81%, items 58%, new=2` 现在不再触发 NO-OP-SCROLL,走 captured + recurse(或 CAPTURE-ONLY-PARENT 如果 title 在 CAPTURE_NO_RECURSE_KEYWORDS)

72. **FAQ question detector 兼容 `?(...)` 括号补充结尾**(2026-05-28 修)
    - 触发场景:G3 카메라 허브 `일반적인 질문` 页有一题 `현재 프록시 허브로 지원되는 기기는 무엇입니까? (다음 제품 중 일부는 일부 국가 또는 지역에서만 사용 가능합니다)` — `?` 后跟括号补充说明,末尾是 `)` 不是 `?`。原 `_detect_webview_faq_questions` 只检测 `endswith("?")` 或 `endswith("?")` → 漏掉这题 → answer 没 probe
    - 用户观察:`21 个问题但扫成 24 个而且少了几个回복`(实际 22 真问题,21 probed,1 个 `)` 结尾的漏 probe → answer 缺失)
    - 修:加 helper `_is_faq_question_text(t)` — 接受 `?` / `?` 直接结尾,**或** `?` 后跟括号补充(regex `[?？]\s*[\(（][^)）]+[\)）]\s*$`)。括号内不能再有 `?` 避免误抓含 `?` 的长答案文本
    - 跨设备影响:所有 WebView FAQ 页面受益。M3 hub FAQ / G3 일반적인 질문 / 其他设备 자주 묻는 질문 都通过同一 detector
    - 回归零影响:加宽不收窄 — 原 `?`/`?` 结尾 case 仍全过(只是多了一种新 pattern 也被识别为 question)
    - 答案数:G3 일반적인 질문 应从 21 → 22 个 answer

71. **'PTZ' 加入 ACTION_BUTTON_EXACT — 防摄像头控制面板模式切换**(2026-05-28 修)
    - 触发场景:G3 카메라 허브 Phase A 控制중심 5 个 button 之一是 `PTZ`(不是 `PTZ 교정`)。click 会切换控制面板模式 — 默认 direction pad 消失换成其他控件 → 后续 items 位置/可见性变化 → find_item_by_title 找不到 → VANISH 链。用户原话:"在控制中心中如果点击ptz会造成控制画面的更改,页面中的操纵方向键会变没"
    - 修:`PTZ` 加进 ACTION_BUTTON_EXACT(精确匹配)。MENU label `PTZ` 已在 Phase A page_texts 抓到(JSON 已有),不需要 click 进 sub-page
    - 跨设备影响:精确匹配 "PTZ" 不影响 "PTZ 교정" / "PTZ 설정" / "PTZ menu" 等长 string。其他设备如果有独立 PTZ 子页 menu(长 string)还会正常 click;只 bare "PTZ" 按钮 SKIP
    - 类似处理:跟 case #57 재시작 / case #64 스마트 고객 서비스 同处方 — "click 后破坏当前页 state 但 menu label 已抓到" → 全 SKIP-ACTION
    - 日志:`[SKIP-ACTION] PTZ: action: 'PTZ'`

70. **DIALOG-RECOVERY 失败前 aggressive BACK 兜底 — 防 tutorial modal 卡住 Phase A**(2026-05-28 修)
    - 触发场景:G3 카메라 허브 Phase A 第 2 个 item `관심구역` click → 弹 **tutorial modal**(图标 + 说明文字 "자주 확인하는 위치를..." + 大蓝 `확인` button)→ `detect_dismissable_dialog` 命中(len(sig)<=4 + no destructive + 有 확인 → layer 3 触发)→ click 확인 → **不是返回 parent 而是进 진짜 관심구역 子页**(中심/맨 왼쪽/맨 오른쪽/중앙 최상단 preset 列表)。sig <30% match Phase A main → 触发 `_try_recover_to_settings`。该函数设计针对 Phase B(找 "..." 重进 settings),Phase A 上 "..." 不在 sub-page 顶部 visible 或 dump 抓不到(RN view 层级)→ S4/S5/S6 全 0 candidates → 函数 return False → 原代码 `return` 中止整个 Phase A traverse_recursive → Phase B 紧接着 nav 也找不到 settings(stuck on sub-page)→ 脚本中断,只扫了 2 个 item
    - 用户原话:"这次直接扫描中断了"(traverse_v8_20260528_085934 只 2 items)
    - 根因深层:`_try_recover_to_settings` 是 Phase B-centric 设计,Phase A drift 时它寻 "..." button 走错路。Phase A 真正需要的是 BACK 回 device main。
    - 修:recovery 失败时再做 5 次 BACK(每次 sleep 2s 给 RN 充分反应)+ sig check 兜底:
      - 每按一次 check 是否在 device list → 是 → return(已越界)
      - 每按一次 dump + sig check vs page_sig(threshold 0.5 容忍 video stream/timestamp drift)→ match → continue iteration
      - 5 次都失败 → 原 return 行为
    - 影响面:命中场景罕见(只 dialog drift + recovery 失败 + RN 子页 BACK 慢的情况)。LED T2 case #43(Zigbee dialog → device main → "..." recovery)不受影响(那里 recovery 第一步就成功)。Phase B drift 也不受影响(同样 recovery 成功率高)
    - 跨设备通用:所有 tutorial modal / onboarding modal click 后进真子页都受益(摄像头类 G3/G4/G2H Pro / 其他 RN 设备的"教学"页可能命中)
    - 最大额外耗时:~10s(5 × 2s)/触发,极少触发,可接受
    - 日志:`[DIALOG-RECOVERY] try aggressive BACK fallback` / `[DIALOG-RECOVERY] aggressive BACK #N succeeded` / `[DIALOG-RECOVERY] hit device list at BACK #N, stopping` / `[DIALOG-RECOVERY] failed,stopping iteration`

69. **[DIALOG] 后 sig 不匹配先 retry 等 IME 动画完成 — 防 L1+ 越界 BACK**(2026-05-28 修)
    - 触发场景:G3 카메라 허브 Phase B L1 `장치 정보` 卡片下 click `장치 이름` → 弹出 `이름 변경` dialog(text input + 韩文键盘)→ [DIALOG] handler 检测 dismissable + click `취소`。原 `sleep(1.0)` 后立即 sig check,**dialog 关 + 键盘 dismiss 动画 ~500ms 没完** → sig <85% match → depth>0 走原 BACK 一次 → 从 L1 越界回 L0 → L1 后续 6 个 items(장치 위치 / 사용자 매뉴얼 / 일반적인 질문 / 개인정보 보호 정책 / 장치 ID / 펌웨어 버전)全 VANISH → ABORT-LEVEL-VANISHED → 这些 items 永久漏抓
    - 用户观察:"扫描菜单的时候,好像是 사용자 매뉴얼 附近,出现了直接退回到设备清单的现象"(其实是退回到 L0 settings 然后再被后续 click 顶到 device list,用户感知是"突然跑到设备清单")
    - 修(只增不减):sig 不匹配时多等 1.5s + re-dump 再 check 一次。真稳定 → no-op;还是不匹配 → 走原 recovery 路径(L0 detect device list / try_recover / sig <30% / 0.3-0.85 BACK)
    - 影响面:命中场景 ~5%(只在 sig <85% 时多 1.5s + 1 dump)。修后对正常 dialog dismissal 零影响(sig 立即 match → 不走 retry);对 IME 类 dialog → 救命
    - 跨设备通用:所有带 text input + IME 弹出的 dialog(설정 → 设备改名 / 邮箱输入 / 密码 etc)都受益,不限 G3
    - 日志不变(没新增 marker,只是减少误触发的 BACK)

68. **scroll_page_up 分屏布局兼容 — 摄像头主页菜单回顶**(2026-05-28 修)
    - 触发场景:G3 카메라 허브 Phase A 11 个 item discover 后 scroll-to-top 失败,前 4 个 items(PTZ 교정 / 관심구역 / PTZ / 관련 이벤트)VANISH 漏抓
    - 根因:G3 主页**上半视频画面**(y 0-1110)+ **下半菜单**(y 1110+)。视频区不响应滚动手势(touch 触发 video controls 不传给 ScrollView)。原 `scroll_page_up` swipe(0.20=444 → 0.80=1776)起点 444px 落在视频区 → 整个 swipe 无效 → 菜单卡在 discover 后的下方位置 → `scroll_page_to_top` 第 2 iter sig 跟第 1 iter 一样 → 误判"已到顶"break → 主循环 find PTZ 교정 全 VANISH
    - 用户洞察:"需要不光在顶部向上拉,需要在下面也尝试一下向上拉回之前向下拉的动作"
    - 修:加第二次 "low-region" swipe(0.65=1443 → 0.95=2109)起点终点都在下半,保证至少一次 swipe 落在分屏可滚区
    - 跨设备通用:全屏可滚页面 → 第二 swipe 多滚 ~30%(可能越过 top,无副作用)+ scroll_page_to_top stable detect 仍正常 break;分屏页面 → 第一 swipe 无效但第二 swipe 生效 ✓
    - 影响面:每个 scroll_page_up call 多 1 swipe + sleep 0.4s。scroll_page_to_top 最多 6 attempts → +2.4s/页。考虑到 G3/G4/G2H Pro 等摄像头主页本来就有 video stream 延迟,这个开销可接受
    - 适用范围:`find_item_by_title` Layer 2-3、`scroll_capture_full_page` 回顶、`discover_all_titles` 末尾 scroll-to-top 都受益

67. **FAQ-PROBE 移除 SAFE_PROBE_PER_SCREEN=2 截断 — 中间 question 不再漏抓**(2026-05-27 修)
    - 触发场景:M3 hub FAQ 19 个 question,case #65 + #66 修后**仍漏抓中间 7 个**(Q3/Q4/Q7-Q11)。实测 traverse_v8_20260527_155402 只抓到 12 个答案(对应 Q1/Q2/Q5/Q6/Q12-Q19)
    - 根因:屏 1 eligible=[Q1,Q2,Q3,Q4,Q5](5 个 cy<1746),top-2 截断只 probe Q1+Q2 → `scroll_page_down`(swipe 0.8→0.2 = 1332px ≈ 4 题距)把 Q3+Q4 推到屏幕外 → 下一屏 dump 从 Q5 开始 → Q3/Q4 永远不在任何屏的 eligible 中 → 漏抓。同样 Q7-Q11 在屏 2→屏 3 跳过 Q5/Q6 后被推走
    - 修:`SAFE_PROBE_PER_SCREEN=2` → 软上限 `MAX_PROBES_PER_SCREEN=20`(典型 FAQ 5-7 题/屏)。**y_max 已防 floating button overlay**(cy < fb_y-100),top-2 截断没有实际防御价值,反被 scroll 距离吞掉中间题
    - 跨题安全性:每题 click+1.2s expand → screenshot/dump → click 再 collapse → 0.6s sleep。collapse 后 layout 复位,下一题用 ORIGINAL (cx,cy)(初屏 dump 坐标)依然准确
    - 副作用:每屏多 probe 几个 → 总耗时 ↑ 但数据完整性飞跃。每屏 ~5 题 × 2s/题 = 10s,FAQ 总耗时从 ~12s 升到 ~30-40s(可接受)
    - 跟 case #65/#66 互补:case #65 防 floating button overlay 仍生效(y_max filter 不变);case #66 final fling-to-bottom 兜底仍生效;case #67 解决"主循环漏中间"
    - 日志:`[FAQ-PROBE] screen N (fb_y=Y): K questions to probe (y<Z), M deferred` — 现在 K 应 = 5 左右,M 应 = 0(除非 question 数超 MAX_PROBES_PER_SCREEN=20)

66. **FAQ-PROBE final fling-to-bottom 收尾扫漏**(2026-05-27 修)
    - 触发场景:case #65 防御性 top-region 点击后,M3 hub FAQ 14 个 question 中漏抓 2 个底部的(`M3는 블루투스 하위 장치 연결을 지원하나요?` / `M3는 어떤 설치 모드를 지원하나요?`)。原因:主循环 scroll 没把底部 2 个 question 带进下一屏 top region → no_new_screens 累计触发 break → 漏抓
    - 修:主循环 break 后加 final 一轮 — 滚 2 次到底 + re-detect + 把所有 unprobed + top-region eligible 的 question 补点完。同样 respect floating button y_max 守卫
    - 跟主循环互补:主循环负责 90% 覆盖,final 兜底剩 10%。各自有 floating button 防御
    - 通用:任何 FAQ 类页面只要底部还有未 probed 的真 question 都会被 final 兜底捞回。不影响"已经全部 probed 完的"FAQ(final 检测 unprobed=0 不会做任何 click)
    - 日志:`[FAQ-PROBE] final scan: N unprobed question(s) at bottom` / `[FAQ-PROBE] q{N}: +X new texts (final scan)`

65. **FAQ-PROBE 防御性 top-region 点击 — 避开 floating 按钮 overlay**(2026-05-27 修)
    - 触发场景:M3 hub `자주 묻는 질문 및 피드백` FAQ 页底部有 `스마트 고객 서비스`(智能客服)floating button,**视觉上 overlay 在某些 FAQ question 之上**(如 q11 `여러 M3가 같은 네트워크로 연결되면 ...`)。
      script 点击该 question 的坐标时,**touch event 实际命中 floating button**(Z-order 上层优先)→ 跳客服页 → FAQ probe 后续乱套 (log 显示 q11-q14 没新 expanded text — 因为 click 没命中 question 而是命中 floating button)
    - 用户洞察:**按手机尺寸不同位置会变,直接位置黑名单不行**。改用"防御性点击": 每屏只点 top 区域 1-2 个,然后滚动,避开 floating button 区域
    - 修:
      1. 新 helper `_detect_floating_button_y_top(xml)`:扫 XML 找 `스마트 고객 서비스` / `Customer Service` 等按钮,返回 y_top
      2. probe loop:每屏只点 top **2 个** `cy < y_max` 的 question(y_max = floating button y - 100 px 留安全余量;没 floating 则用 70% 屏高 default)
      3. 没点的 question(`deferred` 计数)滚动后会重新进入 top 视图被点
      4. max_screens 10 → 15(防御性 probe 每屏少,需更多 screen 轮次)
    - 跨设备通用:任何带底部 floating button 的页面都受益。无 floating button 的页面默认用 70% 屏高 cutoff,跟原行为基本一致(每屏少点几个,多 1-2 次 scroll)
    - 跟 case #64 互补:case #64 防止 Customer Service 在 L1 recursion 时被当 menu 点击。这里 case #65 防止 FAQ probe 期间物理 touch 误中
    - 日志:`[FAQ-PROBE] screen N (fb_y=YYYY): K questions to probe (y<YYYY-100), M deferred`

64. **Customer Service 客服按钮加入 ACTION_BUTTON_EXACT — 防 FAQ 页面误点跳外**(2026-05-27 修)
    - 触发场景:M3 hub `자주 묻는 질문 및 피드백` FAQ 页最底部有 `스마트 고객 서비스`(智能客服)按钮。FAQ-PROBE 完成后 L1 recursion discover 把它当 menu item → `[CLICK L2] Customer Service` → 跳外部客服页 → 中断当前 device traversal
    - 用户原话:"本来应该点击确认每一个问题的回复,但是缺直接点击了 '스마트 고객 서비스',然后就退出去别的菜单了"
    - 修:加 `스마트 고객 서비스 / 고객 서비스 / Customer Service / Smart Customer Service / 客户服务 / 智能客户服务 / 客戶服務` 进 ACTION_BUTTON_EXACT(精确匹配 set)
    - 与 case #57(재시작 DANGER)对比:这个不是 destructive 而是"navigation away" trap。两类都 SKIP-ACTION
    - 跟 FAQ-PROBE 滚动检测互补:即使 scroll 没找到全部 FAQ questions,至少不会被客服按钮带飞
    - 回归零影响:精确匹配,只对这 7 个字符串生效

63. **FAQ probe 滚动遍历 — 捞下方 questions**(2026-05-27 修)
    - 触发场景:M3 hub `자주 묻는 질문 및 피드백` 页有 8+ 个 FAQ questions,但初屏只显示 7 个,下方需要滚动才能看到(如 `M3는 어떤 설치 모드를 지원하나요?`)。原 `probe_faq_expansions` 只 detect 初始 `sub_xml` 一帧,漏抓下方
    - 修(扩 case #60):probe 改成 detect → click probe → scroll-down → re-dump → re-detect → ... 直到连续 2 次滚动没新 question 才停。
      - 用 `probed_question_texts` set 防止滚动后重复 probe 同一 question
      - 用 `base_text_set` 累积 baseline 文本(每屏滚动新出现的也算 base),避免把背景文本误认为 expanded answer
      - 硬上限 max_screens=10,防极端 infinite scroll
      - 完成后 scroll-to-top,便于后续 BACK
    - 兼容性:初屏 questions <= 一屏的情况(短 FAQ 页面),no_new_screens 连续 2 次后退出,行为跟旧版一致(只多 1-2 次额外 scroll)
    - 日志变化:`[FAQ-PROBE] N questions on screen 1; will probe + scroll for more` / `[FAQ-PROBE] +M more questions on screen N` / `total N questions probed, K new native answer texts captured`

61. **viewer 侧 dedup + 62. title-mismatch warning**(2026-05-27 加)
    - case #61: 看 case #61 段(已有,viewer 侧 dedup `_dedup_texts`)
    - case #62: viewer 侧检测 click intent vs 截图实际 page 不符。RN dump 含 Phase A device main items 漏进 Phase B L0 discovered_order(case #59 KNOWN ISSUE 的另一面)→ click stale bounds → 跳错页 → 文件名(click intent)跟内容(实际页)不符。
      - 触发例:L100 门锁 `일회용 비밀번호.png` 内容是 `원격 기능` page;`사용자 관리.png` 是 `방해 금지 모드` page
      - 修(只 viewer):`_extract_page_header(xml)` 提取顶部居中 header,跟 `path` 最后一段对比 → mismatch 标 `_title_mismatch=True` + `_page_header="..."`
      - 豁免规则:完全相等 / 一方 substring / 共享 2 连续韩文字符 / header 是 `장치 정보`(device-info card) / `X 추가`→`Y 선택`(related-items)
      - JS 渲染:tree list 显示 `⚠`;screenshot 上方 yellow alert 框说明 "clicked X but screenshot shows Y"
      - 实测 L100:10 candidate mismatches → 豁免 5 false positives → 5 real (跟用户报告完全一致)
      - 数据完整保留(audit content 是真实韩文,只是 path label 误导)

**KNOWN ISSUE(2026-05-27 记录, 暂不修)**: RN sub-page dump 含父页 "幽灵" 文本
- 现象:RN 设备(如 M3 hub / 모션/조도 P2 / G2H Pro 等)的 sub-page 截图(PNG)只显示子页内容,但 XML dump 含父页 menu items / 标题 / state 等"幽灵"文本。**截图清晰,XML 多余**。
- 根因:RN 设计 sub-page 是 overlay panel(透明 backdrop),底层 settings page items 仍在 view hierarchy 里。`dump_hierarchy()` 不区分可见层 → 全部 text 节点都返回。
- 实际影响:
  - ✅ **不漏抓** — sub-page 真正内容(Thread 网络信息 / FAQ 答案 / etc.)都完整捕获
  - ⚠ **重复抓** — 父页 items 在每个 sub-page 的 XML 里都重复出现 → AI audit 多审 N 次相同 text → token 浪费
  - ⚠ viewer 显示混乱(每个 path 的 app_texts 都含同一批父页 items)
- 已修的"二次影响"(case #58 / #59):
  - 防止脚本"误以为已回 parent"(Case A 守卫)
  - 防止假 VANISHED / 假 ABORT(SKIP-LEAK 区分)
- **未修的"内容污染"本身**:dump 仍含幽灵文本
- 备选 fix(将来按需):
  - A. Sub-page extract 后减去父页 text set(智能去重,中等风险:若 sub-page 真有重复内容会误删)
  - B. Phase 3 audit prompt 加跨 path text dedup(0 风险,改 Phase 3 而非 Phase 2)
- 用户决定:**暂不修**(按"宁可多也不要少"原则,多抓不漏抓可接受)

60. **FAQ probe 加 dump + extract,native 答案文本进 app_texts**(2026-05-27 加)
    - 触发场景:M3 hub 자주 묻는 질문 및 피드백 page 有 7 个 question,展开后下方显示详细答案。原 `probe_faq_expansions` 只做 click + screenshot,**没 dump** → 答案文本完全没进 JSON → AI 翻译审计漏整段 FAQ 答案
    - 用户观察:截图能看到 8-行 韩文答案(`1. Aqara 허브 M3은 클러스터라는 개념을 도입하여 기존 Aqara Zigbee 허브 사용분경을 개선하여 ...`)但 audit 抓不到
    - 修(纯 additive):
      1. probe_faq_expansions 每个 question 点击展开后:除截图外 ALSO `device.dump_hierarchy()` + `extract_app_texts`
      2. 跨 question 去重(seen_expanded set)+ 与 base sub_xml 文本去重 → 只 collect "展开新增" 的文本
      3. 每个展开 XML 也保存(`<sname>__q{idx}.xml`),方便人工检查
      4. 返回值从 `int` 改成 `(count, expanded_texts list)` tuple
      5. caller(traverse_recursive 主 captured branch)解包 + merge expanded_texts 进 app_texts
    - 区分 WebView vs Native:
      - **Native TextView 渲染**(部分 Aqara FAQ)→ dump 能拿到 → app_texts 包含答案 ✓
      - **WebView HTML 渲染**(纯 WebView 类 FAQ)→ dump 拿不到 → expanded_texts 空 → 仍依赖 Phase 3 Vision OCR 截图(行为同旧版)
    - 不损失任何旧能力(截图保留),只**纯加** native 答案文本捕获
    - 日志变化:`[FAQ:7q]` → `[FAQ:7q+25t]`(7 个 question + 25 个新答案文本);每 question 加 `[FAQ-PROBE] q{idx}: +{N} new texts from expanded answer`
    - 回归零影响:只在 FAQ 检测命中的 page 触发(7+ "?" 结尾 TextView),其他设备/页面行为完全不变

59-v2. **case #59 二修 — 撤销过度限制,只在 VANISHED handler 区分 initial vs leak**(2026-05-27 修)
    - **问题**:case #59 v1 用 `initial_discovered_set` 限制主循环只追初始 items,但 M3 hub 实测发现这**过度过滤**:Phase A 主页 click `192.168.50.213` 会 inline 展开网络信息 section,展开后的 items(`지그비 채널 / Wi-Fi 채널 / Thread / MAC 등 16 items`)是 LEGIT click-revealed L0 内容(M3 hub 主页设计),不应该跳过 → 漏抓重要翻译内容
    - 用户原则:"宁可多也不要少"
    - 修(三步,精确区分 legit vs leak):
      1. 撤销 main loop 的 `t in initial_discovered_set` 限制 → 主循环重新追 discovered_order 全部 items(legit click-revealed 重新被扫)
      2. 恢复 `next_title is None` 时的 last-chance dump + scroll-top + _record_items continue 逻辑 → 保留原"捕获 click-revealed L0 item"功能
      3. VANISHED handler 加 `is_initial_item = next_title in initial_discovered_set` 区分:
         - initial item VANISHED → 真问题(device drift),计入 `consecutive_vanished`,3 连击触发 VANISH-RECOVERY / ABORT
         - 非 initial item VANISHED(后期 _record_items 加进来的) → 静默标 SKIP-LEAK,不计 consecutive,不触发 ABORT
    - 结果:
      - M3 hub Phase A 16 个网络信息 items 重新被扫(legit click-revealed) ✓
      - M3 hub Phase B 末尾 3 个 sub-page leak items → SKIP-LEAK 静默处理,不触发 ABORT ✓
      - 其他设备(无 leak 也无 click-revealed)→ 完全等价原行为
    - 日志:`[VANISHED]` 仍是 initial items;新增 `[SKIP-LEAK]` 标识 leak items

59-v1. **discovered_order 加 initial snapshot — 防 sub-page items 泄漏触发假 VANISHED ABORT**(2026-05-26 修,过度限制 / 已被 v2 撤销)
    - 触发场景:M3 hub 22 个 L0 items 全扫完后,末尾出现 `[VANISHED] '장치 프롬프트 언어 설정' / '사용자 정의 벨소리' / '매칭된 에어컨'` → ABORT-LEVEL-VANISHED 假 ABORT。这 3 个其实是 Matter Controller L1 sub-page 的 items。RN overlay panel 关闭后 view tree 残留,L0 主循环每 iter 的 `find_item_by_title` dump 含 L1 items → `_record_items` 把它们误加进 L0 `discovered_order` → 实际 L0 22 items 全 done 后,主循环命中 3 polluted items → find 不到 → VANISHED 链 → ABORT
    - 同根因 case #58:RN sub-page 跟 L0 共享 view hierarchy 文本(那个是 sig 高 overlap,这个是 _record_items 误添加)
    - 修(纯 additive,零行为变化对成功 case):
      - L0 entry 加 `initial_discovered_set = set(discovered_order)` snapshot upfront 真实 items
      - 主循环 next_title selector 加守卫:`t in initial_discovered_set and t not in seen_titles` — 只追真 initial items,后期 _record_items 加进来的不追
      - last-chance check(原本 dump + _record + continue 循环)删掉 → 直接 DONE-LEVEL 退出。原意图"捕获 click-revealed 新 L0 item"极少触发,且现在跟 initial 守卫冲突会无限循环
    - 回归零影响:
      - 真 happy path(没 leak)→ 行为完全一样,只是末尾干净 DONE-LEVEL,不浪费 last-chance dump 时间(还省 1-2s)
      - 有 leak 的设备(M3/P2 等 RN)→ 不再误报 VANISHED + ABORT,真实 items done 就退
      - 假阴性风险:click-revealed L0 item 不再捕获。但 upfront discovery 已经 scroll 找全,这种场景几乎不存在
    - 日志:不变(还是 `[DONE-LEVEL] N processed, M discovered`)— `M discovered` 仍可能含 leak items 数量,但不再追

58. **Case A 守卫 — 防 RN sub-page 因高文本重叠误判已回 parent**(2026-05-26 修)
    - 触发场景:P2 摄像头 L1 `장비 진단` done 返回 L0 后,Case A 阈值 0.7 不够严格。 장비 진단 sub-page dump 含 24 unique texts,L0 settings 含 21 unique texts,**重叠 18/21 = 85.71%** → Case A silent `continue` 不 BACK → 实际还在 장비 진단 → 下一个 click 落 sub-page → 全部抓错(`장치_관련_항목.png` 显示 장비 진단 画面 / 后续 VANISHED chain)。
    - 根因:RN sub-page (장비 진단 等)是 overlay panel,**L0 menu items 仍在底层 view hierarchy** → dump 同时含两层文本 → sig 重叠超 0.7 阈值
    - 用户假设"BACK 没响应"部分正确,但实际是 Case A silent 通过根本没尝试 BACK
    - 修(纯 additive 守卫,只在 L0 启用):Case A 即使 sig 匹配,也要二次验证 `cur menu items 中 ≥70% initial top items 仍存在`。
      - 真回 L0 → initial items 几乎全在 → continue(同原行为) ✓
      - 在 sub-page → initial items 缺多个 → fall through 走 Case C BACK ✓
    - L1/L2/etc 完全不动(避免回归 chooser-back-drift / value-change 等已工作场景)
    - 复用 current_xml(把 `current = get_text_signature(device.dump_hierarchy())` 拆成 dump + sig,避免新增 dump 调用)
    - 日志:`[CASE-A-OVERRIDE] sig match but only X% initial items in cur — likely on sub-page,force BACK`

57. **재시작 / Restart / 重启 加入 DANGER_KEYWORDS — 防 RN Modal 抓不到的 dialog**(2026-05-26 修)
    - 触发场景:G2H Pro 摄像头 L2 `장치 재시작` click → RN Modal "다시 시작하시겠습니까?" dialog 弹出。但 RN Modal 是独立 Android Window → `uiautomator dump_hierarchy()` 抓不到(XML 只含主 activity + systemui,没有 dialog 文本)→ 截图能看到 dialog,XML 完全没。
    - 结果:BOTTOM-SHEET 检查依靠 new_btns(취소/확인 vs parent_sig)— 但 sub_sig 没收录 dialog 文本 → new_btns 空 → BOTTOM-SHEET 不触发。NO-OP-SCROLL 误判 items_preserved=100%(settings 背景仍在 tree)→ 当 mode-toggle 跳过。Dialog 滞留屏幕,后续 하위 기기 / 네트워크 정보 click 被 dialog 阻挡或误中按钮 → ABORT
    - 用户提议:"看 dialog 显示就点 취소"。**不可行** — dump 抓不到 → 没法检测
    - 修:根治方案 — `재시작` / `重启` / `Restart` / `Reboot` 加入 DANGER_KEYWORDS(substring 匹配)。`장치 재시작` 命中 → SKIP-DANGER 不点击 → 没 dialog 弹出 → 跳过该 item 直接进入下一项
    - 等价于用户期望("点击 취소"):都是放弃执行 restart,只是更早(连 click 都不做),更安全
    - 父级菜单 label `장치 재시작` 已在 추가 설정 page 的 XML 里抓到,不影响翻译审计
    - 回归分析:跟 `재설정` / `교체` / `삭제` 同类处理 — 所有 substring 含 `재시작 / 重启 / Restart / Reboot` 的 menu item 全 SKIP。可能误中含这些词的 settings(如 `자동 재시작 설정`),但破坏性 default → safer 选 SKIP

56. **G2H Pro 摄像头 related-items 入口标题适配**(2026-05-26 加)
    - 触发场景:G2H Pro 摄像头 L0 入口标题是 `[desc]장치 연결 연관된 자동 실행, 동시 실행 등`(content-desc 形式的长句),不像 T1/T2 是简短 `장치 관련 항목` / `장치 연관 항목`。my traverse_related_items hook 精确匹配两个固定字符串 → G2H Pro 不命中 → 走通用 traversal → 发现 L1 子 items "장치 관련 항목" + "추가" → 추가 被 SKIP-ACTION → 不深扫 자동/동시실행
    - 用户截图证实:点击 G2H Pro 这个 item 后页面布局**跟 T1/T2 完全一样**(页头是 `장치 관련 항목`,含 자동실행 + 동시실행 sections 各带 추가 按钮)
    - 修(两处同步):
      1. `traverse_recursive` 入口钩子条件加 substring 匹配:`("자동 실행" in title AND "동시 실행" in title)` 或无空格变体 — 强信号,专属 related-items 入口
      2. `title_forces_navigation` 同样扩展(防 NO-OP-SCROLL 拦截)
      3. 两处都加 [desc] 前缀剥离(content-desc 形式 vs text 形式都识别)
    - 回归零影响:T1/T2 精确匹配通路完全保留;只 G2H Pro / 类似长标题设备走新分支
    - 日志:G2H Pro 重扫时应该看到 `[RELATED] entering special traversal (own='智能摄像机G2H Pro(国际版)')`

54. **item-count fallback 误中修复 — 改用 cur titles ∩ initial top items 重叠率**(2026-05-26 二修)
    - 触发场景:G2H Pro 摄像头 L1 추가 설정 BACK 后,scroll-to-top + dump 显示 13 items。settings 总 19 items,case #53 用 `len(cur_items) >= 19*0.7 = 13` 触发 → 误判为 settings 根。但实际可能是 기능 설정 section 中间视图 → 后续 하위 기기 / 네트워크 정보 VANISHED
    - 根因:item-count 单一指标太弱(任何 13 items 的页都满足)。13 不一定是 settings 根
    - 修(case #54 v3):改用 `cur_titles ∩ initial_titles` 重叠率,其中 `initial_titles` 是 L0 第一次 parse_menu_items 的结果(top-scroll 状态的 ~7 个 visible items 标题)。
      - 真 settings 根(scroll-top 后)→ cur 含 top 7 items → 重叠 ~100% ≥ 60% → 触发
      - 기능 설정 section 中间视图(不含 top header / 장치 카드 等)→ 重叠 < 60% → 不触发 → 继续 BACK 或交给 ABORT-RECOVERY
      - 完全无关页 → 重叠 ~0% → 不触发
    - 阈值 60%:留 40% 容错(部分 items 可能 dynamic 文本不一致 / RN 解析浮动)
    - 回归:与 case #53 一样纯 additive,sig match 失败后才考虑;成功的 sig match 通路不变

53. **5-BACK recovery loop 加 item-count fallback(防 dynamic content sig 漂移)**(2026-05-26 修)
    - 触发场景:G2H Pro 摄像头 L1 추가 설정 跑完返回 L0,Case C BACK 把脚本带回 settings 根页(对)。但 settings 含 dynamic 文本(camera live preview 帧 / 网速 / 录制状态 / 时间戳) → page_sig(初次进入时捕获)与 cur(30 秒后)动态文本差异大 → sig 0.7 阈值不过 → scroll-to-top retry 也不行(scroll 完动态文本仍不同) → 误判飘走 → 继续 BACK → settings → device main → device list → ABORT → 后续 7 个 items(하위 기기/네트워크 정보/펌웨어 등)全漏抓
    - 修(纯 additive,不动现有逻辑):scroll-to-top retry 失败后加一道 fallback — 用 `parse_menu_items(cur_xml)` 解析当前页 menu item 数,如果 ≥ `len(discovered_order) * 0.7` (即至少 70% items 还在)→ 认为还在 settings 根
    - 为什么 item count 更可靠:menu item titles(`장치 카드` / `하위 기기` 等)是静态 UI,不随时间变。比 sig(含动态文本)稳定得多。
    - 守卫条件:`expected_n >= 5` — 小 page(子页常 1-3 items)不触发该 fallback,避免误判
    - 回归零影响:原 sig match 通路 100% 保留,只在 sig 失败后多一道防线。Native 设备(M2/T2)走原 activity hint 路径,根本不到这里;快 RN 设备 sig 一般能 match;只有 dynamic-content RN 设备(摄像头 / 视频流类)才命中新 fallback
    - 日志:`[RECOVER] on settings (item-count match: 19/19)` — 报告匹配到的 item 数 / 期望数,便于诊断

52. **S4/S5/S6/S7 nav 等 RN 白屏 loading 稳定后再判断**(2026-05-26 修)
    - 触发场景:5/26 app 更新后,G2H Pro 等重 RN bundle 设备点 "..." 进 settings 前会有 1-3 秒白屏 loading。原代码 `device.click(); time.sleep(2.0); if is_on_settings_page(): return True` — 2 秒不够白屏 → settings 转换 → check 时还在白屏(无 menu item) → `is_on_settings_page(lenient=True)` 误判 False → 试下一个 S4 候选 → 在 loading 结束后错点别处 → 飘回 device main → 偶然 device main 5 items 满足 `looks_like_menu_page` → "arrived via S4" **假报喜** → L0 抓 device main → 全 CYCLE → 整 device 漏抓
    - 为什么 OLD app 不出问题:OLD 渲染快,2 秒够;NEW 加重了 RN bundle / loading screen
    - 为什么 M2/T2 不受影响:Native settings 通过 `SETTINGS_ACTIVITY_HINT` 立即识别,不依赖 menu item 数量
    - 修:S4/S5/S6/S7 tap 后用 `wait_until_rn_page_stable(device, timeout=8.0)` 代替 `time.sleep(2.0)`。等 sig 连续 2 次稳定 = 白屏 → settings 转换真正完成
    - 回归分析:
      - Native 设备(M2/T2):wait_until_rn 在第 2 次 dump 立即匹配 → 几乎不耽误(< 1s)。is_on_settings_page 还是通过 activity hint 判 ✓
      - 快 RN 设备:旧 2s 够,新 wait 也只等 1-2s 早返 ✓
      - 慢 RN 设备(G2H Pro / G4 doorbell):新 wait 等 3-6s 等真正稳定 → 不再误判 ✓
      - 极端 timeout 场景:8 秒 timeout 触发(罕见)→ 行为退化到原版(`force proceeding` 后 check)— 不会更糟
    - 单 device 扫描时间影响:Phase B nav 多花 0-6s(只在 nav 阶段一次)— 整体扫描时间几乎不变

51. **viewer 加 `_scroll_screenshots` 字段**(2026-05-26 加)
    - 触发:traverse_related_items 滚动多帧抓取(case #44 加的)产生 `<sname>__scroll_f{N}.png/.xml` 文件。但 `annotate_screenshots` 当时只挂 `_screenshot` + `_faq_screenshots`,没识别 `__scroll_f` → viewer 看不到这些 frame → 翻译审计漏 RN 长列表内容
    - 修(phase3_build_viewer.py):`annotate_screenshots._attach_faq` 内 scan `__scroll_f` 文件挂 `_scroll_screenshots`;JS render 加 "Scroll frames (N)" 标签 + grid 显示
    - 回归零影响:旧 captures(没 __scroll_f 文件)`_scroll_screenshots` 不挂,行为完全不变

50. **wait_until_rn_page_stable 修 stale-xml bug + 主 loop 去重**(2026-05-26 修)
    - 触发:用户报告 RN 设备(P2 / Matter 等)抓的 PNG 截图与 XML dump 不一致。诊断:`wait_until_rn_page_stable` 检测 sig 稳定后 `time.sleep(0.3)` "视觉缓冲",**但返回的是 sleep 之前 dump 的 xml** → 缓冲期内 RN 可能继续渲染,但返回的 xml 不反映 → 后续 screenshot 抓到更新状态 → 与 xml 错位
    - 二级问题:`wait_until_rn_page_stable` 之前在主 click loop ([line 2068] 已删) 与 `wait_for_page_ready` 重复调用,每 click 多花 3-5 秒(30 设备整体扫描时间翻倍 ~3h)
    - 修(双层):
      - A. `wait_until_rn_page_stable`:sleep(0.3) 后**重新 dump** 一次再 return — 真正捕获缓冲期内的最终渲染状态
      - B. 主 click loop 移除 `wait_until_rn_page_stable` 调用 — `wait_for_page_ready` 已 cover(它本身 poll sig 稳定 + WebView + loading-keyword 检测)。traverse_related_items 内部保留(那里没 wait_for_page_ready)
      - C. screenshot 之前**重新 dump 一次** sub_xml — 确保 PNG 与 XML 完全同时刻(< 50ms 间隔),不再受之前几秒 wait_for_page_ready 期间渲染变化影响
    - 静默化:成功稳定时不打印 `[RN_GUARD]`,只 timeout 时报 — 避免每 click 1500+ 行日志噪音
    - 回归分析:wait_for_page_ready 本来就处理 sig 稳定 + loading,移除冗余 `wait_until_rn_page_stable` 不丢功能;主 loop 减少 3-5s × 每 click → 整体扫描快 50%+;新加的 re-dump in `wait_until_rn_page_stable` 和 screenshot 前的 re-dump 各 + 1 次 dump (~300ms) — 显著小于之前每 click 多花 3-5s

49. **HEURISTIC_* 改成屏幕比例(同事手机抓不到 items 修复)**(2026-05-26 修)
    - 触发:用户同事 Samsung 手机(非 S8,推测 QHD+ 1440×3120 类)跑脚本完全抓不到内容,**也没报错日志,只是 DONE-LEVEL 0 processed**。诊断:`HEURISTIC_MIN_HEIGHT=50 / MAX=300 / MIN_WIDTH=200` 是针对 1080×2220 标定的绝对像素值;在大屏手机上 item 渲染高 > 300px → 全 filter 掉 → 0 items 静默失败
    - 修:HEURISTIC_*_RATIO 改成屏幕比例(50/2220=0.0225, 300/2220=0.135, 200/1080=0.185)。新 helper `_heuristic_pixel_thresholds()` 基于 `get_screen_size()` 计算实际像素 — 1080×2220 上还原成 50/300/200(向后兼容),其他尺寸自适应
    - get_screen_size 在 main() 的 `u2.connect()` 后已 cache 真实尺寸,所以无 stale 风险
    - 回归分析:S8 (1080×2220) 阈值不变 ✓;QHD+ 屏新阈值自动放大 ~30% (覆盖更大 item)
    - 仍未解决:`HEURISTIC_MIN_ITEMS_FOR_MENU=3` 是数量,不是像素,不影响 — 各屏幕通用

37. **CAPTURE-ONLY-PARENT 后强制 BACK — title_forces_navigation 跳过 Case A**(2026-05-21 修)
    - 触发:LED 전구 T2(E26, CCT) Phase B 点击 `전환 설정` 后:
      - `전환 설정` 在 CAPTURE_NO_RECURSE_KEYWORDS 命中 → 递归立即 `CAPTURE-ONLY-PARENT` return,**没有 BACK**
      - sub-page 保留了父页菜单 items(items_preserved 高) → sig overlap >= 0.7
      - 主循环 post-recurse 的 Case A `signatures_match(current, page_sig, threshold=0.7)` 误判 "已回父页" → `continue` 跳过 BACK
      - 下一次点击 `디밍 범위` 落到 sub-page 残留菜单上 → [VANISHED]/[CYCLE-UP] 循环 → ABORT-LEVEL,后面 7+ items 全跳过
    - 修:Case A 加 `not title_forces_navigation` 守卫 — 当 title 命中 CAPTURE_NO_RECURSE_KEYWORDS 时强制跳过 Case A,直接走 Case C (BACK + 检查 save prompt)
    - 影响面:所有 CAPTURE_NO_RECURSE_KEYWORDS 命中的 sub-page(전환 설정 / 디밍 범위 / 장치 검색 / 통신 프로토콜 / 비밀번호 / 언어 / 야간 적외선 等)。修前误判后,下一项点击会落到 sub-page 上;修后保证 BACK 回父页
    - 日志:不再出现 CAPTURE-ONLY-PARENT 后紧接的 [VANISHED] '<next-title>' no longer findable

38. **CHOOSER BACK off-parent recovery — L0 chooser drift 后续扫**(2026-05-21 修)
    - 触发:LED 전구 T2(E26, CCT) Phase B L0 第 10 个 item `신호 강도` click → `[CHOOSER-REVEALED] '장치 관련 항목'` capture 28 条 → BACK 1 下落到陌生中间页 → 现有 `[CHOOSER] BACK landed off parent — return to let caller recover` 直接 return → 单设备 flow L0 return = 整体结束 → 剩余 5 个 settings items(펌웨어 업데이트 / 통신 프로토콜 / 장치 관련 항목 / 장치 로그 / 장치 그룹 생성)全跳过
    - 修:CHOOSER BACK off-parent 分支加 L0 恢复(同 case #34 VANISH-RECOVERY 模式)— 当 `depth == 0` 且 `len(remaining) >= 2` 时调 `_try_recover_to_settings(device, page_sig)`;成功 → `continue` 处理剩余 items;失败 → 原 return 行为
    - 影响面:所有 L0 settings 中间触发 CHOOSER-REVEALED + BACK off-parent 的设备(常见于带 chooser-style sub-page 的 RN 设备)。L1/L2 chooser 不受影响(还是直接 return,让 L0 主循环用 5-BACK 渐进恢复)
    - 日志:`[CHOOSER-RECOVERY] BACK off parent, N titles unprocessed, attempting re-nav...` / `[CHOOSER-RECOVERY] re-nav OK, resuming` / `[CHOOSER-RECOVERY] re-nav failed, returning`

48. **장치 관련 항목 / 장치 연관 항목 加 title_forces_navigation(防 NO-OP-SCROLL 拦截)**(2026-05-21 修)
    - 触发场景:P2 settings page click `장치 관련 항목` → sub-page dump 含父页菜单残留(RN render 时 L0 items 留在 tree)→ `items_preserved = 100%` → NO-OP-SCROLL (mode-toggle, C 条件) 触发 → **不进 recursion** → `traverse_related_items` hook 没机会触发 → 자동/동시实행 deep scan 漏抓
    - 跟用户加 `장치 관련 항목` / `장치 연관 항목` 进 PAGE_CONTENT_NO_RECURSE_MARKERS 无关 — 那个 check 在 recursion 内部,但 recursion 都没进入
    - 修:`title_forces_navigation` 加 `title in ("장치 관련 항목", "장치 연관 항목")`。NO-OP-SCROLL 检查里有 `and not title_forces_navigation` 守卫 → 这两个 title 强制跳过 NO-OP-SCROLL → 走 captured + recurse → recursion 入口 `traverse_related_items` hook 触发
    - 回归分析:精确字符串匹配,只这两个 title 受影响。其他 title 行为零变化
    - 日志:之前 `[NO-OP-SCROLL] text 85%, items 100%, new=6 (mode-toggle)`,修后变 `[OK] N` + `[RELATED] entering special traversal (own='...')`

47. **SLOW_DEVICE_MODE 配置 + 处리 중 / Processing 加 LOADING_KEYWORDS**(2026-05-21 加)
    - 触发场景:P2 `네트워크 정보` 子页 Thread 数据加载时显示"처리 중..."loading overlay。原 LOADING_KEYWORDS 没收录"처리 중",`wait_for_page_ready` 看到 sig 稳定(只有"처리 중..."1 个文本)+ `loading=False` → 误判 ready → 提前返回 → recursion 见空 items 立即 return → 整个 P2 后续 traversal 崩(后面 장치 관련 항목 click 触发 NO-OP-SCROLL,自动실행/동시실행 没扫到)
    - 用户机:三星 S8(2017),性能差,加载更慢,更容易暴露这类 timing bug
    - 修(双层):
      - A. LOADING_KEYWORDS 加 "처리 중" / "처리중" / "Processing" / "处理中"(通用,所有设备受益)
      - B. 文件顶部加 `SLOW_DEVICE_MODE` flag(默认 True 适配 S8),切换到快设备时改 False 即可。`_SLOW_MULT = 2.0` scales 所有 WAIT_* 常量(STABLE_THRESHOLD / MAX_NATIVE / MAX_RN / AFTER_BACK / AFTER_DEVICE_CLICK / ACTIVITY_DETECT_DELAY)。新增 `WAIT_AFTER_CLICK_EXTRA = 1.0s`(只 slow mode 生效)用于 click → wait_for_page_ready 间额外 sleep,给 RN bundle 反应时间
    - 回归分析:
      - LOADING_KEYWORDS 增加几个词 → 只对含这些文本的页面延长等待,其他页面零影响
      - SLOW_DEVICE_MODE = True → 所有等待 ×2,扫描时间 ~×2(可接受);换到快设备改 False 立即恢复原速度
    - 影响面:任何 RN 设备的 loading-heavy 子页(网络信息 / 蓝牙状态 / Thread 数据 / 固件查询 等)。S8 等老设备整体稳定性 ↑↑

46. **设备自身名称卡片统一 CAPTURE-ONLY-PARENT(防 L1 polluting L0)**(2026-05-21 修)
    - 触发场景:P2 settings 顶部 `열림 감지 센서 P2` 卡片 click 进 '장치 정보' 子页(10 个 device-info 子项 + 一个 `<` BACK 箭头)。原行为:递归进 L1 → L1 discovery 因过渡 dump 状态混入 5 个 L0 items(장치 로그/네트워크 정보/펌웨어 업데이트/etc.)→ L1 处理 15 items 后无法干净 BACK 回 L0 → 剩余 L0 items 全 VANISHED → ABORT。同时 L1 sub-items(장치 이름/장치 위치 等)被 leak 到 L0 discovered_order,后续被当 L0 item 重复点击,触发 dialog/drift。
    - 修:traverse_recursive 入口加新 check — `breadcrumb[-1] == CURRENT_DEVICE_NAME` 时 CAPTURE-ONLY-PARENT return;同时 `title_forces_navigation` 加 `title == CURRENT_DEVICE_NAME` 条件,保证 Case A 跳过 + 强制 BACK。
    - 为什么不损失内容:父级 click 时已经 capture 38 条 sub-page 文本(含所有子项 label + value);FAQ probe (자주하는 질문 q01-q08) 在父级 click 时已经触发,8 个 question screenshots 抓全。**实际不损失 audit 数据**。
    - 回归分析:LED T2 own card click → [BOTTOM-SHEET] 先拦截(我的 hook 在 recursion 入口,BOTTOM-SHEET 在 click iter 内更早)→ 不变 ✓。도어락 L100 own card → captured + [CYCLE] 阻止 recursion → 我的 hook 不触发 → 不变 ✓。P2 → 新 CAPTURE-ONLY-PARENT 路径,L0 traversal 完整 ✓。
    - CURRENT_DEVICE_NAME 提取失败(单设备 flow 时偶尔可能)→ check 不触发 → 走原逻辑(安全 fallback)
    - 日志:`[CAPTURE-ONLY-PARENT] '<device-name>' (device-info card,matches CURRENT_DEVICE_NAME)`

45. **[DIALOG] handler drift 恢复 + 장치 연관 항목 翻译变体**(2026-05-21 修)
    - 触发 A([DIALOG] drift):LED 전구 T2 통신 프로토콜 click 弹 "Zigbee" info dialog,按 확인 关 dialog 但**附带导航**到 device main(3 items)→ 后续所有 settings items VANISHED。同样问题任何"info dialog 只有 확인,按完跳走"的 item 都会触发(几乎所有 RN 设备的 통신 프로토콜)。
    - 修(A):[DIALOG] handler 内,确认 click 后检查 current_sig:
      - L0(depth==0) + 在 device list → 停(BACK 会出 app)
      - L0 + `sig overlap < 0.3` → 明显飘走(典型 device main) → `_try_recover_to_settings`
      - L0 + 0.3 ≤ overlap < 0.85 → 还在 settings,只是 state/scroll 略 drift → 原 BACK 一次(不动行为,避免回归)
      - depth > 0 (子页 dialog) → 原 BACK 一次(不动)
    - 为什么用 sig overlap < 0.3 而不是 is_on_settings_page(lenient=True):后者对 device main 也返回 True(≥3 items 满足 heuristic),无法区分
    - 触发 B(翻译变体):有的设备 settings 菜单是 `장치 관련 항목`,有的因翻译错误是 `장치 연관 항목` → traverse_related_items 钩子漏识别 → 走通用 traversal(可能误点 자동실행/동시실행 → 设备切换无限循环)
    - 修(B):`traverse_recursive` 钩子条件 `breadcrumb[-1] in ("장치 관련 항목", "장치 연관 항목")`;PAGE_CONTENT_NO_RECURSE_MARKERS 也加 `장치 연관 항목`
    - 影响面:Fix A 对所有"dialog click 后被顶到 device main"的 RN/Native 设备都生效(통신 프로토콜 / 펌웨어 버전 等可能触发的 item);Fix B 让两种翻译变体都走 deep scan

44. **장치 관련 항목 专项扫描 — 자동실행 + 동시실행 추가流程**(2026-05-21 新增)
    - 需求(用户提出):每台设备 settings 页的 장치 관련 항목 子页有 자동실행 + 동시실행 两个 section,各一个 추가 按钮。需深入扫:추가 → 条件页(트리거 조건 추가 / 상태 조건 추가 / 작업 추가)→ 选项页(장치)→ 设备清单 → 找带 '현재' 标记 + 名称匹配自己设备的项 → click → capture 跳转页
    - 关键约束:严格双要件(`name == CURRENT_DEVICE_NAME` 且 含 '현재' substring) → 防止误点别人触发设备切换 → 无限循环。没匹配上 → skip,只 BACK
    - 设备名 source:
      - 单设备 flow:`extract_device_name_from_main(main_xml)` 从 Phase A 主页顶部 header 抓
      - 多设备 flow:已知 `label` 变量
    - 实现:
      - 模块级 `CURRENT_DEVICE_NAME` 变量,Phase A 入口设置
      - `traverse_related_items(device, own_device_name, breadcrumb, results, indent)` 主函数,所有 step try/except 包,失败 → 多 BACK 几次安全退
      - `traverse_recursive` 入口加钩子:`breadcrumb[-1] == "장치 관련 항목"` 时 call 专项,return(不走通用 capture/recurse)
      - 钩子优先级在 CAPTURE_NO_RECURSE_KEYWORDS / PAGE_CONTENT_NO_RECURSE_MARKERS check 之前
    - 安全:CURRENT_DEVICE_NAME 提取失败 → graceful skip 深入(只 capture 顶页文本),不影响其他扫描
    - 输出:findings 里会多 4 类 status — `captured_related_items` / `captured_conditions` / `captured_options` / `captured_own_in_related`
    - 日志:`[RELATED] entering special traversal (own='...')` / `[RELATED] === section: 자동실행 ===` / `[RELATED] ✓ own device matched ('현재' present)` / `[RELATED] own device not in list,skipping deeper`

43. **`_try_recover_to_settings` lenient=True + 先 auto_nav 再 BACK**(2026-05-21 修)
    - 触发:LED 전구 T2 通信 프로토콜 click 弹 info dialog,`[DIALOG] '확인', dismissing` 关 dialog 但**附带导航**到 device main(3 items:동시실행/조정 가능한 흰색/조명 그룹)→ 后续 [VANISHED] '장치 관련 항목' / 장치 로그 / 장치 그룹 생성 → VANISH-RECOVERY 调 `_try_recover_to_settings` 失败
    - 根因:函数原代码先 BACK loop 再 auto_nav,但 device main 上 BACK 必出 device → device list → `if is_on_device_list: return False` 立即放弃,**没给 auto_navigate_to_settings 一次机会**。加上内部 3 处 `lenient=False` 对 RN 设备永远 false → BACK 越按越坏
    - 修(双层):
      - A. **先 try auto_nav**:函数开头新加一段 — 调 `auto_navigate_to_settings(device)` 找右上 "..."。device main / 中间页都能 find + tap → 进 settings → sig match(threshold 0.5,允许 settings 页 state 略 drift)→ 直接 return True
      - B. **3 处 lenient=False → True**:RN 设备 settings 没 `cl_root_layout`/`item_layout` anchor,严格模式永远 False。改 lenient 兼容 RN 的 `looks_like_menu_page` heuristic
    - 影响面:所有"settings 子页 click 后被 dialog/wizard 顶到 device main"的场景。配合 case #42 的 5-BACK 内 scroll-to-top 修复,RN 设备 settings 末尾 item 漏抓率应该大幅下降
    - 日志:不变(还是 [VANISH-RECOVERY] re-nav OK / failed),但内部成功率明显提升

42. **5-BACK recovery loop 加 scroll-mismatch 修复 + device list 早停**(2026-05-21 修)
    - 触发:LED 전구 T2 `신호 강도` chart fullscreen sub-page → BACK 1 下回到 settings,**但 scroll 位置停在 신호 강도 附近(mid-scroll)** → 不显示 page_sig 顶端 items(page_sig 是在 discover_all_titles 后 scroll-to-top 状态捕获的) → `signatures_match(cur, page_sig, 0.7)` 误判 false → 继续 BACK 把脚本顶到 device main → device list → 出 app → ABORT-RECOVERY 看到 device list 直接 return False
    - 根因:`page_sig` 在 top scroll 状态采集,但 click+BACK 后 settings 可能在 mid-scroll → 文本不重叠
    - 修(双层):
      - A. **scroll-to-top 兜底**:每次 iter dump 后 sig 不匹配时,如果 `is_on_settings_page(lenient=False)` 说在 settings 上,先调 `scroll_page_to_top(device)` → 再 dump + match。能修就 recovered;不能 → fall through 走原 BACK
      - B. **device list 早停**:如果 dump 后 `is_on_device_list(device)`,立即 break 退出循环 — 不要再 BACK 一路顶出 app。然后由 ABORT-RECOVERY 兜底(目前 `_try_recover_to_settings` 在 device list 时直接 return False,等于 ABORT,但至少不会越按越坏)
    - 影响面:scroll-to-top 修复对所有"sub-page BACK 后回 settings 但 scroll 位置不同"的场景都生效(几乎每个 RN 设备的 mid-list item)。device list 早停对所有"5-BACK 太多导致出 app"的场景兜底
    - 日志:`[RECOVER] on settings (scroll-mismatch), scroll-top fixed sig` / `[RECOVERY] hit device list at attempt N, stopping further BACK`

41. **ABORT-LEVEL 前 try re-nav to settings — 5-BACK 不够时的最后挽救**(2026-05-21 修)
    - 触发:LED 전구 T2 `신호 강도` CAPTURE-ONLY-PARENT 后 BACK,但 신호 강도 sub-page 是个全屏图表(包含日/周/分钟级 signal 历史曲线),BACK 行为 RN 自定义可能跳到中间页或 device main,5 次 BACK 都没回到 settings → ABORT-LEVEL → 后面 5 个 items(펌웨어 업데이트 / 통신 프로토콜 / 장치 관련 항목 / 장치 로그 / 장치 그룹 생성)全跳过
    - 类似:门锁 펌웨어 업데이트 L2 递归处理完返回 L1,5-BACK 后没回 settings → ABORT-LEVEL → #16 장치 관련 항목 漏
    - 修:`if not recovered:` 块加 `_try_recover_to_settings` 调用(同 case #34 VANISH-RECOVERY / case #38 CHOOSER-RECOVERY 模式)— `depth == 0` 且 unprocessed >= 2 时调一次 re-nav,成功 → `continue` 继续处理;失败 → 走原 ABORT-LEVEL 行为
    - 通用性:所有 L0 settings 飘出后的"5-BACK 救不回"场景统一兜底。三种 RECOVERY(VANISH / CHOOSER / ABORT)模式一致,只是触发点不同
    - 日志:`[ABORT-RECOVERY] 5 BACKs failed, N titles unprocessed, attempting re-nav...` / `[ABORT-RECOVERY] re-nav OK, resuming` / `[ABORT-RECOVERY] re-nav failed, aborting`

40. **5-BACK recovery loop 内加 save-prompt 处理 + BLE wizard SKIP**(2026-05-21 修)
    - 触发:도어락 동작 확인 wizard(step 1/5,需 BLE + 用户实物开门)— CAPTURE-ONLY-PARENT 拿到截图后 Case C 按 BACK,触发 종료하시겠습니까? dialog,外层 save-prompt 检测命中 → 按 확인。但 확인 click 后 wizard 没退出(BLE 卡住或 confirm 没生效),进 5-BACK recovery loop:loop 只 dump + 比对 sig + BACK,**没有 save-prompt 检测** → 每次 BACK 又触发 종료 dialog → loop 按 BACK = 취소 → 留在 wizard 死循环 → 5 次后 ABORT-LEVEL → 剩余 #14-16(허브 / 펌웨어 업데이트 / 장치 관련 항목)全跳过
    - 修(双层防御):
      - Fix 1 — 5-BACK recovery loop 加 `detect_save_prompt_action` 检查。每轮先 dump XML + sig,如果命中 save-prompt(종료하시겠습니까 / 변경내용 등),按 SAVE_PROMPT_DISCARD_LABELS 里的 확인 / 나가기 → `continue`(跳过 BACK,下轮重新 check)。日志:`[SAVE-PROMPT-LOOP] dialog detected during recovery, clicking 'X'`
      - Fix 2 — `도어락 동작 확인` 加进 DANGER_KEYWORDS_END_ONLY(精确匹配)。BLE wizard 自动化无法走完,父设置页菜单 label 已抓到,wizard step 内容自动化不可达,直接 SKIP 不点击 → `[SKIP-DANGER] 도어락 동작 확인: end-keyword '도어락 동작 확인'`
    - 通用性:Fix 1 对所有 wizard 类 BLE / 多步交互的"BACK 触发对话框"场景都生效;Fix 2 仅针对 도어락 동작 확인 一个 title(以后碰到类似 BLE wizard 加进同一 list 即可)
    - 用户疑问背景:用户问"为什么 종료하시겠습니까 + 확인 不行";答案是确实加了 종료하시겠습니까 进 SAVE_PROMPT_KEYWORDS,但 recovery loop 没用上,所以 wizard 实际没退出。一些更通用的 fallback 关键字(`Are you sure` / `退出吗`)有意没加 — 怕误中"确认删除"这种危险对话框

39. **CHOOSER-REVEALED 误判修复 + 종료하시겠습니까 退出确认对话框**(2026-05-21 修)
    - 触发 A(误判 chooser):LED 전구 T2 `신호 강도` / 도어락 L100 `도어락 동작 확인` click 后,sub_sig 含 `장치 관련 항목` 文本但 `page_sig` 没有 → CHOOSER-REVEALED 触发。但 `장치 관련 항목` 其实是父设置页的菜单 item,只是初始 dump 时滚到屏幕下方,没进 `page_sig`。scroll_capture + BACK → off-parent → recovery 失败 → 剩余 4-8 个 items 全跳过
    - 触发 B(도어락 wizard 退出):点击 `도어락 동작 확인` 进 5 步 wizard(`도어락 동작 확인 (1/5)`,需要 BLE 连接 + 用户配合开门),BACK 退出时弹 `종료하시겠습니까?` 对话框(취소/확인)。现有 `detect_save_prompt_action` 不识别 → recovery 卡死
    - 修(A):CHOOSER-REVEALED 加 `discovered_order` 守卫 — 如果 marker 文本已经出现在 discovered_order 的 title 里,说明只是父页 scroll 出视野的菜单项,不是真 chooser,skip。**通用 fix,不需要给每个新设备显式加白名单**
    - 修(B):`종료하시겠습니까` 加 SAVE_PROMPT_KEYWORDS。BACK 后 detect_save_prompt_action 命中 → 按 SAVE_PROMPT_DISCARD_LABELS 里的 `확인` 退出。注意没加更通用的 `Are you sure` / `退出吗` 等,避免误匹配 "确认删除?" 这类危险对话框
    - 加 兜底:`신호 강도` / `Signal Strength` / `信号强度` 加进 CAPTURE_NO_RECURSE_KEYWORDS(belt-and-suspenders,即使 discovered_order 守卫失效,这个 title 也会走 CAPTURE-ONLY-PARENT 路径)
    - 影响面:所有"父设置页含 `장치 관련 항목` 等 PAGE_CONTENT_NO_RECURSE_MARKERS 菜单项,但 dump 时滚出视野"的设备(几乎所有 RN 设备);所有 wizard 类设置(需 BLE / 用户交互的多步操作)的 BACK 退出
    - 已知限制:门锁部分设置(원격 기능 / 외출 모드 等)需 BLE 在线 — BLE 断开时这些 menu item 可能 VANISHED / click 无响应,现有 VANISH-RECOVERY 能处理部分情况,但不能保证 BLE 慢/断开时一次扫全。用户已知此限制,不展开自动恢复(避免反复重连)

---

## M3 Hub 的具体踩坑过程（参考）

M3 hub 是迄今最难处理的设备，单它就触发了约 6 项边界 case：

```
[Phase A] 主页 5 items → 4 NO-OP-SCROLL + 1 captured (리모컨 추가 wizard)
[Phase A cleanup] 2 BACKs (wizard → IR sub-page → main)
[Phase B] S4 找到 "..." 按钮（[943,99][1080,165]）→ 进设置（但还在同一 activity）
[L0] 13 items 混合 hub main + settings
[L1] 점击 "매칭된 에어컨" → 内嵌展开 22 个品牌
  → CHOOSER-REVEALED 抓 40 条 → return
[L0] 继续 其他 items：大量 CYCLE-UP（M3 设置内嵌，每点都和上层签名相同）
[DONE]
```

CYCLE-UP 数据其实包含了页面文本（`[OK] 28` 表明抓到），只是被标记为 cycle_up。Phase 3 可以使用这些数据。

---

## Phase 3 计划（待实施）

### AI 选择
**Claude API**。

### Glossary 策略
**B：自动从抓取数据生成初稿**，跨设备一致性检查。

### Deliverables
1. **Glossary generator**：扫所有设备 JSON，提取高频专有名词，初步聚类（如"클라우드 동영상" vs "클라우드 비디오"应统一）
2. **Claude API audit prompt**：批量审计每个 path 的韩文，输出：
   - `path`：菜单路径
   - `original`：原文
   - `issue_type`：typo / translation_inconsistency / chinese_leak / english_leak / punctuation / awkward
   - `suggested_translation`：建议译文
   - `priority`：high / medium / low
3. **findings JSON 输出**：合并所有发现
4. **★ WebView 类页面用 Claude Vision OCR**(必做):
   - `자주하는 질문 / 사용자 매뉴얼 / 개인정보 보호 정책 / 사용약관` 等都是 WebView 远程 HTML
   - **UIAutomator dump 看不到 WebView 内部 HTML 元素**(包括 "> 展开箭头"和 FAQ 问题正文) → phase2 只能拿到截图,拿不到文本
   - phase3 直接对这些页面的 PNG 走 Claude Vision API,**一次性 OCR + 翻译审计合并**,省一步独立 OCR
   - phase2 已经在 `wait_for_page_ready` 里加了"等 ProgressBar 消失"逻辑(2026-05-12),保证截图是加载完的状态;但**文本提取靠 Vision**

### 已发现的翻译问题（Phase 3 待审计）
- **中文未翻译**：智能可视门铃G4（国际版）、智能摄像机G2H Pro(国际版)、人体传感器 P1、人体传感器T1-1、摄像机
- **ToggleButton 含中文**：开关（开发者中文标识泄漏）
- **翻译不一致**：장치 연관 항목 vs 장치 관련 항목；클라우드 동영상 vs 클라우드 비디오
- **韩文 typo**：브랜드 서택（应 선택）、움직임명 인식됨（应 움직임이 감지됨）、"전체 집 모니터링" 카드 추가추가하기（重复 추가）
- **英文未翻译**：Doorbell、"Lumi video doorbell face recognition authorization"
- **全角标点混用**：사용 중：29.60 GB（全角冒号）

---

## 未来计划

**计划 #1 三语扫描审计**: ✅ **已实施**(2026-05-18 起,见底部"三语对比 audit"章节)
**计划 #2 GitHub Pages 部署**: ✅ **已实施**(手动版,repo `aqara-audit-reports`)
**计划 #3 不同尺寸手机/平板**: 仍未实施,优先级低
**(新)计划 #4 Decision UI + 协作流程**: ✅ **已实施**(2026-05-19,见底部"Decision UI"章节)

---

(下面是历史计划的详细描述,留作参考)

> 用户在 2026-05-11 提出的中长期方向(2026-05-11 二次修订)。写代码改动时**预留兼容性**,但当前不实施,避免局面更乱。

### 1. 三语扫描(中→英→韩)→ 跨语言对齐 → AI 审计

**最终方案**(用户 2026-05-11 修订):
- **架构保持本地**:用一台专用笔记本(Windows + 当前的 phase2_traverse.py)连接 Android 设备扫描,不上云
- **自动化语言切换**:用户会提供 App 内"切换 UI 语言"的菜单路径(应该是 设정 → 장치 언어 / 시스템 언어 之类)。脚本按这个路径自动切:
  1. 切到中文 → 完整跑一遍 phase2 → 存 `traverse_result_zh.json`
  2. 切到英文 → 完整跑一遍 → 存 `traverse_result_en.json`
  3. 切到韩文 → 完整跑一遍 → 存 `traverse_result_ko.json`
- **跨语言对齐**:按 `path` 1:1 对齐三个 JSON 的 `app_texts`
  - 三语 1:1 直翻可校验 → 跳过,不送 AI
  - 韩文与中/英基线偏差大 → 送 AI 审计
  - path 缺失/新增 → 标 `structural-mismatch`,单独处理
- **预期收益**:大多数 path 在三语基线对比下就能机械判定翻译正确性,送 AI 的只是少数可疑项 → token 大幅下降

**前置验证**(等用户提供切换路径后才知道):
- App 内切语言**是不是真的整个 UI 重渲染**(包括 RN bundle),还是只切系统语言层
- 切完是否需要重启 App(很多 RN 应用绑定 locale 在启动时)
- 三语下的菜单**遍历顺序**要可重复 → 依赖 `discovered_order` + click 决策稳定

**代码层面要预留的**(写新功能时记得不要打破):
- `traverse_result.json` 的 `path` 字段必须保持 stable,不要把动态数据(IP/计数 16→51 这种)塞进 path → **当前 schema 已合规,继续保持**
- 每个 path 输出的 `app_texts` 顺序也要稳定,方便跨语言对齐
- `OUTPUT_DIR` 命名要带 locale 后缀(实施时改成 `traverse_v8_zh_{ts}/`、`traverse_v8_en_{ts}/`、`traverse_v8_ko_{ts}/`)
- 切语言菜单的 click 决策要**不被现有 `DANGER_KEYWORDS` / `NAVIGATION_JUMP_KEYWORDS` 误拦**(可能需要给"切语言"流程一个 bypass tag)

### 2. Web 版作用范围 + 部署方案(2026-05-12 三次修订定稿)

**最终方案**:**只做结果展示**,不做设备控制。**单一 GitHub repo + Pages + Actions cron**,无外部 blob 服务,无 DB。

#### 2.1 总体架构

```
audit-reports/  ← GitHub repo (public)
├── _config.yml                    ← Pages 配置:JSON 发布,PNG/XML 排除
├── .github/workflows/cleanup.yml  ← cron 自动清理 >90 天报告
├── reports/
│   └── 2026-05-12_p2_ko/
│       ├── triples.json           ← 几十 KB,Pages 发布
│       ├── findings.json          ← 几十 KB,Pages 发布
│       └── screenshots/*.png      ← 不发布 Pages,但在 repo 里
├── index.html                     ← SPA 浏览器,JSON-only,img 用 raw URL
└── README.md
```

#### 2.2 关键配置

**`_config.yml`** — 让 Pages 跳过大文件:
```yaml
include: ["reports/**/*.json", "index.html", "assets/**"]
exclude: ["reports/**/*.png", "reports/**/*.xml", "reports/**/*.log"]
```

**HTML 加载截图通过 raw.githubusercontent.com**(不走 Pages):
```html
<img src="https://raw.githubusercontent.com/USER/audit-reports/main/reports/2026-05-12_p2_ko/screenshots/faq__q01.png">
```

**`.github/workflows/cleanup.yml`** — 每周日凌晨 3 点自动删 >90 天报告:
```yaml
name: Cleanup old reports
on:
  schedule: [{cron: '0 3 * * 0'}]
  workflow_dispatch: {}
jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - name: Delete reports older than 90 days
        run: |
          THRESHOLD=$(date -d '90 days ago' +%Y-%m-%d)
          for dir in reports/*/; do
            d=$(basename "$dir" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}')
            if [[ -n "$d" && "$d" < "$THRESHOLD" ]]; then
              git rm -rf "$dir"
            fi
          done
      - name: Commit
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --staged --quiet || (git commit -m "chore: auto-prune >90d" && git push)
```

#### 2.3 容量预估(支撑 100 设备 + 3 个月保留)

- 单 device scan:~3 MB(平均;P2/M3 这类复杂 RN ~7MB)
- 一轮全扫(100 设备 × 3 语言):~900 MB
- 3 个月保留 × 每月 1 轮 = **峰值 ~2.7 GB**

vs GitHub 限制:
- 仓库硬限 5 GB → ✓ 2.3 GB buffer
- Pages 已发布站点 1 GB → ✓ JSON-only ≈ <50 MB,永远不撞
- Pages 带宽 100 GB/月 → ✓ 翻译团队远用不到

**raw.githubusercontent.com 注意事项**:不是 CDN,有 abuse 检测。翻译团队几人用够,但**不能拿来当公开生产 CDN**。

#### 2.4 部署 + Phase 3 完整数据流

```
笔记本(本地)
  ├── phase2_traverse.py 跑设备  → output/traverse_v8_*/(gitignored,本地缓存)
  ├── phase3_align.py(待写)    → triples.json
  ├── phase3_audit.py(待写)    → findings.json  (call Claude API)
  └── upload.py(待写,10-20 行)   → 整理到 audit-reports/reports/YYYY-MM-DD_device_locale/
                                  → git add + commit + push

GitHub(云端 0 维护)
  ├── Pages 自动 build:发布 JSON + HTML → https://USER.github.io/audit-reports/
  ├── raw.githubusercontent.com 服务 PNG 文件
  └── Actions cron 每周自动删 >90 天文件夹

翻译团队
  └── 浏览器打开 URL → JSON from Pages, screenshots lazy-load from raw.github
```

#### 2.5 实操顺序(待执行)

1. 当前 priority:phase2 跑完所有 25 设备(2026-05-12 进行中)
2. 写 `phase3_align.py`(纯代码,Tier 0 三语对齐;Tier 1 机械规则可选)
3. 写 `phase3_audit.py`(调 Claude API;API key 在 `.env`,**绝不入 git**)
4. 写 `upload.py` + 创 `audit-reports` repo + 配 `_config.yml` + cron workflow
5. 写最简静态 HTML viewer(读 JSON 渲染 menu tree + findings)

#### 2.6 API key 安全(强制纪律)

- `.env` 放 `ANTHROPIC_API_KEY`,加进 `.gitignore`,**绝不 commit**
- 代码用 `os.environ.get("ANTHROPIC_API_KEY")`,不硬编码
- 可选:pre-commit hook 扫到 `sk-ant-` 阻止 commit
- 推 GitHub 的内容(JSON/PNG/log)**完全不含 key** — 安全
- 即使 audit-reports repo 设为 public 也安全

**代码层面要预留的**:
- phase2 / phase3 的输出都是**自包含 JSON**(不依赖本地路径)
- 截图文件名稳定(下次扫不变),方便 incremental upload
- 报告目录命名格式必须含日期前缀:`YYYY-MM-DD_<device>_<locale>` — Actions cron 靠这个判 90 天

### 3. 不同尺寸手机/平板兼容性

**当前已 ok 的**(屏 size 无关):
- `BOTTOM_NAV_THRESHOLD_RATIO = 0.85` 是比例
- 所有 swipe/scroll 用 `screen_h * X` 比例
- `click_by_bounds` 用 dump 绝对坐标

**当前有问题的**(针对 1080×2220 硬编码):
- `HEURISTIC_MIN_HEIGHT = 50, MAX_HEIGHT = 300` — item 高度白名单
- `HEURISTIC_MIN_WIDTH = 200` — item 宽度下限

换大屏平板 item 渲染高度可能 > 300 → 漏抓;换小屏手机宽 < 200 → 漏抓。

**修法**(将来做):
- 改成 `min_h = screen_h * 0.025`, `max_h = screen_h * 0.15`, `min_w = screen_w * 0.2` 之类的比例
- 或者脚本启动时先做一次"item 高度分布采样",动态决定阈值

**当前先标记**:`HEURISTIC_MIN_HEIGHT / MAX_HEIGHT / MIN_WIDTH` 这 3 个常量是换屏会爆的硬编码点。

---

## 当前状态(2026-05-19)

**Phase 1/2/3 主线全部 implemented**:
- Phase 2 多设备 flow 稳定,27 台一气呵成 ~1.5h
- Phase 3 audit + viewer + corrections + ignore mechanism 全部到位
- 三语扫描 + AI 审计 + GitHub Pages 发布 已运行
- 累计实际数据点(2026-05-19):
  - 1 次 ko-only audit:₩4,876, 187 findings
  - 1 次 trilingual audit:₩4,548, 593 findings(包含 130 误判)
  - 1 次 trilingual + 反误判修复:₩3,800, 487 findings(误判 130→36, -72%)

**接下来的 known TODO**:
- 等开发改一批 corrections → 重 audit 看 verified/regressed
- 视情况扩 GitHub Pages 给翻译团队协作
- 长期:补 README + 多人协作工作流文档

---

## Pipeline 运行顺序(严格按此顺序)

每次扫完都按 1→2→3→(4) 顺序跑,**绝不能**先跑 3 再跑 2 — 否则 viewer.html 里 findings 是空的,⚠ filter 全都不出。

```powershell
# 1. 扫描(在设备列表页或单设备主页起跑)
python phase2_traverse.py                     # 默认续扫,扫完一台回 list 继续
python phase2_traverse.py --once              # 只扫当前一台(调试/FP2 模式切换)

# 2. AI audit(生成 findings.json;单设备 case 也生成 findings.html)
python phase3_audit_proto.py output/traverse_v8_XXX/

# 3. Build viewer(必须在 audit 之后!findings.json 此时已存在,会被 inline 进 viewer.html)
python phase3_build_viewer.py output/traverse_v8_XXX/

# 4.(可选)同步到 GitHub Pages
# 复制 viewer.html + *.png 到 aqara-audit-reports/<YYYY-MM-DD>/,git push,等 1-2 分钟 build
```

**步骤间依赖**:
- step 2 读 step 1 写的 `traverse_result.json` 或 `all_devices_result.json`
- step 3 同时读 step 1 的 traverse + step 2 的 findings.json — 没有 findings 就 inline 空数组
- 多设备 case 不写 findings.html(被 viewer.html 取代),只产 findings.json + viewer.html

**踩过的坑**(2026-05-14):用户先跑 build_viewer 后跑 audit → viewer.html 里 findings 空 → "only items with findings" filter 没东西 → 误以为 AI 没检出问题。重 build 一次就好。

---

## AI Audit 成本基线(按实测累计)

跟踪每次跑 27 设备 audit 的费用,方便后续改代码 / 换模型时预估变化。

| 日期 | 模型 | BATCH_SIZE | 设备数 | 实际费用 | 备注 |
|---|---|---|---|---|---|
| 2026-05-15 | gemini-2.5-pro(paid) | 60 | 27 | **₩4,876** (~$3.50) | output 占主要,findings ~187 条,全 ko-only |
| 2026-05-19 | gemini-2.5-pro(paid) | 60 | 27 | **₩843**(估算)/ **₩4,548**(实际,含 thoughts tokens) | 三语对比 + rationale 压缩 + 跳 ok + 设备名白名单, findings **593** 条(质量飞跃) |
| 2026-05-19(下午) | gemini-2.5-pro(paid) | 60 | 27 | **~₩3,800**(实际) | + baseline 怀疑 prompt + 短词过滤,findings **487** 条,误判 130→36 (-72%) |

**成本结构**(Gemini 2.5 Pro, 2026 价格):
- input $1.25 / M tokens(prompt 较短,占比小)
- output $10 / M tokens(JSON findings 较长,占比主要)
- 27 设备约 200-400K input + 200-300K output

**节省方向**(改代码前先看这里):
- 调小 `BATCH_SIZE`(60 → 30):API 调用次数翻倍但 input/output 总量不变 → 成本几乎不变
- 简化 SYSTEM_PROMPT(去掉示例):input 略降但 cache hit 率降低 → 总成本可能反而升
- 让 AI rationale 更短(改提示词为"<= 30 字" + 跳 ok findings):output 显著降 → **2026-05-15 已实施,预计 -40~50%**
- 降级模型(Pro → Flash):成本 -80% 但 typo 命中率掉很多
- **三语对比 + 只送可疑句子给 AI**(未来计划 #1):input/output 大幅降,预计 -70% 成本

---

## 三语对比 audit(2026-05-18 加)

未来计划 #1 的实施。zh + en scan 提供 baseline,让 AI 用作 ground truth。

**实施模块**:
- `phase2_traverse.py --locale {zh,en,ko}` — 多 locale 扫描,dir 加后缀 `_zh` / `_en`
- `phase3_align_locales.py` — 按 device_name 匹配设备 + position-based 文本对齐
- `phase3_audit_proto.py --baseline-zh <run> --baseline-en <run>` — 三语 audit
  - 每个 ko unit 附 zh/en baseline 进 AI prompt
  - 收集所有 device_name → ALLOWED_DEVICE_NAMES 白名单(跳过 chinese/english_leak 规则 + 不送 AI)

**完整工作流**(改自单语版):
```powershell
# 1. 三次 scan(用户在 app 内手动切语言)
python phase2_traverse.py                     # ko(无后缀)
python phase2_traverse.py --locale zh         # 中文
python phase2_traverse.py --locale en         # 英文

# 2. 三语对齐 + AI audit
python phase3_audit_proto.py output/traverse_v8_..._ko/ \
  --baseline-zh output/traverse_v8_..._zh/ \
  --baseline-en output/traverse_v8_..._en/

# 3. build viewer + 上传(同单语版)
```

**预期改进**(对比单语):
- 准确率:typo / awkward 类问题命中率 ↑(zh/en 作 ground truth 显式比对)
- 成本:per unit 多 ~50-100 input tokens → input ↑ ~30%,output ↓(更确定不再废输出)→ 总成本预估**与单语持平或略低**,可能 ₩3,500-4,500/次
- 设备名误 flag:消除(白名单)

**容错策略**(graceful degradation):
- 缺 zh/en baseline 某 path → 那行 unit 不带 baseline,AI 单独判(等同 ko-only)
- 缺 zh/en 某 device → 那设备所有 unit 走 ko-only / 部分 baseline
- 三语对齐失败 → 整个 fall back ko-only audit

---

## Corrections tracking + 词典(2026-05-15 加)

`corrections.json`(项目根目录,用户手工维护)记录"已提交给开发的修改建议"和"既成事实保留项",每次 audit:
- **已 verified 的 fix 文本**:从 audit units 里**剔除,不送 AI**(省 token + 不被反向 flag)— 等于自动累积"已批准词典"
- **status='ignored' 的 wrong 文本**(2026-05-19 加):**永不审计**,从 units 里 pre-filter 掉。用于"用了很久不能动"或"AI 建议不可行"的 case(如 동시실행 → 장면 这种用户决定保留)
- **每条 correction 的 observed_state**:`fix_applied` / `not_yet_fixed` / `both_present` / `both_missing`
- **regression alert**:曾 verified 但 wrong 又出现 → 🔴 警告(开发回滚 / 翻译跑掉了)

**工作流**:
1. AI 发现 finding → 你手工 review,确定要改的 → 加进 `corrections.json`(status=`pending`)
2. 把改动提交给开发
3. 下次 audit:终端看到 `⏳ not_yet_fixed` → 开发还没改 / `✅ fix_applied` → 改了
4. 看到 `fix_applied` 后,**手工**把那条 status 改成 `verified`(脚本不自动改,避免误判)
5. 之后 audit 这条 fix 文本被加入词典,AI 不会再花 token 审它

输出在 `findings.json["corrections_report"]` 数组,可被 viewer 显示(viewer 集成 TODO)。

---

## Decision UI(viewer 内决策按钮,2026-05-19 加)

让韩国翻译同事**在 GitHub Pages 在线版 viewer 上直接标记**"要修"或"忽略",不需要懂代码 / 不需要仓库权限。

**用户体验**:
- 每条 finding 卡片下面有两个按钮:`[📋 Add to fix list]` / `[✗ Ignore (legacy)]`
- 点击后存到**浏览器 localStorage**(key 含 RUN_NAME,跨 run 不混)
- 卡片视觉:`pending` 变蓝缘 + ✎ 徽章 / `ignored` 变灰 + ✎ 徽章
- 已经在 corrections.json 里的 finding 显示 `📌 canon-{status}` 徽章,**不再有按钮**(不能改 canonical)
- 底部 sticky 栏:`[N local decisions] [📋 Export] [↩ Clear]`
- Export 弹 modal,有 textarea + `[📋 Copy]` + `[💾 Download .json]`

**协作流程**:
1. 韩国同事打开 GitHub Pages → review → 点 Ignore/Fix 按钮 → localStorage 累积
2. 同事点 Export → 复制 JSON / 下载 .json → Slack/email 发给 engineer
3. Engineer 跑 `python phase3_merge_decisions.py decisions.json`
   - 自动去重(按 wrong 文本)
   - 自动分配下一个 c001/i001 ID(prefix=c for pending, i for ignored)
   - 保护 verified 不被覆盖
   - 写前备份 corrections.json.bak
4. Engineer commit + push corrections.json + 重 build viewer + push viewer.html
5. 同事下次打开 viewer → 看到已处理的 finding 已 📌 标记,不再纠结

**重要约束**:
- Pages 是静态托管,JS **不能写回服务器** — 所以 localStorage + 手动 merge 是唯一可行方案
- 多人协作:每人浏览器独立,各自 export,engineer 集中 merge
- 跨设备:同一台浏览器才能看到自己之前的 decisions(可清 cookie / 换电脑后丢失,所以建议定期 export)

---

## 代码约定

- **不要**调降 `MAX_DEPTH`(=4),会漏页
- **不要**改 `DANGER_KEYWORDS`,加新词请加到 list 末尾
- **不要**移除 `CYCLE-UP / DRIFT-UP` 检测,否则会越级 BACK 把脚本搞乱
- **要**在添加新 marker 时检查它是否可能在 settings 页面作为合法 label 出现
- **要**测试改动时观察 Phase A cleanup 的 attempt 次数和 new=N,这是诊断 RN shell 持久化问题的关键指标
- 修改 phase2_traverse.py 前**先读懂"36 项边界 case"**,每条都是真实失败换来的

---

## 调试技巧

- 跑脚本前确保设备已唤醒、在目标页面
- `phase_b_nav_failed.xml` + `.png` 是 Phase B 找不到 "..." 时自动存的诊断文件
- 日志关键标记：
  - `[OK] N (Xs)` = 成功抓取 N 条文本，等了 X 秒
  - `[NO-OP-SCROLL]` = 内嵌展开/滚动，不递归
  - `[CHOOSER-REVEALED]` = 进入选择器页，capture + 中止
  - `[CYCLE-UP]` = 子页签名是祖先，已访问过
  - `[ABORT-LIST-PAGE]` = 连续 bottom-sheet 中止
  - `[ABORT-DIALOG-LOOP]` = 连续 dialog 中止
  - `[PHASE A] cleanup: ... new=N` = 当前页比主页多 N 条文本（M3 hub 调试关键）

---

*本文档由 Claude 在 claude.ai 网页版生成于 2026-05-11，用于把项目上下文迁移到 VSCode + Claude Code。*