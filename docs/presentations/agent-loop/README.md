# Agents at work

승인된 추상 agent 콘셉트를 움직이는 입체 작업대로 구현한 발표용 시연이다. 파란 유기체는 Explorer, 호박색 렌즈는 Reviewer, 검은 모듈은 결과 Organizer를 나타낸다.

![입체 agent와 탐색 loop의 시연 화면](preview.png)

## 실행

이 폴더에서 `./start.ps1`을 실행한 뒤 브라우저에서 `http://127.0.0.1:8891`을 연다. 사용 중인 포트라면 `./start.ps1 -Port 8892`로 바꿀 수 있다. 종료는 터미널에서 Ctrl+C. Python 3가 필요하다.

일반 정적 HTTP 서버에서도 동작한다. ES 모듈을 사용하므로 `index.html`을 파일로 직접 여는 방식은 지원하지 않는다. 모든 이미지와 Three.js 0.170.0을 로컬로 포함하여, 시작 후 외부 네트워크나 모델 키가 필요 없다. Three.js의 MIT 라이선스는 `vendor/THREE-LICENSE.txt`에 있다.

## 발표 조작

- 재생·일시정지: 버튼 또는 Space
- 이전·다음 단계: 버튼 또는 좌우 방향키
- 처음으로: ↺ 버튼 또는 Home
- 장면 선택: 아래 다섯 장면 또는 단계 슬라이더
- 재생 속도: 0.65×, 1×, 1.5×, 2×
- 구조 설명: 내부 loop, 검토 피드백, 종료 조건 펼치기
- 마지막 단계에서는 정지한다. 재생하면 처음부터 시작한다.
- 다른 탭으로 이동하면 정지한다. 돌아와서 재생 버튼으로 이어갈 수 있다.
- 움직임 축소 설정에서는 자동 시작과 입체 애니메이션을 끈다. 재생·수동 단계 선택은 사용할 수 있다.

## 시연과 실제 구현의 관계

고정된 19단계 설명용 시나리오이며 실제 실행 기록이나 내부 사고가 아니다. 기존 발표의 생성 사진 여섯 장을 재사용한다. 사진별 판정·검색 결과·진행 시간은 예시이다. 서버·Android 코드 및 개인 사진을 변경하거나 접근하지 않는다.

`server/connected_gallery/agent_runtime/runner.py`의 model → tools → model 왕복을 파란 궤도로 표현한다. 첫 검색, 이미지 확인, 재검색, 새 이미지 확인으로 네 번의 왕복을 보여준다. 제출 응답을 합하면 탐색 모델 응답 여섯 번에 대응하는 예시이다.

독립 검토의 귀환은 `review`와 `after_review`의 조건부 분기를 표현한다. 처음 제출한 후보가 모두 미지원이고 결과가 불완전하며 원본 대상이 유효하고 남은 응답·도구 예산이 있을 때 한 번 재탐색한다. 모든 검토가 재탐색을 유발하지 않는다.

결과 Organizer는 `result_organizer`가 주입된 구성을 의미하며 폐기된 Spaces 역할이 아니다. 최종 관계는 예시이며, 실제 실행은 부분 결과·빈 결과·실패로도 끝날 수 있다.

## 시각 자산

- `assets/gallery.png`: 기존 `connected-gallery-pitch.html`의 `.photo` 생성 이미지 원본을 변경 없이 추출.
- `assets/concept.png`: 이 작업에서 사용자가 승인한 생성 이미지. WebGL 미지원/실패 시 대체 화면.
- 정상 렌더링의 agent·궤도·사진 프레임은 `scene.js`에서 생성하는 실제 입체 장면이다.

변경 명제와 검증 증거: [agent-loop-proposition.md](../../agent-loop-proposition.md).

## 검증 재현

시연 서버를 실행한 상태에서 저장소 루트의 `node scripts/verify-agent-loop.cjs`를 실행한다. 검증 환경에는 Node.js, Playwright 패키지와 Microsoft Edge가 필요하다. Playwright가 별도 경로에 있다면 `NODE_PATH`로 지정한다. 기본 산출물은 Git에서 제외된 `work/agent-loop-validation/`이다. 주소와 출력 디렉터리는 첫 번째·두 번째 인자로 바꿀 수 있다. 전체 재생 검사에는 약 1분이 걸린다.
