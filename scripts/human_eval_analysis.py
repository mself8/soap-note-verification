# -*- coding: utf-8 -*-
"""사람 라벨(E3) 분석 — 평가자 간 일치도 + judge 검증

팀원 2인(고은·다연)이 동일한 150문장에 대해 독립 채점한 결과를 사용해
  1) 사람끼리 얼마나 일치하는가 (Cohen's kappa) — 과제 난이도의 상한선
  2) 우리 32B judge가 사람 기준으로 얼마나 정확한가 (정확도·정밀도·재현율)
를 산출한다. judge 판정은 봉인해 둔 judge_key(사람에게 비공개)에서 읽는다.

  .venv/bin/python scripts/human_eval_analysis.py
출력: reports/human_eval_results.json (+ 표준출력 요약)
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SHEETS = {"goeun": ROOT / "data/human_eval/human_eval_sheet_goeun (1).csv",
          "dayeon": ROOT / "data/human_eval/human_eval_sheet_dayeon (1).csv"}
KEY = ROOT / "outputs/human_eval/judge_key_DO_NOT_SHARE.csv"
OUT = ROOT / "reports/human_eval_results.json"

GCOL, CCOL = "human_grounded(Y/N)", "human_citation_ok(Y/N/NA)"


def cohen_kappa(a, b):
    n = len(a)
    labels = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return po, ((po - pe) / (1 - pe) if pe < 1 else 1.0)


def binary_scores(truth, pred):
    """truth/pred = grounded 여부 bool 리스트. '환각 탐지'를 양성으로 본 지표."""
    tp = sum(1 for t, p in zip(truth, pred) if not t and not p)   # 둘 다 환각
    fp = sum(1 for t, p in zip(truth, pred) if t and not p)       # 멀쩡한데 환각이라 함
    fn = sum(1 for t, p in zip(truth, pred) if not t and p)       # 환각인데 놓침
    tn = sum(1 for t, p in zip(truth, pred) if t and p)
    n = len(truth) or 1
    return {"accuracy": round((tp + tn) / n, 4),
            "halluc_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "halluc_recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def main():
    sheets = {k: pd.read_csv(v).set_index("item_id") for k, v in SHEETS.items()}
    key = pd.read_csv(KEY).set_index("item_id")
    common = sheets["goeun"].index.intersection(sheets["dayeon"].index).intersection(key.index)
    # [미확인] 마커 줄은 '내용 문장'이 아니라 부재 표기 — judge는 근거있음으로,
    # 사람은 환각으로 본 채점기준 불일치가 생기므로 비교에서 제외한다.
    marker = [i for i in common if "미확인" in str(sheets["goeun"].loc[i, "sentence"])
              or "확인:" in str(sheets["goeun"].loc[i, "sentence"])]
    common = [i for i in common if i not in marker]
    res = {"n_items": len(common), "excluded_marker_rows": len(marker)}

    # 1) 평가자 간 일치도
    ga = [str(sheets["goeun"].loc[i, GCOL]).strip().upper() for i in common]
    da = [str(sheets["dayeon"].loc[i, GCOL]).strip().upper() for i in common]
    po, k = cohen_kappa(ga, da)
    res["interrater"] = {"agreement": round(po, 4), "kappa": round(k, 4),
                         "goeun_N": ga.count("N"), "dayeon_N": da.count("N")}

    # 2) judge vs 사람. judge_key의 label: grounded/ungrounded
    jl = [str(key.loc[i, "label"]).strip().lower() for i in common]
    judge = [x.startswith("g") or x in ("true", "y", "yes") for x in jl]
    human = {"goeun": [x == "Y" for x in ga], "dayeon": [x == "Y" for x in da]}
    res["judge_vs_human"] = {who: binary_scores(h, judge) for who, h in human.items()}

    # 두 사람이 합의한 항목만(신뢰 구간이 가장 단단한 부분집합)
    agree_idx = [n for n, (x, y) in enumerate(zip(ga, da)) if x == y]
    res["judge_vs_consensus"] = binary_scores(
        [human["goeun"][n] for n in agree_idx], [judge[n] for n in agree_idx])
    res["judge_vs_consensus"]["n_items"] = len(agree_idx)

    # 2-b) judge가 환각이라 찍은 문장을 사람이 얼마나 확인해 주는가
    #      (표본이 환각 농축 설계라 코퍼스 전체 비율로 읽으면 안 된다)
    flagged = [n for n, i in enumerate(common) if str(key.loc[i, "label"]).strip().upper() == "N"]
    res["judge_flagged_confirm_rate"] = {
        who: round(sum(1 for n in flagged if not h[n]) / len(flagged), 4) if flagged else None
        for who, h in human.items()}
    res["judge_flagged_n"] = len(flagged)

    # 3) 참고: 인용 적절성(NA 제외)
    cit = {}
    for who, sh in sheets.items():
        vals = [str(sh.loc[i, CCOL]).strip().upper() for i in common]
        ok = [v for v in vals if v in ("Y", "N")]
        cit[who] = {"labeled": len(ok),
                    "citation_ok_rate": round(ok.count("Y") / len(ok), 4) if ok else None}
    res["human_citation"] = cit

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\n저장 → {OUT}")


if __name__ == "__main__":
    main()
