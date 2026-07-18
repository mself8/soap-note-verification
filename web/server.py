"""SOAP 플레이그라운드 — FastAPI. 대화 입력 → SOAP 생성(+한글), 프롬프트 라이브 편집 A/B.

실행:
  .venv/bin/uvicorn web.server:app --host 0.0.0.0 --port 8000 --app-dir /workspace/soap-note-verification
사전조건: 생성 vLLM(Qwen 8001), 번역 vLLM(Llama 8002)이 떠 있어야 함.
UI는 단일 예시 확인·데모용 — 프롬프트 A/B 판정은 배치 평가(pipeline.metrics/judge)가 진실.
"""
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "aci-bench" / "baselines"))

from pipeline import clients, config, dialogue  # noqa: E402
from pipeline.generate import generate_one  # noqa: E402
from pipeline.translate import translate_note  # noqa: E402
from sectiontagger import SectionTagger  # noqa: E402

ST = SectionTagger()
HERE = Path(__file__).resolve().parent
app = FastAPI(title="SOAP Playground")

SOAP_LABEL = {"S": "S · Subjective", "O": "O · Objective", "A": "A · Assessment",
              "P": "P · Plan", "AP": "A·P · Assessment & Plan", "U": "· 기타/미분류"}


def _split_ap(text):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().strip("*#[] ").rstrip(":").strip().lower() == "plan":
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i:]).strip()
    return text, None


def group_soap(note):
    """공식 section_tagger로 노트를 S/O/A·P 구역으로 그룹핑 → [{key,label,text}]."""
    note = str(note)
    try:
        divs = ST.divide_note_by_metasections(note)
    except Exception:  # noqa: BLE001
        divs = []
    segs = []
    if divs and len({d[0] for d in divs}) >= 2:
        parts = {}
        for label, _code, _a, s, _b, e in divs:
            parts[label] = parts.get(label, "") + note[s:e]
        pre = note[:divs[0][3]].strip()
        if pre:
            segs.append(("U", pre))
        if parts.get("subjective", "").strip():
            segs.append(("S", parts["subjective"].strip()))
        otext = "\n\n".join(t for t in [parts.get("objective_exam", "").strip(),
                                        parts.get("objective_results", "").strip()] if t)
        if otext:
            segs.append(("O", otext))
        ap = parts.get("assessment_and_plan", "").strip()
        if ap:
            a_txt, p_txt = _split_ap(ap)
            if p_txt is not None:
                if a_txt.strip():
                    segs.append(("A", a_txt.strip()))
                segs.append(("P", p_txt.strip()))
            else:
                segs.append(("AP", ap))
    else:
        segs = [("U", note.strip())]
    return [{"key": k, "label": SOAP_LABEL.get(k, k), "text": t} for k, t in segs]


class GenReq(BaseModel):
    dialogue: str
    stage: str = "soap"
    custom_prompt: str | None = None
    gen_model: str = "qwen2.5-7b"
    translate: bool = False
    translate_model: str = "llama3.1-8b"
    max_tokens: int = 2048


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "index.html").read_text(encoding="utf-8")


@app.get("/config")
def get_config():
    return {"stages": list(config.STAGES), "models": list(config.MODELS),
            "judge": config.JUDGE_MODEL}


@app.get("/prompt/{stage}")
def get_prompt(stage: str):
    st = config.STAGES.get(stage)
    if not st:
        return {"error": f"unknown stage {stage}"}
    text = (config.PROMPTS / st["prompt"]).read_text(encoding="utf-8").strip()
    return {"stage": stage, "prompt": text, "self_verify": st["self_verify"]}


@app.get("/sample")
def sample():
    """빠른 테스트용 ACI valid 첫 대화(D2N068)."""
    recs = dialogue.load("aci", "valid", limit=1)
    r = recs[0]
    return {"encounter_id": r["encounter_id"], "dialogue": r["dialogue"]}


@app.post("/generate")
def generate(req: GenReq):
    try:
        turns = dialogue.parse_turns(req.dialogue)
        if not turns:
            return {"error": "대화에서 turn을 못 찾음 — '[doctor] ...' 또는 'Doctor: ...' 형식인지 확인"}
        st = config.STAGES.get(req.stage, config.STAGES["soap"])
        sys_prompt = req.custom_prompt.strip() if (req.custom_prompt and req.custom_prompt.strip()) \
            else (config.PROMPTS / st["prompt"]).read_text(encoding="utf-8").strip()
        verify_prompt = (config.PROMPTS / config.SELF_VERIFY_PROMPT).read_text(encoding="utf-8").strip() \
            if st["self_verify"] else None

        t0 = time.time()
        note = generate_one(req.gen_model, sys_prompt, verify_prompt, {"turns": turns}, req.max_tokens)
        out = {
            "note_en": note,
            "sections_en": group_soap(note),
            "turns_fmt": dialogue.format_dialogue(turns),
            "n_turns": len(turns),
            "gen_ms": int((time.time() - t0) * 1000),
        }
        if req.translate:
            t1 = time.time()
            note_ko = translate_note(req.translate_model, note)
            out["note_ko"] = note_ko
            out["sections_ko"] = group_soap(note_ko)
            out["tr_ms"] = int((time.time() - t1) * 1000)
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
