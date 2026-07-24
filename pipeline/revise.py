"""Judge-guided 자동 교정 (B안) — 탐지에서 수술로.

judge(D5)가 근거 없음(RED)으로 판정한 문장을 노트에서 제거(drop)하거나
근거 있는 내용으로 재작성 후 재판정 통과 시에만 유지(rewrite, 실패 시 drop).
자기검증(improve3)과 달리 생성모델이 아닌 '분리된 검증기' 신호로 교정한다.

  python -m pipeline.revise --preds outputs/preds/aci-valid__qwen2.5-7b__soap.csv \
      --dataset aci --split valid --mode drop [--limit 3]

출력: outputs/preds_revised/<stem>__rev-<mode>.csv (+ 표준출력 전후 환각률 요약)
ROUGE 전후 비교는 metrics CLI를 revised CSV에 다시 돌려서 확인.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import clients, config, dialogue, judge

OUT = config.OUT / "preds_revised"
UNK_LINE = "[미확인: not mentioned in conversation]"
_SPLIT = re.compile(r"(?<=[.!?])\s+")  # judge.split_sentences와 동일한 문장 경계

REWRITE_SYS = (
    "You fix ONE sentence of a clinical SOAP note so that it is fully supported by the "
    "conversation transcript. Return ONLY the corrected sentence, ending with the supporting "
    "turn citation(s) like [T3] or [T3, T5]. Keep clinical register. Do NOT add information "
    "beyond the transcript. If the transcript does not support any version of this sentence, "
    "return exactly: [REMOVE]"
)
REWRITE_USER = "Conversation transcript:\n\n{dialogue}\n\nSentence to fix:\n{sent}"


def _norm(s):
    s = judge._CITE_BLOCK.sub("", s)
    s = re.sub(r"[*#]+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def revise_note(note, flagged_sents, convo, mode="drop", gen_model=None,
                judge_model=None, judge_prompt=None, max_tokens=None):
    """flagged_sents(정규화 전 clean 문장들)를 노트 텍스트에서 수술. → (revised, stats)"""
    flagged = {_norm(s) for s in flagged_sents if _norm(s)}
    stats = {"flagged": len(flagged), "dropped": 0, "rewritten": 0}
    if not flagged:
        return note, stats

    out_lines = []
    for line in str(note).splitlines():
        stripped = line.strip()
        # 배너·헤더·빈줄·미확인 마커는 그대로 통과
        if (not stripped or stripped.endswith(":") or judge._HEADER.match(stripped)
                or judge._BANNER.match(stripped) or "[미확인" in stripped):
            out_lines.append(line)
            continue
        spans = _SPLIT.split(stripped)
        kept = []
        for span in spans:
            if _norm(span) not in flagged:
                kept.append(span)
                continue
            if mode == "rewrite" and gen_model:
                try:
                    fix = clients.chat(gen_model, REWRITE_SYS,
                                       REWRITE_USER.format(dialogue=convo, sent=span),
                                       max_tokens=150).strip()
                except Exception:  # noqa: BLE001
                    fix = "[REMOVE]"
                if fix and fix != "[REMOVE]" and judge_model:
                    verdict = judge._judge_sentence(judge_model, judge_prompt, convo, fix,
                                                    max_tokens=max_tokens)
                    if verdict["grounded"]:
                        kept.append(fix)
                        stats["rewritten"] += 1
                        continue
            stats["dropped"] += 1
        if kept:
            out_lines.append(" ".join(kept))

    # 수술로 비어버린 구역엔 [미확인] 삽입 (배너/헤더만 남은 구역)
    revised = []
    i = 0
    while i < len(out_lines):
        revised.append(out_lines[i])
        cur = out_lines[i].strip()
        if judge._BANNER.match(cur) or judge._HEADER.match(cur):
            j = i + 1
            has_content = False
            while j < len(out_lines):
                nxt = out_lines[j].strip()
                if judge._BANNER.match(nxt) or judge._HEADER.match(nxt):
                    break
                if nxt:
                    has_content = True
                j += 1
            if not has_content and (judge._BANNER.match(cur) and cur.split(":")[0] in ("A", "P")
                                    or judge._HEADER.match(cur)):
                revised.append(UNK_LINE)
        i += 1
    return "\n".join(revised).strip(), stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--dataset", default="aci", choices=["aci", "mts", "own", "dysem"])
    ap.add_argument("--split", default="valid")
    ap.add_argument("--mode", default="drop", choices=["drop", "rewrite"])
    ap.add_argument("--gen-model", default="qwen2.5-7b", choices=list(config.MODELS))
    ap.add_argument("--judge-model", default=config.JUDGE_MODEL, choices=list(config.MODELS))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4, help="encounter 동시 처리 수")
    ap.add_argument("--judge-prompt", default=None,
                    help="판정 프롬프트 파일명(기본 config.JUDGE_PROMPT). 예: judge_grounded_cot2.txt")
    ap.add_argument("--max-tokens", type=int, default=None, help="판정 응답 토큰 상한(CoT는 380 권장)")
    ap.add_argument("--tag", default=None, help="출력 파일명 접미사(판정기별 결과 분리용)")
    args = ap.parse_args()

    judge_prompt = (config.PROMPTS / (args.judge_prompt or config.JUDGE_PROMPT)).read_text(
        encoding="utf-8").strip()
    df = pd.read_csv(args.preds)
    if args.limit:
        df = df.head(args.limit)
    turns_by_id = {r["encounter_id"]: r["turns"] for r in dialogue.load(args.dataset, args.split)}
    print(f"[revise] {args.preds}  mode={args.mode} judge={args.judge_model}  ({len(df)}건)")

    def _run(row):
        convo = dialogue.format_dialogue(turns_by_id.get(row.encounter_id, []))
        before = judge.judge_note(args.judge_model, judge_prompt, convo, row.note,
                                  max_tokens=args.max_tokens)
        flagged = [r["sent"] for r in before if r["grounded"] is False]
        revised, stats = revise_note(row.note, flagged, convo, mode=args.mode,
                                     gen_model=args.gen_model, judge_model=args.judge_model,
                                     judge_prompt=judge_prompt, max_tokens=args.max_tokens)
        after = judge.judge_note(args.judge_model, judge_prompt, convo, revised,
                                 max_tokens=args.max_tokens)
        return revised, judge.summarize(before), judge.summarize(after), stats

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_run, df.itertuples(index=False)))

    bh = sum(s["hallucination_rate"] * s["judged"] for _, s, _, _ in results)
    bj = sum(s["judged"] for _, s, _, _ in results) or 1
    ah = sum(s["hallucination_rate"] * s["judged"] for _, _, s, _ in results)
    aj = sum(s["judged"] for _, _, s, _ in results) or 1
    dropped = sum(st["dropped"] for _, _, _, st in results)
    rewritten = sum(st["rewritten"] for _, _, _, st in results)
    summary = {"mode": args.mode, "notes": len(results),
               "hallucination_before": round(bh / bj, 4), "hallucination_after": round(ah / aj, 4),
               "sentences_before": bj, "sentences_after": aj,
               "dropped": dropped, "rewritten_kept": rewritten}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_df = df.copy()
    out_df["note"] = [r for r, _, _, _ in results]
    OUT.mkdir(parents=True, exist_ok=True)
    stem = args.preds.split("/")[-1].rsplit(".", 1)[0]
    suffix = f"__rev-{args.mode}" + (f"__{args.tag}" if args.tag else "")
    out = OUT / f"{stem}{suffix}.csv"
    out_df.to_csv(out, index=False)
    (OUT / f"{stem}{suffix}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[revise] 저장 → {out}")


if __name__ == "__main__":
    main()
