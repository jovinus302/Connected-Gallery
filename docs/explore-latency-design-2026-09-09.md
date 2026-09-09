# 설계 노트 — Connect 탐색 지연 단축 1단계

2026-09-09 · 브랜치 `worktree-explore-latency` (base: origin/main c8182ae) · 등급 **Complex** (다중 모듈, 동시 실행; 위험은 consequential — 잘못된 연결·누락은 사용자 재시도로 복구 가능, 데이터 손실 없음)

핸드오프(`docs/claude-handoff.md`)의 "탐색 시간과 개선 제안" 중 1·2번(전체 사진 OCR 재사용, 후보 검색 병렬 실행 + 이미지·근거 묶음 공급으로 모델 왕복 축소)을 구현하고, 전후를 같은 서버·같은 데이터로 실측한다. 3·4번(사전 연결 준비, 사진 변경 증분 갱신)은 이번 범위 밖이며 §미결정에 후속 메모만 남긴다.

## 컨텍스트 브리프 요약 (근거)

- 기록된 기준 프로파일 (device-ready 서버 DB, 2026-09-08 실행, 서버 요청 생성 → finished):

| 사례 | 총 | 모델 턴 | 모델 합계 | 도구 | 독립 검수 | 그룹화(추정) |
|---|---:|---:|---:|---:|---:|---:|
| ORBIT M2 object (_22) | 24.0s | 3 (2.8/2.8/5.3) | 10.9s | 0.2s | 4.6s | ~8.2s |
| BA217 text (_36) | 28.0s | 3 (2.5/4.5/6.5) | 13.5s | 0.2s | 6.1s | ~8.0s |
| 소라식탁 receipt text (_24, box) | 79.1s | 3 (2.3/3.6/5.8) | 11.7s | **56.3s** (recognize_text 32.4 + 23.4) | 4.2s | ~6.7s |

  세 사례 모두 턴 구조가 같다: 턴1 `search_visual`+`search_text`(각 0.5초 이내) → 턴2 `inspect_photos`(+`recognize_text`) → 턴3 `submit`. 실패 사례 1건에서 `search_text` 13.6초는 텍스트 모델 지연 로드.
- OCR 비용 실측 (이 PC, CPU 추론, PaddleOCR korean, 1024×1536 원본): 모델 로드 8초, **전체 사진 145초**, 40% 크롭 24초, 한 줄 띠 6초. 즉 영역 OCR 1회가 6~25초이고 전체 사진 OCR을 탐색 중에 강제하면 훨씬 더 느리다.
- `gallery_tools/registry.py:recognize_text` → `artifact("ocr-v1", args, models.ocr)`: 캐시 키가 (사진 id, 사진 version, `{photo_id, box}`, 모델 pins)이므로 **같은 사진이라도 box가 다르면 캐시 미스 → 크롭 OCR 재실행**. 반환 좌표는 이미 전체 사진 정규화 xywh(`pixel_box`).
- 분석 시점: 분석가(analyst)가 24/24장 모두 `recognize_text`(box=None, 전체 사진)를 호출해 artifact가 이미 저장돼 있다(`artifacts` 테이블, `pages.res.rec_texts/rec_scores/rec_boxes`). 호스트가 강제한 것이 아니라 에이전트 선택이다.
- 탐색 루프 (`agent_runtime/runner.py`): 초기 메시지 = 요청 JSON + `library_status` + anchor 이미지 블록(초기 사진 전송은 "transport, not semantic tool selection"으로 이미 정당화됨, runner.py:325). `tools` 노드는 한 턴의 도구 호출을 for 루프로 **순차** 실행(`asyncio.to_thread`). 저장소는 RLock, 모델은 종류별 lock — 동시 실행에 안전(`agent_runtime/context.py:_review_both`가 `asyncio.gather` 선례).
- 독립 검수자(`agent_runtime/reviewer.py`): 원본 crop·후보 전체 이미지만 새 문맥으로 받고 검색 도구·이전 추론 없음. 후보 이미지를 디스크에서 다시 읽어 인코딩한다(`image_block`). 그 뒤 `ResultOrganizer`가 그룹 제안·검수 모델 호출(~7~8초).
- 선례: 사진 맥락 계약(`docs/photo-context-contract.md` "후보 확보와 의미 판단")은 원본 전체 이미지와 최대 40장의 메타데이터를 **명시적 초기 후보 공급(prior)** 으로 보내고 "관계의 근거가 아니다"라고 못 박는다.
- 제품 제약: `docs/connected-gallery-product-ux.md:39` "코드는 접근 권한·삭제·버전·스키마·실행 예산을 검증하고, 의미 판단은 에이전트가 수행한다." / `docs/connect-result-revision-contract.md:21` 검수자는 제안자 자료를 받지 않고 예산도 늘리지 않는다. / 핸드오프: "기존 ready/prepared 캐시를 먼저 조사하고 중복 구조를 만들지 않는다", "고정 24장 성공을 일반화의 증거로 취급하지 않는다."

## 변경 명제

### 1. 확정된 의도
- (INTENT.md) 사진이 바뀌어도 동작하는 분석·Connect 구조. 확인 가능한 근거 안에서만 연결하고 단정하지 않는다.
- (핸드오프) 탐색 지연의 주요 원인은 대기·모델 왕복·추가 OCR·검수/그룹화. 이번 작업은 **추가 OCR과 모델 왕복**을 줄인다. 독립 검수는 유지한다. 준비된 결과 1초·새 영역 5~10초는 "제안 목표이지 측정된 보장이 아니다."
- (사용자 답변, 2026-09-09) 범위 = 1·2번 구현 + 전후 비교 측정 ("측정 및 개[선]"으로 해석 — 최종 보고에서 확인 요청). 실행 중 PC 서버 재시작과 유료 탐색 실행 허용. 새 사진은 Claude가 합성 생성.

