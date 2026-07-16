"""평가 전제 검증 — 계획서 §5-2의 핵심 가정을 우리 손으로 재계산한다.

계획서 §5-2 주장:
  "ROUGE / BERTScore ... 두 지표 모두 원 데이터셋 논문에서 사람 채점과의 상관관계가
   확인된 지표이므로, 별도의 타당성 검증 없이 채택 근거를 확보한다."

그런데 그 상관은 '전체 factual F1'과의 상관이다. 이 프로젝트의 주제는 '환각(hallucination)'이다.
- '노트 전체 품질과의 상관'과 '환각률과의 상관'은 다른 문제.
- 문헌상 ROUGE는 factuality/hallucination과 상관이 약한 것이 정설.
따라서 우리가 실제로 쓰려는 방식(환각을 잡는 스크리닝)에 ROUGE가 유효한지는 별도 확인이 필요하다.

원자료(둘 다 400행, 위치 정렬):
  - MTS-Dialog-Automatic-Summaries-ValidationSet.csv : 4모델 × 100대화 생성 요약 (블록형: ID 0..99 ×4)
  - MTS-Dialog-Manual-Scores4CorrelationStudy.csv     : 같은 순서의 사람 채점
    (FactualPrecision/Recall/F1, HallucinationRate, OmissionRate, EditDistance)

실행: python recon/correlation_check.py
"""

import csv
import math
from pathlib import Path

csv.field_size_limit(10**7)
ROOT = Path(__file__).resolve().parent.parent
CS = ROOT / "data" / "MTS-Dialog" / "Correlation-Study"


def load(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = math.sqrt(sum((a - mx) ** 2 for a in x))
    vy = math.sqrt(sum((b - my) ** 2 for b in y))
    return cov / (vx * vy) if vx and vy else float("nan")


auto = load(CS / "MTS-Dialog-Automatic-Summaries-ValidationSet.csv")
man = load(CS / "MTS-Dialog-Manual-Scores4CorrelationStudy.csv")
assert len(auto) == len(man) == 400, (len(auto), len(man))

# 위치 조인 무결성: auto는 블록형(ID 0..99 4회)이어야 함
ids = [r["ID"] for r in auto]
assert ids[0:100] == ids[100:200] == ids[200:300] == ids[300:400], "블록 정렬 깨짐"
print(f"[조인] 400행 위치 정렬 확인. auto는 4모델 블록형(ID 0..99 ×4), man은 동일 순서.\n")

man_f = {k: [float(r[k]) for r in man] for k in
         ["FactualPrecision", "FactualRecall", "FactualF1", "HallucinationRate", "OmissionRate"]}

# ---- ROUGE
from rouge_score import rouge_scorer  # noqa: E402

scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
rouge = {"rouge1": [], "rouge2": [], "rougeL": []}
for r in auto:
    s = scorer.score(r["Reference Summary"], r["Automatic Summary"])
    for k in rouge:
        rouge[k].append(s[k].fmeasure)
print("[ROUGE] 400개 요약 재계산 완료.")

# ---- BERTScore (설치돼 있을 때만)
bert = None
try:
    from bert_score import score as bscore  # noqa: E402
    cands = [r["Automatic Summary"] for r in auto]
    refs = [r["Reference Summary"] for r in auto]
    print("[BERTScore] roberta-large 계산 중… (최초 1회 모델 다운로드)")
    _, _, F1 = bscore(cands, refs, lang="en", verbose=False, rescale_with_baseline=True)
    bert = F1.tolist()
    print("[BERTScore] 완료.\n")
except Exception as e:
    print(f"[BERTScore] 스킵 (사유: {type(e).__name__}: {e}). ROUGE만 보고.\n")

metrics = dict(rouge)
if bert:
    metrics["BERTScore-F1"] = bert

# ---- 상관 표
print("=" * 84)
print("자동지표 × 사람채점 Pearson r  (n=400)")
print("=" * 84)
head = "자동지표\\사람채점  " + "".join(f"{k:>16}" for k in man_f)
print(head)
print("-" * len(head))
for mk, mv in metrics.items():
    row = f"{mk:18}"
    for hk in man_f:
        row += f"{pearson(mv, man_f[hk]):>16.3f}"
    print(row)

print("\n" + "=" * 84)
print("해석 — 이 프로젝트에 직접 걸리는 질문")
print("=" * 84)

for mk, mv in metrics.items():
    r_f1 = pearson(mv, man_f["FactualF1"])
    r_hal = pearson(mv, man_f["HallucinationRate"])
    print(f"\n{mk}:")
    print(f"  · FactualF1 과의 |r| = {abs(r_f1):.3f}   ← §5-2가 채택 근거로 든 '전체 품질' 상관")
    print(f"  · HallucinationRate 과의 r = {r_hal:+.3f}   ← 우리가 실제로 잡으려는 것")
    if abs(r_hal) < 0.4:
        print(f"    ⚠ 환각률과의 상관이 약함(|r|<0.4). '{mk} 하나로 환각 스크리닝'은 근거 부족.")
        print(f"      → LLM-as-a-judge(문장단위 이진)이 주 지표, {mk}는 보조여야 함.")

print("\n" + "=" * 84)
print("결론")
print("=" * 84)
print("""\
- ROUGE/BERTScore는 '노트가 정답과 얼마나 겹치는가'(전체 품질)의 대리지표로는 근거가 있으나,
  '환각을 일으켰는가'와의 상관은 위 표의 HallucinationRate 열로 직접 판단해야 한다.
- 이 프로젝트의 주장(차팅 '검증' 자동화)은 환각·누락을 잡는 것이므로,
  §5-2의 자동지표는 '전체 유사도 확인용'으로 위치를 좁히고,
  환각·누락은 LLM-judge 이진판정 + 함정셋의 금지문장 검출률(계획서 §5-3)로 측정하는 것이
  데이터와 정합적이다.
- 이 스크립트가 산출한 r 값을 MTS-Dialog 논문(EACL 2023) Table의 보고값과 대조하면,
  우리 재현이 맞는지까지 확인된다.""")
