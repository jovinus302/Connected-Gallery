# PC 서버 연결

휴대폰 → HTTPS 주소 → Cloudflare Tunnel → PC API(127.0.0.1:8765) → 기존 분석·검색·모델.

앱의 서버 주소는 실행 중 설정으로 저장한다. PC의 주소를 APK에 고정하지 않는다. Wi-Fi와 모바일 데이터 모두 외부 HTTPS 주소를 사용하며 USB 포트 전달은 필요 없다. APK 설치에 사용한 USB는 분리해도 된다.

## 실행과 연결

1. `scripts/start-pc-server.ps1`로 서버와 터널을 실행한다. 이미 살아 있는 연결은 재사용한다.
2. 앱의 **서버**에서 HTTPS 주소와 접속 키를 입력한다. PC의 `.runtime/pc-connection.json`에서 확인할 수 있다. 이 파일에는 비밀 키가 있으므로 공유하거나 Git에 올리지 않는다.
3. **확인 후 저장**은 `/manifest` 인증과 API 버전 1을 확인한다. 실패하면 기존 설정을 유지한다.
4. PC를 켜 두고 절전 상태로 들어가지 않도록 한다. 서버를 종료하려면 `scripts/stop-pc-server.ps1`을 사용한다. 진행 중 탐색이 있으면 먼저 완료하거나 취소한다.

개발용 APK는 `scripts/connect-device.ps1`로 설치와 1회 접속 설정을 할 수 있다. 앱 전용 디버그 입력 파일은 암호화 저장 후 삭제한다. 외부 앱이 호출하는 설정 Intent나 비밀 키가 들어간 APK는 만들지 않는다.

설치는 APK를 base64로 인코딩해 ADB shell의 표준 입력으로 보내고 기기에서 디코딩한다. 로컬과 기기의 SHA-256이 일치한 경우에만 `pm install -r`을 실행하며 임시 APK는 설치 성공·실패 모두에서 삭제를 시도한다. 기존 앱 데이터는 유지한다.

서버 설정 없이 APK만 설치하려면 Python 3.12와 ADB가 있는 환경에서 `python scripts/install-device.py`를 실행한다. `--apk`로 APK 경로를, `--serial emulator-5554`로 대상 기기를 지정할 수 있다. 설치 후 `adb shell monkey -p com.connectedgallery.app 1`로 실행한다. 샘플 사진은 APK에 포함되지 않으므로 기기 사진 저장소에 준비하고 앱에서 사진 접근을 허용해야 한다.

## 인증과 데이터

전체 API(health, 미리보기, 이벤트, 조회·수정, 문서 포함)는 독립적인 Bearer 키를 요구한다. 키가 없거나 틀리면 데이터를 읽거나 작업을 실행하기 전에 401로 거절한다. 응답은 `Cache-Control: no-store`로 중계 캐시에 보관하지 않도록 한다. 인증 키는 모델 Proxy 키와 다르다.

앱은 공개 서버에 HTTPS만 허용한다. 리다이렉트는 따라가지 않으며, 키는 Android Keystore의 AES-GCM으로 암호화해서 보관한다. 기존 개발용 loopback HTTP는 명시적으로 설정할 때만 허용한다.

사진·영역·분석 요청은 Cloudflare의 HTTPS 중계 경로를 통과한다. 분석과 사진 저장은 기존 PC에서 계속 처리한다. 현재 인증은 개인 사용자 한 명을 위한 방식이다.

## 현재 주소의 수명

[Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)은 개발·테스트용이며 고정 주소나 가용성을 보장하지 않는다. 프로세스 재시작 시 주소가 바뀔 수 있다. 앱은 HTTP 폴링을 사용하므로 Quick Tunnel의 SSE 미지원 제약에 해당하지 않는다.

PC를 장기간 서버로 쓸 때는 도메인에 연결한 Named Tunnel 등 고정 HTTPS 주소를 설정하고 앱의 주소를 갱신한다. 키나 주소를 변경한 후 실행 중인 동기화·탐색은 다시 시작한다.

## 별도 백엔드로 이전할 때

앱은 동일한 API 버전 1 계약과 HTTPS 주소를 사용할 수 있다. 서버의 `.runtime` 사진·SQLite·벡터·모델 의존성을 새 환경으로 이전하고 인증·GPU 실행을 구성해야 기존 분석과 Spaces가 유지된다. 주소만 바꿔도 기존 데이터가 자동으로 새 서버로 복사되는 것은 아니다.

사용자가 여러 명이 되는 운영 단계에서는 사용자별 인증과 데이터 분리, 키 회수, 백업·복구, 서버 모니터링을 추가한다. 현재 MVP는 개인 PC 서버 연결을 제공한다.
