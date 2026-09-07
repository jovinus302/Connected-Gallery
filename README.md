# Connected Gallery

> PC 데모 완료 (2026-09-08): 합성 사진 20장·선택 대상 47개의 Connect와 사진별 자동 맥락을 준비하고, 두 출발점의 3hop·뒤로 가기 복원을 실제 브라우저에서 검증했다. [데모 실행과 검증 범위](docs/pc-demo-completion.md)를 참고한다. 아래 Android 연결 안내와 PC 데모의 검증 범위는 구분한다.

**See → Tap → Follow → Tap → Follow**

Android 갤러리에서 사진 속 사람·사물·텍스트·장소를 눌러 내 사진을 탐색합니다. MVP는 Organize + Connect입니다. Time/Timeline은 후속 기능으로 분리했습니다. 의미 판단은 모델이 도구를 선택하는 agentic 실행으로 처리합니다.

## PC 데모

사진을 열면 함께 볼 사진과 이유가 자동으로 나타납니다. 관심 대상을 선택해 Connect 결과를 보고, 결과나 맥락의 사진으로 이동해 다른 관심사를 따라갈 수 있습니다. 별도 Organize 버튼이나 Space 생성은 데모 흐름에 없습니다.

별도로 전달한 준비 데이터가 `.runtime/demo`에 있다면 Python 3.12 이상에서 실행합니다.

```powershell
python -m pip install -e .
python scripts/start-demo.py --data-dir .runtime/demo --prepared-only --port 8879
```

서버가 출력하는 로컬 `demo-launch.html`로 접속합니다. 준비 데이터 조회에는 모델 API 키나 휴대폰이 필요 없습니다. [사용·전달 안내](docs/pc-demo-completion.md)에 데이터 준비, 의미 검수와 속도 측정의 범위를 기록했습니다.

## Android와 PC 서버 시작

Windows / Python 3.12 / JDK 17 / Android SDK 36.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[test,vision]"
# 기존 .env 또는 .env.example을 참고해 Proxy 설정
.\.venv\Scripts\python.exe scripts\prepare-models.py
.\scripts\start-pc-server.ps1
```

NVIDIA GPU 사용 시에는 기본 환경을 유지하면서 선택적으로 CUDA 패키지를 설치할 수 있습니다.
시작 스크립트가 아래 경로를 자동으로 사용합니다. PaddleOCR는 CPU에서 동작합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install --target .runtime\torch-cuda --no-deps torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
```

CUDA 빌드 조합은 [PyTorch 공식 설치 안내](https://pytorch.org/get-started/previous-versions/#v291)를 참고했습니다.

최초 시작 전 [Cloudflare 공식 다운로드](https://developers.cloudflare.com/tunnel/downloads/)의 Windows 64-bit `cloudflared.exe`를 `.runtime/bin/cloudflared.exe`에 둡니다. 시작 스크립트는 PC의 loopback 서버와 HTTPS 터널을 숨겨진 프로세스로 실행합니다. 동일한 연결이 살아 있으면 재사용합니다.

최초 APK 설치·접속 설정 시 USB 디버깅 기기를 연결합니다. 이후 앱 사용에는 USB나 같은 Wi-Fi가 필요하지 않습니다.

```powershell
.\android\gradlew.bat -p android assembleDebug testDebugUnitTest
.\scripts\connect-device.ps1
```

설치 스크립트는 `.runtime/pc-connection.json`의 주소·접속 키를 앱 전용 저장소로 전달하고 USB 포트 전달을 제거합니다. 앱은 키를 Android Keystore로 암호화해 보관합니다. 키는 APK·Git에 포함하지 않습니다. 수동 설정은 앱의 **서버 → 서버 주소 / 접속 키 → 확인 후 저장**에서 가능합니다. HTTPS와 API 호환성·인증을 확인한 뒤 저장합니다.

PC를 다시 켰다면 `scripts/start-pc-server.ps1`을 실행합니다. 현재 MVP의 Quick Tunnel 주소는 터널 재시작 시 바뀔 수 있으므로, 바뀐 경우 앱의 서버 주소도 갱신합니다. 접속 키는 `.runtime/server-token.txt`에 유지됩니다. `CG_SERVER_TOKEN`으로 별도 지정할 수도 있습니다. PC와 서버가 실행 중이어야 새 탐색이 가능합니다. 중지는 `scripts/stop-pc-server.ps1`입니다.

운영 구조와 고정 주소·별도 백엔드 이전은 [PC 서버 연결 안내](docs/pc-server.md)를 참고하세요.

앱의 **사진 연결**에서 접근을 허용한 사진 최대 1,000장을 연결합니다. **새로고침**으로 전송/분석을 재개합니다. 사진을 열고 대상을 누르세요. 길게 누르면 영역을 선택할 수 있습니다. 분석 중에도 수동 영역 탐색이 가능합니다. 이 브랜치의 최신 자동 사진 맥락 수용 검증은 PC 데모를 대상으로 합니다.

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

사진, 모델 실행 상태, 분석 결과는 `.runtime/`에 저장되며 Git에서 제외됩니다. Proxy 키는 `.env`에만 두며 APK에 포함하지 않습니다. 서버 원점은 loopback에서 실행하고 HTTPS 터널을 통해 인증된 외부 요청을 받습니다. Android 원본은 수정하지 않습니다.
