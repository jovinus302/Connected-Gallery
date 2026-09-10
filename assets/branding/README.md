# Connected Gallery 앱 아이콘

2026-09-10. 세이지 배경에 겹친 사진 프레임과 풍경을 배치했다. 뒤쪽 프레임은 밝은 세이지, 앞쪽 사진은 아이보리로 표시한다. 사진을 출발점으로 다른 사진을 찾아가는 제품 흐름을 표현한다.

![컬러·단색·크기별 아이콘 미리보기](../../docs/images/android-icon-2026-09-10.png)

## 원본과 내보내기

- 실제 앱 원본: `android/app/src/main/res/drawable/ic_gallery_foreground.xml`
- 단색 테마 원본: `android/app/src/main/res/drawable/ic_gallery_monochrome.xml`
- 배경색: `android/app/src/main/res/values/icon_colors.xml`의 `#526B51`
- 적응형 아이콘: `android/app/src/main/res/mipmap-anydpi/ic_gallery.xml`
- `connected-gallery-icon.svg`: 배경 포함, 마스크 없는 아이콘 원본 내보내기
- `connected-gallery-icon-512.png`: 512px PNG
- `connected-gallery-mark.svg`: 투명 배경의 단색 심볼

SVG와 PNG는 Android 벡터에서 생성한다. 수정할 때는 Android 원본을 변경하고 `node scripts/render-launcher-icon.cjs`로 내보낸다. Node.js와 `sharp`가 필요하며, 번들 라이브러리를 사용하는 환경에서는 `NODE_PATH`를 해당 node_modules 폴더로 설정한다. 렌더러는 컬러·단색 버전의 도형이 일치하는지도 확인한다.

108dp 레이어, 중앙 안전 영역, 배경·전경·단색 레이어는 [Android 공식 적응형 아이콘 가이드](https://developer.android.com/develop/ui/compose/system/icon_design_adaptive)를 따른다. 앱 최소 버전이 API 26이므로 기본 anydpi 리소스를 사용한다. 미리보기의 원형·둥근 사각형과 테마 색상은 검수용 예시이며 실제 모양과 단색 테마 색은 런처 설정에 따른다.

## 적용 검증

- `:app:assembleDebug :app:lintDebug` 통과. Lint 오류 0개, 기존 경고 6개.
- Android 벡터로 만든 컬러·단색·어두운 테마 및 64/48/32px 미리보기 확인.
- Galaxy S23 Ultra의 애플리케이션 정보에서 설치된 아이콘 표시 확인.
- 최종 APK의 SHA-256을 기기에서 대조한 뒤 기존 데이터 유지 설치 완료.
- APK SHA-256: `c3755471cbb0fafef3c597c2f2ff6b39e89910d57e1f7e8886767c1214ace208`

최종 APK와 미리보기는 `outputs/android-icon/connected-gallery-icon-debug.apk`, `outputs/android-icon/connected-gallery-icon-preview.png`에 보관한다. 검수 로그와 기기 캡처도 같은 outputs 폴더에 있다.

저장소에서 볼 수 있는 미리보기는 위 `docs/images/` 사본이다. 재생성 후 문서 이미지를 갱신하려면 다음 명령을 사용한다.

```powershell
node scripts/render-launcher-icon.cjs
Copy-Item outputs/android-icon/connected-gallery-icon-preview.png docs/images/android-icon-2026-09-10.png
```

화면 변경과 이전 APK 기록은 [Android 디자인·검증 문서](../../docs/android-design-2026-09-10.md)에 정리했다.
