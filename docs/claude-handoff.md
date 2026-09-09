# Claude 인수인계 — 2026-09-09

## 사용자 의도와 다음 작업

먼저 INTENT.md와 docs/photo-context-contract.md를 읽는다. 사용자는 고정 샘플에만 맞춘 앱이 아니라 사진이 바뀌어도 동작하는 분석·Connect·Organize 구조를 원한다. Connect는 선택 대상, Organize는 열린 사진 전체를 출발점으로 한다. 현재 사용자 요청은 샘플/APK 테스트 브랜치를 main에 머지하고 인수인계 맥락을 정리하는 것이다. 아래 성능 개선은 제안 단계이며 아직 구현하지 않았다.

## 반영한 작업

- 6725f04: scripts/install-device.py와 설치 실패/해시 불일치/전송 실패 테스트. base64로 전송하고 기기 SHA-256 비교 후 pm install -r, 임시 APK 정리. scripts/connect-device.ps1에서 재사용.
- 4ee0bae: 디버그 자산에 가상 캡처·문서·일상·여행 사진 24장. SampleGalleryImporter와 ‘샘플 사진 추가’ 버튼. MediaStore에 복사하며 중복 방지와 본인 소유 미완료 항목 복구. 기존 개인 사진을 덮어쓰지 않는다. release 자산에는 샘플 없음.
- f322b5b: PC 모델 설치 후 실제 분석·탐색 검증 증거. 이후 최신 origin/main의 INTENT.md를 충돌 없이 통합했다.
- 사진 원본과 생성 프롬프트·캡처 생성 스크립트는 레포에 있다. 프롬프트와 기대 관계는 분석 입력으로 보내지 않는다. 완성 APK, 모델 가중치, 가상환경, 인증 정보는 Git에 넣지 않는다.
- 전체를 한 번에 수행하는 자동 E2E 테스트는 아직 없다. 기기 조작과 결과 검수 일부는 직접 수행했다.

## 검증된 사실과 한계

- 기존 Android 빌드·29개 단위 테스트·lint 통과 기록: docs/sample-apk-proposition.md. 이번 머지 직전 설치 테스트 4개를 재실행해 통과했다. Android 전체 빌드는 이번 머지에서 반복하지 않았다(통합된 원격 변경은 문서뿐).
- 모델 실제 추론 6종 통과: docs/pc-model-smoke-result.json.
- 사진 24/24 분석·검색 준비 완료, 전체 텍스트 인덱스 24, 영역 인덱스 68/68, 누락 0.
- 실제 Connect: ORBIT M2 캡처→설명서 1장, BA217 항공 예약→일정/탑승권 2장, 에뮬레이터 영수증 ‘소라식탁’ 선택→메뉴판/식당 캡처 3장. 최종 결과는 docs/pc-sample-analysis-result.json.
- M2 실물 사진은 최종 연결에서 누락됐다. 동일 상호의 다른 지점은 같은 문자열 관계로 포함됐다. 동일 지점·물리적 동일 제품으로 검증한 것이 아니다.
- 영수증 자동 주변 맥락은 두 번 모두 RuntimeError: Context wording review lacked complete exact-field evidence. agent_runtime/context.py의 _wording_review에서 excerpt_not_in_field. 검수 인용문이 해당 필드의 실제 부분 문자열이 아니어서 거부됐다. 게이트를 완화하지 않았고 자동 맥락 성공으로 보고하지 않았다.
- 분석 진행 중 시작한 탐색 1건은 corpus 갱신으로 무효화됐다. 전체 분석 완료 후 재실행은 성공했다. 초기 작업 복구 시 종료된 작업 제출 오류 2건도 관찰. 최종 분석은 모두 완료.
- 검증 기기는 emulator-5554다. 실제 휴대폰 검증으로 표현하지 않는다.

## 탐색 시간과 개선 제안

서버 요청 생성부터 finished 이벤트까지 측정했다. 앱 렌더링 시간은 포함하지 않는다.

| 사례 | 전체 | 특이사항 |
|---|---:|---|
| M2 제품 | 24초 | 실제 실행 약 24초 |
| BA217 | 52초 | 선행 탐색 대기 약 24초, 실행 약 28초 |
| 소라식탁 영수증 | 79초 | 추가 OCR 32.391초 + 23.359초 |

