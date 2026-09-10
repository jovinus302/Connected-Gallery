# PC 데모 합성 사진 20장

기존 PC 데모 전달본의 사진 bytes를 그대로 보존한다. Android APK의 샘플 24장과는 다른 이미지 묶음이다.

- 출처: 이전 Codex 작업 `connected-gallery-mvp-thread-01a076f1-b2ae`의 `outputs/demo-complete/delivery/connected-gallery-ready-data.zip`.
- 전달 보고서: revision 68, 사진 20장, Connect 캐시 47개, 자동 맥락 캐시 20개.
- `images/`: 전달 ZIP의 `.runtime/demo/images/`에서 파일명과 bytes를 유지해 복사한 20장.
- `manifest.json`: ZIP·보고서의 SHA-256, 사진별 과거 ID·경로·SHA-256·크기. 20장 모두 전달 보고서의 해시와 일치하고 이미지 디코딩을 확인했다.

이 폴더는 사진 자산만 보존한다. 준비 DB와 모델 결과는 포함하지 않으며, 사진이 있다는 사실이 최신 정책의 준비 완료를 뜻하지 않는다. 새 분석은 저장소의 `scripts/prepare-demo.py`에 이 `images/` 폴더를 입력으로 제공하고, 별도 실행 데이터 폴더를 지정한다. 세부 옵션은 `--help`를 따른다. manifest와 이 문서는 모델 판단 입력이 아니다.

관련 시연과 검증 범위는 [PC 데모 완료 기록](../../docs/pc-demo-completion.md), 전체 자산 관계는 [이미지 자산 목록](../../docs/image-assets.md)을 참고한다.
