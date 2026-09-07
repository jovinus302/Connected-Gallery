# PC 데모와 main 통합 — 2026-09-08

후속 실기기 수정 통합으로 현재 Context는 v9 (`photo-context-v9-integrated-grounded-review`)이다. 아래 v6은 당시 첫 통합 기록이며 현재 계약은 [이미지·맥락 진단 기록](image-context-diagnosis-2026-09-08.md)을 따른다. 과거 준비 데이터를 새 계약으로 이름만 바꾸지 않고 재준비한다.

PC 데모 구현 `3b076af`와 기존 main `52ad20f`를 통합했다. main의 Android 자동 사진 맥락·Space 제거·HTTPS 시작 복구·제품 소개 페이지를 유지하고, 데모에서 검증한 Connect·Context 검토와 사전 준비·조회·패키징 보호를 합쳤다.

## 통합한 동작

- Android의 사진 열기 → 자동 맥락 → 대상 Connect → 다른 사진 탐색과 뒤로 가기 복원.
- 선택한 대상을 유지하는 Connect 검토, 전체 후보를 독립 검토한 빈 결과, 명시적 모델 namespace의 준비 캐시 조회.
- 사진 전체의 관찰 계획 이행, 후보별 비교 주장·최종 문구 검토, 실패한 재준비 시 기존 유효 결과 보존.
- 실제 촬영 시각이 알려진 경우 가까운 시각의 사진을 우선 공급하는 최대 40장 초기 후보 목록. 최종 관계는 모델이 판단한다.
- 모델 전송용 사진 ID 별칭. 메시지·도구 응답·동적 JSON Schema의 ID enum을 같은 매핑으로 전달하고, 실제 ID로 복원한 뒤 기존 검증을 실행한다.
- Space의 앱 진입·목록·편집·새 Organizer·자동 실행 차단과 저장 이력 보존.

## 맥락 캐시 버전

통합 Context 사양은 **6**, 정책은 `photo-context-v6-source-prior-plan-and-wording-review`다. 준비 과정의 후보 공급과 검토 계약이 합쳐졌으므로 v3 또는 v5 캐시를 새 결과로 인정하거나 이름만 바꾸지 않는다. 과거 데이터는 보존하며 통합 소스에서 사용할 맥락은 새 계약으로 준비한다. Connect spec18은 유지한다.

[20장 PC 데모 완료 기록](pc-demo-completion.md)은 머지 전 v3 런타임의 실제 사진·브라우저 수용 검증이다. 그 전달 소스 ZIP과 준비 데이터 ZIP을 함께 사용하면 당시 데모를 재현할 수 있다. 최신 소스와 과거 준비 데이터를 섞어서 전체 맥락이 준비됐다고 해석하지 않는다. 이 머지에서 유료 모델 재준비나 개인 갤러리·실행 중 데모의 데이터 변경은 수행하지 않았다.

## 통합 검증

| 검사 | 결과 |
|---|---|
| Python 전체 대상 | 679개 사례 검증 완료, 미해결 실패 0 |
| 웹 Node | 28개 통과 |
| Android 단위 검사 | 29개 통과, 실패·오류·skip 0 |
| Android 빌드 | debug 앱과 feature-explore의 AndroidTest APK 컴파일 성공 |
| Android lint | 오류 0, 기존 경고 6 |
| Git | 모든 충돌 해결, diff whitespace 검사 통과 |

Python 전체 첫 실행에서는 667개 통과, 12개가 공통 패키지 fixture의 `context_spec == 3`에서 멈췄다. 이 고정값을 현재 계약 상수 `CONTEXT_SPEC`으로 수정한 뒤 해당 12개를 모두 재실행해 통과했다. 모델 namespace·본문 바이트 보존·변조 거부·빈 결과 근거 검증은 유지했다. 전체 실행 후 제품 코드는 변경하지 않았으며 동일한 679개 사례의 실패 목록과 재실행 목록을 대조했다.

새 통합 회귀에는 v3/v5 캐시의 읽기 전용 거부, 모델 별칭과 동적 스키마의 일치·실제 ID 복원, main의 시각 근접 후보 공급·HTTPS 진단·Space 폐기 검사를 포함한다.

```powershell
python -m pytest -q --tb=short
node --test tests/demo_context.test.cjs tests/demo_layout.test.cjs
android\gradlew.bat -p android --offline --no-daemon assembleDebug testDebugUnitTest lintDebug :feature-explore:assembleDebugAndroidTest
```

Android는 main의 구현과 동일하며 로컬 SDK·캐시로 위 빌드를 확인했다. `--offline`은 이미 의존성이 설치된 환경의 검증 옵션이다. 새 환경에서는 의존성을 먼저 준비해야 한다. 이번 검사에서 실제 휴대폰 테스트·설치나 새 v6 맥락의 모델 품질 평가를 수행한 것은 아니다. 기존 기기 수용·사진 품질 기록은 [Android 검증](context-ux-validation.md), PC 합성 사진 수용 기록은 [데모 완료 기록](pc-demo-completion.md)을 각각 따른다.
