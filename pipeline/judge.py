"""LLM-as-a-judge 이진 근거판정 (D5) — 문장별 "대화에 근거하는가?".

  python -m pipeline.judge --preds outputs/preds/aci-valid__qwen2.5-7b__improve2.csv \
      --dataset aci --split valid [--limit 3] [--judge-model qwen2.5-32b]

지표(1일차 결론: 환각은 자동지표 아닌 judge가 담당):
  - grounded_rate         : 근거 있는 문장 비율(↑ 좋음)
  - hallucination_rate    : 1 - grounded_rate (스크리닝)
  - citation_precision    : 모델이 [T#]로 근거를 단 문장 중, judge가 근거 있다고 본 비율
  - citation_turn_match   : 그중 judge가 고른 turn이 모델이 단 turn과 일치한 비율
recall은 gold 부재로 측정 불가(docs/B §B-4의 비대칭).
출력: outputs/judge/<preds-stem>.jsonl(문장별) + <preds-stem>.summary.json(집계)
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import clients, config, dialogue

_CITE_TURN = re.compile(r"T(\d+)")
_CITE_BLOCK = re.compile(r"\[T\d+(?:\s*,\s*T?\d+)*\]")
_JSON = re.compile(r"\{[^{}]*\}")
_HEADER = re.compile(r"^[A-Z][A-Z /&]{2,}$")  # 대문자 섹션헤더 줄
_BANNER = re.compile(r"^[SOAP]: (SUBJECTIVE|OBJECTIVE|ASSESSMENT|PLAN)$")  # soap 단계 콜론 배너
_JUDGE_USER = "Conversation transcript:\n\n{dialogue}\n\nNote sentence:\n\"{sent}\""


def split_sentences(note):
    """노트 → 판정 대상 문장 리스트. 헤더·라벨줄·마크다운·빈줄 제외, 불릿·문장 유지.

    문단(줄) 끝에 몰아 단 인용 블록은 분리 시 "인용만 남는 프래그먼트"가 되므로,
    문장으로 내보내지 않고 그 줄의 실제 문장들에 재부착한다(문단 인용 = 문단 전체의 근거).
    인용만 있는 단독 줄은 직전 문장에 부착한다.
    """
    out = []
    for line in str(note).splitlines():
        line = re.sub(r"[*#]+", "", line).strip().lstrip("•-* ").strip()  # 마크다운 제거
        if not line or line.endswith(":") or _HEADER.match(line) or _BANNER.match(line):  # 라벨/헤더/배너 줄 스킵
            continue
        sents, line_cites = [], []
        for s in re.split(r"(?<=[.!?])\s+", line):
            s = s.strip()
            clean = _CITE_BLOCK.sub("", s).strip()
            if not re.search(r"[A-Za-z]", clean):  # 인용 블록만 남는 프래그먼트
                line_cites += _CITE_BLOCK.findall(s)
                continue
            if len(clean) >= 8:  # 실제 문장만
                sents.append(s)
        if line_cites:
            tail = " " + " ".join(line_cites)
            if sents:
                sents = [s + tail for s in sents]
            elif out:  # 인용 단독 줄 → 직전 문장에 부착
                out[-1] += tail
        out.extend(sents)
    return out


def cited_turns(sent):
    turns = []
    for block in _CITE_BLOCK.findall(sent):
        turns += [int(x) for x in _CITE_TURN.findall(block)]
    return sorted(set(turns))


def parse_verdict(text):
    m = _JSON.search(text or "")
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
        return bool(d.get("grounded")), d.get("turn")
    except Exception:  # noqa: BLE001
        return None, None


def _judge_sentence(judge_model, sys_prompt, convo, sent):
    turns = cited_turns(sent)
    clean = _CITE_BLOCK.sub("", sent).strip()
    try:
        reply = clients.chat(judge_model, sys_prompt,
                             _JUDGE_USER.format(dialogue=convo, sent=clean), max_tokens=60)
        grounded, jturn = parse_verdict(reply)
    except Exception as e:  # noqa: BLE001
        print(f"  ! judge 실패: {e}", file=sys.stderr)
        grounded, jturn = None, None
    return {"sent": clean, "cited_turns": turns, "grounded": grounded, "judge_turn": jturn}


def judge_note(judge_model, sys_prompt, convo, note, workers=16):
    sents = split_sentences(note)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda s: _judge_sentence(judge_model, sys_prompt, convo, s), sents))


def summarize(all_rows):
    judged = [r for r in all_rows if r["grounded"] is not None]
    grounded = [r for r in judged if r["grounded"]]
    cited = [r for r in judged if r["cited_turns"]]
    cited_ok = [r for r in cited if r["grounded"]]
    turn_match = [r for r in cited_ok if r["judge_turn"] in r["cited_turns"]]
    n = len(judged) or 1
    return {
        "sentences": len(all_rows),
        "judged": len(judged),
        "grounded_rate": round(len(grounded) / n, 4),
        "hallucination_rate": round(1 - len(grounded) / n, 4),
        "citation_precision": round(len(cited_ok) / len(cited), 4) if cited else None,
        "citation_turn_match": round(len(turn_match) / len(cited_ok), 4) if cited_ok else None,
        "cited_sentences": len(cited),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--dataset", default="aci", choices=["aci", "mts", "own", "dysem"])
    ap.add_argument("--split", default="valid")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--judge-model", default=config.JUDGE_MODEL, choices=list(config.MODELS))
    ap.add_argument("--workers", type=int, default=16, help="문장 동시 판정 수(vLLM 배칭)")
    args = ap.parse_args()

    sys_prompt = (config.PROMPTS / config.JUDGE_PROMPT).read_text(encoding="utf-8").strip()
    pred_df = pd.read_csv(args.preds)
    if args.limit:
        pred_df = pred_df.head(args.limit)
    turns_by_id = {r["encounter_id"]: r["turns"] for r in dialogue.load(args.dataset, args.split)}

    print(f"[judge] {args.preds}  judge={args.judge_model}  ({len(pred_df)}개 노트)")
    all_rows = []
    for i, row in enumerate(pred_df.itertuples(index=False), 1):
        turns = turns_by_id.get(row.encounter_id, [])
        convo = dialogue.format_dialogue(turns)
        rows = judge_note(args.judge_model, sys_prompt, convo, row.note, workers=args.workers)
        for r in rows:
            r["encounter_id"] = row.encounter_id
        all_rows.extend(rows)
        g = sum(1 for r in rows if r["grounded"])
        print(f"  [{i}/{len(pred_df)}] {row.encounter_id}: {g}/{len(rows)} grounded")

    config.JUDGE_OUT.mkdir(parents=True, exist_ok=True)
    stem = args.preds.split("/")[-1].rsplit(".", 1)[0]
    with open(config.JUDGE_OUT / f"{stem}.jsonl", "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = summarize(all_rows)
    (config.JUDGE_OUT / f"{stem}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
