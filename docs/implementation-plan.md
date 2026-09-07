# Connected Gallery MVP — 인터랙션 중심 구현계획

## 현재 제품 기준 — 2026-09-07 개정

[Connect와 사진 맥락 UX](connected-gallery-product-ux.md)가 아래 초기 계획의 제품 범위에 우선한다. **대상 탭 → 관련 사진 → 사진 열기와 동시에 맥락 표시 → 다음 탐색**을 구현 목표로 삼는다. Organize는 에이전트가 열린 사진의 주변 관계를 구성하는 역할이다. 별도 자동 묶음 홈이나 맥락 요청 버튼을 전제하지 않는다.

사진 상세 맥락의 후보 확보·입력·API·사전 준비·화면 상태는 후속 설계다. 아래의 Space 진입점, Same moment 동작, 전역 Organizer와 초기 완료 조건은 당시 계획 이력이며 최신 UX의 완료 여부를 판단하는 기준으로 사용하지 않는다.

### Space 제외와 현재 완료 기준

Space 생성·자동 게시·저장·목록·편집·사용자 쓰기 권한을 MVP 범위에서 제외한다. Organize는 사진 상세의 에이전트 기반 맥락 구성으로 유지하고, 준비된 맥락의 내부 캐시는 Space와 독립적으로 관리한다. Space 재도입은 예정된 후속 작업이 아니며 별도의 사용자 필요를 확인한 뒤 판단한다.

현재 완료 기준은 대상 선택 → 관련 사진 → 사진 열기와 동시에 맥락 표시 → 다음 탐색이다. 근거 있는 맥락, 선택 변경·뒤로 가기 복원, 준비/실패/없음 상태, 3hop에서 다음 선택의 이유와 실제 대기 시간을 검증한다. 최종 Spaces 생성 수·앱 진입·사용자 편집 성공은 완료 조건에서 제거한다.

MVP의 Spaces 노출·모으기·Android 호출과 모듈, 서버 목록·편집·새 Organizer 실행·자동 생성 경로를 제거 또는 차단했다. 기존 대기 작업의 재시작도 차단하며 Space 데이터는 보존한다. [Space 제거 검증](space-removal-validation.md)에 실제 범위를 기록한다. 사진 상세의 새로운 Organize 맥락은 별도 후속 구현이다.

## 초기 구현계획 (이력)

## 제품 계약

See → Tap → Follow → Tap → Follow. Organize는 실제 Gallery의 재사용 맥락 진입점이며 Connect가 핵심이다. 사용자 결정(2026-09-07)에 따라 Time/Timeline은 후속 기능으로 분리한다. 이번 MVP는 Organize + Connect이며 연도 스크럽과 과거 탐색은 완료 조건에서 제외한다. Rediscovery는 결과다.

10개 개발일, 사용자+Codex, Android와 개인 Windows PC, 실제 접근 허용 사진 최대 1,000장. World/3D, Commerce, 공유, 영상, 완벽한 인물 ID, 범용 비서 UI는 제외한다. 완성 OSS 앱/서버는 구조만 참고하고 제품 코드는 직접 작성한다. 범용 라이브러리와 모델은 재사용한다.

## 인터랙션

평소 사진은 깨끗하다. 알려진 영역 탭은 즉시 선택, 빈 곳 탭은 영역 표시, 길게 누르면 후보 또는 수동 영역을 제공한다. 겹치는 대상은 사용자에게 선택권을 준다. 이름을 모르는 얼굴은 이 사람으로 표현한다. 결과 사진을 열고 새로운 요소를 눌러 탐색을 계속한다.

MVP 상태는 SemanticAnchor / FollowDirection / 화면 기록이다. 새 요소 탭은 새 anchor와 hop, Related로 초기화한다. 결과 사진 열기와 방향 변경은 기존 anchor를 유지한다. 뒤로 가기는 사진·맥락·결과·스크롤을 복원한다. 기존 저장 기록의 연도 필터와 해당 결과는 이관 시 해제하며 숨은 필터를 남기지 않는다.

Same moment는 기준 사진의 사건 맥락으로 확장한다. 대상이 모든 결과에 등장할 필요는 없고 고정 시간창으로 사건을 확정하지 않는다. 촬영 시각은 Same moment의 사건 후보 탐색에 사용할 수 있다. 기존 year API와 관련 계약 테스트는 후속 기능을 위한 기반으로 보존하지만 MVP UI에서 연도 선택을 제공하지 않는다.

## 구조

Android: Kotlin/Compose, ViewModel+StateFlow, Hilt, Room, WorkManager, Coil, Telephoto. app 조립, domain 계약, data 어댑터, core-ui 좌표·뷰어, library/spaces/explore 기능 모듈. 기능 간 직접 참조 없음.

PC: Python3.12, FastAPI, SQLite+FTS5, NumPy exact vector retrieval. domain/application/agent_specs/agent_runtime/gallery_tools/adapters/bootstrap. LangGraph는 AgentRunner 뒤에 둔다. ModelGateway, EmbeddingProvider, VisionTools, PhotoRepository, ArtifactStore, SearchIndex를 교체 지점으로 사용한다.

PhotoAsset은 URI·기기·버전·촬영일 출처·회전·위치. Region은 정규화 box·종류·label·evidence. PhotoAnalysis는 설명·OCR·불확실성·coverage·regions. EmbeddingArtifact는 사진·crop·모델 공간·버전. Space는 의미·구성 근거와 사용자 수정. 탐색은 anchor/direction/year/revision, 결과는 확인한 ID와 순서·근거. 실행은 queued/running/completed/incomplete/failed/cancelled.

