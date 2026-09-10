# 제작 출처

| 요소 | 출처와 처리 |
|---|---|
| 사진 6장 | 기존 `docs/presentations/agent-loop/assets/gallery.png`의 3×2 시트. 새 사진 생성·외부 사진 추가·내용 합성 없음. 원본 시트를 그대로 포함하고 UV로 해당 사진과 확대 인서트를 표시 |
| 사진 의미·날짜 | 기존 pitch, Agent loop, `INTENT.md`, 제품 UX, runtime/context/organizer 계약을 검토한 `scenario.md`의 고정 예시. 사진 0=집 식탁, 1=식당, 2=매장, 3=거리, 4=카페, 5=바닷가 |
| Agent 시각 기준 | 기존 `agent-loop/assets/concept.png`. 따뜻한 크림 공간, 파란 유기체, 호박색 유리, 차콜 돌을 기준으로 새 3D 메시·재질·안무 제작 |
| 3D 공간·조명·오브젝트 | `scripts/astra-film/film.py`로 직접 구성. 외부 모델·유료 애셋·물리 시뮬레이션 없음 |
| 음악·효과음 | `scripts/astra-film/score.py`에서 고정 난수 시드와 파형 합성으로 제작한 54초 스테레오 PCM. 외부 녹음·음원·샘플·음성·유료 생성 서비스 없음 |
| 한글 글꼴 | 이 PC의 Microsoft 맑은 고딕 Regular/Bold. OS/2 `fsType=8`(editable embedding) 확인 후 `.blend` 문서에 포함. 별도 TTF 파일은 배포하지 않음 |
| 렌더·인코딩 | 설치된 Blender 5.2.1 LTS, 내장 Eevee와 VSE의 H.264/AAC 인코더. 외부 동영상 생성 서비스 없음 |
| 제작 크레딧 | `Made with Astra · Blender / Eevee` |

기존 Agent loop 검증 기록은 이전 제작의 증거다. 이번 영화의 출력·장면·매체 검증은 별도의 `validation.md`와 JSON 기록에 남긴다. 영화는 재현 가능한 연출 예시이며 실제 모델의 실행 기록을 녹화한 것이 아니다.