### 2. 이번 변경의 해석 (선택 / 배제)
- **A. 영역 OCR의 전체 OCR 재사용 (COMMITTED)** — `recognize_text(photo, box)`에서 같은 사진·버전·모델 pins의 전체 사진 OCR artifact(`box=None` 키)가 있으면 그 결과를 재사용한다. 저장된 `rec_boxes`는 전체 사진의 **픽셀 xyxy**이므로, 저장된 전체 이미지 크기(`store.read_image(photo)`의 size — 분석 시와 같은 파일)로 정규화한 뒤 요청 영역과 정규화 공간에서 교차 검사한다(줄 상자 면적의 50% 이상이 영역 안). 반환 형식은 기존과 동일(`full_oriented_photo_normalized_xywh`, `text/score/box`)하고 `source: "full_photo_ocr"`을 덧붙인다. 추가 OCR 추론 없음. 전체 artifact가 없으면 기존처럼 크롭 OCR을 실행한다(전체 OCR을 탐색 중에 강제하지 않음 — CPU에서 145초). **필터 결과가 비어 있으면**(영역 크기와 무관) 크롭 OCR을 1회 실행하고 영역 키로 캐시한다 — 이 경우 비용은 현재와 같다. 탈출구: `RegionArgs`에 `refresh: bool = False`를 추가해 모델이 재사용된 줄이 불완전하다고 판단하면 정확한 크롭 OCR을 요청할 수 있다(도구 설명에 명시; 기본은 재사용). (v2: Codex finding 7·8 반영 — 25% 면적 규칙 삭제, 좌표 공간 명시)
  - 배제 A′: 분석 시 호스트가 전체 OCR을 기계적으로 강제. 이미 분석가가 24/24장에서 수행하므로 새 저장소·강제 단계는 중복 구조다. 도구 선택은 에이전트 몫으로 유지.
  - 배제 A″: 별도 "전체 OCR 좌표 저장소" 신설. 기존 `artifacts`가 좌표를 이미 보존한다.
- **B. 탐색기 첫 턴 전 초기 후보 병렬 공급 (EXPERIMENT)** — 호스트가 첫 모델 호출 전에 스레드로 병렬 실행: 시각(anchor crop 임베딩 → `store.search`), 텍스트(**캐시된** 전체 OCR artifact를 영역으로 필터한 텍스트가 있으면 그 텍스트, 없으면 label — literal FTS + 의미 검색; 초기 공급 단계에서는 OCR 추론을 절대 실행하지 않음), 얼굴(`kind=="person"`일 때 anchor crop의 얼굴 artifact — 있으면 재사용, 없으면 얼굴 검출 1회 — 검출된 얼굴 중 큰 순서로 최대 3개 각각 검색). 채널별 결과를 round-robin으로 합쳐 anchor 제외·중복 제거 후 상위 **N=8**장(`inspect_photos`·검수 배치 상한과 동일)의 전체 이미지 블록(`image_block`, 기존과 같은 메타데이터 포함)과 채널·유사도·literal 일치 여부·인덱스 커버리지 수치를 초기 메시지에 `initial_candidates`로 첨부한다. 각 채널은 독립적으로 try/except — 실패한 채널은 `channel_errors`에 유형명만 기록하고 나머지 채널은 그대로 공급한다("Tool failures mean unavailable evidence, not empty truth"). 문구는 "host-retrieved leads from the selected anchor, not accepted results and not evidence of relation; judge from the images against the anchor; search further with your own strategy if leads are insufficient or coverage is partial; you may submit in your first response". 호스트는 후보를 결과에 넣지 않는다. 초기 공급은 `seen`만 갱신하고 `covered`·`searched`(커버리지·탐색 크레딧)는 갱신하지 않는다 — 탐색 여부는 모델의 도구 호출로만 기록된다. 복구를 위해 초기 사진과 같은 형식(`kind="tool"`, `name="initial_candidates"`, `seen` 목록)으로 이벤트를 남기고, 별도 `initial_candidates` 이벤트에 채널별 건수·오류·소요 시간·N을 기록한다. 환경 변수 `CG_EXPLORE_INITIAL_CANDIDATES`(기본 8, 0이면 비활성)로 즉시 되돌릴 수 있고, 실행 identity 이벤트(`exploration_attempt_identity`)에 N을 기록한다(준비 캐시 키는 바꾸지 않는다 — 캐시된 결과는 검수를 통과한 결과이며 검색 경로와 무관하게 유효).
  - 선례와 경계: `docs/photo-context-contract.md` "후보 확보와 의미 판단" 첫 문장은 호스트가 시각 근접·기본 순서로 고른 초기 후보(메타데이터)를 prior로 공급한다. B는 같은 성격의 prior를 선택 anchor 기반 인덱스 조회로 만들고 이미지까지 붙인다. 같은 절의 "호스트가 후보를 추천하거나 추가하지 않는다"는 계획(`plan_photo_context`) 단계에 대한 규정이며, B는 계획·결과에 후보를 넣지 않는다. 그럼에도 B는 계약 밖의 새 동작이므로 EXPERIMENT로 두고 사용자 확인 대상으로 보고한다. (v2: Codex finding 3·4·5·6·10·11 반영)
  - 가설: 모델이 첫 응답에서 제출해 턴 수가 3 → 1~2로 줄고, 결과 품질(기대 사진 포함·금지 사진 제외)은 기준과 같거나 낫다. 성공 기준·검증은 §5.
  - 배제 B′: 검색+관찰 복합 도구 신설 — 첫 턴 공급으로 대부분 해결되므로 후속 과제.
  - 배제 B″: `same_moment` 방향의 시간 검색을 호스트가 대신 수행 — 시간 창 선택은 모델 판단. 초기 공급은 시각·텍스트·얼굴 채널만이며 방향과 무관하게 적용한다.
