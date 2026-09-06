# Connected Gallery

**See → Tap → Follow → Tap → Follow**

Android 갤러리에서 사진 속 사람·사물·텍스트·장소를 눌러 내 사진을 탐색합니다. Organize는 진입점, Time은 Connect modifier입니다. 의미 판단은 모델이 도구를 선택하는 agentic 실행으로 처리합니다.

## 시작

Windows / Python 3.12 / JDK 17 / Android SDK 36.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[test,vision]"
# 기존 .env 또는 .env.example을 참고해 Proxy 설정
.\.venv\Scripts\python.exe scripts\prepare-models.py
.\scripts\start-server.ps1
```

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

## 구성

- `android/`: domain, data, core-ui, feature-library, feature-spaces, feature-explore, app.
- `server/connected_gallery/`: domain, application, agent_specs, agent_runtime, gallery_tools, adapters, bootstrap.
- `docs/implementation-plan.md`: 제품·기술·10일 계획.
- `docs/oss-reference.md`: 참고 출처와 재사용 범위.
- `docs/issues/`: 작업별 계약과 완료 기준.
- `docs/validation.md`: 실제 검증 결과와 남은 검증.

사진, 모델 실행 상태, 분석 결과는 `.runtime/`에 저장되며 Git에서 제외됩니다. Proxy 키는 `.env`에만 두며 APK에 포함하지 않습니다. 서버는 loopback 전용입니다. Android 원본은 수정하지 않습니다.
