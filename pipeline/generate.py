"""단계별 SOAP 생성 러너 — D1(baseline)·D2(개선판)·D3(자기검증).

  python -m pipeline.generate --model qwen2.5-7b --stage baseline --dataset aci --split valid --limit 3

단계는 프롬프트파일로만 갈린다(STAGES). --self-verify 없이도 stage=improve3 이면 2차 검증 패스가 붙는다.
출력: outputs/preds/<dataset>-<split>__<model>__<stage>.csv  (cols: dataset, encounter_id, dialogue, note)
      note = 생성노트(대문자 헤더 포함), 행순서 = gold와 동일 → metrics/공식스코어러가 바로 소비.
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import clients, config, dialogue

USER_TEMPLATE = "Conversation transcript (turns are marked [T#]):\n\n{dialogue}"
SELF_VERIFY_USER = (
    "Conversation transcript:\n\n{dialogue}\n\n"
    "Draft SOAP note:\n\n{draft}\n\n"
    "Return the corrected SOAP note only."
)


def _load_prompt(name):
    p = config.PROMPTS / name
    if not p.exists():
        sys.exit(f"프롬프트 없음: {p}")
    return p.read_text(encoding="utf-8").strip()


def generate_one(model, sys_prompt, verify_prompt, rec, max_tokens):
    convo = dialogue.format_dialogue(rec["turns"])
    note = clients.chat(model, sys_prompt, USER_TEMPLATE.format(dialogue=convo), max_tokens=max_tokens)
    if verify_prompt:  # 개선3: 원본 대화 재대조 → 근거없는 문장 수정
        note = clients.chat(
            model, verify_prompt,
            SELF_VERIFY_USER.format(dialogue=convo, draft=note), max_tokens=max_tokens,
        )
    return note.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=list(config.MODELS))
    ap.add_argument("--stage", required=True, choices=list(config.STAGES))
    ap.add_argument("--dataset", default="aci", choices=["aci", "mts"])
    ap.add_argument("--split", default="valid")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--workers", type=int, default=8, help="encounter 동시 생성 수(vLLM 배칭)")
    args = ap.parse_args()

    stage = config.STAGES[args.stage]
    sys_prompt = _load_prompt(stage["prompt"])
    verify_prompt = _load_prompt(config.SELF_VERIFY_PROMPT) if stage["self_verify"] else None

    recs = dialogue.load(args.dataset, args.split, limit=args.limit)
    print(f"[generate] {args.model} × {args.stage} × {args.dataset}-{args.split}  ({len(recs)}건)"
          f"{' +self-verify' if verify_prompt else ''}")

    def _run(rec):
        try:
            return generate_one(args.model, sys_prompt, verify_prompt, rec, args.max_tokens)
        except Exception as e:  # noqa: BLE001 — 행정렬 유지 위해 실패해도 행은 남김
            print(f"  ! {rec['encounter_id']} 실패: {e}", file=sys.stderr)
            return "[GENERATION ERROR]"

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        notes = list(ex.map(_run, recs))  # 입력 순서 보존 → gold와 행정렬 유지

    rows = [{"dataset": r["dataset"], "encounter_id": r["encounter_id"],
             "dialogue": r["dialogue"], "note": n} for r, n in zip(recs, notes)]
    print(f"  {len(rows)}건 생성 (평균 {sum(len(n) for n in notes)//max(len(notes),1)} chars)")

    config.PREDS.mkdir(parents=True, exist_ok=True)
    out = config.PREDS / f"{args.dataset}-{args.split}__{args.model}__{args.stage}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"[generate] 저장 → {out}")


if __name__ == "__main__":
    main()