- **C. 한 턴 내 도구 호출 동시 실행 (COMMITTED)** — `tools` 노드가 같은 AI 메시지에서 **첫 `submit_*` 호출 앞에 오는 연속 구간**의 호출들만 `asyncio.gather(to_thread…)`로 동시에 실행하고, 그 뒤(첫 submit부터)는 지금처럼 순차 실행한다. 이렇게 하면 순차 실행의 의미(submit 전에 앞선 호출이 모두 끝남, submit 뒤 호출은 submit 뒤에 실행)가 정확히 보존된다. `ToolMessage`는 호출 순서·`tool_call_id`대로 반환한다. 예산 검사(`calls`, `max_calls`, repair 규칙)는 실행 전에 지금과 같은 순서로 판정해 각 호출의 실행/거부를 확정한다. 같은 구간에서 (name, args)가 동일한 호출은 한 번만 실행하고 결과를 각 `tool_call_id`에 복사한다(중복 OCR·중복 읽기 방지). `GalleryTools`의 추적 집합(`seen/covered/searched`)과 `invoke`의 이벤트 스냅숏은 툴킷 내부 `threading.Lock`으로 보호한다(집합 순회 중 변경 예외 방지). (v2: Codex finding 1·2·9 반영 — finding 1의 전제 "순차 실행에서는 모델이 같은 응답의 도구 출력을 보고 제출한다"는 성립하지 않지만, 순서 의미는 그대로 보존한다)
- **D. 실행(run) 내 이미지 블록 렌더링 메모 (COMMITTED)** — `GalleryTools.image_block`이 같은 (photo_id, box, version) 결과의 인코딩 바이트를 run 안에서 재사용한다(`authorize`·`seen` 갱신은 매번 수행; 메모 접근은 락으로 보호, 같은 키의 동시 요청은 한 번만 렌더링). 검수자·그룹화가 같은 후보를 다시 읽고 JPEG 인코딩하지 않는다. 검수자의 입력 내용·격리는 바뀌지 않는다("같은 자료를 다시 수집하지 않게"의 해석을 이 범위로 한정).
- 되돌리기: B는 런타임 플래그로 즉시 비활성. A·C·D는 스키마·데이터 형식·캐시 키를 바꾸지 않으므로 코드 revert만으로 복귀한다(마이그레이션 없음). (v2: finding 15)
- 배제(전체): 인터랙티브 세마포어(1) 변경, 검수·그룹화 병렬화/생략, 턴·도구 예산 수치 변경, 프롬프트 예산 문구 변경, 사전 연결(3), 증분 갱신(4), Android 변경.

### 3. 관찰 가능한 결과
- 전체 OCR artifact가 있는 사진의 영역 `recognize_text`는 OCR 추론 없이 완료된다: `tool_timing.recognize_text.seconds < 0.5`, 결과에 영역 내 줄이 포함된다.
- 영수증 사례(_24 box '소라식탁')의 서버 측 총 시간 79초 → **30초 미만**(OCR 56초 제거).
- 탐색기 모델 턴 수 3 → **1~2** (`model_timing` 이벤트 수), 초기 메시지에 `initial_candidates` 이미지가 포함되고 `initial_candidates` 이벤트에 채널별 건수·소요 시간이 기록된다.
- 세 기록 사례와 신규 사례 10건(기존 24장 5건 + 합성 8장 5건)에서 총 시간 감소, 기대 사진 recall이 기준 이상, 금지 사진 0건.
- **비목표(명시)**: "새 영역 5~10초"는 이번 단계로 달성되지 않는다 — 검수 4~6초 + 그룹화 7~8초가 남으므로 object/text 사례의 현실적 기대치는 24~28초 → 약 17~20초다.

### 4. 불변 조건
- 독립 검수자·그룹화의 입력·격리·예산 불변. 검수 결과가 아닌 사진은 결과에 들어가지 않는다.
- 제출 검증 불변: 관찰(`seen`)한 사진만 제출, anchor 제외, 연도 제한, corpus revision 검사, 빈 결과 근거 검증.
- 모델 턴·도구 호출 예산 수치 불변. 초기 후보 공급은 초기 사진과 같은 전송으로 예산에 계산하지 않되 `initial_candidates` 이벤트로 기록한다.
- 호스트는 후보를 결과에 추가·삭제하지 않고, 고정 규칙으로 의미 판단을 대체하지 않는다(초기 후보는 prior).
- artifact 캐시 키 규율(사진 id·version·args·모델 pins) 유지; 필터 반환 좌표 공간·필드(`text/score/box`) 동일. 사진 version이 바뀌면 이전 artifact는 키가 달라 재사용되지 않는다(기존 규율).
- 검색 결과·초기 후보는 `candidate_ids()`(접근 범위·연도) 안에서만 나온다.
- 동시 실행 도구의 응답 순서·`tool_call_id` 매칭, 오류 리다이렉션(ValidationError 상세/기타 유형명만), `tool_timing`/`tool_error` 이벤트 기록은 지금과 동일.
- 기존 테스트 전부 통과. Android·API 스키마 변경 없음.

