# 본평가 결과 (07-18) — 4모델 × 5단계 격자 + 검증기 함정셋

> 산출물: `reports/comparison.{md,csv}`(격자), `outputs/scores/traps__aci-valid.json`(함정셋).
> outputs/·reports/는 gitignore — 수치는 이 문서에 고정, 재현은 아래 명령.

## 1. 설정

- **데이터**: ACI-Bench valid 전체 20건 (스모크 n=3 아님 — 본평가). test1~3(120건) 확장 배치 진행 중.
- **생성모델 4종**: Qwen2.5-7B / Llama-3.1-8B / Mistral-7B / Qwen2.5-32B (로컬 vLLM, greedy).
- **단계 5종**: baseline → improve1(프롬프트) → improve2(컨텍스트+citation) → improve3(+자기검증 2패스) → soap(최종규격 S/O/A/P).
- **판정**: 자동지표(ROUGE/BERTScore, 유사도·누락 대리) + **Qwen2.5-32B judge**(문장별 근거판정 → 환각률·citation precision·turn match). 환각은 judge가 주지표(1일차 결론).

## 2. 모델 격자 (valid 20건, improve2 기준)

| 모델 | ROUGE-1 | 환각률 | citation 정밀도 | turn 일치 |
|---|---|---|---|---|
| **qwen2.5-32b** | **0.535** | **0.020** | 0.981 | 0.806 |
| mistral-7b | 0.522 | 0.037 | 0.980 | **0.837** |
| llama3.1-8b | 0.522 | 0.037 | 0.984 | 0.688 |
| qwen2.5-7b | 0.492 | 0.048 | 0.961 | 0.690 |

- **32B 전 지표 최상** (단, judge=자기 자신 → self-preference caveat).
- **7B급 1위는 mistral**: 전 단계 환각률 일관되게 낮음(0.034~0.045) + turn 일치 최고. 문장별 인라인 인용을 가장 성실히 닮.
- qwen7b는 환각 최다(baseline 0.091). llama는 soap 단계에서 과소생성(평균 1,194자 → R1 0.419, 인용률 54%).
- 추천 조합: **생성 mistral-7b(또는 GPU 여유 시 32B) + 검증 32B judge**.

### 단계 효과

- **baseline→improve2가 결정적**: 구역 정렬 해결(32B objective_results 구역 R1 0 → 0.51 — baseline은 tagger가 못 읽는 마크다운 헤더 탓) + 환각 개선.
- **improve3(자기검증 2패스)는 무익**: 7B급 3종 모두 환각 오히려 소폭↑, ROUGE 제자리, 비용 2배 → 폐기 권고.
- **soap 단계**: 명시적 S/O/A/P 유지, R1 소폭 희생(허용 범위). 최종 출력규격으로 채택.

### 채점기 버그 수정 이력 (수치 해석 주의)

`pipeline/judge.py`의 문장분리가 **문단끝 몰아단 인용블록을 "빈 문장"으로 분리** → ungrounded 오판 + 실문장 무인용화. 수정(de2c5a2) 전 32B citation 정밀도 0.21은 전부 이 아티팩트(수정 후 전 모델 0.96~0.99). 07-18 이전에 뽑은 judge 수치는 폐기하고 이 문서 수치를 쓸 것.

## 3. 검증기 함정셋 (`pipeline.perturb`) — judge 자체의 성적표

gold 노트 20건에 **규칙기반 교란 147개**를 심고, 원문이 grounded로 판정된 유효 쌍 139개에서 32B judge 검출률 측정 (쌍대 설계 — gold 엄격성 혼입 제거):

| 함정 유형 | 유효 쌍 | 검출률 |
|---|---|---|
| 날조 삽입 (없는 병력·약물·검사) | 40 | **100%** |
| 부위/계열 스왑 (left↔right, hyper↔hypo …) | 29 | **96.6%** |
| 수치 변조 (혈압+40, 용량×2, 등급+2 …) | 35 | **91.4%** |
| 부정 뒤집기 (denies↔reports …) | 35 | **74.3%** |
| **전체** | **139** | **90.6%** |

- **약점 프로파일**: 놓친 13건 중 9건이 부정 뒤집기 — (a) 확실성 뒤집기("is not sure"→"is sure"), (b) 초압축 신체진찰 소견("No murmurs."→"Murmurs."). → judge 프롬프트에 극성(부정/확실성) 명시 대조 지시 추가가 다음 개선.
- **gold 오탐율 9.1%**: 사람이 쓴 gold 768문장도 9.1%는 "대화에 직접 근거 없음" 판정(의사의 표준관행 문구). **모델 환각률 2~5%는 이 기준선보다 낮음** — 발표 시 함께 제시할 것.

재현: `.venv/bin/python -m pipeline.perturb --dataset aci --split valid`

## 4. soap 프롬프트 v2 (인라인 인용 강제)

RULE 4 강화: 문장마다 개별 [T#] 필수, 문단 몰아달기 금지. valid 재생성 결과 **ROUGE 동등**(±0.005, llama만 +0.018) → 품질 손실 없이 인용 커버리지 확보. 커버리지·judge 수치는 test 확장 배치에서 갱신.

## 5. 진행 중 / 다음

- [진행 중] test1~3(120건) × {baseline, improve2, soap} × 4모델 — 생성·자동지표 완료, judge 배치 실행 중. 완료 시 이 문서에 test 격자 추가.
- [다음] ② 사람 라벨 vs judge kappa(`pipeline.interrater`, 문장 100~200개 × 2인) — 회의 안건.
- [다음] judge 프롬프트에 부정/확실성 극성 대조 추가 → 함정셋 재실행으로 개선 확인.
- [대기] C 함정 대화 데이터 오면 `pipeline.own_metrics`(생성기 대상 E2) 활성.
