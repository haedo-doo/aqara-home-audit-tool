# Aqara Home 한국어 번역 검수 도구

Aqara Home Android 앱의 메뉴를 자동 탐색 → AI 번역 검수 → 정적 viewer 생성하는 파이프라인.

- **언어**: 한국어 (이 문서)
- **개발 문맥 / 엣지케이스 74개**: [CLAUDE.md](CLAUDE.md)
- **현재 검증된 규모**: 27 디바이스, 3 언어(ko/zh/en), 1회 audit ≈ ₩4,000 (Gemini 2.5 Pro paid)

---

## 1. 빠른 시작

### 1.1 환경

| 항목 | 버전 |
|---|---|
| OS | Windows 10/11 (Linux/macOS도 가능) |
| Python | 3.13+ |
| Android | API 28+, 1080×2220 권장 |
| App | `com.lumiunited.aqarahome.play` (한국 store 버전) |
| 디바이스 | USB 디버깅 활성화 + uiautomator2 init 완료 |

### 1.2 의존성 설치

```powershell
pip install -r requirements.txt
```

uiautomator2 첫 사용 시 (한 번만):
```powershell
python -m uiautomator2 init
```

### 1.3 API key 설정 (AI audit용)

**Gemini 2.5 Pro 권장** — Google AI Studio billing 활성화 필요 (paid tier, RPD 제한 없음):

```powershell
# 현재 세션만
$env:GEMINI_API_KEY = "AIza..."

# 영구 (Windows 사용자 환경변수)
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "AIza...", "User")
```

(선택) Anthropic Claude를 fallback으로 쓰려면 `ANTHROPIC_API_KEY`도 같이 설정.

> ⚠ **절대 .py / .json / Git에 직접 키를 쓰지 말 것.** `.gitignore`가 `.env` 등을 차단하지만, 코드에 하드코딩하면 막을 수 없다.

### 1.4 키 확인

```powershell
python -c "import os; print('GEMINI OK' if os.environ.get('GEMINI_API_KEY') else 'MISSING')"
```

---

## 2. 사용법 (전체 흐름)

### 2.1 1회 스캔 — 한국어만

폰을 **장치 목록 탭**(앱 언어를 한국어로)으로 이동시킨 후:

```powershell
python phase2_traverse.py
```

- 27 디바이스 자동 순회, ≈ 1.5h
- 결과: `output/traverse_v8_YYYYMMDD_HHMMSS/` (JSON + PNG + XML + run.log)

#### 옵션
- `--once`: 1 디바이스만 스캔하고 중단 (디버깅 / FP2 다중 모드 분리 스캔용)

#### FP2 다중 모드 스캔

FP2 (재실 센서)는 모드별로 메뉴 구조가 다름 (region sensing / fall detection / sleep / combined). 모든 모드의 번역을 커버하려면 폰에서 **수동으로 모드를 전환한 뒤 매번** `--once`로 스캔:

```powershell
# 모드 A로 전환 → 장치 메인 페이지
python phase2_traverse.py --once
# → output/traverse_v8_..._/  (이 모드의 menu만 포함)

# 모드 B로 전환 → 다시 실행
python phase2_traverse.py --once

# (4 모드 다 스캔하면 4 개 output dir 생성)
```

CLAUDE.md "FP2 multi-mode" 섹션 참고.

#### 느린 폰 (Samsung S8 등)

`phase2_traverse.py` 상단의 `SLOW_DEVICE_MODE = True` 가 기본. 빠른 폰이면 `False`로 바꾸면 스캔 시간 절반.

### 2.2 3개 언어 스캔 (정확도 ↑, 권장)

폰에서 앱 언어를 **수동으로** 바꾼 후 각각 실행:

```powershell
# 한국어로 전환 → 장치 목록 탭
python phase2_traverse.py
# → output/traverse_v8_..._  (suffix 없음 = ko)

# 중국어로 전환 → 장치 목록 탭
python phase2_traverse.py --locale zh
# → output/traverse_v8_..._zh

# 영어로 전환 → 장치 목록 탭
python phase2_traverse.py --locale en
# → output/traverse_v8_..._en
```

> **앱이 언어 전환 후 홈 탭으로 이동**한다. 매번 **장치 목록 탭으로 이동 후** 스크립트 실행.

### 2.3 AI audit

기본 (한국어만):
```powershell
python phase3_audit_proto.py output/traverse_v8_..._ko/
```

**3언어 비교 (정확도 ↑, 권장)**:
```powershell
python phase3_audit_proto.py output/traverse_v8_..._ko/ `
  --baseline-zh output/traverse_v8_..._zh/ `
  --baseline-en output/traverse_v8_..._en/
```

- AI provider 우선순위: `GEMINI_API_KEY` → `ANTHROPIC_API_KEY` → mock(키 없음)
- 결과: `output/.../findings.json`

### 2.4 Viewer 생성 (audit 이후 실행)

```powershell
python phase3_build_viewer.py output/traverse_v8_..._ko/
```

- 결과: `output/.../viewer.html` (self-contained, 브라우저로 바로 열기)
- 우측 sticky export bar의 `[📋 Export]`로 번역팀의 결정을 JSON으로 받을 수 있음

> ⚠ **순서**: scan → audit → viewer. viewer를 audit 전에 빌드하면 finding이 빈 채로 inline됨.

### 2.5 (선택) GitHub Pages 배포

별도 public repo (예: `aqara-audit-reports`)에 `viewer.html` + PNG 복사 후 push.
자세한 절차는 [CLAUDE.md](CLAUDE.md)의 "Web 版作用范围 + 部署方案" 참고.

---

## 3. 번역팀 결정 → 코드로 반영

