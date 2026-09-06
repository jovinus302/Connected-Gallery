# 오픈소스 참고와 자체 설계

완성 앱/서버를 포크하거나 코드를 복사하지 않는다. 아래 프로젝트는 구조와 경계의 참고다.

| 출처 | 참고 | 자체 작성 |
|---|---|---|
| https://github.com/immich-app/immich | 사진 식별·분석 분리·삭제 전파 | 경량 SQLite 저장소와 API |
| https://github.com/drolosoft/immich-photo-manager | agent 도구의 이미지/검색 입출력 | GalleryTools와 제품 계약 |
| https://github.com/deckerst/aves | Android 갤러리·메타데이터·뷰어 | Kotlin MediaStore/Compose |
| https://github.com/openara-ai/media-search-agent | 로컬 embeddings·face 영역 | agentic 후보 retrieval |

LangGraph/LangChain, FastAPI, Pydantic, NumPy, Pillow, AndroidX, Hilt, Coil, Telephoto는 라이브러리로 재사용한다. 설치된 Python 버전은 requirements.lock, Android 버전은 Gradle에 기록한다.

모델: google/siglip2-base-patch16-224 (Apache2), intfloat/multilingual-e5-small (MIT), IDEA-Research/grounding-dino-tiny (Apache2), PaddleOCR (Apache2), OpenCV Zoo YuNet (MIT), SFace (해당 디렉터리 Apache2). 선택 모델의 출처·revision은 준비 스크립트가 기록한다.

https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface
https://huggingface.co/google/siglip2-base-patch16-224
https://huggingface.co/intfloat/multilingual-e5-small
https://huggingface.co/IDEA-Research/grounding-dino-tiny
https://github.com/PaddlePaddle/PaddleOCR

Immich의 InsightFace 허용 범위는 우리 앱에 이전된다고 가정하지 않으므로 사용하지 않는다. 모델과 코드 라이선스는 분리해서 확인한다. 배포물의 라이브러리 공지는 의존성 버전과 함께 유지한다.
