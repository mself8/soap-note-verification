# SOAP Note Verification

진료 대화(비정형 텍스트) → **SOAP 노트**(EMR 등재 단위) 변환에서, "차팅 자동화"가 아니라 **"차팅 검증 자동화"**에 초점을 둔다. 즉 자동 생성된 SOAP 노트가 EMR에 신뢰 가능하게 등재되도록 **환각 방지 + 근거(citation) 추적**을 붙인다.

인공지능 커리어패스 1조 팀 프로젝트. 이 레포는 **1일차(7/16) 데이터·전제 검증** 결과물이다.

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
data/                             (gitignore) MTS-Dialog, aci-bench
```

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
