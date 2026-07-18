# SOAP Note Verification

진료 대화(비정형 텍스트) → **SOAP 노트**(EMR 등재 단위) 변환에서, "차팅 자동화"가 아니라 **"차팅 검증 자동화"**에 초점을 둔다. 즉 자동 생성된 SOAP 노트가 EMR에 신뢰 가능하게 등재되도록 **환각 방지 + 근거(citation) 추적**을 붙인다.

인공지능 커리어패스 1조 팀 프로젝트. 1일차(7/16) 데이터·전제 검증 → 파이프라인 구축 → **본평가(7/18) 완료** 순으로 진행 중.

---

## 현재 상태 (07-18 본평가) — [`docs/eval_results_day3.md`](docs/eval_results_day3.md)

**4모델 × 5단계 × ACI valid 전체(20건)** 격자 + **검증기 함정셋** 완료:

- 모델: **32B 최강**(환각 2.0%) / 7B급 1위는 **mistral-7b**. 추천 조합 = 생성 mistral(또는 32B) + 검증 32B judge.
- 단계: baseline→improve2가 결정적(구역정렬+환각 개선). **improve3(자기검증)는 무익 → 폐기 권고**. `soap` = 최종 출력규격.
- **함정셋(신규 `pipeline/perturb.py`)**: gold에 심은 환각 139개 중 judge가 **90.6% 검출**(날조 100%·스왑 96.6%·수치 91.4%·부정뒤집기 74.3%). gold 오탐율 9.1% — 모델 환각률 2~5%는 사람 기준선보다 낮음.
- test1~3(120건) 확장 배치 진행 중. 상세 수치·해석은 위 문서.

---

## TL;DR — 1일차에 데이터로 확인한 것

계획서(`1조 프로젝트 정리`)의 사실 주장을 실제 데이터와 대조했다. **A/B/C가 공통으로 딛고 선 전제 중 3개가 데이터와 어긋났고, 셋 다 지금 고치는 편이 프로젝트에 유리하다.**

| # | 계획서 주장 | 데이터 실측 | 조치 |
|---|---|---|---|
| 1 | MTS-Dialog은 정보 없으면 `N/A` 표기 → "미확인 명시"가 이미 채택된 관행 | **0 / 1,301행.** N/A 전무 | "미확인 명시"를 물려받는 관행이 아니라 **우리 기여**로 재프레이밍 → 오히려 강해짐 |
| 2 | MTS-Dialog으로 SOAP 노트 생성 평가 | 1행 = 6턴·63단어 → 14단어 요약. **4파트 노트 불가** | **ACI-Bench 주 / MTS-Dialog 보조**로 확정 |
| 3 | "환자 발화→S, 의사 발화→O/A" | ACI 첫 대화가 반례(의사 구술 병력이 S로 감) | 규칙축을 화자 → **발화행위(speech act)**로 교체 |
| 4 | ROUGE/BERTScore는 "검증 없이 채택" 가능 | FactualF1 상관 0.40~0.52 ✓ 이지만 **환각률 상관 ≈ 0** (−0.05~−0.10) | 자동지표는 유사도·누락용으로 축소, **환각은 LLM-judge가 담당** |

4번이 오늘 최고 임팩트 → [`docs/evaluation_premise_check.md`](docs/evaluation_premise_check.md).

---

## 재현

```bash
# 1) 데이터 (레포엔 미포함 — 각자 clone, .gitignore에 data/)
mkdir -p data && cd data
git clone --depth 1 https://github.com/abachaa/MTS-Dialog.git
git clone --depth 1 https://github.com/wyim/aci-bench.git
cd ..

# 2) 환경 (전용 venv — 아래 '환경 함정' 참고)
python3 -m venv .venv && . .venv/bin/activate
pip install rouge-score==0.1.2 nltk bert-score torch --index-url https://download.pytorch.org/whl/cpu
# (torch는 CPU 휠, bert-score는 최초 실행 시 roberta-large ~1.4GB 다운로드)

# 3) 검증 스크립트
python recon/verify_claims.py       # 위 표 1~3의 숫자 전부 재현
python recon/correlation_check.py   # 위 표 4: ROUGE/BERTScore ↔ 사람채점 Pearson r
```

