"""ROUGE + BERTScore — 생성note vs gold note (D4). recon/correlation_check.py 패턴 재사용.

  python -m pipeline.metrics --preds outputs/preds/aci-valid__qwen2.5-7b__baseline.csv \
      --dataset aci --split valid [--divisions]

자동지표는 '유사도·누락 대리'로만 본다(1일차 결론: 환각률과 상관 ≈0). 환각은 judge가 담당.
인라인 [T#] citation 태그는 채점 전 제거(gold엔 없으므로 공정성). 출력: outputs/scores/<preds-stem>.json
"""
import argparse
import json
import re
import sys

import pandas as pd

from . import config, dialogue

_CITE = re.compile(r"\s*\[T\d+(?:\s*,\s*T?\d+)*\]")  # "[T3]" / "[T3, T5]"
_UNKNOWN = "[미확인: not mentioned in conversation]"


def strip_citations(text):
    return _CITE.sub("", text or "")


def _rouge(preds, refs):
    from rouge_score import rouge_scorer
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    acc = {"rouge1": [], "rouge2": [], "rougeL": []}
    for p, r in zip(preds, refs):
        s = scorer.score(r, p)
        for k in acc:
            acc[k].append(s[k].fmeasure)
    return {k: round(sum(v) / len(v), 4) for k, v in acc.items()} if preds else {}


def _bertscore(preds, refs):
    try:
        from bert_score import score as bscore
        _, _, F1 = bscore(preds, refs, lang="en", verbose=False, rescale_with_baseline=True)
        return round(float(F1.mean()), 4)
    except Exception as e:  # noqa: BLE001
        print(f"[bertscore 스킵] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _divisions(texts):
    """SectionTagger로 노트를 SOAP 4구역 텍스트로 분할(라이선스 無 부분만 사용)."""
    sys.path.insert(0, str(config.DATA / "aci-bench" / "baselines"))
    from sectiontagger import SectionTagger  # noqa: E402
    tagger = SectionTagger()
    keys = ["subjective", "objective_exam", "objective_results", "assessment_and_plan"]
    out = []
    for t in texts:
        parts = {k: "" for k in keys}
        try:
            for sec in tagger.divide_note_by_metasections(t):
                parts[sec[0]] = t[sec[-3]:sec[-1]]
        except Exception:  # noqa: BLE001 — 헤더 없으면 전체가 subjective로 감
            parts["subjective"] = t
        out.append(parts)
    return out, keys


def score_file(preds_csv, dataset, split, do_divisions=False):
    pred_df = pd.read_csv(preds_csv)
    gold = {r["encounter_id"]: r["note"] for r in dialogue.load(dataset, split)}

    preds, refs, missing = [], [], 0
    for _, row in pred_df.iterrows():
        ref = gold.get(row["encounter_id"])
        if ref is None:
            missing += 1
            continue
        preds.append(strip_citations(str(row["note"])))
        refs.append(str(ref))
    if missing:
        print(f"[정렬 경고] gold에서 못 찾은 encounter {missing}건 — encounter_id 확인", file=sys.stderr)

    result = {"preds_file": str(preds_csv), "n": len(preds), **_rouge(preds, refs)}
    result["bertscore_f1"] = _bertscore(preds, refs)

    if do_divisions and preds:
        pv, keys = _divisions(preds)
        rv, _ = _divisions(refs)
        result["divisions"] = {
            k: _rouge([p[k] for p in pv], [r[k] for r in rv]) for k in keys
        }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--dataset", default="aci", choices=["aci", "mts", "own", "dysem"])
    ap.add_argument("--split", default="valid")
    ap.add_argument("--divisions", action="store_true", help="SOAP 4구역별 ROUGE도 계산")
    args = ap.parse_args()

    res = score_file(args.preds, args.dataset, args.split, args.divisions)
    config.SCORES.mkdir(parents=True, exist_ok=True)
    stem = args.preds.split("/")[-1].rsplit(".", 1)[0]
    out = config.SCORES / f"{stem}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"[metrics] 저장 → {out}")


if __name__ == "__main__":
    main()
