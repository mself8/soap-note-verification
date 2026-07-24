"""구조 강제 디코딩 (A안) — 형식은 프롬프트가 아니라 디코더가 보장한다.

vLLM의 OpenAI 표준 response_format(json_schema)으로 S/O/A/P 7필드 + 문장별
citations(대화 턴 범위의 정수)를 스키마 레벨에서 강제 → 배너 붕괴·반복 생성·
존재하지 않는 턴 인용이 디코딩 단계에서 불가능해진다.
모델은 JSON을 뱉고, 표준 배너 텍스트(soap 단계와 동일 규격)는 코드가 렌더링
→ metrics/judge/웹 파서가 기존 그대로 소비.

  python -m pipeline.structured --model qwen2.5-7b --split valid --limit 3
출력: outputs/preds/aci-<split>__<model>__soap_strict.csv (generate.py와 동일 스키마)
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import clients, config, dialogue

USER_TEMPLATE = "Conversation transcript (turns are marked [T#]):\n\n{dialogue}"
UNK_LINE = "[미확인: not mentioned in conversation]"

# (배너, [(json필드, 세부헤더 or None)]) — 렌더 순서 = soap 단계 규격과 동일
SECTIONS = [
    ("S: SUBJECTIVE", [("chief_complaint", "CHIEF COMPLAINT"),
                       ("history_of_present_illness", "HISTORY OF PRESENT ILLNESS"),
                       ("review_of_systems", "REVIEW OF SYSTEMS")]),
    ("O: OBJECTIVE",  [("physical_examination", "PHYSICAL EXAMINATION"),
                       ("results", "RESULTS")]),
    ("A: ASSESSMENT", [("assessment", None)]),
    ("P: PLAN",       [("plan", None)]),
]
FIELDS = [f for _, subs in SECTIONS for f, _ in subs]


def note_schema(n_turns):
    """대화 길이에 맞춘 스키마 — citations는 0..n_turns-1 정수만 디코딩 가능."""
    sent = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 400},
            "citations": {"type": "array", "items": {"type": "integer", "minimum": 0,
                                                     "maximum": max(n_turns - 1, 0)},
                          "maxItems": 8},
        },
        "required": ["text", "citations"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {f: {"type": "array", "items": sent, "maxItems": 25} for f in FIELDS},
        "required": FIELDS,
        "additionalProperties": False,
    }


def render_note(obj):
    """JSON → soap 단계 규격의 배너 텍스트. 빈 필드 = [미확인](빈칸 처리도 코드가 보장)."""
    out = []
    for banner, subs in SECTIONS:
        out.append(banner)
        for field, hdr in subs:
            if hdr:
                out.append(hdr)
            sents = obj.get(field) or []
            if not sents:
                out.append(UNK_LINE)
            for s in sents:
                text = str(s.get("text", "")).replace("\n", " ").strip()
                cites = sorted({int(c) for c in (s.get("citations") or [])})
                tail = f" [{', '.join('T%d' % c for c in cites)}]" if cites else ""
                if text:
                    out.append(text + tail)
        out.append("")
    return "\n".join(out).strip()


def generate_structured_one(model, sys_prompt, rec, max_tokens=6144):
    """한 encounter 생성 → (렌더된 배너 노트, 원본 JSON)."""
    turns = rec["turns"]
    convo = dialogue.format_dialogue(turns)
    rf = {"type": "json_schema",
          "json_schema": {"name": "soap_note", "schema": note_schema(len(turns))}}
    raw = clients.chat(model, sys_prompt, USER_TEMPLATE.format(dialogue=convo),
                       max_tokens=max_tokens, response_format=rf)
    obj = json.loads(raw)  # 스키마 강제라 파싱은 항상 성공해야 정상 — 실패는 상위에서 에러 행 처리
    return render_note(obj), obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=list(config.MODELS))
    ap.add_argument("--dataset", default="aci", choices=["aci"])
    ap.add_argument("--split", default="valid")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=6144)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    sys_prompt = (config.PROMPTS / config.STAGES["soap_strict"]["prompt"]).read_text(encoding="utf-8").strip()
    recs = dialogue.load(args.dataset, args.split, limit=args.limit)
    print(f"[structured] {args.model} × soap_strict × {args.dataset}-{args.split}  ({len(recs)}건)")

    def _run(rec):
        try:
            note, _ = generate_structured_one(args.model, sys_prompt, rec, args.max_tokens)
            return note
        except Exception as e:  # noqa: BLE001 — 행정렬 유지
            print(f"  ! {rec['encounter_id']} 실패: {e}", file=sys.stderr)
            return "[GENERATION ERROR]"

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        notes = list(ex.map(_run, recs))

    rows = [{"dataset": r["dataset"], "encounter_id": r["encounter_id"],
             "dialogue": r["dialogue"], "note": n} for r, n in zip(recs, notes)]
    ok = sum(1 for n in notes if n != "[GENERATION ERROR]")
    print(f"  {ok}/{len(rows)}건 성공 (평균 {sum(len(n) for n in notes)//max(len(notes),1)} chars)")

    config.PREDS.mkdir(parents=True, exist_ok=True)
    out = config.PREDS / f"{args.dataset}-{args.split}__{args.model}__soap_strict.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"[structured] 저장 → {out}")


if __name__ == "__main__":
    main()
