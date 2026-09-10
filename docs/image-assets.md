# 샘플·발표·브랜드 이미지 원본 목록

2026-09-10 현재 작업 사본 기준. 자료 재현에 사용하는 합성 이미지 원본은 레포에 보존한다. 분석 DB·캐시와 사진 원본의 보관 여부는 별도로 판단한다.

| 이미지 묶음 | 원본 위치 | 사용하는 자료 | 보관 상태 |
|---|---|---|---|
| Android 샘플 24장 | `android/app/src/debug/assets/sample-gallery/cg_sample_01.png`–`cg_sample_24.png` | 디버그 APK, 24장 PC 모델 검증 | 24개 모두 Git 추적 중 |
| 발표용 사진 6장 시트 | `docs/presentations/agent-loop/assets/gallery.png` | Agent Loop 웹 시연, Astra Film | Git 추적 중. 3×2 시트 자체가 보존 원본 |
| Agent 콘셉트 | `docs/presentations/agent-loop/assets/concept.png` | Agent Loop 대체 화면, Astra Film 시각 참조 | Git 추적 중 |
| PC 데모 합성 사진 20장 | `assets/demo-gallery/images/` | PC 데모의 Connect 47개·자동 맥락 20개 및 두 경로의 3hop 검증 | 이전 Codex 작업의 전달 ZIP에서 복사. 20장 모두 보고서 SHA-256 일치 |
| 앱 아이콘 | `android/app/src/main/res/drawable/ic_gallery_foreground.xml`, `ic_gallery_monochrome.xml` | Android 적응형·단색 아이콘 | 벡터 원본과 `assets/branding/`의 SVG·512px PNG 보존 |
| Android 화면·아이콘 미리보기 | `docs/images/android-ui-2026-09-10.png`, `android-icon-2026-09-10.png` | README, Android 디자인 기록 | 합성 사진 기반 실기기 화면 모음과 벡터 기반 아이콘 검수 이미지 보존 |
| Paper & Ink Android 화면 | `docs/images/android-paper-ink-2026-09-11.png` | README, 홈/날짜별 구현 기록 | SM-S918N의 실제 Compose 화면. 기존 PC 데모 합성 사진과 고정 응답으로 촬영한 5개 상태 |

Android 24장과 PC 데모 20장은 서로 다른 데이터다. 발표 시트의 6장을 PC 데모 원본 20장으로 대신하지 않는다.

## PC 데모 원본 반입

이전 Codex 작업 `connected-gallery-mvp-thread-01a076f1-b2ae`의 `outputs/demo-complete/delivery/connected-gallery-ready-data.zip`을 찾았다. 합성 사진 20장을 `assets/demo-gallery/images/`에 복사하고 파일별 SHA-256·출처·과거 파일명과 ID 대응을 [manifest](../assets/demo-gallery/manifest.json)에 기록했다. 전달 보고서의 revision 68·Connect 47개·맥락 20개는 PC 데모 완료 기록과 일치한다. 사진 bytes와 이름은 변경하지 않았다. 기존 자료 참조 경로는 유지하고 필요한 실행 복사본은 이 원본에서 만든다.

`.runtime/images/`는 개인 갤러리 실행 저장소이므로 데모 이미지 폴더로 간주하여 일괄 반입하지 않는다. 실행 DB·접속 정보도 이미지 반입에 포함하지 않는다.

과거 준비 DB는 당시 소스와 함께 쓰는 재현 자료다. 최신 앱에서 사용하려면 현재 모델·정책 계약에 맞게 다시 준비해야 한다.

## 관련 기록

- [Android 샘플 구성](sample-gallery.md)
- [Android 디자인 적용과 검증](android-design-2026-09-10.md)
- [앱 아이콘 원본과 재생성](../assets/branding/README.md)
- [24장 후속 분석·Connect 검증](pc-model-validation.md)
- [20장 PC 데모 완료 기록](pc-demo-completion.md)
- [데모 통합과 캐시 버전](demo-main-integration.md)
- [발표 시연 원본](presentations/agent-loop/README.md)
- [Astra Film 이미지 출처](presentations/astra-film/sources.md)
