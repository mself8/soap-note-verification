"""경로·모델 레지스트리·프롬프트 단계. 다중모델 비교 = 여기 MODELS 한 줄 추가."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ACI_DIR = DATA / "aci-bench" / "data" / "challenge_data"
MTS_DIR = DATA / "MTS-Dialog" / "Main-Dataset"
PROMPTS = ROOT / "prompts"
OUT = ROOT / "outputs"
PREDS = OUT / "preds"
SCORES = OUT / "scores"
JUDGE_OUT = OUT / "judge"
REPORTS = ROOT / "reports"

# ACI-Bench(주 데이터). 파일명이 곧 split.
ACI_SPLITS = {
    "train": "train.csv",
    "valid": "valid.csv",
    "test1": "clinicalnlp_taskB_test1.csv",
    "test2": "clinicalnlp_taskC_test2.csv",
    "test3": "clef_taskC_test3.csv",
}
# MTS-Dialog(보조 — 단일섹션 스니펫). note=section_text.
MTS_SPLITS = {
    "train": "MTS-Dialog-TrainingSet.csv",
    "valid": "MTS-Dialog-ValidationSet.csv",
    "test1": "MTS-Dialog-TestSet-1-MEDIQA-Chat-2023.csv",
    "test2": "MTS-Dialog-TestSet-2-MEDIQA-Sum-2023.csv",
}

# 자체 데이터(팀원 제작, 07-20 반입). 폴더명이 한글(macOS NFD 자모분해)이라 경로를 glob으로 해석.
def _team_csv(pattern):
    hits = sorted(DATA.glob(pattern))
    return hits[0] if hits else None

TEAM_SPLITS = {  # (dataset, split) -> csv. 모두 ACI 4컬럼 스키마(dataset, encounter_id, dialogue, note).
    ("own", "noise100"): _team_csv("*/noise_en_100_main.csv"),      # 고은: 영어 노이즈 100 (정량)
    ("own", "ko60"):     _team_csv("*/ko_demo_60_main.csv"),        # 고은: 한국어 60 (시연 전용)
    ("dysem", "flat128"): _team_csv("*/aci_semantic_noise_eval_flat_128.csv"),  # 다연: clean64+noisy64
    ("dysem", "plus271"): _team_csv("*/aci_plus_semantic_noise_271.csv"),       # 다연: ACI207+noisy64 통합
}

# 로컬 vLLM(OpenAI 호환) 엔드포인트. served_name = serve_vllm.sh 의 --served-model-name.
# hf_id 가 게이트 모델(llama/mistral)이면 hf-mirror에서 401 시 ungated 재업로드로 교체
# (예: NousResearch/Meta-Llama-3.1-8B-Instruct, unsloth/mistral-7b-instruct-v0.3). 주석의 대안 참고.
MODELS = {
    "qwen2.5-7b":  {"hf_id": "Qwen/Qwen2.5-7B-Instruct",          "port": 8001, "tp": 1},
    "llama3.1-8b": {"hf_id": "NousResearch/Meta-Llama-3.1-8B-Instruct",  "port": 8002, "tp": 1},  # ungated 재업로드(게이트 회피)
    "mistral-7b":  {"hf_id": "mistralai/Mistral-7B-Instruct-v0.3", "port": 8003, "tp": 1},  # 게이트면 unsloth/… 로 교체
    "qwen2.5-32b": {"hf_id": "Qwen/Qwen2.5-32B-Instruct",         "port": 8004, "tp": 2},
}
for _name, _spec in MODELS.items():
    _spec.setdefault("served_name", _name)

# 고정 judge — 생성모델과 분리·최상위 모델로 고정(생성품질↔채점품질 혼입 방지).
# 32b가 생성풀에도 있으므로 자기출력 채점 칸은 self-preference caveat 대상.
JUDGE_MODEL = "qwen2.5-32b"

# 프롬프트 단계(§4). improve3 = improve2 프롬프트 + 자기검증 2차 패스(Test-Time Scaling).
# label = 표시용 이름(웹 UI·리포트) — 키는 파일명·CLI 호환을 위해 유지.
STAGES = {
    "baseline": {"prompt": "baseline.txt",         "self_verify": False,
                 "label": "Baseline — 맨몸 프롬프트"},
    "improve1": {"prompt": "improve1_prompt.txt",  "self_verify": False,
                 "label": "개선1 · 프롬프트 엔지니어링 (규칙 강화)"},
    "improve2": {"prompt": "improve2_context.txt", "self_verify": False,
                 "label": "개선2 · 컨텍스트 엔지니어링 ([T#] 구조화)"},
    "improve3": {"prompt": "improve2_context.txt", "self_verify": True,
                 "label": "개선3 · Test-Time Scaling (자기검증 2패스)"},
    "soap":     {"prompt": "soap.txt",             "self_verify": False,  # 명시적 S/O/A/P + 세부헤더
                 "label": "최종 · SOAP 규격 (컨텍스트+인용+미확인)"},
    "soap_hard": {"prompt": "soap_hard.txt",     "self_verify": False,
                  "label": "최종·강화 · 노이즈 대응 규칙 (거짓전제·타인정보·조건부)"},
    "soap_strict": {"prompt": "soap_strict.txt",   "self_verify": False, "structured": True,
                    "label": "최종+ · 구조 강제 디코딩 (스키마 보장)"},  # 형식·인용범위를 디코더가 강제
    "soap_fewshot": {"prompt": "soap_fewshot.txt", "self_verify": False,  # 실패모드 3예시(미확인A/P·자기진단·보호자)
                     "label": "최종+예시 · Few-shot (실패모드 예시 3종)"},
    "soap_fewshot_v2": {"prompt": "soap_fewshot_v2.txt", "self_verify": False,  # 고은 예시 18종(규칙4+노이즈5, 반례 포함)
                        "label": "최종+예시 v2 · Few-shot (고은 18예시)"},
    "soap_nocite": {"prompt": "soap_nocite.txt", "self_verify": False,  # A안 사다리 개선1′ = soap 규격+규칙, 인용 없음
                    "label": "개선1′ · 규격+규칙 (인용 없음)"},
}
SELF_VERIFY_PROMPT = "improve3_selfverify.txt"
JUDGE_PROMPT = "judge_grounded.txt"