### 5. 검증 계획
- 단위 테스트(기존 fake: `tests/test_agent.py:ScriptedGateway`, `tests/test_contracts.py:store`, `tests/test_indexing.py:Models`):
  1. OCR: fake `ocr()` 호출 횟수 계측. 전체 OCR 1회 저장 후 영역 요청 2건 → 추가 호출 0, 영역 밖 줄 제외, 좌표 공간 유지. 전체 artifact 없음 → 크롭 OCR 1회(기존 동작). 작은 영역·빈 필터 → fallback 크롭 OCR 정확히 1회, 두 번째 같은 요청은 캐시.
  2. 초기 후보: 벡터가 있는 저장소에서 explorer 실행 → 첫 HumanMessage에 `initial_candidates`와 후보 이미지 블록(anchor 제외, ≤N), `toolkit.seen`에 후보 포함, 첫 응답 submit 성공, `calls`/`turns` 예산 소모 없음, `initial_candidates` 이벤트 기록. `CG_EXPLORE_INITIAL_CANDIDATES=0`이면 첨부·이벤트 없음. 벡터 없음 → 빈 후보 + 커버리지 정보.
  3. 병렬 도구: 두 도구 fake가 각 0.3초 sleep → 한 턴 wall time < 0.5초, `ToolMessage` 순서·id 유지; submit과 섞인 배치에서 submit이 마지막에 실행; 예산 초과 응답 동일.
  4. 메모: 같은 run에서 같은 사진의 `image_block` 2회 → 디스크 읽기 1회(fake store 계측), 다른 box는 별도.
- 회귀: `pytest -q` 전체 (device-ready venv, worktree에서 `pythonpath=server`).
- 실측(`scripts/benchmark-explore-latency.py`, 같은 서버·같은 데이터): 합성 8장을 먼저 등록·분석 완료 → **변경 전** 12건 실행(완료) → 서버에 변경 코드 배포·재시작 → **변경 후** 같은 12건을 기본 N=8로 실행 → ablation으로 `CG_EXPLORE_INITIAL_CANDIDATES=0`(A+C+D만)에서 6건 실행. 비교 지표: 총 시간, 턴 수, 모델 시간(턴1 지연 증가 여부 포함), `recognize_text` 시간·횟수, 검수 시간, 기대 recall·금지 사진·예상 밖 사진. `prepared_cache_hit` 실행과 모델 프록시 타임아웃(`Model unavailable`) 실패는 비교에서 제외하고 건수만 보고한다. 결과는 `docs/explore-latency-benchmark.json`(집계)과 `work/`(비공개 상세).
- 반증 기준(EXPERIMENT B): 같은 사례 쌍에서 (i) 모델 턴 수의 중앙값이 N=0 대비 1 이상 줄지 않거나, (ii) 금지 사진이 1건이라도 결과에 들어가거나, (iii) 기대 recall이 기준보다 낮아진 사례가 2건 이상이면 가설 기각 → B를 기본 비활성(N=0)으로 두고 보고한다. A의 반증: 전체 artifact가 있는 사진의 영역 `recognize_text`가 0.5초를 넘거나 재사용 결과에 영역 밖 줄이 섞이면 실패.
- 일반화 한계(명시): 측정 대상은 이 PC·이 갤러리(합성 캡처 32장)·현재 모델 프록시다. 결과는 이 조건의 전후 비교이지 다른 사진·기기·모델에서의 보장이 아니다(핸드오프 "고정 24장 성공을 일반화의 증거로 취급하지 않는다"). (v2: Codex finding 13·14 반영)
- 실행 증거는 리뷰 대상 최종 리비전에서 다시 얻는다(코드가 바뀌면 단위·회귀 재실행).

### 6. 실행 증거
- 구현 리비전(worktree-explore-latency, 미커밋 diff 9파일 +409/−73 + 신규 테스트 파일): `pytest -q` 전체 **704 passed, 0 failed (167s)** — 기준 694 + 신규 10. 구현자의 1차 실행에서 `test_compatible_model_profile` 1건이 Windows 임시 디렉터리 rename `PermissionError`로 실패했으나 최종 리비전 재실행에서 재현되지 않음(flake).
- 신규 테스트(`tests/test_explore_latency.py`, 10개): OCR 재사용·영역 필터·fallback·refresh·전체 artifact 없음(비정방형 이미지), 초기 후보 블록·seen·이벤트·예산 불변·N=0·벡터 없음, 동시 실행 순서·중복 병합·submit 순서·예산 초과 메시지, image_block 메모.
- 구현 이탈(구현자 보고, 수용): `initial_candidate_limit`은 identity 비교(`load_prior_attempt_feedback`, prepared revision)에 영향을 주지 않도록 별도 이벤트 `exploration_attempt_initial_candidates`로 기록; 추적 집합 락은 재진입 필요(`list_photos`→`coverage_status`)로 `RLock`; 초기 후보가 0건이면 복구용 `tool` 이벤트를 남기지 않음(측정 이벤트는 항상 기록). `AGENT_SPEC_VERSION` 18→19로 준비 캐시 네임스페이스가 바뀜(프롬프트 변경의 문서화된 결과).
- 최종 리비전(v4) 빌드 게이트: `pytest -q` 전체 2회 — 각각 **707 passed, 2 failed**; 실패 2건은 모두 `tests/test_mixed_model_package.py::test_post_staging_tamper_is_rejected_before_any_archive_or_source_mutation[...]`의 Windows `PermissionError: [WinError 5]`(스테이징 임시 디렉터리 `os.replace`) — 이번 변경이 건드리지 않은 파일이며 같은 파일을 격리 실행하면 통과(`test_mixed_model_package.py + test_compatible_model_profile.py + test_explore_latency.py` = 52 passed). 오늘 전체 실행 5회 중 3회에서 나타난 기존 flake(기준 코드 실행에서는 0/1회, v2 게이트 0/1회). 신규 테스트 15개는 전부 통과.
- 변경 후 실측: (아래 §변경 후 실측에 기록)

