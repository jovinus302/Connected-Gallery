# Connected Gallery

**사진 속 대상을 따라가며 관련 사진을 발견하는 Android 갤러리.**

사진을 열고 사람·사물·텍스트·장소를 선택하면 관련 사진을 찾습니다. 도착한 사진에서는 주변 맥락을 보고 새로운 관심사를 따라 탐색을 이어갑니다.

## 주요 기능

| 기능 | 사용 방법과 동작 |
|---|---|
| 사진 연결 | 접근을 허용한 사진 최대 1,000장을 PC 서버에 연결합니다. 새로고침으로 전송·분석을 재개합니다. |
| Connect | 사진 속 대상을 눌러 관련 사진을 찾습니다. 길게 눌러 수동 영역을 선택할 수도 있습니다. |
| 자동 맥락 | 사진을 열면 아래에 함께 볼 사진과 이유가 나타납니다. 미준비 맥락은 자동으로 준비합니다. |
| 이어서 탐색 | 결과나 맥락 속 사진을 열고 다른 대상을 선택합니다. 맥락 그룹 제목을 누르면 전체 목록을 펼칩니다. |
| 돌아가기 | 이전 사진·선택 대상·결과·맥락·스크롤 위치를 복원합니다. |
| 상태와 재시도 | 준비 중, 실패, 확인된 빈 결과를 구분하고 실패한 맥락의 재시도를 제공합니다. |

## Android 시작

Windows, Python 3.12, JDK 17, Android SDK 36이 필요합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[test,vision]"
# .env.example을 참고해 .env에 모델 Proxy 설정
.\.venv\Scripts\python.exe scripts\prepare-models.py
.\scripts\start-pc-server.ps1
```

최초 실행 전에 Windows 64-bit `cloudflared.exe`를 `.runtime/bin/cloudflared.exe`에 둡니다. 서버 시작 스크립트는 PC 서버와 HTTPS 터널을 실행합니다. 설치와 연결 옵션은 [PC 서버 안내](docs/pc-server.md)를 참고하세요.

USB 디버깅 기기를 연결한 뒤 앱을 빌드하고 설치합니다.

```powershell
.\android\gradlew.bat -p android assembleDebug testDebugUnitTest
.\scripts\connect-device.ps1
```

앱의 **사진 연결**에서 사진 접근을 허용합니다. 서버를 수동으로 설정하려면 **서버 → 서버 주소 / 접속 키 → 확인 후 저장**을 사용합니다. 접속 키는 Android Keystore로 암호화해 보관합니다.

설정 후에는 USB나 같은 Wi-Fi 없이 사용할 수 있습니다. 새 탐색에는 PC와 서버가 실행 중이어야 합니다. PC 재부팅 후 `scripts/start-pc-server.ps1`을 실행하고, 터널 주소가 바뀌었다면 앱의 서버 주소를 갱신합니다. 서버 중지는 `scripts/stop-pc-server.ps1`입니다.

## PC 브라우저 데모

소스와 호환되는 준비 데이터가 `.runtime/demo`에 있어야 합니다.

```powershell
python -m pip install -e .
python scripts/start-demo.py --data-dir .runtime/demo --prepared-only --port 8879
```

서버가 출력한 로컬 `demo-launch.html`을 엽니다. 준비된 Connect와 자동 맥락을 조회하는 모드로, 모델 API 키나 휴대폰이 필요 없습니다. 사진·모델·정책 버전이 맞지 않는 데이터는 다시 준비해야 합니다.

새 데이터는 모델 연결을 설정한 환경에서 `scripts/prepare-demo.py`와 `scripts/prepare-contexts.py`로 준비하고 `scripts/audit-complete-demo.py`로 확인합니다. 세부 옵션은 각 명령의 `--help`를 참고하세요.

## 개발과 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\proxy-smoke.py
.\android\gradlew.bat -p android testDebugUnitTest lintDebug
```

Proxy smoke는 합성 이미지를 사용합니다. 자동 테스트와 실제 사진의 관련성·설명 정확도·기기 대기 시간 검수는 별도로 수행합니다.

- [제품의 핵심 의도](INTENT.md)
- [제품과 사용자 흐름](docs/connected-gallery-product-ux.md)
- [구현 구조와 검증 기준](docs/implementation-plan.md)
- [기능별 작업 목록](docs/issue-breakdown.md)
- [사진 맥락 API 계약](docs/photo-context-contract.md)
- [PC 서버 운영](docs/pc-server.md)
- [OSS 참고 자료](docs/oss-reference.md)

Android 코드는 `android/`, 서버 코드는 `server/connected_gallery/`, PC 데모는 `web/demo/`에 있습니다. 사진·분석·실행 데이터는 Git에서 제외되는 `.runtime/`에 저장합니다. 모델 Proxy 키는 PC의 `.env`에 두고 APK에 포함하지 않습니다. Android 원본 사진은 수정하지 않습니다.
