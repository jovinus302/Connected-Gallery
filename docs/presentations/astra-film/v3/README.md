# Agent 소개와 회전하는 3D 역할 표시

처음 보는 사람이 세 Agent의 역할을 이해하도록 7초 소개를 추가하고, 같은 미니어처가 오른쪽 위로 이동해 본편 내내 현재 담당과 행동을 안내한다. 100초, 1920×1080, 24fps.

- **탐색 / Explorer:** 관련 사진을 찾고 직접 확인한다.
- **검토 / Reviewer:** 원본과 후보의 연결 근거를 확인한다. 첫 검토의 피드백 장면에는 `검토 → 탐색`을 표시한다.
- **정리 / Organizer:** 확인된 사진을 묶어 보여준다.

미니어처는 v2의 실제 Agent 메시에서 가져왔다. 활동 중인 심볼만 천천히 좌우로 회전하며, 쉬는 심볼은 각도를 유지하고 크기·색의 강조를 낮춘다. 한글 이름·영어 이름·현재 행동 문구는 회전하지 않는다. 사용자 선택 구간은 특정 Agent를 강조하지 않는다. 본편 마지막 크레딧에서는 안내판을 숨긴다.

본편 93초는 v2 MP4를 입력으로 합성한다. 기존 장면·사진·자막·소리의 순서는 유지하며, 음원도 영상과 함께 7초 이동한다. 소개의 짧은 음악은 같은 음원의 첫 구간을 낮은 음량으로 사용한다. MP4 재인코딩이 있으므로 본편 영상 바이트가 v2와 동일하다는 뜻은 아니다. 원본 파일 자체의 SHA-256 보존은 별도로 검사한다.

## 파일

| 파일 | 용도 |
|---|---|
| [connected-gallery-astra.mp4](connected-gallery-astra.mp4) | 완성 영상 |
| [connected-gallery-roles.blend](connected-gallery-roles.blend) | 글꼴·형상·재질·애니메이션을 포함한 3D 안내 장면 |
| [connected-gallery-edit.blend](connected-gallery-edit.blend) | v2 영상·음원과 안내 장면의 최종 합성 |
| [timeline.json](timeline.json) | 소개 길이, 역할 문구, 초·프레임 단위 전환 시점, 입력 해시 |
| [plan.md](plan.md) | 사용자 의도와 작업 계획 |
| [scene-validation.json](scene-validation.json) | 역할 전환·정지·화면 범위·기존 사진과 자막의 비겹침 검사 |
| [media-validation.json](media-validation.json) | 최종 MP4와 모든 RGBA 프레임 검사 |
| [delivery-validation.json](delivery-validation.json) | 편집 파일의 프레임·음원 경로와 포함된 글꼴 확인 |
| [validation.md](validation.md) | 실제 확인한 범위와 최종 영상에서 추출한 화면 |

중간 RGBA 프레임은 `outputs/astra-film/v3/overlay/`에 있으며 Git에서 제외된다. 합성 Blender 파일은 이 프레임과 같은 저장소의 v2 MP4를 상대 경로로 참조한다. 다른 컴퓨터에서는 아래 명령으로 프레임을 재생성한 뒤 합성 파일을 열거나 MP4를 인코딩할 수 있다. 3D 안내 원본은 중간 프레임 없이도 열린다.

## 재현

저장소 루트에서 Blender 5.2.1 LTS와 NumPy·Pillow가 설치된 Python을 사용한다. 제작 스크립트를 다시 실행할 때 Windows의 맑은 고딕 글꼴을 사용하며, 완성 3D 원본에는 글꼴이 포함돼 있다.

```powershell
$blender = '.\.runtime\tools\blender-5.2.1-windows-x64\blender.exe'
& $blender -b --python-exit-code 1 --python scripts/astra-film/film_v3.py -- --mode build
& $blender -b --python-exit-code 1 --python scripts/astra-film/verify_v3.py
& $blender -b --python-exit-code 1 --python scripts/astra-film/film_v3.py -- --mode render
& $blender -b --python-exit-code 1 --python scripts/astra-film/film_v3.py -- --mode encode
python scripts/astra-film/verify_media_v3.py
& $blender -b --python-exit-code 1 --python scripts/astra-film/verify_delivery_v3.py
```

장면을 다시 만들거나 해상도를 바꾼 경우 기존 `overlay` 폴더를 보관한 뒤 새 폴더에서 렌더한다. 다른 장면의 중간 프레임이 섞이지 않도록 렌더 설정의 해시를 검사한다. 중단된 동일 장면은 `--start`와 `--end`로 구간을 지정해 이어서 출력할 수 있다.

이 영상은 설명용 고정 시나리오다. 새 모델 실행이나 개인 사진 사용을 추가하지 않는다. 기술적 검사와 제작자 화면 검수는 실제 관객의 이해도나 사용자 최종 승인을 대신하지 않는다.
