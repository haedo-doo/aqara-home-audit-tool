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

## 累计 36 项边界 case 修复（按发现顺序）

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