"""영어 SOAP 노트 → 한글 번역(표시용). 채점용 영어 note는 보존하고 note_ko만 추가.

구조 보존 번역: S:/O:/A:/P: 배너·세부헤더·[T#] citation은 코드가 고정하고,
순수 문장(prose)만 번역기에 넘긴다 → 태그 훼손 원천 차단.

  python -m pipeline.translate --preds outputs/preds/aci-valid__qwen2.5-7b__soap.csv --model qwen2.5-7b
  출력: outputs/preds_ko/<name>__ko.csv  (cols: encounter_id, note, note_ko)
"""
import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import clients, config

OUT = config.OUT / "preds_ko"
BANNERS = {"S: SUBJECTIVE", "O: OBJECTIVE", "A: ASSESSMENT", "P: PLAN"}
HEADERS_KO = {
    "CHIEF COMPLAINT": "주호소", "HISTORY OF PRESENT ILLNESS": "현병력",
    "REVIEW OF SYSTEMS": "계통 문진", "PHYSICAL EXAMINATION": "신체 진찰",
    "RESULTS": "검사 결과", "PAST MEDICAL HISTORY": "과거력",
    "PAST SURGICAL HISTORY": "과거 수술력", "MEDICATIONS": "투약",
    "CURRENT MEDICATIONS": "투약", "SOCIAL HISTORY": "사회력",
    "FAMILY HISTORY": "가족력", "ALLERGIES": "알레르기", "VACCINATIONS": "예방접종",
    "VITALS": "활력징후", "VITALS REVIEWED": "활력징후",
}
CITE = re.compile(r"\[T\d[\dT,\s]*\]")  # [T9], [T30, T33], [T9, T11, T13] 모두 매칭
UNK = re.compile(r"\[미확인[^\]]*\]")
TR_SYS = ("You are a professional English-to-Korean medical translator. "
          "Translate the given English clinical text into natural, concise Korean (Hangul), clinical register. "
          "Output ONLY the Korean translation of the text — nothing else. "
          "Absolutely NO Chinese characters. NO English words except proper drug names (e.g. Lasix, lisinopril). "
          "No explanations, no meta-commentary, no quotes, no brackets, no citations. Translate short fragments directly.")


def _classify(line):
    s = line.strip()
    if not s:
        return ("blank", line)
    if s in BANNERS:
        return ("verbatim", line)
    if UNK.search(s):
        return ("unknown_marker", line)
    if s.upper() == s and re.search(r"[A-Za-z]", s) and len(s) < 40 and not CITE.search(s):
        return ("header", s)
    return ("content", line)


def _split_cites(line):
    """모든 [T#]를 보존. 선두 인용은 앞에, 나머지는 뒤에 재부착(줄 내 위치는 근거상 무의미)."""
    lead = ""
    m = re.match(r"^\s*((?:" + CITE.pattern + r"\s*)+)", line)
    if m:
        lead = re.sub(r"\s+", " ", m.group(1)).strip() + " "
        line = line[m.end():]
    rest = CITE.findall(line)
    prose = CITE.sub("", line).strip()
    trail = (" " + " ".join(rest)) if rest else ""
    return lead, prose, trail


def translate_note(model, note):
    lines = str(note).splitlines()
    kinds = [_classify(ln) for ln in lines]
    jobs = {}  # 줄idx -> 번역할 영어 텍스트
    for i, (k, v) in enumerate(kinds):
        if k == "content":
            lead, prose, trail = _split_cites(v)
            kinds[i] = ("content", (lead, prose, trail))
            if prose:
                jobs[i] = prose
        elif k == "header" and v not in HEADERS_KO:
            jobs[i] = v.title()  # 사전에 없는 헤더도 번역

    def _tr(text):
        try:
            return clients.chat(model, TR_SYS, text, temperature=0.3, max_tokens=400).strip()
        except Exception:  # noqa: BLE001
            return text

    idxs = list(jobs)
    with ThreadPoolExecutor(max_workers=8) as ex:
        done = dict(zip(idxs, ex.map(_tr, [jobs[i] for i in idxs])))

    out = []
    for i, (k, v) in enumerate(kinds):
        if k == "blank":
            out.append(lines[i])
        elif k == "verbatim":
            out.append(v)
        elif k == "unknown_marker":
            out.append(UNK.sub("[미확인: 대화에 언급되지 않음]", lines[i]))
        elif k == "header":
            out.append(HEADERS_KO.get(v, done.get(i, v)))
        else:  # content
            lead, prose, trail = v
            out.append(lead + done.get(i, prose) + trail)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--model", default="qwen2.5-7b", choices=list(config.MODELS))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.preds)
    if args.limit:
        df = df.head(args.limit)
    print(f"[translate] {args.preds} → 한글 (구조보존)  ({len(df)}건, model={args.model})")

    kos = []
    for _, row in df.iterrows():
        kos.append(translate_note(args.model, row["note"]))
        print(f"  · {row['encounter_id']} 완료", file=sys.stderr)

    out_df = df[["encounter_id"]].copy()
    out_df["note"] = df["note"].values
    out_df["note_ko"] = kos
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / os.path.basename(args.preds).replace(".csv", "__ko.csv")
    out_df.to_csv(out, index=False)
    print(f"[translate] 저장 → {out}")


if __name__ == "__main__":
    main()