후보 검색 도구는 이 세 사례에서 각 0.5초 이내. 대기, 모델 왕복, 추가 OCR, 독립 검수와 그룹화가 주요 지연이다. application/service.py는 interactive Semaphore(1). gallery_tools/registry.py의 recognize_text는 artifact 캐시를 사용하므로 ‘OCR 캐시 없음’이라고 설명하면 안 된다. 새 영역 OCR을 재실행하는 경로를 조사한다.

제안: 전체 사진 OCR과 좌표를 사전 저장해 영역 선택에 재사용하고 필요한 경우만 재인식; 후보 검색을 병렬 실행해 이미지와 근거를 묶어 모델 왕복 감소; 독립 검수 유지; 자주 선택할 영역의 연결을 사전 준비; 사진 추가·수정·삭제 시 영향받는 자료와 연결만 안전하게 갱신. 기존 ready/prepared 캐시를 먼저 조사하고 중복 구조를 만들지 않는다. 준비된 결과 1초 이내, 새 영역 5~10초는 제안 목표이지 측정된 보장이 아니다. 전처리 비용·새 사진 즉시 사용·임의 영역·빈 결과·동시 변경과 삭제·캐시 최신성도 검증해야 한다.

## 로컬 실행 환경

- 기본 체크아웃: C:/Users/siheon.ryu/Desktop/workspace/Connected Gallery
- 샘플 작업 worktree: 기본 경로/work/sample-apk (codex/sample-apk). worktree는 삭제하지 않는다.
- PC 서버 실행 worktree: C:/Users/siheon.ryu/Desktop/workspace/Connected-Gallery-device-ready
- 위 PC 경로의 .venv 및 .runtime/gallery.sqlite 사용. 서버는 마지막 확인 시 127.0.0.1:8765, 부모 PID 36844/서버 PID 33768. PID는 재사용될 수 있으므로 조작 전 명령·경로를 재확인한다.
- Python 3.12, PyTorch 2.9.1+cpu, Transformers 4.57.6, PaddleOCR 3.7.0, PaddlePaddle 3.3.1. RTX 3050 6GB는 있지만 현재 추론은 CPU. GPU 드라이버는 변경하지 않았다.
- 서버 .env와 .runtime/server-token.txt는 비공개. 값 출력 금지. 인증된 관리 요청은 scripts/pc_client.py 재사용. 에뮬레이터는 adb reverse tcp:8765 tcp:8765로 연결돼 있었다.
- 새 서버 코드를 변경하면 실행 중인 device-ready 서버에 자동 반영되지 않는다. 해당 editable install 경로와 데이터 위치를 확인하고 명시적으로 배포/재시작한다.
- 모델은 기존 server/model-lock.json의 revision으로 다운로드했고 얼굴 모델은 face-model-lock.json 체크섬 검증. scripts/prepare-models.py는 최신 revision으로 lock을 갱신하는 동작이 있어 고정 버전 재현 용도로 무심코 실행하지 않는다.
- APK: work/sample-apk/android/app/build/outputs/apk/debug/app-debug.apk, 46,037,497 bytes, SHA256 ecad831d48fb26a9723b16e89d4275a1140d8aae85e6ba2e44ba9a9922fe5ca4. 파일 존재는 필요 시 확인한다.
- 빌드: android/gradlew.bat -p android assembleDebug testDebugUnitTest lintDebug. 이전 wrapper 다운로드 문제 때 설치된 Gradle 8.11.1을 --offline --no-daemon --max-workers=1로 사용했다.
- 설치: python scripts/install-device.py --serial emulator-5554.

## 주의

기본 체크아웃의 미추적 docs/samsung-gallery-data-reuse-research.md는 다른 작업이며 커밋에 섞지 않았다. docs/sample-gallery.md의 마지막 환경 미설치 설명은 당시 기록이며 이후 상태는 docs/pc-model-validation.md를 따른다. 기존 데모 사진은 없었던 것이 아니라 docs/presentations/connected-gallery-pitch.html에 base64로 임베드돼 있었고 다른 작업이 추출해 사용했다. 처음의 ‘사진 없음’ 설명은 탐색 누락이었다.

후속 구현은 별도 worktree에서 변경 명제를 먼저 기록하고, 새로운 사진 및 교체·삭제·복구·동시성 사례로 검증한다. 고정 24장 성공을 일반화의 증거로 취급하지 않는다.
