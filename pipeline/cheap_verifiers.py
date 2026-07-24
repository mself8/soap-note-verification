"""저비용 검증기 ablation (C안) — "환각 탐지에 32B LLM이 꼭 필요한가?"

함정셋(perturb)의 동일 표본·동일 방법론으로 4개 검증기를 정면 비교:
  judge      : 32B LLM 문장별 판정 (traps jsonl에 기록된 판정 재사용)
  lexical    : 문장↔대화 턴 최대 token-F1 (모델 0개, 사실상 무료)
  embedding  : 문장↔대화 턴 최대 cosine (MiniLM-L6 22M, CPU)
  agreement  : 문장↔다른 모델들이 생성한 노트 문장 최대 token-F1 (모델 간 합의)

정답 라벨 = 교란 주입 여부(judge 의견이 아님). 평가는 perturb.py 공식 쌍대 방법론:
  - 임계값: gold 문장에서 judge와 동일한 오탐율이 나오도록 보정(동일 운영점)
  - 유효 쌍: 원문이 통과(judge=grounded / score≥thr)한 쌍만
  - sensitivity: 유효 쌍 중 교란문이 플래그된 비율 (유형별)
  - pairwise: score(교란문) < score(원문) 인 쌍 비율 (임계값 무관 보조지표)

실행: .venv/bin/python -m pipeline.cheap_verifiers
출력: outputs/scores/cheap_verifiers__aci-valid.json + 표준출력 마크다운 표
"""
import argparse
import json
import re
import time
from collections import Counter

import numpy as np

from . import config, dialogue
from .judge import _CITE_BLOCK, split_sentences

_WORD = re.compile(r"[a-z0-9']+")


def _tokens(s):
    return _WORD.findall(s.lower())


def token_f1(a_tokens, b_tokens):
    if not a_tokens or not b_tokens:
        return 0.0
    common = sum((Counter(a_tokens) & Counter(b_tokens)).values())
    if not common:
        return 0.0
    p, r = common / len(a_tokens), common / len(b_tokens)
    return 2 * p * r / (p + r)


