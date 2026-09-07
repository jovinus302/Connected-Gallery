# 데모의 Context 전용 모델 프로필

`synthetic-demo.json`의 기존 `model`은 Connect의 모델 프로필이다. 선택적인 `context_model`은 사진 상세 맥락을 구성하는 모델만 지정한다. 두 값은 공개 모델명 형식으로 검증하며 자격 증명이나 API 주소를 저장하지 않는다.

```json
{"synthetic": true, "model": "claude-sonnet-5", "context_model": "gpt-5.4-mini"}
```

`prepare-contexts.py --data-dir <데모 경로> --context-model gpt-5.4-mini --photo-id <원본 ID>`는 Connect 프로필을 보존하면서 선택한 원본의 맥락을 준비한다. 기존 `--model`은 Connect 주 프로필을 바꾸는 동작을 유지한다. Context override를 생략하면 저장된 값을 보존하며, override가 없는 갤러리는 자신의 `model`을 사용한다. 다른 데모를 열 때 override가 없으면 이전 데모의 `CG_CONTEXT_MODEL`은 제거된다.

실제 Context 실행에서만 별도의 ProxyGateway를 구성해 선택한 primary, fallback 없음, primary 반복 없음, 기존 attempt timeout을 사용한다. 기존 gateway와 명시적으로 주입한 가짜 gateway·Context agent는 보존한다. 현재 문구 검토 모델 `gpt-5.4-mini`와 맥락 spec 3의 독립 검토 기준은 유지한다. 새 공급자나 자격 증명을 연결하지 않는다.

맥락 캐시 키는 override 또는 Connect 주 모델로 결정한 실제 Context 구성 모델을 포함한다. Connect 키와 기존 비어 있지 않은 Connect 결과를 변경하지 않고, 다른 Context 모델의 기존 캐시도 삭제하거나 재표기하지 않는다. 준비 보고서는 `context_model`, `connection_model`, `wording_review_model`을 구분하며 기존 `model` 항목은 실제 Context 구성 모델이다. 각 새 실행 기록에도 세 모델을 기록한다.

실행·stage·audit는 저장된 프로필을 적용하고, stage/audit 종료 시 호출자의 환경을 복원한다. stage/package의 공개 marker에는 검증한 모델 필드만 포함하며 기타 비공개 marker 필드는 내보내지 않는다.

## 기존 Connect 모델의 검증 결과 조회

새 준비 모델로 전환하면서 이전 모델의 검증된 결과도 조회하려면 선택적인 `compatible_connection_models`를 명시한다.

```json
{"synthetic": true, "model": "gpt-5.4", "context_model": "gpt-5.4", "compatible_connection_models": ["claude-sonnet-5"]}
```

`prepare-demo.py --samples <이미지 경로> --data-dir <데모 경로> --stage prepare --model gpt-5.4 --compatible-model claude-sonnet-5`로 설정한다. `--compatible-model`은 반복할 수 있고, 공개 모델명 검증 후 primary와 중복 항목을 제거한 순서대로 최대 4개를 허용한다. 옵션을 생략하면 기존 목록을 보존하고, primary 변경 시 새 primary와 중복된 항목만 제거한다. 프로필 함수에 빈 목록을 주면 호환 조회를 해제한다.

조회는 primary namespace를 먼저 확인하고 이후 명시한 namespace만 동일한 준비 완료 기준으로 검사한다. 캐시의 키·모델명·본문을 복사하거나 재표기하지 않는다. 새 모델 실행은 primary를 사용하며 이 목록은 실행 fallback 설정이나 Context 모델 선택에 영향을 주지 않는다. `connection_models()`와 `CG_COMPATIBLE_CONNECTION_MODELS`의 JSON 배열이 이 조회 순서를 전달한다. 다른 marker에 목록이 없거나 marker 자체가 없으면 이전 데모의 호환 환경값을 제거해 단일 모델 기본 동작을 유지한다.

stage/package는 검증한 호환 목록을 공개 marker와 보고서에 보존하고, audit는 실제 적용 목록을 기록한다. stage/audit 종료 시 호출자의 호환 환경값도 복원한다. 호환 목록 자체는 기존 결과의 의미 품질을 보증하지 않으며 각 캐시가 현재 사진·revision·검토 계약을 통과해야 조회된다.

오프라인 준비 CLI의 `--refresh`를 명시하면 기존 준비 결과가 있어도 선택한 범위를 현재 primary 모델로 다시 실행한다. `--photo-id`, `--region-id`, `--limit` 필터는 그대로 적용한다. 이전 모델 namespace는 건드리지 않고 일반 준비·검토 경로를 통과한 결과만 primary namespace에 저장한다. 기본 실행은 검증된 호환 결과를 재사용한다. 보고서는 새 실행의 `model`과 실제 조회된 `ready_cache_model`을 구분하므로 새 준비가 실패해 기존 호환 결과를 조회한 경우도 드러난다. 이 옵션은 공개 HTTP 요청에 노출하지 않는다.

## 지정 사진의 Context 재준비

`prepare-contexts.py --data-dir <데모 경로> --photo-id <원본 사진 ID> --refresh`는 기존 맥락이 준비돼 있어도 지정한 한 사진을 다시 준비한다. `--refresh`에는 명시적인 `--photo-id`가 필수다. 기본값인 한 pass만 실행하며 `--passes`로 재시도 횟수를 명시해도 새 결과가 검증되면 추가 재준비를 멈춘다.

내부 `ContextService.start(photo_id, refresh_prepared=True)`가 캐시 재사용을 건너뛰지만, 동일한 현재 context key의 queued/running 작업은 함께 기다린다. 기존 맥락은 작업 중에도 조회할 수 있고 새 결과가 현재 이미지·revision·관찰/문구 검토 계약을 통과한 후에만 교체한다. 실패·미완료·취소 시 원본 cache row를 유지한다. 비공개 `context_refresh_requested` 이벤트에는 이전 row의 원래 key·revision·본문 SHA-256을 기록하며 본문을 복제하지 않는다. 공개 준비 API의 동작과 요청 스키마는 바꾸지 않는다.

CLI 보고서는 조회 가능한 `state`와 새 실행의 `status`, `new_result_prepared`, `previous_result_still_available`을 구분한다. 기존 결과가 ready로 남았어도 새 준비가 실패하면 종료 코드 2다. refresh의 성공 여부는 지정한 사진으로 판단하고 전체 갤러리 준비율은 별도로 기록한다.

Context의 요약·제목·설명에 알려진 opaque photo ID가 노출되면 구조 검증에서 거부한다. 32자리 hex·UUID, 숫자를 포함한 16자 이상 식별자 형태를 완전한 영숫자 토큰 경계로 검사하며, 짧은 숫자·일반 단어 ID의 자연 문장 출현은 거부하지 않는다. 특정 데모 ID를 하드코딩하거나 문구를 자동 치환하지 않는다. 같은 검증을 준비 결과와 캐시 조회에 적용하므로 과거 구조 검증을 통과한 ID 노출 결과도 재준비가 필요하다.
