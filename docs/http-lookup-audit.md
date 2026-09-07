# 준비 조회의 HTTP 지연과 비변경 검사

`scripts/audit-demo-http.py`는 읽기 전용 서버의 실제 사진·region 목록을 사용한다. 20장·47개 같은 수를 경로에 고정하지 않는다. 모든 region은 `POST /explorations/ready`, 모든 사진의 맥락은 `GET /assets/{id}/context`로 조회한다. `pending`·`failed`라고 준비 요청을 보내지 않으며, `/runs`, `/context/prepare`, `/demo/session`을 호출하지 않는다.

실제 서버를 검사할 때에는 `--prepared-only`와 작업이 없는 marked synthetic DB가 필요하다. 기존 서버 토큰을 Authorization 헤더에서만 사용하고 브라우저의 일회용 launch key는 읽거나 소비하지 않는다. 각 대상마다 새 HTTP client의 첫 요청을 측정하고 이후 같은 연결의 반복 요청을 측정한다. 첫 요청은 새 프로세스나 비어 있는 DB 캐시를 의미하지 않는다. 이미지 표시·브라우저 렌더링·모델 생성 시간은 측정 범위에 포함하지 않는다.

보고서는 Connect와 Context를 각각 집계하며, 개별 반복 조회와 전체 반복 조회의 p50·p95를 기록한다. p50은 중앙값, p95는 정렬한 표본의 nearest-rank 95백분위다. Context의 `ready/empty/pending/running/failed` 개수와 준비 완료인 응답만의 지연을 따로 제공한다. 관찰한 응답의 사진 ID·revision·내용 hash가 조회 중 바뀌면 정상적인 안정 조회로 취급하지 않는다.

조회 전후의 revision·실행·이벤트 개수와 SQLite 각 테이블 내용 digest를 비교한다. 이로써 행 수가 같아도 캐시 내용이 수정된 경우를 잡는다. 보고서에는 원문 DB 내용이나 토큰을 넣지 않는다. `lookup_audit_passed`는 안정적인 HTTP 조회와 관찰한 비변경에 대한 결과다. 전체 준비 여부는 별도 `all_lookups_prepared`이며, 실제로 준비가 덜 된 데이터에서 조회 검사만 통과할 수 있다. 이 검사는 의미 정확도·3-hop 경험·UI 완성도의 합격 판정이 아니다.

자동 테스트는 MockTransport와 임시 DB를 연결한 실제 API TestClient를 사용한다. 이 테스트에서 나온 지연을 실제 loopback 서버 성능으로 제시하지 않는다. 실제 서버 측정은 따로 실행해야 한다.