## 구성

```
recon/verify_claims.py        데이터 규모·구조·N/A·입도·화자태그·섹션스키마 실측 (주장 1~3)
recon/correlation_check.py    ROUGE/BERTScore × 사람채점 상관 재계산 (주장 4)
docs/A_data_and_noise_types.md    §10-A: 데이터 역할 + 잡음/함정 유형(실측 빈도 기반)
docs/B_rules_and_prompts.md       §10-B: 규칙 4종(발화행위/hedge/미확인/citation) gold 대조
docs/C_own_data_construction.md   §10-C: 자체데이터 스키마·음성라벨·분량 현실성
docs/evaluation_premise_check.md  평가 전제 재계산 결과 (오늘의 핵심)
docs/eval_results_day3.md         본평가(07-18) 격자·함정셋 결과 정리
pipeline/                         §10-D 백엔드 + §10-E 평가 (아래 '파이프라인' 참고)
pipeline/perturb.py               검증기 함정셋 — gold에 교란 주입 → judge 검출률
pipeline/translate.py             구조보존 한글 번역(배너·[T#] 고정, 문장만 번역)
prompts/                          단계별 프롬프트(baseline→improve1→2→3→soap, judge). B가 최종 확정
scripts/serve_vllm.sh             로컬 vLLM 서빙(모델별)
web/                              웹 플레이그라운드(FastAPI+단일 HTML) — 데모·정성확인용
data/                             (gitignore) MTS-Dialog, aci-bench
outputs/, reports/                (gitignore) 생성노트·점수·judge·비교표
```

## 파이프라인 (D+E) — 다중모델 SOAP 검증

**설계**: 모델-불가지 `chat()` + 프롬프트파일 단계 + 스코어러가 바로 먹는 CSV. 모델 비교 = `pipeline/config.py`의 `MODELS` 한 줄 추가.

**2-환경 분리**: 생성은 `.venv-vllm`(GPU, vLLM 서버), 평가는 이 레포의 `.venv`(CPU, rouge/bert + `openai`). preds CSV로만 핸드오프.

```bash
# 0) 준비: 평가 venv에 openai 추가 / 생성용 vLLM venv (최초 1회)
.venv/bin/pip install openai
python3.10 -m venv .venv-vllm && .venv-vllm/bin/pip install vllm

# 1) 모델 서빙 (GPU. huggingface.co 직접. flashinfer 샘플러 off는 스크립트에 내장)
bash scripts/serve_vllm.sh qwen2.5-7b 0        # GPU0, 포트8001
bash scripts/serve_vllm.sh qwen2.5-32b 0,1     # judge용 32B는 tp=2

# 2) 생성 (D1·D2·D3) — 단계는 프롬프트파일로만 갈림
.venv/bin/python -m pipeline.generate --model qwen2.5-7b --stage baseline --dataset aci --split valid --limit 3
.venv/bin/python -m pipeline.generate --model qwen2.5-7b --stage improve2 --dataset aci --split valid
# stage ∈ baseline|improve1|improve2|improve3(=improve2+자기검증)|soap(최종규격 S/O/A/P+인라인 인용)

# 3) 평가 (D4 ROUGE/BERTScore, D5 LLM-judge)
.venv/bin/python -m pipeline.metrics --preds outputs/preds/aci-valid__qwen2.5-7b__improve2.csv --dataset aci --split valid --divisions
.venv/bin/python -m pipeline.judge   --preds outputs/preds/aci-valid__qwen2.5-7b__improve2.csv --dataset aci --split valid --judge-model qwen2.5-32b

# 4) 비교표 (E1·E4): outputs/를 격자로 → reports/comparison.{md,csv} + failures.md
.venv/bin/python -m pipeline.report

# 5) 검증기 함정셋: gold에 교란(부정뒤집기·수치변조·스왑·날조) 주입 → judge 검출률
.venv/bin/python -m pipeline.perturb --dataset aci --split valid

# 자체 함정셋(E2, C데이터 대기): pipeline.own_metrics --preds … --traps …
# 2인 교차채점(E3): pipeline.interrater --a r1.csv --b r2.csv

# 웹 플레이그라운드(데모): vLLM 서버들 띄운 뒤
.venv/bin/uvicorn web.server:app --host 0.0.0.0 --port 8000
```

