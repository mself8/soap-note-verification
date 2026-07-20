"""데이터 로드 + 화자태그 정규화 + turn_id 부여(citation·judge 공통 근거단위).

ACI: '[doctor] ...' / '[patient] ...' / '[patient_guest] ...'
MTS: 'Doctor: ...' / 'Patient: ...'  (오타태그 'Guest_clinican' 등 흡수 — docs/B §A-4)
"""
import re

import pandas as pd

from . import config

# 줄머리 화자태그: [bracket] 형식 또는 'Word:' 형식 (한글 '의사:'/'환자:' 포함)
_SPEAKER = re.compile(r"^\s*(?:\[(?P<b>[^\]]+)\]|(?P<c>[A-Za-z가-힣][A-Za-z_ 가-힣]{0,19}):)\s*(?P<text>.*)$")


def _canon_speaker(raw):
    s = raw.strip().lower().replace(" ", "_")
    if "doctor" in s or "clinic" in s or "physician" in s or "provider" in s:  # 'clinician'/오타 'clinican'
        return "doctor"
    if "patient" in s or "guest" in s or "caregiver" in s or "family" in s or "mother" in s or "father" in s:
        return "patient"
    if "의사" in s or "닥터" in s or "원장" in s or "선생" in s or "간호" in s:
        return "doctor"
    if "환자" in s or "보호자" in s or "가족" in s or "어머니" in s or "아버지" in s:
        return "patient"
    return s or "other"


def parse_turns(dialogue):
    """대화문 → [{turn_id, speaker, text}]. 태그 없는 줄은 직전 발화에 이어붙임."""
    if not isinstance(dialogue, str):
        return []
    turns = []
    for line in dialogue.splitlines():
        if not line.strip():
            continue
        m = _SPEAKER.match(line)
        if m and (m.group("b") or m.group("c")):
            turns.append({
                "turn_id": len(turns),
                "speaker": _canon_speaker(m.group("b") or m.group("c")),
                "text": m.group("text").strip(),
            })
        elif turns:
            turns[-1]["text"] += " " + line.strip()
    return turns


def format_dialogue(turns):
    """프롬프트/judge에 넣는 정규화 대화(턴번호 명시 → citation 근거)."""
    return "\n".join(f"[T{t['turn_id']}] {t['speaker']}: {t['text']}" for t in turns)


def load(dataset, split, limit=None):
    """→ [{dataset, encounter_id, dialogue, note, turns, (section_header)}]. dialogue=원본, note=gold."""
    if dataset == "aci":
        df = pd.read_csv(config.ACI_DIR / config.ACI_SPLITS[split])
        recs = [{
            "dataset": r["dataset"], "encounter_id": r["encounter_id"],
            "dialogue": r["dialogue"], "note": r["note"],
            "turns": parse_turns(r["dialogue"]),
        } for _, r in df.iterrows()]
    elif dataset == "mts":
        df = pd.read_csv(config.MTS_DIR / config.MTS_SPLITS[split])
        recs = [{
            "dataset": "mts", "encounter_id": str(r["ID"]),
            "dialogue": r["dialogue"], "note": r["section_text"],
            "section_header": r["section_header"],
            "turns": parse_turns(r["dialogue"]),
        } for _, r in df.iterrows()]
    elif (dataset, split) in config.TEAM_SPLITS:
        path = config.TEAM_SPLITS[(dataset, split)]
        if path is None:
            raise FileNotFoundError(f"팀 데이터 파일 없음: {dataset}/{split} — data/ 폴더 확인")
        df = pd.read_csv(path)
        recs = [{
            "dataset": r["dataset"], "encounter_id": r["encounter_id"],
            "dialogue": r["dialogue"], "note": r["note"],
            "turns": parse_turns(r["dialogue"]),
        } for _, r in df.iterrows()]
    else:
        raise ValueError(f"알 수 없는 dataset '{dataset}' (aci|mts|own|dysem)")
    return recs[:limit] if limit else recs