### 7. 미결정 사항
- 초기 후보 수 N=8과 fallback 크롭 OCR 조건(면적 < 25%, 필터 결과 없음)은 가설 — 실측 후 조정.
- 합성 벤치마크 사진 8장을 측정 후 서버 갤러리에 남길지 삭제할지(사용자 결정; 기본은 유지, 삭제 명령은 보고에 첨부).
- 그룹화(7~8초)·검수(4~6초)의 단축은 별도 명제 필요(예: 검수 중 그룹 제안 병렬 시작) — 이번 범위 밖.
- 5~10초 목표 달성 경로는 3번(사전 연결)이며 이번 실측 결과가 그 설계의 입력이 된다.

## 통합 지점
- `server/connected_gallery/gallery_tools/registry.py`: `recognize_text`(필터·fallback), `artifact`(전체 artifact 조회 헬퍼), `image_block`(run 메모), 초기 후보 검색 헬퍼(`initial_candidates(anchor)`).
- `server/connected_gallery/agent_runtime/runner.py`: 초기 메시지 구성(`initial_candidates` 첨부·이벤트), `tools` 노드 동시 실행.
- `server/connected_gallery/agent_specs/prompts.py`: explorer 프롬프트에 초기 후보의 성격(leads) 한 단락 추가. `agent_specs/versions.py`의 spec 버전 증가(프롬프트 변경 시 진행 중 실행 재개 방지 규칙).
- `tests/`: 위 4종 신규 + 기존 통과.
- `scripts/benchmark-explore-latency.py`, `scripts/create-benchmark-captures.py`, `docs/explore-latency-benchmark-cases.json`, `docs/explore-latency-benchmark.json`.
- 배포: device-ready 서버는 editable install이라 자동 반영되지 않음 → `scripts/stop-pc-server.ps1` 후 이 worktree의 `server/`를 `PYTHONPATH` 앞에 두고 같은 `.runtime` 데이터로 uvicorn 재시작(터널은 측정에 불필요; 에뮬레이터는 adb reverse).

## 의도 이탈 지점
- 제안 1 "전체 사진 OCR과 좌표를 사전 저장": 새 저장 단계 대신 **기존 분석 시 artifact 재사용**으로 구현(핸드오프 "중복 구조 금지"와 일치). 분석가가 OCR을 생략한 사진은 탐색 시 종전과 같은 크롭 OCR 비용을 낸다.
- 제안 2 "독립 검수는 유지하되 같은 자료를 다시 수집하지 않게": 검수자 입력을 바꾸지 않고 **렌더링 메모**로만 해석. 검수자에게 탐색기의 근거를 넘기는 해석은 계약 위반이라 배제.
- 성능 목표 5~10초: 이번 단계 비목표로 선언(§3).

## 가정 (사용자 부재 시 판단)
- 범위 답변 "측정 및 개"는 "측정 및 개선"(1·2번 구현 + 전후 측정)으로 해석했다.
- 합성 사진을 실행 중 서버 갤러리에 추가한다(device_id `benchmark-explore-latency`, id `bench-explore-NN`). Android 앱은 기기 사진만 목록에 보이므로 서버 전용 사진은 Connect 결과로만 나타날 수 있다 — 측정 후 유지/삭제를 사용자에게 묻는다.

## 변경 전 실측 (기준, 2026-09-09, 이 PC·같은 서버)

| 사례 | 상태 | 총 | 턴 | 모델 s | OCR s | 검수 s | recall | 금지 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| new-bookstore-name | completed | 22.3 | 4 | 12.8 | 1.3 | 2.2 | 1.0 | 0 |
| new-book-title | completed | 20.7 | 4 | 11.9 | 1.2 | 2.3 | 1.0 | 0 |
| new-train-number | completed | 18.9 | 3 | 8.5 | 1.1 | 3.0 | 1.0 | 0 |
| new-hotel-name | completed | 27.1 | 6 | 17.2 | 0 | 3.3 | 1.0 | 0 |
| new-distractor-empty | incomplete(빈 결과 검수 insufficient) | 10.3 | 3 | 10.0 | 0 | – | – | 0 |
| existing-m2-object | failed(Model unavailable TimeoutError) | 45.9 | 3 | 14.6 | 0 | – | – | 0 |
| existing-ba217-text | failed(Model unavailable TimeoutError) | 38.2 | 2 | 7.4 | 0 | – | – | 0 |
| existing-receipt-text (같은 box → OCR 캐시 적중) | completed | 34.7 | 3 | 13.8 | 0 | 7.2 | 1.0 | 0 |
| existing-lighthouse-text | completed | 26.4 | 4 | 12.4 | 0.9 | 5.0 | 1.0(_42 보정) | 0 |
| existing-nightwalk-text | completed | 60.1 | 4 | 16.0 | 1.9 | 25.5 | 1.0 | 0 |

| existing-m2-object (재실행) | completed | 22.5 | 3 | 13.1 | 0 | 5.2 | 0.0 | **1** (ORBIT M1 오연결) |
| existing-ba217-text (재실행) | completed | 22.5 | 3 | 11.0 | 0 | 3.9 | 0.5 | 0 |
| existing-receipt-text-newbox | completed | 39.1 | 4 | 17.5 | 0 (모델이 OCR 미호출) | 8.3 | 1.0 | 0 |
| existing-menu-text-newbox | completed | 59.3 | 3 | 16.9 | 4.5 | 8.0 | 1.0 | 0 |

