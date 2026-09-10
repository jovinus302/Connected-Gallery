# Connected Gallery · Astra film

**최근 수정본:** 전환·Agent 동작·설명 가독성에 대한 사용자 피드백을 반영한 [93초 두 번째 편집](v2/README.md). 아래 파일과 기록은 1차 54초 버전을 보존한 것이다.

사진 속 와인을 선택하고, 근거를 비교한 결과에서 식당을 열고, 사진 전체의 맥락을 본 뒤 사람을 선택해 바닷가로 이어지는 **54초·35숏·1920×1080·24fps** 홍보 영상이다. 2026-09-10 승인 기획을 Blender 5.2.1 LTS / Eevee로 제작했다. 내레이션은 없으며 음악과 효과음은 이번 작업에서 직접 합성했다.

## 파일

| 파일 | 용도 |
|---|---|
| [connected-gallery-astra.mp4](connected-gallery-astra.mp4) | H.264 / AAC 본편 |
| [connected-gallery-astra.blend](connected-gallery-astra.blend) | 수정 가능한 3D 장면, 카메라, 재질, 조명, 35개 숏, 한글 문구 |
| [connected-gallery-edit.blend](connected-gallery-edit.blend) | 렌더 이미지 시퀀스와 음원의 최종 편집, 3D 장면도 함께 보존 |
| [scenario.md](scenario.md) | 제작 전 제안과 콘티 원문 |
| [proposition.md](proposition.md) | 제작 의도·불변 조건·검증 계획 |
| [validation.md](validation.md) | 이번 실행의 검증과 한계 |
| [timeline.json](timeline.json) | 숏 ID, 시간, 프레임, 기준 사진, 후보 범위 |
| [sources.md](sources.md) | 사진·글꼴·음악·모델 출처 |

전체 PNG 시퀀스와 무압축 음원은 저장소 루트의 `outputs/astra-film/frames/`와 `outputs/astra-film/score.wav`에 있다. 대용량 중간 산출물은 Git에서 제외한다. 로컬 납품 ZIP에는 이 시퀀스와 원본·문서·스크립트가 같은 상대 경로로 포함된다. ZIP을 풀고 `docs/presentations/astra-film/connected-gallery-edit.blend`를 열면 시퀀스 경로가 맞는다. 3D 원본은 이미지 시퀀스 없이도 다시 렌더링할 수 있다.

3D 원본에는 사진 시트, 사용한 한글 글꼴, 합성 음원이 포함되어 있다. 장면의 Collection 이름은 `S01`부터 `S31`까지이며 추가 비교 숏은 `S19a/b`, `S24a/b/c`, `S28a/b`로 구분한다. 타임라인 마커로 각 컷에 이동할 수 있다. 원본 파일의 화면은 카메라 뷰로 확인한다. VSE 편집 장면은 `Final edit / image sequence + original score`다.

## 재현

Windows 기본 설치의 Blender 5.2, NumPy와 Pillow가 있는 Python을 사용한다. 빌드 시 `C:/Windows/Fonts/malgun.ttf`, `malgunbd.ttf`를 읽고 문서에 포함한다. 다른 환경에서는 해당 글꼴 경로를 사용 가능한 한글 글꼴로 지정해야 한다. 저장된 `.blend`를 여는 데는 별도 글꼴 설치가 필요하지 않다.

저장소 루트에서 실행한다. 아래 `python`은 NumPy/Pillow가 있는 Python, `blender`는 설치된 Blender 실행 파일을 가리킨다.

```powershell
python scripts/astra-film/score.py
blender -b --python-exit-code 1 --python scripts/astra-film/film.py -- --mode build
blender -b --python-exit-code 1 --python scripts/astra-film/verify_scene.py
blender -b --python-exit-code 1 --python scripts/astra-film/film.py -- --mode preview --percent 25 --samples 16
python scripts/astra-film/verify_media.py --preview
blender -b --python-exit-code 1 --python scripts/astra-film/film.py -- --mode render --samples 32
blender -b --python-exit-code 1 --python scripts/astra-film/film.py -- --mode encode
python scripts/astra-film/verify_media.py
```

`--mode stills --frames 45,324,462,774,924,1020,1182,1272 --percent 100 --samples 32`로 대표 프레임만 출력할 수 있다. 전체 렌더는 이미 존재하는 프레임을 건너뛴다. **장면이나 샘플 설정을 바꾼 경우 이전 출력 폴더를 별도로 보관하고 빈 출력 폴더에서 시작해야 한다.** 수정한 장면에 오래된 프레임을 섞지 않는다.

움직이는 구간은 24fps로 계산한다. 시뮬레이션·시간 기반 셰이더·드라이버가 없는 이 장면에서 모든 애니메이션 속성 값이 정확히 같은 프레임은 기존 렌더를 재사용한다. 프레임을 생략하거나 보간하지 않으며, 정지 구간의 노이즈가 흔들리지 않게 한다. 재사용 근거는 `frames/render-evidence.json`에 남긴다.

## 제작 의미

와인 검색의 첫 후보 4·3은 그 와인 주장에 대해 모두 미지원이다. 결과가 불완전하고 원본 선택이 유효하며 실행 예산이 남아 있는 **이번 고정 예시**에서 한 번 재탐색한다. 원본 선택을 유지한 채 라벨 단서를 구체화한다. 성공이나 재탐색을 보장하는 기능 설명이 아니다.

식당을 여는 행동, 사람을 선택하는 행동, 바닷가를 여는 행동은 각각 새 기준을 만든다. 사진 전체 맥락은 Connect 결과 정리와 별도의 후보 확보·전체 이미지 관찰·독립 검토를 거친다. Organizer가 임의의 새 사진을 만들어 넣지 않는다. 마지막 탐색 경로의 선은 `0–1 라벨`, `0–2 라벨`, `1–4 설정 날짜`, `1–5 사람`, `5–3 사람` 다섯 개다.

생성 사진·가상 날짜·고정 시나리오 표시를 본편에 유지한다. 영상 속 판정은 실제 모델 실행 결과, 내부 사고, 실측 속도, 물리적으로 동일한 와인병, 구매·소유·친족·동일 사건의 증명이 아니다. 마지막의 **Made with Astra · Blender / Eevee**는 이 영상의 제작 크레딧이다.
