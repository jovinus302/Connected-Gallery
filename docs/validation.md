# 검증 결과 — 2026-09-07

## 구현된 흐름

Android 실제 Gallery 접근(허용된 사진 최대1,000장), 사진 뷰어·확대·영역 탭·수동 crop, 연속 hop, Related/Same moment, Time, 뒤로 가기, Spaces 포함/제외·인물 이름, Room 저장과 WorkManager 재시도.

PC SQLite·FTS5·모델 공간별 vector retrieval, Photo Analyst/Explorer/Organizer의 LangGraph 실행, Proxy 어댑터, 실제 OSS 인식/embedding 모델, 이벤트·캐시·취소·idempotency·파생 데이터 삭제. 분석 완료 뒤 Spaces 자동 생성. 모델 장애에는 의미 판단 규칙 fallback이 없다.

## 자동 검증

- Python 계약/실행 테스트: **12개 통과**.
- Android domain 상태 전이·좌표 변환 단위 테스트: **4개 통과**.
- APK assembleDebug + Android lintDebug: **통과**. 라이브러리 최신 버전 안내 등 경고는 남아 있으며 lint 오류는 없음.
- 실제 Proxy 합성 이미지 이해 + tool-result 왕복: 통과.
- 실제 Explorer, 연도2015 고정 + 대상사진 선택: 통과, **9.67초** (단일 합성 사례).
- 실제 Photo Analyst, 합성 안내 이미지: 영역 **3개**, **79.66초**. 초기 모델 준비·CPU 추론 포함.
- 실제 Organizer: Space **1개**, **4.86초**. 고정 카테고리를 제공하지 않음.
- SigLIP2 image/text, e5 한국어 text, Grounding DINO, YuNet/SFace 실행 경로, PaddleOCR: 호출 smoke 전부 통과. 얼굴 양성 샘플 매칭 정확도는 미검증.
- synthetic 1,000개 768차원 벡터, 연도 조건 적용 후 검색30회: p50 **5.84ms**, p95 **7.62ms**. 모델·네트워크·Android 화면 시간은 포함하지 않음.

## 실제 제품 수용 검증은 남아 있음

연결된 Android 기기 또는 에뮬레이터가 아직 없어 UI 조작과 실제 Gallery 전송은 실행하지 못했다. APK 컴파일 통과를 기기 동작 검증으로 간주하지 않는다.

실제50/1,000장 품질·전체 인덱싱 시간, 대상별 P@5, 반복hop p95, Find 성공시간·object tap rate·연속hop·재사용 의향은 **미측정**이다. `evaluation-template.csv`에 실제 평가를 기록하고 `scripts/evaluate.py`로 집계한다.

현재 설치된 PyTorch는 CPU 빌드다. RTX4070Ti의 CUDA 실행과 1,000장90분 목표는 아직 검증되지 않았다. 첫 사진 분석79.66초를 기준으로20장3분 목표 달성을 주장할 수 없으며, warm 실행·GPU·모델 호출량을 측정해 최적화해야 한다.

## 운영 방법

프로젝트 루트 `.env`를 사용하고 `scripts/start-server.ps1`로 loopback8765 서버를 실행한다. USB 디버깅 기기 연결 후 `scripts/connect-device.ps1`로 reverse와APK설치를 수행한다. 앱에서 사진 연결을 누르면 허용 사진을 가져온다.

키·원본·분석 이미지·실행 DB는 Git에서 제외한다. 공개 리포트의 사진과 결과는 합성 데이터다. 의존성 버전은 requirements.lock, Android Gradle, 모델 revision은 server/model-lock.json 및 face-model-lock.json에 기록한다.
