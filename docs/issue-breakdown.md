# 작업 단위

| 작업 | 선행 | 완료 기준 |
|---|---|---|
| [CG-01: 모듈·데이터·API·탐색 상태 계약](https://github.com/jovinus302/Connected-Gallery/issues/1) | 없음 | 연도 변경은 anchor 유지, 새 탭은 전체 기간·Related로 초기화 |
| [CG-02: 실제 사진과 평가 시나리오 구성](https://github.com/jovinus302/Connected-Gallery/issues/2) | 없음 | 실제 사진과 합성 fixture를 분리하고 정답·무정답 과제 기록 |
| [CG-03: Android 갤러리·뷰어·좌표 변환](https://github.com/jovinus302/Connected-Gallery/issues/3) | CG-01 | 권한 범위에서 최대 1,000장 표시, 확대 후 영역 탭 |
| [CG-04: 사진 동기화·근거·artifact·인덱스](https://github.com/jovinus302/Connected-Gallery/issues/4) | CG-01 | 버전 변경·삭제 시 파생 데이터 무효화 |
| [CG-05: VLM·OCR·영역·얼굴·임베딩 도구](https://github.com/jovinus302/Connected-Gallery/issues/5) | CG-01 | 실제 관찰 근거와 영역·모델 버전 반환, 오류 명시 |
| [CG-06: AgentRunner·상태 저장·실행 예산](https://github.com/jovinus302/Connected-Gallery/issues/6) | CG-01 | 도구 선택은 모델 결정, 취소·예산·복구 제공 |
| [CG-07: Photo Analyst와 사전 분석](https://github.com/jovinus302/Connected-Gallery/issues/7) | CG-04, CG-05, CG-06 | 실제 이미지 관찰 후에만 분석 완료 |
| [CG-08: Explorer와 후보의 시각 확인](https://github.com/jovinus302/Connected-Gallery/issues/8) | CG-07 | 실제 ID·확인한 이미지·연도 범위만 제출 |
| [CG-09: 사진 속 탭·결과 표시·연속 hop](https://github.com/jovinus302/Connected-Gallery/issues/9) | CG-03, CG-08 | See→Tap→Follow 3회 이상, 대기 중 사진 유지 |
| [CG-10: Related·Same moment·Time·기록](https://github.com/jovinus302/Connected-Gallery/issues/10) | CG-09 | anchor 보존, Same moment는 사건 맥락, 뒤로 가기 복원 |
| [CG-11: Organizer·Spaces·사용자 수정](https://github.com/jovinus302/Connected-Gallery/issues/11) | CG-07, CG-09 | 고정 taxonomy 없음, 사용자 포함·제외 유지 |
| [CG-12: 캐시·취소·삭제·재개·오프라인](https://github.com/jovinus302/Connected-Gallery/issues/12) | CG-04, CG-06, CG-09 | 오래된 응답 차단, 삭제 후 재등장 방지 |
| [CG-13: 지표 수집과 사용자·성능 평가](https://github.com/jovinus302/Connected-Gallery/issues/13) | CG-02, CG-10, CG-11 | 실측·목표·미검증 구분, 실제 n과 실패 보고 |
| [CG-14: 통합 QA·APK·문서](https://github.com/jovinus302/Connected-Gallery/issues/14) | CG-12, CG-13 | 빌드·계약 테스트 통과, 실제 기기 검증 상태 보고 |

실제 기기 검증이 필요한 항목은 코드 구현만으로 이슈를 닫지 않는다.
