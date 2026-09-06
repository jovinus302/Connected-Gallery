# 검증 결과 — 2026-09-07

## 구현된 흐름

Android 실제 Gallery 접근(허용된 사진 최대1,000장), 사진 뷰어·확대·영역 탭·수동 crop, 연속 hop, Related/Same moment, Time, 뒤로 가기, Spaces 포함/제외·인물 이름, Room 저장과 WorkManager 재시도.

PC SQLite·FTS5·모델 공간별 vector retrieval, Photo Analyst/Explorer/Organizer의 LangGraph 실행, Proxy 어댑터, 실제 OSS 인식/embedding 모델, 이벤트·캐시·취소·idempotency·파생 데이터 삭제. 분석 완료 뒤 Spaces 자동 생성. 모델 장애에는 의미 판단 규칙 fallback이 없다.

## 자동 검증

- Python 계약/실행 테스트: **15개 통과**. 마지막 호출의 제출 예약, 실제 SDK 메시지 형식, 추론 대기 중 저장소 접근과 취소 후 저장 방지를 포함한다.
- Android domain 상태 전이·좌표 변환 단위 테스트: **4개 통과**.
- APK assembleDebug + Android lintDebug: **통과**. 라이브러리 최신 버전 안내 등 경고는 남아 있으며 lint 오류는 없음.
- GitHub CI: 초기 구현 커밋의 server·android 검사 모두 통과. 이후 서버 목록 context 보완은 로컬13개 테스트로 재검증.
- 실제 Proxy 합성 이미지 이해 + tool-result 왕복: 통과.
- 실제 Explorer, 연도2015 고정 + 대상사진 선택: 통과, **9.67초** (단일 합성 사례).
- 실제 Photo Analyst, 합성 안내 이미지: 영역 **3개**, **79.66초**. 초기 모델 준비·CPU 추론 포함.
- 실제 Organizer: Space **1개**, **4.86초**. 고정 카테고리를 제공하지 않음.
- SigLIP2 image/text, e5 한국어 text, Grounding DINO, YuNet/SFace 실행 경로, PaddleOCR: 호출 smoke 전부 통과. 얼굴 양성 샘플 매칭 정확도는 미검증.
- synthetic 1,000개 768차원 벡터, 연도 조건 적용 후 검색30회: p50 **5.84ms**, p95 **7.62ms**. 모델·네트워크·Android 화면 시간은 포함하지 않음.

## 실제 제품 수용 검증은 남아 있음

2026-09-07 Galaxy S23 Ultra(SM-S918N)에 APK 설치·실행, 사진 권한 허용, USB reverse 연결을 확인했다. 실제 사진 목록과 분석 이미지 **1,000장 전송이 완료**됐다. 전체 검색 흐름·연속 hop과 품질 평가는 아직 완료되지 않았다.

실제50/1,000장 품질·전체 인덱싱 시간, 대상별 P@5, 반복hop p95, Find 성공시간·object tap rate·연속hop·재사용 의향은 **미측정**이다. `evaluation-template.csv`에 실제 평가를 기록하고 `scripts/evaluate.py`로 집계한다.

초기 CPU 실행에서 분석 25장 완료 시점에 호출 상한 초과11건·시간 초과2건이 확인됐다. 관찰/임베딩으로 마지막 호출을 소진하는 실행 기록에 근거해 agent spec v2를 적용했다. 첫 요청에 사진을 첨부하고 역할별 도구 범위를 한정하며, 마지막 모델 호출·도구 슬롯은 제출에 예약한다. 의미 해석과 도구 선택은 모델이 담당한다. 텍스트 임베딩을 계산하는 동안 저장소 잠금을 잡지 않도록 수정했다.

PyTorch **2.9.1+cu128**, torchvision **0.24.1+cu128**을 `.runtime/torch-cuda`에 별도로 설치했다. RTX4070Ti CUDA 계산과 실제 모델 실행을 확인했다. 기본 CPU 환경을 덮어쓰지 않으며 시작 스크립트가 설치된 GPU 경로를 사용한다. PaddleOCR는 여전히 CPU에서 실행한다.

기존 실패 사진 중 처음 나타난 서로 다른6장을 별도 저장소에서 재분석했다. **6/6 완료**, 모델 호출2~3회, 동시실행3개, 총125.59초. 초기 모델 준비가 포함된 첫3장은71.12~71.84초, 이후3장은44.66~54.47초였다. 선택된 작은 실패 표본이며 일반 갤러리 품질·p95·1,000장 총시간으로 일반화하지 않는다. 상세한 도구/모델 시간은 `recovery-benchmark.json`에 있으며 사진 ID나 내용은 공개하지 않는다.

DB 온라인 백업 후 실제 서버를 spec v2/GPU로 재시작했다. 완료42장과 대기 작업을 보존했고, 대기열에서 빠진 실패 사진6장을 한 차례 재시도 등록했다. 적용 후 실제 대기열에서 추가3장 완료(누적45장)를 확인했다. **1,000장90분과20장3분 목표는 여전히 미달성/미검증**이다.

## 운영 방법

프로젝트 루트 `.env`를 사용하고 `scripts/start-server.ps1`로 loopback8765 서버를 실행한다. USB 디버깅 기기 연결 후 `scripts/connect-device.ps1`로 reverse와APK설치를 수행한다. 앱에서 사진 연결을 누르면 허용 사진을 가져온다.

키·원본·분석 이미지·실행 DB는 Git에서 제외한다. 공개 의미 내용은 합성 데이터만 사용하고, 실제 Gallery 검증은 집계 수치·도구 시간만 기록한다. 의존성 버전은 requirements.lock, Android Gradle, 모델 revision은 server/model-lock.json 및 face-model-lock.json에 기록한다.