## Full agentic

Photo Analyst는 실제 사진을 보고 필요한 OCR/grounding/face/embedding 도구를 선택한다. Explorer는 anchor 관찰→도구 선택→후보 관찰→필요시 재검색→결과 제출을 수행한다. Organizer는 전체 근거를 페이지별 확인하고 새로운 재사용 맥락을 발견한다. 고정 카테고리·키워드 분류·고정 가중치 합산·의미 판단 fallback을 금지한다.

입력 사진·OCR·caption은 신뢰하지 않는 데이터다. 이름·관계·ID를 추측하지 않는다. 데이터 검증·실행 예산·좌표 변환·명시적 요청 제약은 결정적인 코드로 보장한다.

기본 VLM gpt-5.4-mini, 대체 claude-sonnet-5 (기존 Proxy). 사진/crop SigLIP2 base, 한국어 설명 e5-small, OCR PaddleOCR, 사물 Grounding DINO tiny, 얼굴 YuNet+SFace. 모델 공간은 분리하고 유사도는 후보 근거일 뿐 최종 순위가 아니다.

Tools: list_photos, inspect_photos, inspect_region, recognize_text, ground_regions, analyze_faces, ensure_embeddings, search_visual, search_text, search_faces, search_location, read_spaces와 역할별 submit. 사진을 확인하지 않은 검색 결과는 저장 거부한다.

## 경계와 API

Android 원본 유지, PC 1,536px 분석 이미지와 근거·인덱스 저장. 작은 글씨에는 고해상도 crop 추가 전달을 지원한다. Proxy 키는 PC .env에만 저장. USB adb reverse로 loopback API 연결. 오프라인은 저장 결과 열람, 새 분석은 연결 후 재개.

GET health/manifest; POST assets/sync; PUT assets/{id}/preview; GET assets/{id}/analysis; POST runs; GET runs/{id}; GET runs/{id}/events?after; POST runs/{id}/cancel; GET spaces; POST feedback; DELETE assets/{id}. 세부 wire contract는 FastAPI OpenAPI와 domain model에 둔다.

동일 탐색의 확정 결과만 캐시, 사진·분석·프롬프트·모델 버전에 따라 무효화한다. 취소된 요청과 오래된 revision이 최신 화면을 덮지 못한다. metadata 변경·권한 철회·삭제 시 파생 데이터 무효화. 작업은 idempotency와 durable 상태를 갖는다.

분석 동시 3, GPU 도구 1, 사용자 탐색 우선. 모델 턴 상한 analyst4/explorer6/organizer30, 도구12/12/100. Explorer 기본 상한90초(공통 설정). 일시 호출 실패1회 재시도와 대체 모델1회 후 실패·부분완료 표시.

## 성능 목표 (실측 전)

사진·탭 p95 300ms, 캐시500ms, 새 탐색 첫 확인결과5초/최종15초 목표, 현재 운영 상한90초. 최초20장3분, 1,000장90분 목표. 모델 준비 시간 별도. 실제 hop 대기와 이탈을 함께 측정한다.

## 10일 일정

D1 계약·AgentRunner·Proxy / D2 Android 뷰어·상태 / D3 동기화·모델·50장 / D4 실제 탭→결과 / D5 연속3hop / D6 방향·뒤로 가기·결과 검증 / D7 Spaces / D8 캐시·취소·삭제·복구 / D9 500~1,000장 성능·품질 / D10 사용자 평가·APK·문서.

## 평가

50장 개발 세트와 분리된 평가 사진을 사용한다. 가족·문서·구매후보·차량·여행·스크린샷, 다년도·유사 인물·작은 한글·회전·누락 시간·중복·무정답 포함. 합성 fixture는 실제 평가와 분리한다.

Find 성공률80%/중앙값30초/기존 갤러리 대비25% 단축, eligible 2초 이상 사진의 tap30%, 새 요소 hop중앙값2, 재사용4점이상70%, P@5사물·텍스트.8/인물.9 목표. 뒤로 가기와 방향 변경은 hop에서 제외한다. 평가 n과 실패를 보고한다.

실행 예산 초과, proxy 중단, 잘못된 ID·좌표, 사진 속 지시문, 권한 철회, 취소 직후 응답, 라이브러리 변경 중 검색을 검증한다. 의미 오류는 후보 재확인·수동 영역·사용자 수정으로 대응한다.

## 완료와 제한

문서·이슈·코드·APK는 자동 생성 가능하다. 실제 사진 품질·1,000장 성능·사용자 재사용 의향은 연결된 사용자 기기와 평가 참여가 필요하며 코드 작성만으로 완료 처리하지 않는다.

## 최신 MVP 완료 조건

1,000장 분석·필수 인덱스, 최종 Spaces 및 앱 진입, 실제 대상별 Connect 관련성, Android 연속3hop·방향 전환·취소·뒤로 가기·스크롤·재연결을 검증한다. API completed만으로 의미 품질을 통과 처리하지 않는다. Time/Timeline 전용 의미 유지·연도 스크럽·과거 탐색은 후속 이슈 CG-15로 분리하며 이번 완료를 막지 않는다. 완벽한 인물 ID도 요구하지 않는다.
