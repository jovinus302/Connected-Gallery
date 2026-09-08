// A presentation fixture, not a recorded run or a model's private reasoning.
// Matches the model/tools loop and one bounded review refinement in runner.py.
export const chapters = [
  {start:0,label:'탐색의 시작'}, {start:3,label:'관찰 → 다음 행동'},
  {start:7,label:'검토와 피드백'}, {start:9,label:'다시 탐색'}, {start:16,label:'확인과 정리'}
];
export const steps = [
  {agent:'explorer',phase:'decide',round:1,title:'어디서부터 찾을까.',description:'선택한 와인 사진을 출발점으로 시각 검색 도구를 선택합니다.',label:'선택한 도구',evidence:'search_visual',photos:[],caption:'선택한 대상에서 시작하는 첫 번째 행동.',duration:4300},
  {agent:'explorer',phase:'tool',round:1,title:'도구에 일을 맡기고.',description:'검색 도구가 사진 인덱스에서 시각적으로 비슷한 후보를 가져옵니다.',label:'도구 실행 예시',evidence:'search_visual → 후보 2장',photos:[4,3],caption:'Agent가 선택한 행동을 도구가 실행합니다.',duration:3900},
  {agent:'explorer',phase:'observe',round:1,title:'결과를 받아본다.',description:'사진 ID와 검색 점수가 agent에게 돌아옵니다. 검색된 후보는 아직 관련성이 확인된 결과가 아닙니다.',label:'도구의 응답',evidence:'후보 ID · 검색 점수',photos:[4,3],caption:'도구의 출력이 agent에게 돌아옵니다. ↻',duration:4300},
  {agent:'explorer',phase:'decide',round:2,title:'이번에는 직접 보자.',description:'검색 결과를 관찰한 뒤, 후보 사진을 직접 확인하는 도구를 선택합니다.',label:'다음 행동',evidence:'inspect_photos',photos:[4,3],caption:'같은 loop, 달라진 행동. 검색에서 이미지 확인으로.',duration:4300},
  {agent:'explorer',phase:'tool',round:2,title:'사진을 펼쳐보고.',description:'사진 확인 도구가 후보의 실제 이미지와 저장된 정보를 가져옵니다.',label:'도구 실행 예시',evidence:'inspect_photos → 이미지 2장',photos:[4,3],caption:'도구는 자료를 가져오고, agent는 다음 행동을 선택합니다.',duration:3900},
  {agent:'explorer',phase:'observe',round:2,title:'관찰을 쌓는다.',description:'후보 이미지를 입력으로 받습니다. 독립 검토에서는 이 후보와 원본 대상을 다시 비교합니다.',label:'도구의 응답',evidence:'후보 이미지 · 사진 정보',photos:[4,3],caption:'새로운 관찰이 다음 모델 입력에 더해집니다. ↻',duration:4200},
  {agent:'explorer',phase:'submit',round:2,title:'후보를 건넨다.',description:'탐색 agent가 후보 목록을 제출합니다. 아직 사용자에게 보여줄 최종 결과는 아닙니다.',label:'제출 도구',evidence:'submit_exploration_result',photos:[4,3],caption:'탐색의 제안을 독립적인 검토에 전달합니다.',duration:4300},
  {agent:'reviewer',phase:'review',round:2,title:'정말 관련이 있을까.',description:'렌즈가 원본의 와인과 후보를 비교합니다. 이 예시에서는 두 후보 모두 직접적인 관련 근거가 부족합니다.',label:'독립 검토 예시',evidence:'지원된 후보 0장 · 결과 불완전',photos:[4,3],verdict:'rejected',caption:'검색된 사진과 근거가 확인된 사진은 다릅니다.',duration:5100},
  {agent:'reviewer',phase:'feedback',round:2,title:'근거와 함께 돌아간다.',description:'선택 대상은 유효하고 예산이 남아 있습니다. 첫 검토의 피드백을 받아 한 번 더 탐색합니다.',label:'이 시연의 재탐색 조건',evidence:'대상 유효 · 첫 검토 · 남은 실행 예산',photos:[],caption:'검토 → 탐색: 근거가 부족할 때의 조건부 귀환.',duration:5600},
  {agent:'explorer',phase:'decide',round:3,title:'단서를 더 구체적으로.',description:'검토 피드백을 받아 원래 선택한 와인에 맞춰 검색 요청을 조정합니다. 탐색 대상은 바뀌지 않습니다.',label:'조정한 검색 예시',evidence:'search_visual · 빨간 원 라벨의 와인병',photos:[],caption:'피드백이 바꾸는 것은 검색 행동. 선택한 대상은 그대로.',duration:4500},
  {agent:'explorer',phase:'tool',round:3,title:'다시 찾아본다.',description:'수정한 검색으로 식사 자리와 와인 진열대의 새로운 후보 사진을 가져옵니다.',label:'도구 실행 예시',evidence:'search_visual → 새 후보 2장',photos:[1,2],caption:'새로운 요청으로 같은 도구를 다시 사용합니다.',duration:3900},
  {agent:'explorer',phase:'observe',round:3,title:'새 후보가 돌아온다.',description:'새로 찾은 후보가 agent에게 돌아옵니다. 사진을 직접 확인하는 다음 행동으로 이어집니다.',label:'도구의 응답',evidence:'새 후보 ID · 검색 점수',photos:[1,2],caption:'검색 결과 → 관찰 → 다음 행동. ↻',duration:4200},
  {agent:'explorer',phase:'decide',round:4,title:'원본과 함께 확인하자.',description:'새 후보의 실제 이미지를 확인하도록 도구를 선택합니다.',label:'다음 행동',evidence:'inspect_photos',photos:[1,2],caption:'두 번째 탐색에서도 이미지 확인을 생략하지 않습니다.',duration:4000},
  {agent:'explorer',phase:'tool',round:4,title:'후보의 이미지를 연다.',description:'원본 와인의 특징과 비교할 수 있도록 후보 사진 두 장을 가져옵니다.',label:'도구 실행 예시',evidence:'inspect_photos → 새 이미지 2장',photos:[1,2],caption:'사진 확인 도구에서 새로운 관찰 자료를 가져옵니다.',duration:3900},
  {agent:'explorer',phase:'observe',round:4,title:'관찰에서 제출로.',description:'선택한 와인과 비교할 이미지가 준비되었습니다. 확인한 후보를 제출할 수 있습니다.',label:'도구의 응답',evidence:'식사 사진 · 와인 진열 사진',photos:[1,2],caption:'충분한 관찰을 얻으면 탐색 loop에서 빠져나옵니다.',duration:4200},
  {agent:'explorer',phase:'submit',round:4,title:'확인할 후보를 다시.',description:'새 후보 두 장을 제출합니다. 독립 검토가 원본과 후보의 관계를 다시 확인합니다.',label:'제출 도구',evidence:'submit_exploration_result',photos:[1,2],caption:'새 후보와 근거를 검토 agent에게 전달합니다.',duration:4200},
  {agent:'reviewer',phase:'review',round:4,title:'연결의 근거를 확인.',description:'이 예시에서는 두 사진에서 원본과 비교할 와인병의 라벨과 형태를 확인합니다. 검토를 통과한 후보가 남습니다.',label:'독립 검토 예시',evidence:'supported · 후보 2장',photos:[1,2],verdict:'supported',caption:'독립 검토를 통과한 후보만 결과 정리로 넘어갑니다.',duration:5000},
  {agent:'organizer',phase:'organize',round:4,title:'관계가 있는 자리로.',description:'검토된 후보를 「함께한 식사」와 「와인을 발견한 곳」으로 구성합니다. 정리와 검증이 끝난 묶음을 보여줍니다.',label:'결과 정리 예시',evidence:'함께한 식사 / 와인을 발견한 곳',photos:[1,2],verdict:'supported',caption:'검은 모듈이 확인된 사진에 관계와 자리를 만듭니다.',duration:5200},
  {agent:'organizer',phase:'done',round:4,title:'다음 사진으로 연결.',description:'한 번의 피드백과 네 번의 도구·관찰 왕복 끝에, 관련 사진 두 장과 연결 이유가 남았습니다.',label:'이 시연의 결과',evidence:'관련 사진 2장 · 검토 후 재탐색 1회',photos:[1,2],verdict:'supported',caption:'Loop의 끝에는 사진과 확인된 연결 이유가 남습니다.',duration:4500}
];

export function currentChapter(index) {
  return chapters.reduce((found, chapter, i) => index >= chapter.start ? i : found, 0);
}

export class Playback {
  constructor(onChange, reducedMotion = false) {
    this.index = 0; this.elapsed = 0; this.speed = 1; this.playing = false;
    this.reducedMotion = reducedMotion; this.onChange = onChange;
  }
  emit() { this.onChange(this); }
  seek(index) { this.index = Math.max(0, Math.min(steps.length - 1, Math.round(index))); this.elapsed = 0; this.playing = false; this.emit(); }
  toggle() {
    if (this.index === steps.length - 1 && !this.playing) { this.index = 0; this.elapsed = 0; }
    this.playing = !this.playing; this.emit();
  }
  tick(delta) {
    if (!this.playing) return;
    this.elapsed += Math.min(delta, 250) * this.speed;
    if (this.elapsed >= steps[this.index].duration) {
      this.elapsed = 0;
      if (this.index < steps.length - 1) this.index++;
      if (this.index === steps.length - 1) this.playing = false;
      this.emit();
    }
  }
}