def auc(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return None
    ranks = np.concatenate([pos, neg]).argsort().argsort()[:len(pos)] + 1
    u = ranks.sum() - len(pos) * (len(pos) + 1) / 2
    return round(float(u / (len(pos) * len(neg))), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traps", default=str(config.JUDGE_OUT / "traps__aci-valid.jsonl"))
    ap.add_argument("--split", default="valid")
    ap.add_argument("--others", default="qwen2.5-7b,llama3.1-8b,mistral-7b,qwen2.5-32b")
    ap.add_argument("--others-stage", default="soap")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.traps, encoding="utf-8")]
    gold = [r for r in rows if r["kind"] == "gold"]
    pairs = [r for r in rows if r["kind"] == "trap"]
    types = sorted({p["type"] for p in pairs})
    print(f"[cheap] gold {len(gold)}문장, 교란쌍 {len(pairs)} ({types})")

    recs = dialogue.load("aci", args.split)
    turns_txt = {r["encounter_id"]: [t["text"] for t in r["turns"]] for r in recs}

    # 채점 대상 텍스트: gold 문장 + 쌍의 원문/교란문
    items = [(r, "sent") for r in gold] + [(p, "original") for p in pairs] + [(p, "perturbed") for p in pairs]

    # ── lexical ──
    t0 = time.time()
    turn_toks = {e: [_tokens(t) for t in ts] for e, ts in turns_txt.items()}
    for obj, field in items:
        toks = _tokens(_CITE_BLOCK.sub("", str(obj[field] or "")))
        obj[f"lex_{field}"] = max((token_f1(toks, tt) for tt in turn_toks.get(obj["encounter_id"], [])), default=0.0)
    t_lex = time.time() - t0

    # ── embedding (MiniLM, CPU) ──
    from sentence_transformers import SentenceTransformer
    t0 = time.time()
    st_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    emb_turn = {e: st_model.encode(ts, normalize_embeddings=True, show_progress_bar=False)
                for e, ts in turns_txt.items()}
    texts = [_CITE_BLOCK.sub("", str(obj[field] or "")) for obj, field in items]
    embs = st_model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    for (obj, field), v in zip(items, embs):
        mat = emb_turn.get(obj["encounter_id"])
        obj[f"emb_{field}"] = float((mat @ v).max()) if mat is not None and len(mat) else 0.0
    t_emb = time.time() - t0

    # ── agreement (다른 모델 생성노트) ──
    import pandas as pd
    t0 = time.time()
    model_sents = {}
    used_models = []
    for m in args.others.split(","):
        p = config.PREDS / f"aci-{args.split}__{m}__{args.others_stage}.csv"
        if not p.exists():
            continue
        used_models.append(m)
        for row in pd.read_csv(p).itertuples(index=False):
            for s in split_sentences(row.note):
                model_sents.setdefault(row.encounter_id, []).append(_tokens(_CITE_BLOCK.sub("", s)))
    for obj, field in items:
        toks = _tokens(_CITE_BLOCK.sub("", str(obj[field] or "")))
        obj[f"agr_{field}"] = max((token_f1(toks, ms) for ms in model_sents.get(obj["encounter_id"], [])), default=0.0)
    t_agr = time.time() - t0

    # ── 평가 ──
    judge_gold_fpr = sum(1 for r in gold if r["grounded"] not in (True, "True")) / max(len(gold), 1)
    out = {"n_gold": len(gold), "n_pairs": len(pairs), "judge_gold_fpr": round(judge_gold_fpr, 4),
           "agreement_models": used_models, "others_stage": args.others_stage,
           "timing_s": {"lexical": round(t_lex, 1), "embedding": round(t_emb, 1), "agreement": round(t_agr, 1)},
           "verifiers": {}}

    header = ["verifier", "AUC(쌍)", "gold오탐", *types, "전체민감도", "pairwise"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]

    # fabrication은 '원문 없는 삽입형' — 유효쌍 필터를 적용하지 않고 무조건 평가
    real_pairs = [p for p in pairs if p["type"] != "fabrication"]
    for name, pfx in [("judge", None), ("lexical", "lex"), ("embedding", "emb"), ("agreement", "agr")]:
        if name == "judge":
            valid = [p for p in pairs if p["type"] == "fabrication"
                     or p["orig_grounded"] in (True, "True")]
            det = lambda p: p["pert_grounded"] not in (True, "True")  # noqa: E731
            a, pw, fp = None, None, judge_gold_fpr
        else:
            thr = float(np.percentile([r[f"{pfx}_sent"] for r in gold], judge_gold_fpr * 100))
            valid = [p for p in pairs if p["type"] == "fabrication" or p[f"{pfx}_original"] >= thr]
            det = lambda p: p[f"{pfx}_perturbed"] < thr  # noqa: E731
            a = auc([p[f"{pfx}_original"] for p in real_pairs], [p[f"{pfx}_perturbed"] for p in real_pairs])
            pw = round(sum(p[f"{pfx}_perturbed"] < p[f"{pfx}_original"] for p in real_pairs)
                       / max(len(real_pairs), 1), 3)
            fp = round(sum(1 for r in gold if r[f"{pfx}_sent"] < thr) / max(len(gold), 1), 4)
        res = {"auc": a, "gold_fp": fp, "pairwise": pw, "n_valid_pairs": len(valid)}
        for t in types:
            sub = [p for p in valid if p["type"] == t]
            res[t] = round(sum(det(p) for p in sub) / max(len(sub), 1), 3) if sub else None
        res["overall"] = round(sum(det(p) for p in valid) / max(len(valid), 1), 3)
        out["verifiers"][name] = res
        fmt = lambda v: "—" if v is None else (f"{v:.1%}" if isinstance(v, float) and v <= 1 else str(v))  # noqa: E731
        lines.append("| " + " | ".join([name, str(a) if a else "—", f"{res['gold_fp']:.1%}",
                                        *[fmt(res[t]) for t in types], fmt(res["overall"]), fmt(pw)]) + " |")

    print("\n".join(lines))
    dest = config.SCORES / "cheap_verifiers__aci-valid.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[cheap] 저장 → {dest}")


if __name__ == "__main__":
    main()
