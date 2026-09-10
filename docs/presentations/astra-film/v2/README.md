# Connected Gallery · 동작과 읽는 시간을 고친 두 번째 편집

1차 영상의 끊기는 전환, 짧게 끝나는 Agent 동작, 읽기 어려운 설명에 대한 사용자 피드백을 반영한 **93초·1080p·24fps** 편집이다. 제작 과정과 관찰 증거는 [proposition.md](proposition.md), [validation.md](validation.md)에 구분해 기록한다. 기존 54초 영상은 상위 폴더에 그대로 남는다.

카메라 한 대와 같은 Agent가 작업을 이어간다. Explorer의 발·몸·팔이 움직이고, 운반 중 손끝이 사진을 따라간다. Reviewer는 원본과 후보 방향으로 이동해 차례로 비교한다. Organizer는 바닥을 따라 이동하며 팔로 사진을 받쳐 옮긴다. 마지막 크레딧 전까지 구도를 순간 교체하는 컷이 없다. 핵심 문구는 화면 위의 고정된 자리에서 한 문장씩 4~12초 유지한다.

| 파일 | 용도 |
|---|---|
| [connected-gallery-astra.mp4](connected-gallery-astra.mp4) | 수정본 H.264 / AAC 영상 |
| [connected-gallery-astra.blend](connected-gallery-astra.blend) | 사진·글꼴·음원이 포함된 편집 가능한 3D 원본 |
| [connected-gallery-edit.blend](connected-gallery-edit.blend) | 전체 프레임 시퀀스와 오디오의 최종 편집 |
| [timeline.json](timeline.json) | 문구 구간, 실제 행동 순서, 사진 접촉 구간 |
| [scene-validation.json](scene-validation.json) | 평가된 3D 위치·접촉·사진 범위 검사 |
| [media-validation.json](media-validation.json) | 전체 프레임·MP4·오디오 검사 |
| [delivery-validation.json](delivery-validation.json) | 편집본의 프레임 경로·포함된 사진·글꼴·음원 검사 |
| [repair-validation.json](repair-validation.json) | 피드백 전달 동작의 106프레임 수정 범위와 반영 기록 |
| [package-validation.json](package-validation.json) | 전체 편집 패키지의 파일 수·CRC·SHA-256 |

무압축 이미지 시퀀스와 음원은 저장소 루트의 `outputs/astra-film/v2/frames/`, `outputs/astra-film/v2/score.wav`에 있다. 전체 편집 패키지는 같은 상대 경로를 유지한다. 3D 원본은 렌더 시퀀스 없이도 다시 렌더할 수 있다.

## 다시 제작하기

Blender 5.2.1 LTS / Eevee, NumPy와 Pillow가 있는 Python을 사용한다. 사진·글꼴·시각 디자인은 기존 제작에서 재사용하며, 새 서비스·사진 생성·외부 음원은 없다. 출처와 제품 의미는 상위 [sources.md](../sources.md), [README.md](../README.md)의 설명을 따른다.

```powershell
blender -b --python-exit-code 1 --python scripts/astra-film/film_v2.py -- --mode build
blender -b --python-exit-code 1 --python scripts/astra-film/verify_v2.py
blender -b --python-exit-code 1 --python scripts/astra-film/film_v2.py -- --mode preview --end 384 --percent 50 --samples 16
blender -b --python-exit-code 1 --python scripts/astra-film/film_v2.py -- --mode encode-preview --end 384
python scripts/astra-film/verify_media_v2.py --preview --seconds 16
blender -b --python-exit-code 1 --python scripts/astra-film/film_v2.py -- --mode render --samples 16
blender -b --python-exit-code 1 --python scripts/astra-film/film_v2.py -- --mode encode
python scripts/astra-film/verify_media_v2.py
blender -b --python-exit-code 1 --python scripts/astra-film/verify_delivery_v2.py
python scripts/astra-film/package_v2.py
```

빌드가 시간표와 그에 맞춘 음원을 함께 만들고 원본에 포함한다. 최종 렌더의 첫 16초로 프리뷰를 다시 만들려면 `--mode preview-from-final`을 사용한다. 장면이나 샘플을 바꿨다면 기존 출력 폴더를 보관하고 새 빈 폴더에서 렌더해야 한다. 이전 렌더 프레임을 새 장면과 섞지 않는다.

납품 해상도는 네이티브 1920×1080이며 Eevee 16샘플을 사용한다. 32샘플과 같은 첫 구도의 사진·텍스트·유리 영역을 비교하고 실제 프레임을 확인했다. 사진 내부 평균 차이는 8비트 채널 기준 약 0.045다. [render-quality-check.json](render-quality-check.json)에 비교 범위와 한계를 남겼다. 모든 픽셀이 같거나 재질 노이즈가 없다는 주장은 아니다.

형식·접촉·시간 검사 결과와 관객의 감상은 별개다. 사용자의 첫 피드백은 1차 영상의 자연스러움과 가독성에 대한 실패 증거로 보존한다. 2차 검사 PASS가 사용자의 미적 만족이나 실제 모델 성능을 확정하지 않는다.
