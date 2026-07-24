"""2인 교차채점 일치도 (E3 · 계획서 §5-4).

애매사례(함정셋 20건 등)를 팀원 2인이 독립 이진/범주 채점 → 일치율 + Cohen's kappa.
입력 CSV 2개(같은 item_id 집합): 컬럼 item_id, label
  실행: python -m pipeline.interrater --a rater1.csv --b rater2.csv

sklearn 미설치 → kappa 직접 계산.
"""
import argparse

import pandas as pd


def cohen_kappa(a, b):
    """관측일치도 po, 우연일치도 pe → (po-pe)/(1-pe)."""
    n = len(a)
    labels = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    return po, kappa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="rater1 CSV (item_id,label)")
    ap.add_argument("--b", required=True, help="rater2 CSV (item_id,label)")
    args = ap.parse_args()

    da = pd.read_csv(args.a).set_index("item_id")["label"]
    db = pd.read_csv(args.b).set_index("item_id")["label"]
    common = da.index.intersection(db.index)
    if len(common) == 0:
        raise SystemExit("공통 item_id 없음 — 두 파일의 item_id 집합 확인")

    a = [str(da[i]) for i in common]
    b = [str(db[i]) for i in common]
    po, kappa = cohen_kappa(a, b)
    print(f"공통 항목: {len(common)}")
    print(f"단순 일치율: {po:.3f}")
    print(f"Cohen's kappa: {kappa:.3f}")
    print("해석: kappa <0.2 미미 / 0.2-0.4 약함 / 0.4-0.6 보통 / 0.6-0.8 상당 / >0.8 거의완전")


if __name__ == "__main__":
    main()