관찰: (1) 같은 box 재선택은 artifact 캐시에 적중해 OCR 0초; 720×1280 캡처의 작은 영역 OCR은 0.9~1.9초, 1024×1536 메뉴판 영역은 4.5초; 탐색기가 OCR을 호출할지는 매 실행 모델 선택이라 같은 사례에서도 0~2회로 달라진다. (2) 모델 턴은 2~6회. (3) 결과가 5장이면 **그룹화**가 `group_proposal` + 멤버별 `group_member_review` 모델 호출(각 ~1초) + 재제안(2라운드)으로 13~30초를 차지한다(menu-newbox: 검수 종료 29.6초 → 결과 59.2초). 이는 이번 범위 밖이며 후속 명제 후보다(멤버 검수 배치·병렬화). (4) 기준에서도 오연결 1건(M2 → ORBIT M1)과 recall 손실이 있어 품질 비교는 기준 대비 상대 평가다.

## 변경 후 실측 (같은 서버·같은 데이터, worktree 코드 배포, `CG_EXPLORE_INITIAL_CANDIDATES` 기본 8)

| 사례 | 전 총 | 전 턴 | **후 총** | **후 턴** | 후 모델 s | 후 OCR s | 후 검수 s | 후 recall (전) | 금지 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| new-bookstore-name | 22.3 | 4 | 45.9 † | 3 | 20.1 | 0 | 3.1 | 1.0 (1.0) | 0 |
| new-book-title | 20.7 | 4 | **14.4** | 1 | 5.4 | 0 | 3.8 | 1.0 (1.0) | 0 |
| new-train-number | 18.9 | 3 | 19.5 | 2 | 11.2 | 0 | 2.4 | 1.0 (1.0) | 0 |
| new-hotel-name | 27.1 | 6 | **13.4** | 1 | 4.3 | 0 | 2.5 | 1.0 (1.0) | 0 |
| new-distractor-empty | 10.3 | 3 | 15.9 | 3 | 14.9 | 0 | – | 빈 결과·incomplete (동일) | 0 |
| existing-m2-object | 22.5 | 3 | 31.3 | 2 | 14.4 | 0 | 7.2 | **1.0 (0.0, 전에는 M1 오연결)** | 0 (전 1) |
| existing-ba217-text | 22.5 | 3 | 30.7 ‡ | 0 | 0 | 0 | – | 실패(Model unavailable) | – |
| existing-receipt-text | 34.7 | 3 | 32.7 | 1 | 8.9 | 0 | 7.0 | 0.67 (1.0) | 0 |
| existing-lighthouse-text | 26.4 | 4 | 33.2 | 1 | 6.5 | 0 | 6.7 | 1.0 (1.0) | 0 |
| existing-nightwalk-text | 60.1 | 4 | **18.9** | 1 | 6.1 | 0 | 5.8 | **0.33 (1.0)** — 5장 제출·검수 1장 수용 | 0 |
| existing-receipt-text-newbox | 39.1 | 4 | **33.2** | 1 | 8.6 | 0 | 7.6 | 1.0 (1.0) | 0 |
| existing-menu-text-newbox | 59.3 | 3 | **30.7** | 1 | 7.4 | 0 (전 4.5) | 6.9 | 1.0 (1.0) | 0 |

† 서버 재시작 직후 첫 실행: `initial_candidates` 16.8초 = 임베딩 모델 콜드 로드(전 측정에서는 실패 사례의 `search_text` 13.6초로 나타났던 비용). 워밍업 후 재실행 예정. ‡ 모델 프록시 타임아웃(전 측정에서도 같은 사례가 1회 실패) — 재실행 예정.

구조 관찰(후): `initial_candidates` 0.16~0.17초(워밍 상태) → 1턴 5~9초(이미지 8장 첨부로 턴당 시간은 2~3배) → 검수 2.4~7.6초 → 그룹화 3~16초(멤버 수 비례). 1턴 실행의 총 시간 13~33초 중 검수+그룹화가 절반 이상.

첫 N=0 ablation(6건)은 직전 N=8 결과의 **준비 캐시 적중**(0.03~0.05초, 0턴)으로 무효 — 앵커 box를 0.002 이동(jitter)해 캐시 키를 바꾼 재측정을 진행했다(`--jitter` 옵션 추가; 재시작마다 워밍업 실행 1건을 먼저 돌려 콜드 로드를 제외).

### Ablation — 같은 최종 코드, 워밍 상태, jitter 적용 (N=0: A+C+D만 / N=8: 초기 후보 포함)

| 사례 | N=0 턴 | N=0 총 | N=0 recall(장수) | N=8 턴 | N=8 총 | N=8 recall(장수) |
|---|---:|---:|---|---:|---:|---|
| new-bookstore-name | 7 | 24.2 | 0.0 (0) | 1 (재실행) | **14.9** | 1.0 (1) |
| new-book-title | 6 | 39.3 | 1.0 (1) | 1 | **14.4** | 1.0 (1) |
| new-train-number | 3 | 40.4 | 0.0 (0) | 2 | **19.5** | 1.0 (1) |
| existing-nightwalk-text | 3 | 69.6 | 1.0 (4) | 1 / 2 (재실행) | **18.9 / 23.5** | **0.33 (1) / 0.33 (1)** |
| existing-receipt-text-newbox | 3 | 35.3 | 1.0 (4) | 1 | 33.2 | 1.0 (5) |
| existing-menu-text-newbox | 3 | 32.8 | 0.67 (3) | 1 | 30.7 | 1.0 (5) |
| existing-ba217-text (재실행) | – | – | – | 1 | 25.0 | 1.0 (2) |

