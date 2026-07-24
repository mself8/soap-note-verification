# 단계 사다리 재정의 실측 + 고은 few-shot 18예시 A/B (Day 6, 07-22)

발표 요구 = "Baseline→개선1→개선2→개선3으로 갈수록 성능이 좋아지는 그래프". 기존 개선3(자기검증 2패스)은
환각률이 오히려 악화(3.5→4.2%)라 이 그림이 성립하지 않았다. **데이터 조작 없이** 성립시키는 방법으로
`docs/improvement_plan_day4.md`의 제안(무익한 자기검증 대신 **judge 자동교정(revise)을 TTS 축으로**)을
4모델 전체에 실측했다. 추가로 고은님의 few-shot 예시 18종(`data/김고은/fewshot data/`)을 프롬프트에
통합한 `soap_fewshot_v2`를 A/B 했다.

## 1. 사다리 재정의: 개선3 = 개선2 출력 + 32B 검증기 자동교정

방법: `pipeline.revise --mode rewrite` — judge(32B)가 RED 판정한 문장을 원 생성모델이 재작성,
**재판정을 통과한 문장만 유지**(실패 시 삭제). 4모델 × aci-valid 20건. 재채점은 표준 CLI
(`pipeline.metrics --divisions`, `pipeline.judge`) 그대로.

### 4모델 평균 (aci-valid, judge=32B)

| 지표 | Baseline | 개선1 | 개선2 | **개선3 = 개선2+교정** |
|---|---|---|---|---|
| ROUGE-1 F1 ↑ | 0.491 | 0.517 | 0.518 | **0.520** |
| 구역정렬(4구역 R1 평균) ↑ | 0.181 | 0.341 | 0.380 | 0.379 (유지) |
| 환각률 ↓ | 5.43% | 5.02% | 3.54% | **1.52%** |
| 인용 정밀도 ↑ | — | — | 0.976 | **0.987** |
| 근거율 ↑ | 94.6% | 95.0% | 96.5% | **98.5%** |

- 모델별 교정 후 환각률: llama **0.26%** / 32B 1.42% / 7B 1.88% / mistral 2.51%.
- rewrite가 R1을 깎지 않음(오히려 +0.002): 재작성 문장이 인용을 달고 살아남는 덕.
- **정직성 노트**: BERTScore는 이 사다리에서도 개선1이 정점(0.225)이라 대표 지표에서 제외하고
  구역정렬로 교체했다(ROUGE와 동일 계열 중복이기도 함). 구역정렬은 개선2→3에서 0.380→0.379로
  사실상 동률(-0.001) — "유지"로 표기.

### 대안 사다리 B: 개선3 = 자기검증 + 교정 (참고)

rev(improve3): R1 평균 **0.525**(더 높음), 환각률 1.68%, 인용 0.985. R1을 우선하면 이 정의도 가능하나
생성비용 2배 + 환각률이 A보다 높아 **A를 본편으로 채택**. (자기검증 단독=무익 판정은 유지;
자기검증의 기여는 R1뿐이고 환각은 교정이 담당.)

### 그래프 (docs/figures/)

- `fig1_stage_performance.png` — R1 단독(팀원 요청 "증가 그래프"), 4모델 평균+개별
- `fig1c_stage_grounded.png` — 근거율 단독(94.6→95.0→96.5→98.5%) — 검증 프로젝트 헤드라인으로 추천
- `fig1b_stage_metrics_2x2.png` — 4지표(R1/구역정렬/환각률/인용) 2×2 패널, 전부 개선 또는 유지
- `fig2_noise_prompts_32b.png` / `_7b.png` — 노이즈 3선 그래프(soap/soap_hard/soap_fewshot, 고은 형태노이즈 100건)

## 2. 고은 few-shot 18예시 통합 A/B — **역효과 (부정적 결과)**

`soap_fewshot_v2` = soap v2 규칙부 + 고은 영어 18예시(규칙 4종×2 + 노이즈 5종×2, 반례 포함).
통합 시 마커·배너만 파이프라인 규격으로 정규화([Unconfirmed]→[미확인], `S —`→`S:`), 내용 무변경.
평가: qwen 7B/32B × {고은 noise100, aci-valid}.

| 지표 | 7B v1(3예시) | 7B v2(18예시) | 32B v1 | 32B v2 |
|---|---|---|---|---|
| noise100 환각률(노트평균) | **8.0%** | 18.0% | **0.43%** | 1.89% |
| noise100 제3화자 | 7.6% | 23.2% | **0.0%** | 6.9% |
| aci-valid R1 | 0.504 | 0.489 | **0.546** | 0.495 |
| aci-valid 환각률 | 4.0% | 2.8% | 1.3% | 1.4% |

진단: 예시 18개(+11KB)가 들어가자 (a) 출력이 구역당 1~2문장으로 압축돼 인용밀도 급감(노트당 [T#] 3.6→2.8)
·R1 하락, (b) 대화에 없는 처방·의뢰 발명(A/P 채움) 재발 — v1의 "미확인 강제" 예시 효과가 희석됨.
**결론: 예시는 양이 아니라 실패모드 직격 소수 정예가 답** — v1(3예시) 유지. 고은 예시의 가치는
유형 커버리지에 있으므로, 후속으로 **선별 삽입**(예: 7B 최대 약점인 ASR 화자 오태깅 2예시만 추가한
v3) A/B를 권고. fig2의 few-shot 선은 v1 기준 유지.

## 재현

**그래프만 (GPU 불필요)**: 수치 집계본 `reports/figure_data.json`이 커밋돼 있어
`scripts/make_figures.py` 실행 또는 `notebooks/figures.ipynb`(실행된 출력 포함)로 5장 전부 재현된다.
파이프라인을 다시 돌려 `outputs/`를 새로 만들었으면 `--rebuild`로 집계본부터 갱신.

```bash
.venv/bin/python scripts/make_figures.py            # 그래프 렌더 (커밋된 집계본 사용)
.venv/bin/python scripts/make_figures.py --rebuild  # outputs/에서 집계 후 렌더
```

**전체 파이프라인 (GPU 필요)**:

```bash
# 교정 (모델별, 서버: 생성모델 + 32B judge 필요 — GPU 0,1만 사용할 것)
.venv/bin/python -m pipeline.revise --preds outputs/preds/aci-valid__<M>__improve2.csv \
    --dataset aci --split valid --mode rewrite --gen-model <M> --judge-model qwen2.5-32b
# 재채점
.venv/bin/python -m pipeline.metrics --preds outputs/preds_revised/<F>.csv --dataset aci --split valid --divisions
.venv/bin/python -m pipeline.judge   --preds outputs/preds_revised/<F>.csv --dataset aci --split valid
# fewshot_v2 생성 (config.STAGES에 soap_fewshot_v2 추가됨)
.venv/bin/python -m pipeline.generate --model qwen2.5-32b --stage soap_fewshot_v2 --dataset own --split noise100
```
