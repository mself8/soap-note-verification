# 3축 보강안 — 프롬프트·컨텍스트·Test-Time Scaling (2026-07-20, 송윤)

팀 노이즈 평가(고은: noise100/ko60, 다연: dysem flat128/plus271)와 맞물리는 성능 보강.
다연 데이터의 8개 노이즈 범주는 정확히 우리 RULE 1~3(발화행위 라우팅·확신도 보존·미확인)을
겨냥한 공격이고, `forbidden_claims`/`unknown_required`가 정답 라벨이다. 각 축을 그 공격에
정면 대응시키고, 가능한 것은 실측까지 마쳤다.

## 1. 컨텍스트 축 — 보호자(guest) 화자 분리 [적용 완료]

**버그였다**: `_canon_speaker`가 `[patient_guest]`(보호자·가족)를 `patient`로 뭉개서
모델 입력에 "환자 발화"로 넣고 있었음 → **'타인 정보 혼입' 노이즈에 구조적으로 취약**.
- 수정: guest/caregiver/family/보호자·가족 → `guest` 역할로 분리 (transcript에 `[T#] guest:`),
  웹 채팅에도 보호자 버블(청록) 표시. 기존 오타태그 흡수(Guest_clinican→doctor)는 유지.
- 영향 범위: **고은 noise100의 24/100건**, ACI valid 1/20, dysem 2/128.
- ⚠️ 주의: 이 변경 후 생성/판정 트랜스크립트 표기가 바뀜 → **진행 중인 스윕과 섞지 말 것**.
  팀 스윕이 끝난 뒤 새 라운드부터 적용(또는 guest 포함 건만 재실행).

## 2. 프롬프트 축 — `soap_hard` 단계 신설 [적용 완료, 평가는 팀 하네스로]

soap(v2) + **RULE 5: 노이즈 방어 7규칙** — 8개 노이즈 범주에 1:1 대응:
거짓 전제(질문은 증거가 아님·부정되면 부정을 기록) / 환자 자기진단(S의 보고된 믿음으로,
의사가 승인할 때만 A) / 부정·극성 보존 / 조건부 계획은 조건부로 / 과거력 vs 현재 구분 /
타인(guest) 정보는 가족력·사회력까지만 / 차트↔진술 충돌 시 양쪽 병기.

- config 등록: `--stage soap_hard` (웹 드롭다운 "최종·강화")로 즉시 비교 가능.
- 스모크(qwen7b): 거짓전제 easy·타인정보 hard 각 1건에서 금지 주장 미단정 —
  단 soap도 통과했으므로 **변별은 전량 평가(특히 severity=hard)에서 판가름**.
  → 고은·다연 하네스에 stage 하나 추가해서 `baseline vs soap vs soap_hard` 3열 비교 권장.

## 3. 검증기(judge) — `judge_grounded_v2.txt` [파일만 추가, 스왑 보류]

함정셋에서 judge의 약점은 **부정 뒤집기 74.3%**였다. v2 = 극성 엄격 검사 + "질문의 전제는
근거 아님" 2줄 추가. **A/B 실측(부정쌍 35 + gold 150 표본, 32B)**:

| | negation 검출 | gold 오탐 |
|---|---|---|
| v1 (현행) | 74.3% | 14.7% |
| **v2** | **88.6% (+14.3pt)** | 16.7% (+2.0pt) |

- 판단: 검출 +14.3pt에 오탐 +2pt는 남는 장사. 단 **현행 파일은 교체 안 함**(팀 평가 일관성).
- 채택 절차 제안: 팀 스윕 종료 후 → 전체 함정셋(4유형)로 v2 재검 1회 → 이상 없으면
  `judge_grounded.txt` 교체 + 영향 받는 summary 재판정.

## 4. TTS 축 — "자기검증"이 아니라 "검증기 루프"로 재정의 [측정 완료, 재배치 제안]

- 실측 근거: improve3(자기검증 2패스)=무익(본평가), **revise(judge-guided 교정)=환각
  1.58→0.20%(-87%)·R1 손실 ~0** (`docs/eval_beyond_prompting.md`).
- 제안: 발표의 TTS 축을 improve3이 아니라 **"생성→judge→교정(2.5× 컴퓨트)"**로 세우고,
  improve3은 "같은 컴퓨트를 자기반성에 쓰면 안 된다"는 대조군으로 인용.
- 노이즈 데이터 예측: forbidden_claims야말로 judge가 잡는 대상 → **revise를 팀 노이즈
  preds에 적용하면 forbidden 검출률 하락 폭이 곧 결과 슬라이드**
  (`python -m pipeline.revise --preds <노이즈 preds> --dataset dysem --split flat128 --mode rewrite`).
- (여력 시) self-consistency k=3: temp 0.7 3표본 → 2/3 합의 문장만 유지. 설계만 해둠 —
  judge 없이 환각을 줄이는 대안 축이라 C(ablation)와 묶으면 얘기가 됨.

## 적용 요약 (팀 하네스 기준)

| 축 | 무엇 | 상태 | 팀이 할 일 |
|---|---|---|---|
| 컨텍스트 | guest 분리 | 코드 반영 | 새 라운드부터 적용(혼합 금지) |
| 프롬프트 | soap_hard | stage 등록 | 스윕에 stage 1개 추가 |
| 검증기 | judge v2 | 파일만 추가 | 스윕 후 함정셋 재검→스왑 결정 |
| TTS | revise 재배치 | 측정 완료 | 노이즈 preds에 revise 1회 |
