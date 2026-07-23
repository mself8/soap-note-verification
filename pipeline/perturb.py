"""검증기 함정셋 (①실험) — gold 노트에 규칙기반 교란을 심고 judge가 잡는지 측정.

own_metrics.py(E2: C의 함정 대화로 '생성기' 환각 측정)와 별개로,
여기서는 '검증기(judge)' 자체의 성적표를 만든다: 심은 환각 검출률(sensitivity)과 오탐율.

쌍대 설계 — 같은 문장의 (원문, 교란문) 쌍을 모두 판정:
  - sensitivity   = 원문이 grounded 로 판정된 쌍 중, 교란문이 ungrounded 로 판정된 비율
                    (원문부터 ungrounded 인 쌍은 무효 처리 → gold 엄격성 혼입 제거)
  - gold_fp_rate  = 교란 없는 gold 문장이 ungrounded 로 판정된 비율(오탐 상한.
                    gold 에도 대화에 직접 없는 표준문구가 있어 완전한 FP 는 아님)

교란 4종(규칙기반·결정적·감사 가능):
  negation_flip : denies/no/not/without ↔ 긍정 뒤집기
  number_shift  : 수치 변조(혈압쌍·심잡음 등급·용량/활력징후+단위)
  entity_swap   : 좌우/부위/계열 스왑(left↔right, systolic↔diastolic …)
  fabrication   : 대화에 없는 그럴듯한 문장 삽입(템플릿 뱅크, 대화 키워드 스크린으로 미언급 확인)

실행: python -m pipeline.perturb --dataset aci --split valid [--limit N] [--judge-model qwen2.5-32b]
출력: outputs/scores/traps__<dataset>-<split>.json (집계)
      outputs/judge/traps__<dataset>-<split>.jsonl (함정별 원문/교란/판정 — 감사용)
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import clients, config, dialogue
from .judge import _judge_sentence, split_sentences

MAX_PER_TYPE = 2  # 노트당 교란 상한(유형별)

# ---------- 교란 규칙 ----------

_NEG_RULES = [
    (re.compile(r"\bdenies\b"), "reports"),
    (re.compile(r"\bdenied\b"), "reported"),
    (re.compile(r"\bwithout\b"), "with"),
    (re.compile(r"\bno evidence of\b", re.I), "evidence of"),
    (re.compile(r"\bdoes not\b"), "does"),
    (re.compile(r"\bis not\b"), "is"),
    (re.compile(r"\bare not\b"), "are"),
    (re.compile(r"^No ([a-z])"), lambda m: m.group(1).upper()),
    (re.compile(r"\bno (?=[a-z])"), ""),
]

_BP = re.compile(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b")          # 혈압 120/80
_GRADE = re.compile(r"\b([1-5])/6\b")                        # 심잡음 3/6
_NUM_UNIT = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?|mmhg|bpm|%|percent|lbs?|pounds|kg|cm|mm"
    r"|weeks?|months?|days?|years?|hours?|minutes?|times)\b", re.I)

_SWAP_PAIRS = [
    ("left", "right"), ("Left", "Right"),
    ("upper", "lower"), ("systolic", "diastolic"),
    ("arm", "leg"), ("knee", "hip"), ("shoulder", "elbow"),
    ("tachycardia", "bradycardia"), ("hypertension", "hypotension"),
    ("increased", "decreased"), ("elevated", "reduced"),
]

# (문장, 대화 스크린 키워드) — 키워드가 대화에 하나라도 있으면 그 템플릿은 스킵
_FABRICATIONS = [
    ("The patient has a documented history of type 2 diabetes mellitus.", ["diabet", "a1c", "metformin"]),
    ("The patient is currently taking lisinopril 20 mg daily.", ["lisinopril"]),
    ("The patient reports smoking one pack of cigarettes per day.", ["smok", "cigarette", "tobacco"]),
    ("The patient underwent an appendectomy two years ago.", ["appendectomy", "appendix"]),
    ("The patient has a known allergy to penicillin.", ["penicillin"]),
    ("A recent colonoscopy revealed two benign polyps.", ["colonoscopy", "polyp"]),
    ("The patient reports drinking six beers daily.", ["beer", "alcohol", "drinks per"]),
    ("MRI of the brain showed a small lacunar infarct.", ["mri", "infarct", "stroke"]),
]


def perturb_negation(sent):
    for pat, rep in _NEG_RULES:
        if pat.search(sent):
            return pat.sub(rep, sent, count=1)
    return None


def perturb_number(sent):
    m = _BP.search(sent)
    if m:
        s, d = int(m.group(1)), int(m.group(2))
        return sent[:m.start()] + f"{s + 40}/{d + 30}" + sent[m.end():]
    m = _GRADE.search(sent)
    if m:
        return sent[:m.start()] + f"{min(int(m.group(1)) + 2, 6)}/6" + sent[m.end():]
    m = _NUM_UNIT.search(sent)
    if m:
        v = float(m.group(1)) * 2
        v = int(v) if v == int(v) else round(v, 1)
        return sent[:m.start(1)] + str(v) + sent[m.end(1):]
    return None


def perturb_entity(sent):
    for a, b in _SWAP_PAIRS:
        if re.search(rf"\b{a}\b", sent):
            return re.sub(rf"\b{a}\b", b, sent, count=1)
        if re.search(rf"\b{b}\b", sent):
            return re.sub(rf"\b{b}\b", a, sent, count=1)
    return None


_PERTURBERS = [
    ("negation_flip", perturb_negation),
    ("number_shift", perturb_number),
    ("entity_swap", perturb_entity),
]


def build_traps(gold_sents, dialogue_text):
    """→ [{type, original(None=fabrication), perturbed}]. 결정적(랜덤 없음)."""
    traps, used = [], set()  # used: 같은 문장에 교란 1개만(쌍대 해석 단순화)
    for tname, fn in _PERTURBERS:
        count = 0
        for s in gold_sents:
            if count >= MAX_PER_TYPE or s in used:
                continue
            p = fn(s)
            if p and p != s:
                traps.append({"type": tname, "original": s, "perturbed": p})
                used.add(s)
                count += 1
    low = dialogue_text.lower()
    count = 0
    for sent, keys in _FABRICATIONS:
        if count >= MAX_PER_TYPE:
            break
        if any(k in low for k in keys):
            continue
        traps.append({"type": "fabrication", "original": None, "perturbed": sent})
        count += 1
    return traps


# ---------- 실행 ----------

def run(dataset, split, judge_model, limit=None, workers=16,
        judge_prompt=None, max_tokens=None):
    sys_prompt = (config.PROMPTS / (judge_prompt or config.JUDGE_PROMPT)).read_text(
        encoding="utf-8").strip()
    recs = dialogue.load(dataset, split, limit=limit)
    rows = []  # 판정 단위: {kind: gold|trap, ...}

    for i, rec in enumerate(recs, 1):
        convo = dialogue.format_dialogue(rec["turns"])
        gold_sents = split_sentences(rec["note"])
        traps = build_traps(gold_sents, str(rec["dialogue"]))

        def _j(sent):
            return _judge_sentence(judge_model, sys_prompt, convo, sent, max_tokens=max_tokens)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            gold_v = list(ex.map(_j, gold_sents))
            pert_v = list(ex.map(_j, [t["perturbed"] for t in traps]))

        orig_map = {r["sent"]: r["grounded"] for r in gold_v}
        for r in gold_v:
            rows.append({"kind": "gold", "encounter_id": rec["encounter_id"],
                         "sent": r["sent"], "grounded": r["grounded"]})
        for t, pv in zip(traps, pert_v):
            rows.append({"kind": "trap", "encounter_id": rec["encounter_id"], "type": t["type"],
                         "original": t["original"], "orig_grounded": orig_map.get(t["original"]),
                         "perturbed": t["perturbed"], "pert_grounded": pv["grounded"]})
        n_traps = sum(1 for r in rows if r["kind"] == "trap")
        print(f"  [{i}/{len(recs)}] {rec['encounter_id']}: gold {len(gold_sents)}문장, 누적함정 {n_traps}")

    return rows


def summarize(rows):
    gold = [r for r in rows if r["kind"] == "gold" and r["grounded"] is not None]
    traps = [r for r in rows if r["kind"] == "trap" and r["pert_grounded"] is not None]
    out = {
        "gold_sentences": len(gold),
        "gold_fp_rate": round(sum(1 for r in gold if not r["grounded"]) / (len(gold) or 1), 4),
        "traps_total": len(traps),
        "by_type": {},
    }
    for tname in ["negation_flip", "number_shift", "entity_swap", "fabrication"]:
        sub = [r for r in traps if r["type"] == tname]
        if tname == "fabrication":
            valid = sub  # 원문 없음 — 삽입문 자체가 함정
        else:
            valid = [r for r in sub if r["orig_grounded"]]  # 원문 grounded 쌍만 유효
        caught = sum(1 for r in valid if not r["pert_grounded"])
        out["by_type"][tname] = {
            "traps": len(sub), "valid_pairs": len(valid), "caught": caught,
            "sensitivity": round(caught / len(valid), 4) if valid else None,
        }
    all_valid = [v for t, d in out["by_type"].items() for v in [d] if d["valid_pairs"]]
    tot_valid = sum(d["valid_pairs"] for d in all_valid)
    tot_caught = sum(d["caught"] for d in all_valid)
    out["overall_sensitivity"] = round(tot_caught / tot_valid, 4) if tot_valid else None
    out["overall_valid_traps"] = tot_valid
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="aci", choices=["aci", "mts"])
    ap.add_argument("--split", default="valid")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--judge-model", default=config.JUDGE_MODEL, choices=list(config.MODELS))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--judge-prompt", default=None,
                    help="판정 프롬프트 파일명(기본 config.JUDGE_PROMPT). 예: judge_grounded_cot.txt")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="판정 응답 토큰 상한(CoT는 300 권장)")
    ap.add_argument("--tag", default=None, help="출력 파일명 접미사(A/B 구분용)")
    args = ap.parse_args()

    print(f"[perturb] {args.dataset}-{args.split}  judge={args.judge_model} "
          f"prompt={args.judge_prompt or config.JUDGE_PROMPT}")
    rows = run(args.dataset, args.split, args.judge_model, limit=args.limit, workers=args.workers,
               judge_prompt=args.judge_prompt, max_tokens=args.max_tokens)
    summary = summarize(rows)

    config.JUDGE_OUT.mkdir(parents=True, exist_ok=True)
    config.SCORES.mkdir(parents=True, exist_ok=True)
    stem = f"traps__{args.dataset}-{args.split}" + (f"__{args.tag}" if args.tag else "")
    with open(config.JUDGE_OUT / f"{stem}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (config.SCORES / f"{stem}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[perturb] → {config.SCORES / (stem + '.json')}")


if __name__ == "__main__":
    main()