번역팀이 viewer에서 `[📋 Add to fix list]` 또는 `[✗ Ignore]` 버튼 사용 → Export로 JSON 받기:

```powershell
# JSON 파일을 받았다면
python phase3_merge_decisions.py decisions_from_translator.json

# 또는 클립보드 stdin에서
Get-Clipboard | python phase3_merge_decisions.py -

# 미리보기 (실제 쓰기 안 함)
python phase3_merge_decisions.py decisions.json --dry-run
```

- `corrections.json`에 자동 merge (ID 자동 할당 c001/i001 ...)
- 쓰기 전 `corrections.json.bak`로 백업
- merge 후 viewer 재빌드 (`python phase3_build_viewer.py ...`)하면 finding에 `📌 status` 뱃지 표시

---

## 4. 파이프라인 핵심 흐름 요약

```
[Phase 2 SCAN]                  [Phase 3 AUDIT]                 [REVIEW]
phase2_traverse.py    ──→  phase3_audit_proto.py    ──→   phase3_build_viewer.py
ko / zh / en 별 3회         (3언어 비교 + AI)              → viewer.html
                              │                              │
                              ↓                              ↓
                       findings.json                   번역팀 review
                                                            │
                                                            ↓
                                                  decisions.json export
                                                            │
                                                            ↓
                                              phase3_merge_decisions.py
                                                            │
                                                            ↓
                                                    corrections.json
                                                  (다음 audit 자동 반영)
```

---

## 5. 디렉토리 구조

```
.
├── phase2_traverse.py            # Phase 2: UI scan
├── phase3_audit_proto.py         # Phase 3: AI audit
├── phase3_align_locales.py       # 3언어 정렬 (audit이 import)
├── phase3_build_viewer.py        # viewer.html 생성
├── phase3_merge_decisions.py     # 번역팀 decisions → corrections.json
├── phase3_combine_runs.py        # FP2 다중 모드 등 여러 run을 하나로 머지
├── phase3_glossary_gen.py        # (선택) 고빈도 명사 자동 사전 초안 생성
├── corrections.json              # 수정 추적 + ignored 사전 (수동 관리)
├── requirements.txt              # Python 의존성
├── README.md                     # 이 문서
├── CLAUDE.md                     # 개발 문맥, 74개 엣지케이스, 미래계획
├── output/                       # 모든 스캔 결과 (gitignore됨, 동기화 X)
└── (선택) probe_*.py, diagnose.py, inspect_xml.py  # 수동 디버그 도구
```

---

## 6. 트러블슈팅

### `503 UNAVAILABLE` — Gemini 서버 과부하
- 자동 retry (5→15→45→120초). 4회 실패 시 그 batch만 skip하고 계속 진행.
- 미서부 daytime (한국 밤)에 자주 발생. 한국 새벽/오전이 안정적.

### `429 PerDay` — Gemini 일일 할당량 초과
- 무료 tier (RPD=20) 사용 중이면 즉시 발생. **Google AI Studio에서 billing 활성화** 권장.

### `phase_b_nav_failed.xml` 저장됨
- 디바이스 설정 페이지의 "..." 버튼을 못 찾음.
- 해당 .xml 파일을 보면 layout을 확인 가능. 새 strategy 추가가 필요할 수 있음 (CLAUDE.md 엣지케이스 #14 / #35 참고).

### viewer.html에서 `[📋 Export]` 눌렀는데 아무 일도 안 일어남
- finding을 적어도 1개 이상 `[📋 Add to fix list]` 또는 `[✗ Ignore]`로 표시한 적이 있어야 함.
- localStorage에 저장되므로, 같은 브라우저에서 다시 viewer를 열면 표시가 유지됨.

### 멀티 디바이스 스캔이 1대만 스캔하고 멈춤
- 보통 `[FLOW] cannot return to list, stopping` 로그. App 강제 재시작 recovery가 자동 실행됨.
- 그래도 멈추면 폰에서 Aqara Home 앱이 비정상 상태일 수 있음 — 수동으로 앱 재시작 후 재실행.

---

## 7. 비용 (Gemini 2.5 Pro paid 기준, 27 디바이스)

| 옵션 | 비용 (실측) |
|---|---|
| 한국어만 audit | ≈ ₩4,876 |
| 3언어 + 최적화 (현재 기본값) | ≈ ₩3,800 |

- thinking 토큰 (Pro 내부 추론) 포함. 자세한 분석은 [CLAUDE.md](CLAUDE.md) "AI Audit 비용 기준선" 참고.
- 무료 tier (Flash Lite)는 RPD 20 제한으로 27 디바이스 1회 audit 못 함.

---

## 8. 추가 개발 시

- **반드시 [CLAUDE.md](CLAUDE.md)의 "74개 엣지케이스" 먼저 읽기** — 모든 항목이 실제 실패에서 나옴.
- 코드 컨벤션은 CLAUDE.md "代码约定" 섹션 참고.
- 새 디바이스 추가 후 처음 스캔할 때 `phase_b_nav_failed.xml` 또는 무한 루프 발생 가능 — 그 경우 디바이스 main page XML을 분석하여 새 strategy 추가.
- 새 발견된 "click 후 dialog drift" / "RN inline expansion 오판" 같은 패턴은 우선 `ACTION_BUTTON_EXACT` / `CAPTURE_NO_RECURSE_KEYWORDS` 에 항목 추가로 회피하고, 비슷한 case가 누적되면 heuristic 자체를 손볼 것 (예: case #73의 condition B + items_preserved 가드).

---

## 라이선스 / 내부 사용

내부 도구. 외부 공유 시 API key, 디바이스 ID, 사용자 위치 정보가 포함되지 않았는지 `output/` 디렉토리 확인 후 공유할 것.
