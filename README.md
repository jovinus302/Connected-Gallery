# Connected Gallery

**See → Tap → Follow → Tap → Follow**

Android 갤러리에서 사진 속 사람·사물·텍스트·장소를 눌러 내 사진을 탐색합니다. MVP는 Organize + Connect입니다. Time/Timeline은 후속 기능으로 분리했습니다. 의미 판단은 모델이 도구를 선택하는 agentic 실행으로 처리합니다.

## 시작

Windows / Python 3.12 / JDK 17 / Android SDK 36.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[test,vision]"
# 기존 .env 또는 .env.example을 참고해 Proxy 설정
.\.venv\Scripts\python.exe scripts\prepare-models.py
.\scripts\start-server.ps1
```

NVIDIA GPU 사용 시에는 기본 환경을 유지하면서 선택적으로 CUDA 패키지를 설치할 수 있습니다.
시작 스크립트가 아래 경로를 자동으로 사용합니다. PaddleOCR는 CPU에서 동작합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install --target .runtime\torch-cuda --no-deps torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
```

CUDA 빌드 조합은 [PyTorch 공식 설치 안내](https://pytorch.org/get-started/previous-versions/#v291)를 참고했습니다.

별도 터미널에서 USB 디버깅 기기를 연결합니다.

```powershell
.\android\gradlew.bat -p android assembleDebug testDebugUnitTest
.\scripts\connect-device.ps1
```

앱의 **사진 연결**에서 접근을 허용한 사진 최대 1,000장을 연결합니다. **새로고침**으로 전송/분석을 재개합니다. 사진을 열고 대상을 누르세요. 길게 누르면 영역을 선택할 수 있습니다. 분석 중에도 수동 영역 탐색이 가능합니다. 사진 분석이 끝나면 Spaces를 자동으로 생성합니다. **맥락 찾아보기**로 다시 정리할 수 있습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\proxy-smoke.py
.\android\gradlew.bat -p android testDebugUnitTest lintDebug
```

Proxy smoke는 합성 이미지만 전송합니다. 자동 계약 테스트는 fake 모델과 실제 모델 검증을 구분합니다.

`scripts/benchmark-recovery.py`는 이미 연결·전송한 실제 사진 중 과거 실패6장을 별도 저장소에서 재분석합니다. `--count 3 --latest --report docs/example.json`으로 최근 실패 표본과 출력 경로를 지정할 수 있습니다. 실제 사진을 설정된 Proxy로 다시 보내므로 합성 smoke와 구분합니다. 실행 시 `PYTHONPATH`에 `.runtime/torch-cuda` 절대 경로를 넣으면 GPU 빌드를 사용합니다. `scripts/retry-failed-analysis.py`는 아직 분석되지 않았고 활성 작업도 없는 실패 사진만 **사진 버전·배포된 agent spec별 한 차례** 재시도 등록합니다.

`scripts/benchmark-connect.py`는 연결된 실제 사진으로 PC API 연속3hop을 확인합니다. 이 결과는 Android 화면 조작 검증을 대체하지 않습니다.

기존 분석의 선택 영역 인덱스는 서버 실행 후 `scripts/repair-missing-indexes.py`로 채웁니다. 원본·분석을 다시 만들지 않고 빠진 전체 이미지, 설명/OCR 텍스트, 에이전트가 선택한 영역의 벡터만 추가합니다. 중단 후 같은 명령으로 재개할 수 있습니다. 인덱스 준비 완료는 이 세 종류가 모두 있는 사진을 뜻합니다.

## 구성

- `android/`: domain, data, core-ui, feature-library, feature-spaces, feature-explore, app.
- `server/connected_gallery/`: domain, application, agent_specs, agent_runtime, gallery_tools, adapters, bootstrap.
- `docs/implementation-plan.md`: 제품·기술·10일 계획.
- `docs/oss-reference.md`: 참고 출처와 재사용 범위.
- `docs/issues/`: 작업별 계약과 완료 기준.
- `docs/validation.md`: 실제 검증 결과와 남은 검증.
- `docs/final-mvp-validation.md`: 1,000장 준비, 최종 Spaces, 실제 Android 3hop과 속도·품질 한계.

사진, 모델 실행 상태, 분석 결과는 `.runtime/`에 저장되며 Git에서 제외됩니다. Proxy 키는 `.env`에만 두며 APK에 포함하지 않습니다. 서버는 loopback 전용입니다. Android 원본은 수정하지 않습니다.
