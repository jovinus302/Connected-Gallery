// Illustrative public actions and observations, never a model thought transcript.
export function storyFor(step) {
  const later=step.round>=3,ids=later?[1,2]:[4,3];
  const isSearch=step.round===1||step.round===3;
  const request=isSearch?(later?'빨간 원 라벨의 와인병':'선택한 와인과 비슷한 사진'):'후보 사진 2장 직접 확인';
  const observation=step.round===1?'선택한 원본에서 시작':step.round===3?'받은 피드백 · 와인병 자체의 근거 부족':'도구 → Explorer · 후보 ID 2개 + 검색 점수';
  let story={shot:step.phase,station:0,camera:'WIDE',request,observation,photos:ids,original:false,focus:false,verdict:'candidate',payload:{direction:'none',title:'',detail:''}};
  if(step.phase==='decide') {
    story.photos=isSearch?[0]:ids;story.original=isSearch;story.camera=later?'PUSH IN':'WIDE';
    story.payload={direction:'outbound',title:isSearch?'검색 요청':'이미지 확인 요청',detail:request};
  } else if(step.phase==='tool') {
    story.shot=isSearch?'search':'inspect';story.camera=isSearch?'TRACK RIGHT':'PUSH IN';story.focus=!isSearch;
    story.payload={direction:'outbound',title:isSearch?'검색 도구 실행':'사진 확인 도구 실행',detail:isSearch?'사진 인덱스에서 후보 찾기':'후보의 실제 이미지 가져오기'};
  } else if(step.phase==='observe') {
    story.shot='return';story.camera='FOLLOW BACK';story.focus=!isSearch;
    story.payload={direction:'return',title:isSearch?'후보 ID 2개 + 검색 점수':'후보 이미지 2장',detail:isSearch?'다음 행동 · 사진을 직접 확인':'다음 행동 · 관찰한 후보를 제출'};
    story.observation=`도구 → Explorer · ${story.payload.title}`;
  } else if(step.phase==='submit') {
    story.camera='TRACK RIGHT';story.station=12;story.payload={direction:'handoff',title:'검토할 후보 2장',detail:'아직 최종 결과가 아닙니다'};
  } else if(step.phase==='review') {
    story.station=12;story.camera='CLOSE UP';story.photos=[0,...ids];story.original=true;story.focus=true;story.verdict=later?'supported':'rejected';
    story.payload={direction:'none',title:'원본과 후보를 독립 비교',detail:later?'라벨과 병의 형태 확인':'원본 와인과의 직접적인 근거 부족'};
    story.observation=later?'독립 검토 · 관련성 확인':'독립 검토 · 관련성 미확인';
  } else if(step.phase==='feedback') {
    story.station=0;story.camera='FOLLOW CLUE';story.photos=[];
    story.payload={direction:'feedback',title:'와인병 자체의 근거 부족',detail:'원본 대상 유지 · 검색 단서를 구체화'};
    story.observation='첫 검토 · 후보 전부 미통과 · 불완전 · 대상 유효 · 예산 남음';story.request='다음 검색 · 빨간 원 라벨의 와인병';
  } else if(step.phase==='organize'||step.phase==='done') {
    story.station=24;story.camera=step.phase==='done'?'PULL BACK':'TRACK RIGHT';story.photos=[1,2];story.verdict='supported';
    story.payload={direction:'none',title:'확인된 사진만 정리',detail:'함께한 식사 / 와인을 발견한 곳'};story.observation='최종 결과 · 관련 사진 2장 · 검토 후 재탐색 1회';
  }
  return story;
}
export const photoNames=['선택한 와인','와인과 함께한 식사','와인을 발견한 곳','야외 인물','커피와 디저트','해변 인물'];
// Storyboard highlights in the generated sheet, not model detections.
export const photoRegions={0:[34,5,28,86],1:[4,15,32,83],2:[40,3,31,95]};
