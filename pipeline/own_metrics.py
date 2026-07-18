"""자체 함정셋 환각률·누락회피실패율 (E2 · 계획서 §5-3).

C의 함정 데이터 스키마(docs/C §C-2):
  dataset, encounter_id, dialogue, note(gold, optional),
  forbidden_claims : JSON 리스트  # "나오면 안 되는" 의미명제
  unknown_required : JSON 리스트  # 미확인 처리돼야 할 항목

채점(judge 모델 entailment — exact-match 불가하므로):
  - 환각률          = 생성노트가 forbidden_claim 을 함의하는 비율
  - 누락회피실패율  = unknown_required 항목을 미확인표기 없이 채운 비율

※ C의 데이터 도착 시 활성화. 지금은 코드만 준비(계획서 스코프: 오늘 E2E는 ACI 기준).
  실행: python -m pipeline.own_metrics --preds <preds.csv> --traps <trap.csv> [--judge-model qwen2.5-32b]
"""
import argparse
import json

import pandas as pd

from . import clients, config

_ENTAIL = ("You check whether a clinical note asserts a specific claim.\n"
           "Answer ONLY 'yes' or 'no'. 'yes' = the note states or clearly implies the claim.")
_ENTAIL_USER = "NOTE:\n{note}\n\nCLAIM: {claim}\n\nDoes the note assert this claim?"

_UNKNOWN = ("You classify how a clinical note handles a topic.\n"
            "Answer ONE word: 'claim' (note makes a specific factual statement about it), "
            "'unknown' (note marks it not-mentioned/unconfirmed), or 'absent' (topic not present at all).")
_UNKNOWN_USER = "NOTE:\n{note}\n\nTOPIC: {topic}\n\nHow does the note handle this topic?"


def _yes(reply):
    return (reply or "").strip().lower().startswith("y")


def _first_word(reply):
    return (reply or "").strip().lower().split()[0] if reply else ""


def score_traps(preds_csv, traps_csv, judge_model):
    preds = {r["encounter_id"]: str(r["note"]) for _, r in pd.read_csv(preds_csv).iterrows()}
    traps = pd.read_csv(traps_csv)

    hall_hits = hall_total = 0
    omit_hits = omit_total = 0
    per_enc = []
    for _, t in traps.iterrows():
        enc = t["encounter_id"]
        note = preds.get(enc)
        if note is None:
            continue
        forbidden = json.loads(t.get("forbidden_claims") or "[]")
        unknown = json.loads(t.get("unknown_required") or "[]")

        h = sum(_yes(clients.chat(judge_model, _ENTAIL, _ENTAIL_USER.format(note=note, claim=c), max_tokens=5))
                for c in forbidden)
        o = sum(_first_word(clients.chat(judge_model, _UNKNOWN, _UNKNOWN_USER.format(note=note, topic=u), max_tokens=5)) == "claim"
                for u in unknown)

        hall_hits += h; hall_total += len(forbidden)
        omit_hits += o; omit_total += len(unknown)
        per_enc.append({"encounter_id": enc, "hallucinations": h, "of_forbidden": len(forbidden),
                        "omission_failures": o, "of_unknown": len(unknown)})

    return {
        "preds_file": str(preds_csv), "traps_file": str(traps_csv),
        "hallucination_rate": round(hall_hits / hall_total, 4) if hall_total else None,
        "omission_avoidance_failure_rate": round(omit_hits / omit_total, 4) if omit_total else None,
        "n_forbidden": hall_total, "n_unknown": omit_total, "per_encounter": per_enc,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--traps", required=True)
    ap.add_argument("--judge-model", default=config.JUDGE_MODEL, choices=list(config.MODELS))
    args = ap.parse_args()

    res = score_traps(args.preds, args.traps, args.judge_model)
    config.SCORES.mkdir(parents=True, exist_ok=True)
    stem = args.preds.split("/")[-1].rsplit(".", 1)[0]
    out = config.SCORES / f"{stem}.traps.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_encounter"}, ensure_ascii=False, indent=2))
    print(f"[own_metrics] → {out}")


if __name__ == "__main__":
    main()