- **환각은 judge가 주지표**(1일차 결론: ROUGE/BERTScore는 환각률과 상관≈0 → 유사도·누락 대리). judge=강한 모델 1개(Qwen2.5-32B) 고정.
- **citation**: precision·turn-match만 측정(recall은 gold 부재, docs/B §B-4).
- **vLLM 함정**: 이 머신엔 시스템 CUDA 없음 → flashinfer 샘플러 JIT 실패. `serve_vllm.sh`가 `VLLM_USE_FLASHINFER_SAMPLER=0`으로 우회(greedy라 동등).

## 재사용 — 새로 짜지 말 것

`data/aci-bench/`에 **MEDIQA-Chat 공식 스코어러가 이미 있다**. 계획서 §10-D의 "ROUGE/BERTScore 자동 계산 스크립트"는 자작 불필요:

- `evaluation/evaluate_fullnote.py` — ROUGE / BERTScore / BLEURT / UMLS concept F1
- `metric/rouge.py`, `evaluation/semantics.py`, `evaluation/data_statistics.py`

공식 채점기를 쓰면 선행연구 수치와 직접 비교 가능(자작 스크립트로는 불가). 자체 데이터도 ACI 스키마(`dataset, encounter_id, dialogue, note`)에 맞추면 이 스코어러를 그대로 적용.

## 환경 함정

- **전용 venv 필수**: aci-bench `requirements.txt`가 `rouge-score==0.1.2` / `bert-score==0.3.12` / `evaluate==0.4.0` / `nltk==3.8.1` / `spacy==3.4.4` 등 구버전 핀 → 시스템 conda의 `transformers 5.0.0`과 충돌. 격리 필수.
- **UMLS concept F1 보류**: `quickumls`는 UMLS 라이선스 계정 필요 → 당장은 ROUGE/BERTScore만.
- **BLEURT 스킵 권장**: git 설치 + TF 의존, 무거움.
- **API 키 없음**: `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` 미설정 → baseline LLM 실행은 키 발급 후.

## 팀 회의 안건 (2일차 조율용)

1. `N/A` 근거 소멸 → §3-1 문장 수정, "미확인 명시"를 기여로 재프레이밍
2. MTS-Dialog 역할 재정의 → §5-5 수정(ACI 주/MTS 보조)
3. 발화주체 규칙 → §10-B를 화자×발화행위 매핑으로 교체
4. §5-2 자동지표 → "유사도·누락용"으로 위치 축소, 환각은 §5-3(LLM-judge)로
5. 자체 데이터 50건 사람 작성 분량 → 파일럿 1건 실측 후 §9 일정 재산정
6. hedge 규칙에 **i2b2 2010 assertion 6분류** 채택 여부 (기성 표준 → 방어 유리)

## 데이터 출처

- **MTS-Dialog** — Ben Abacha et al., *An Empirical Study of Clinical Note Generation from Doctor-Patient Encounters*, EACL 2023. github.com/abachaa/MTS-Dialog
- **ACI-Bench** — Yim et al., *ACI-BENCH: a Novel Ambient Clinical Intelligence Dataset*, Nature Scientific Data 2023. github.com/wyim/aci-bench
- 둘 다 의료배경 어노테이터가 만든 **합성 데이터**(실제 환자 아님) → IRB·개인정보 이슈 없음.
