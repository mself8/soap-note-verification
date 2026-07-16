# 데이터 페이지 — 정송윤 (1일차 조사)

> MTS-Dialog·ACI-Bench를 실물로 받아 계획서 주장을 대조. 아래 숫자는 전부 재현 가능.
> 코드·재현: https://github.com/mself8/soap-note-verification (`python recon/verify_claims.py`, `correlation_check.py`)

## 1. 두 데이터셋 실측 요약

| | MTS-Dialog | ACI-Bench |
|---|---|---|
| 규모 | 1,701 (train 1,201 / val 100 / test1 200 / test2 200) ✓ | 207 (train 67 / val 20 / test1~3 각 40) ✓ |
| 1행 = | 6턴·63단어 스니펫 → 20헤더 중 1개 → 14단어 요약 | 1,240단어 full-visit 대화 → 415단어 전체 노트 |
| 화자태그 | `Doctor:` `Patient:` `Guest_family` (+오타 `Guest_clinican`) | `[doctor]` `[patient]` `[patient_guest]` |
| SOAP 노트 생성 | **불가** (1행당 섹션 1개) | 가능 |
| **우리 용도** | **보조** — 섹션매핑·hedge어휘·정정패턴 근거 | **주** — SOAP 생성·평가 |

- 둘 다 GitHub 레포에 데이터가 그대로 있음 → **figshare·승인 절차 불필요, 바로 clone**.
- 둘 다 의료배경 어노테이터가 만든 **합성 데이터**(실제 환자 아님) → IRB·개인정보 이슈 없음.

## 2. 계획서 대비 정정 (데이터로 확인)

**(1) MTS-Dialog "N/A 표기" 주장 → 실제 0건**
계획서 §3-1은 "정보 없으면 N/A 표기 → 미확인 명시 원칙이 이미 채택됨"이라 했는데, 라벨 공개 세트 **1,301행 전수에 N/A가 0건**. MTS-Dialog 1행은 "존재하는 섹션 하나"만 담아서 부재를 적을 자리 자체가 없음.
→ "미확인 명시"는 물려받는 관행이 아니라 **우리가 새로 도입하는 규약** = 기여 강화 포인트.

**(2) MTS-Dialog으로 SOAP 노트 생성 평가 → 구조상 불가**
1행 = 중앙값 6턴·63단어 → 14단어 요약, 섹션 1개. 4파트(S/O/A/P) 노트를 만들 원본이 없음.
→ **ACI-Bench 주 / MTS-Dialog 보조**로 확정.

## 3. 잡음(Noise) 유형 — ACI-Bench 실측 빈도 (n=207)

빈도 높음 = 벤치마크에 이미 있음(자체 제작 불필요), 낮음 = 자체 제작 가치.

| 잡음 유형 | ACI 실측 | 판단 |
|---|---|---|
| filler (um/uh/mm-hmm/yeah) | 207/207 (100%) | 이미 충분 |
| 정정·되묻기 (actually/sorry/i mean) | 155/207 (75%) | 이미 충분 |
| 발화 끊김 (`--` `...`) | 65/207 (31%) | 보강 여지 |
| 잡담·화제이탈 | 52/207 (25%) | 존재 |
| 제3화자 `[patient_guest]` | **5/207 (2%)** | **희소 → 자체 제작** |
| ASR 화자태그 **오류** | ACI 정제됨 / MTS엔 실제 오타 | **자체 재현 가치** |

→ 자체 잡음셋 우선순위: ① ASR 화자 오태깅 ② 보호자가 환자정보 대신 진술 ③ 시간순서 뒤섞임 ④ 수치 정정. (filler·구어체는 이미 100%라 만들 필요 없음.)

## 4. 평가용 원자료로 확인한 것 (오늘 핵심) — ROUGE/BERTScore는 환각을 못 잡는다

MTS-Dialog `Correlation-Study/`의 사람 채점 400건으로 자동지표 상관을 직접 재계산 (n=400, Pearson r):

| 자동지표 | FactualF1 | **HallucinationRate** | OmissionRate |
|---|---|---|---|
| ROUGE-1 | 0.401 | **−0.074** | −0.467 |
| ROUGE-L | 0.411 | **−0.073** | −0.465 |
| BERTScore-F1 | 0.516 | **−0.099** | −0.514 |

- 자동지표는 **누락엔 민감(−0.5)**, **환각엔 눈이 멀었음(≈0)**.
- 우리 프로젝트가 파는 건 환각 방지 → §5-2 자동지표는 "전체 유사도·누락 확인용"으로 위치를 좁히고, **환각은 LLM-as-a-judge + 함정셋 금지문장 검출률**로 측정해야 정합.

## 5. 재사용 발견

`data/aci-bench/evaluation/evaluate_fullnote.py` = MEDIQA-Chat **공식 스코어러**(ROUGE/BERTScore/BLEURT/UMLS). §10-D "ROUGE/BERTScore 자동계산 스크립트"는 자작 불필요. 자체 데이터도 ACI 스키마(`dataset, encounter_id, dialogue, note`)에 맞추면 그대로 적용.

---

*규칙 설계(발화행위·hedge·미확인·citation), 자체데이터 구축(스키마·음성라벨·분량)은 레포 `docs/B_*`, `docs/C_*` 참고.*