- 턴 수 중앙값: N=0 **3** → N=8 **1** (반증 기준 i 통과). 금지 사진: N=8 전 실행 0건(기준 ii 통과). 총 시간: 6쌍 중 5쌍 개선(−30~−73%), 1쌍 비슷(receipt-newbox).
- recall: N=8에서 기준(변경 전)보다 낮아진 사례 **2건**(existing-nightwalk-text 1.0→0.33 두 번 연속, existing-receipt-text 1.0→0.67) → **반증 기준 iii에 해당 → 사전 등록한 규칙대로 B는 기본 비활성(N=0)으로 두고 사용자 결정으로 넘긴다.** 단, 같은 코드의 N=0 ablation도 기준 대비 recall 하락 3건(bookstore 0, train 0, menu 0.67)을 보여 실행 간 변동이 크다 — receipt-text의 하락은 변동 범위 안일 수 있으나 nightwalk의 하락은 2회 연속 재현돼 실제 신호로 본다(여러 사진이 관련된 행사 사례에서 모델이 초기 후보만 보고 제출하고 추가 검색을 하지 않음).
- 콜드 스타트: 서버 재시작 후 첫 탐색은 임베딩 모델 로드 비용(16.8초)이 초기 후보 단계에 잡힌다(전 코드에서는 첫 `search_text`에 13.6초로 잡혔던 같은 비용). 비교에서 제외.
- 실행 비용(이 시점): 유료 탐색 총 41회(전 14, 후 12, 무효 ablation 6 중 유료 1, jitter ablation 6, 재실행 3, 워밍업 2).

### v3 수정(label 우선 텍스트 채널) 후 재측정 — 최종 리비전, N=8, 워밍 상태, jitter 0.006

| 사례 | 총 | 턴 | 모델 s | OCR s | 검수 s | recall(장수) | 금지 | 비교 |
|---|---:|---:|---:|---:|---:|---|---:|---|
| existing-nightwalk-text | 27.7 | 1 | 6.7 | 0 | 6.2 | **1.0 (4)** | 0 | 전 60.1s/4턴/1.0(5), v2 18.9~23.5s/0.33(1) |
| new-bookstore-name | 17.4 | 1 | 7.9 | 0 | 3.6 | 1.0 (1) | 0 | 전 22.3s/4턴 |
| existing-receipt-text | 35.3 | 2 | 13.0 | 0 | 6.6 | **1.0 (5)** | 0 | 전 34.7s/3턴/1.0, v2 32.7s/0.67 |
| existing-menu-text-newbox | 32.7 | 1 | 7.2 | 0 | 6.0 | 1.0 (5) | 0 | 전 59.3s/3턴/OCR 4.5s |

(nightwalk 2회째 반복은 같은 jitter 키의 준비 캐시 적중이라 표본에서 제외.) 야간산책의 leads 8장이 이번에는 '제주 빛산책' 사진들을 포함했고 모델이 4장을 제출·검수 전부 수용.

### 최종 리비전(v4: Codex finding 3·4 수정 후) 스모크 — N=8, jitter 0.008, 재시작 직후

| 사례 | 총 | 턴 | 초기 후보(검색/렌더) | 검수 | 결과 |
|---|---:|---:|---|---:|---|
| existing-nightwalk-text (콜드) | 45.3 | 1 | 16.2s (16.1 콜드 로드 / 0.11) | 7.0s, 4/4 수용 | **incomplete** — 그룹화 단계의 독립 검토가 `anchor_supported=false`("Original selected source was not supported")로 그룹화 실패. 이 단계는 이번 변경이 건드리지 않은 기존 코드(`organizer.py`)이며, jitter로 이동한 crop에 대한 검토 모델의 판단 변동으로 본다. 탐색기·후보 검수는 정상(recall 계산상 0.67 = 4장 중 기대 2장 + acceptable 1장 + _39). |
| existing-menu-text-newbox (워밍) | 33.4 | 1 | 0.44s (0.33 / 0.11) | 8.2s, 5/5 | completed, recall 1.0 |

v4 변경(관찰 크레딧 시점·이벤트 시간 필드)은 검색·제출 동작을 바꾸지 않으므로 v3 재측정 표를 B 판정 근거로 유지하고, 이 스모크는 최종 리비전의 동작 확인용이다.

**EXPERIMENT B 판정**: (i) 턴 중앙값 N=0 3 → N=8 1 ✔ (ii) 금지 사진 0 ✔ (iii) recall — v2 N=8 12건 중 기준보다 낮은 사례 2건 → v3(label 우선)에서 그 2건을 포함한 4건만 재측정해 모두 1.0 회복; **나머지 8건은 v3 코드로 재측정하지 않았다**(유료 실행 예산). 따라서 "최종 리비전 12건 전부 통과"는 입증된 것이 아니라 v2 결과(8건: 하락 없음) + v3 재측정(4건: 회복)의 조합이며, label 우선 질의가 나머지 8건의 leads를 바꿨을 가능성은 미측정이다(Codex 재검 finding 1 이견). 판단: 측정된 범위에서는 기준을 만족하므로 **기본 N=8 유지**하되, 전체 12건 재측정(유료 약 13회)으로 확정할지, N=0 기본으로 보수적으로 둘지는 **사용자 결정**으로 넘긴다. 일반화 한계는 §5 그대로(이 갤러리·이 모델·이 PC의 단일 표본 비교).

- 실행 비용(최종): 유료 탐색 총 47회 — 사용자가 허용한 "전후 각 6~10회"를 넘겼다(설계 리뷰가 요구한 ablation, 캐시 적중으로 무효가 된 ablation 재실행, v3 수정 재검증). 최종 보고에 명시.

## Codex Sol 최종 diff 리뷰 (2026-09-09, v2 diff 기준, 세션 재검 예정) — 판정 FAIL / EXPERIMENT → 처리

설계 리뷰 finding 1·2·3·6·7·8·9·10·11 이행 확인(HONOURED). 4축 검토에서 검수·그룹화 입력 불변, 미선언 정책 없음 확인. 새 finding과 처리:

| # | 심각도 | finding | 처리 |
|---|---|---|---|
| 1 | major | v2 실측에서 recall 하락 2건으로 B 기각 기준 충족인데 기본값이 N=8 | v3(label 우선) 재측정에서 두 사례 모두 recall 1.0 회복, 기준 (i)(ii)(iii) 통과 → 사전 등록 규칙의 "새 측정으로 기준 통과" 경로로 N=8 유지. 같은 Codex 세션에 증거 제출해 재검. |
| 2 | major | 선언한 관찰 결과 "영수증 79초 → 30초 미만"이 미달(같은 box 32.7초, 새 box 33.2초; 메뉴판 새 box 30.7초) | **미달 인정.** 잔여 시간은 검수 4~8초 + 그룹화 3~16초(범위 밖). 관찰 결과를 낮추는 개정은 사용자 확인 사항이므로 개정하지 않고 미달로 보고 → 사용자 결정(수용 또는 후속 명제). |
| 3 | minor | `image_block`이 메타데이터 블록 구성 전에 `seen`을 추가해, 구성 실패 시 관찰 크레딧만 남을 수 있음 | bounded fix: 블록 구성 성공 후에만 `seen` 추가 + 테스트. |
| 4 | minor | `initial_candidates.seconds`가 이미지 렌더링 시간을 제외 | bounded fix: 총 시간(`seconds`) + `retrieval_seconds`/`render_seconds` 분리 기록. |
| 5 | minor | 벤치마크 같은 태그 재실행이 집계를 덮어씀; 집계 JSON이 diff에 없음 | 수정(태그 내 누적) + 집계를 비공개 기록 전체에서 재생성해 커밋에 포함. |

### Codex Sol 재검 (같은 세션, 최종 리비전 diff) — 판정 **FAIL 유지** / A·C·D COMMITTED, B EXPERIMENT

- finding 3·4·5: RESOLVED(코드·테스트로 확인). finding 1: DISPUTED — v3 재측정이 12건 중 4건이라 전체 통과를 증명하지 못함(위 판정 문단에 반영). finding 2: NOT RESOLVED — 정직하게 미달로 보고됐으나 선언한 관찰 결과가 미달이므로 FAIL; 목표를 낮추는 PROPOSITION CHANGE는 사용자 확인이 선행돼야 함(이 노트의 판정 우선순위 FAIL > PROPOSITION CHANGE와 일치).
- 새 minor 결함: 같은 태그·사례를 별도 호출로 다시 돌리면 `repeat`가 0부터 다시 시작해 (id, repeat)가 중복 → 벤치마크 스크립트가 기존 기록 수만큼 offset을 두도록 수정, 집계는 기록 순서로 재번호.
- 리뷰 시점에 미반영이던 증거: 최종 빌드 게이트(707 passed + 기존 flake 2), 최종 스모크 2건(§최종 리비전 스모크).

**최종 상태 요약(오케스트레이터)**: 코드 결함 finding은 모두 해소. 남은 FAIL 사유는 (a) 선언 결과 "영수증 <30초" 미달(30.7~35.3초)과 (b) B의 최종 리비전 전체 재측정 부재 — 둘 다 사용자 결정 사항(목표 개정 수용 여부, 추가 유료 측정 여부, 기본 N). 이 두 항목이 결정되면 같은 Codex 세션에서 판정만 갱신하면 된다.

## 개정 이력
- v1 2026-09-09 초안.
- v5 2026-09-09 Codex 재검 반영: 판정 문단 정정(4건만 재측정), `repeat` 중복 수정, 최종 상태 요약.
- v4 2026-09-09 Codex 최종 diff 리뷰 반영: finding 3·4 bounded fix, 5 수정, 1은 v3 재측정 증거로 해소, 2는 미달로 사용자 결정 이관(관찰 결과 문구는 낮추지 않음).
- v3 2026-09-09 실측(ablation) 후 B의 텍스트 채널 개정: 영역 OCR 줄에서 만든 질의가 짧은 흔한 토큰("제주")이 되어 관련 없는 leads 8장을 공급하고 모델이 그대로 제출한 사례(existing-nightwalk-text, 2회 재현) → 질의를 **label 우선**(label literal+semantic 먼저, OCR 텍스트는 label과 다를 때만 보조)으로 바꾸고 leads 문구를 "유사도·키워드 적중이며 다수가 무관할 수 있음, 이미지에서 선택 의미를 확인한 lead만 제출, 없으면 직접 검색"으로 강화. 관찰 가능한 결과·불변 조건은 그대로(낮추지 않음). 재측정 후 기본 N 결정: 반증 기준 iii를 여전히 만족하지 못하면 기본 N=0.
- v2 2026-09-09 Codex Sol 설계 리뷰(REVISE, finding 15건) 반영: A의 25% 면적 규칙 삭제·`refresh` 탈출구·좌표 정규화 명시(7·8); B의 캐시 전용 텍스트 채널·채널별 실패 격리·얼굴 규칙·복구용 tool 이벤트·커버리지 미갱신·N 기록·선례 경계(3·4·5·6·10·11); C의 첫 submit 앞 구간만 동시 실행·중복 호출 병합·추적 집합 락(1·2·9); 되돌리기 서술(15); ablation·반증 기준·일반화 한계(13·14). finding 1의 전제는 기각(순차 실행도 같은 응답의 도구 출력을 모델이 보지 못함)하되 순서 의미는 보존. finding 12(후보 스냅숏 불일치)는 현재 순차 도구와 같은 위험이라 기록만.
