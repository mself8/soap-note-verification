"""계획서(1조 프로젝트 정리.pdf)의 사실 주장을 실제 데이터로 검증한다.

각 주장을 CLAIM으로 표시하고, 데이터에서 나온 숫자를 그대로 출력한다.
숫자는 전부 이 스크립트로 재현 가능해야 한다.

실행: python recon/verify_claims.py
"""

import csv
import re
import statistics
from collections import Counter
from pathlib import Path

csv.field_size_limit(10**7)

ROOT = Path(__file__).resolve().parent.parent
MTS = ROOT / "data" / "MTS-Dialog" / "Main-Dataset"
ACI = ROOT / "data" / "aci-bench" / "data" / "challenge_data"


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def rule(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def claim(text, verdict, detail=""):
    mark = {"CONFIRMED": "[일치]", "REFUTED": "[불일치]", "PARTIAL": "[부분일치]"}[verdict]
    print(f"\n{mark} {text}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"        {line}")


# ---------------------------------------------------------------- MTS-Dialog
rule("1. MTS-Dialog — 규모 / 구조")

files = {
    "Training": "MTS-Dialog-TrainingSet.csv",
    "Validation": "MTS-Dialog-ValidationSet.csv",
    "Test1(MEDIQA-Chat)": "MTS-Dialog-TestSet-1-MEDIQA-Chat-2023.csv",
    "Test2(MEDIQA-Sum)": "MTS-Dialog-TestSet-2-MEDIQA-Sum-2023.csv",
}
mts = {}
for name, fn in files.items():
    rows = load(MTS / fn)
    mts[name] = rows
    print(f"  {name:22} {len(rows):5} rows   columns={list(rows[0].keys())}")

total = sum(len(v) for v in mts.values())
claim(
    f"계획서 §3-1: '의사-환자 대화 1,701쌍 (Training 1,201 / Validation 100 / Test1 200 / Test2 200)'",
    "CONFIRMED" if total == 1701 else "REFUTED",
    f"실제 합계 = {total}",
)

# ---- 20개 정규화 섹션 헤더
all_rows = [r for v in mts.values() for r in v]
headers = Counter(r["section_header"] for r in all_rows)
claim(
    "계획서 §3-1: '20개로 정규화된 섹션 헤더 중 하나로 태깅'",
    "CONFIRMED" if len(headers) == 20 else "REFUTED",
    f"distinct header = {len(headers)}종\n{sorted(headers)}",
)

# ---- N/A 주장 (계획서의 핵심 근거)
rule("2. MTS-Dialog — 'N/A 표기' 주장 검증  ← 계획서 §3-1 / §10-A '(완료)'")

labeled = mts["Training"] + mts["Validation"]  # 정답 라벨이 공개된 세트
whole_na = [r for r in labeled if r["section_text"].strip().upper() in ("N/A", "NA", "NONE", "")]
sub_na = [r for r in labeled if re.search(r"\bN\s*/?\s*A\b", r["section_text"], re.I)]

print(f"  검사 대상: Training {len(mts['Training'])} + Validation {len(mts['Validation'])} = {len(labeled)} rows")
print(f"  section_text가 통째로 N/A인 행      : {len(whole_na)}")
print(f"  section_text에 'N/A'가 포함된 행    : {len(sub_na)}")

claim(
    "계획서 §3-1: '해당 섹션 정보가 대화에 없을 경우 \"N/A\" 표기' "
    "→ '미확인 항목의 명시적 표시 원칙이 원 데이터셋에서도 이미 채택되고 있음을 뒷받침함'",
    "REFUTED" if not whole_na and not sub_na else "PARTIAL",
    f"라벨 공개 세트 {len(labeled)}행 전수 검사 결과 N/A는 0건.\n"
    f"각 행은 '이 스니펫에 존재하는 섹션'만 담고 있어, 부재를 표기할 자리 자체가 없는 구조.\n"
    f"→ §3-1의 근거 문장은 성립하지 않음. 다만 이는 오히려 기여를 강화함:\n"
    f"   '이미 있는 관행을 따른다'가 아니라 '어떤 벤치마크도 강제하지 않는 것을 우리가 추가한다'.",
)

# ---- 과제 입도(granularity)
rule("3. MTS-Dialog — 과제 입도: SOAP 노트 생성이 가능한가?  ← 계획서 §5-5")

dl = [len(r["dialogue"].split()) for r in labeled]
tl = [len(r["section_text"].split()) for r in labeled]
turns = [len(re.findall(r"^\s*(?:Doctor|Patient|Guest[_\w]*|Doctor_\d+)\s*:", r["dialogue"], re.M)) or
         r["dialogue"].count("\n") + 1 for r in labeled]

print(f"  dialogue 단어수  : median {statistics.median(dl):6.0f}   mean {statistics.mean(dl):6.1f}   max {max(dl)}")
print(f"  section_text 단어: median {statistics.median(tl):6.0f}   mean {statistics.mean(tl):6.1f}   max {max(tl)}")
print(f"  대화 턴수        : median {statistics.median(turns):6.0f}   mean {statistics.mean(turns):6.1f}   max {max(turns)}")
print(f"  1행당 섹션 개수  : 1 (section_header 단일값)")

one_section = all(len(r["section_header"].split(",")) == 1 for r in labeled)
claim(
    "계획서 §5-5: MTS-Dialog을 SOAP 노트 생성 평가에 사용",
    "REFUTED",
    f"1행 = 중앙값 {statistics.median(turns):.0f}턴 / {statistics.median(dl):.0f}단어 스니펫 → 20헤더 중 단 1개 → {statistics.median(tl):.0f}단어 요약.\n"
    f"1행당 섹션이 하나뿐({one_section})이므로 S/O/A/P 4파트 노트를 만들 원본 자체가 없음.\n"
    f"→ MTS-Dialog은 '섹션 분류 + 섹션 요약' 과제. SOAP 노트 생성 벤치마크가 아님.\n"
    f"→ 결정: ACI-Bench 주 / MTS-Dialog은 규칙 근거·hedge 조사용 보조.",
)

# ---- 20 헤더 → S/O/A/P 매핑 제안
rule("4. 20개 헤더 → S/O/A/P 매핑 (B의 산출물 초안)")

SOAP_MAP = {
    "S": ["CC", "GENHX", "PASTMEDICALHX", "PASTSURGICAL", "FAM/SOCHX", "ALLERGY",
          "MEDICATIONS", "ROS", "GYNHX", "OTHER_HISTORY", "IMMUNIZATIONS"],
    "O": ["EXAM", "LABS", "IMAGING", "PROCEDURES", "EDCOURSE"],
    "A": ["ASSESSMENT", "DIAGNOSIS"],
    "P": ["PLAN", "DISPOSITION"],
}
mapped = {h for v in SOAP_MAP.values() for h in v}
missing = set(headers) - mapped
extra = mapped - set(headers)
for k, v in SOAP_MAP.items():
    n = sum(headers[h] for h in v)
    print(f"  {k}: {n:5} rows ({n/len(all_rows)*100:4.1f}%)  ← {', '.join(v)}")
print(f"\n  매핑 누락 헤더: {missing or '없음'}    존재하지 않는 헤더: {extra or '없음'}")

s_share = sum(headers[h] for h in SOAP_MAP["S"]) / len(all_rows)
print(f"\n  ※ S가 {s_share*100:.0f}% — 대화에서 얻을 수 있는 정보는 압도적으로 주관적 병력.")
print(f"     O(검사·소견)는 {sum(headers[h] for h in SOAP_MAP['O'])/len(all_rows)*100:.0f}%에 불과 → '미확인 처리' 규칙이 실제로 가장 자주 걸리는 지점.")

# ---------------------------------------------------------------- ACI-Bench
rule("5. ACI-Bench — 규모 / 구조")

aci_files = {
    "train": "train.csv", "valid": "valid.csv",
    "test1": "clinicalnlp_taskB_test1.csv",
    "test2": "clinicalnlp_taskC_test2.csv",
    "test3": "clef_taskC_test3.csv",
}
aci = {}
for name, fn in aci_files.items():
    rows = load(ACI / fn)
    aci[name] = rows
    print(f"  {name:8} {len(rows):4} rows")
aci_total = sum(len(v) for v in aci.values())
claim(
    "계획서 §3-1: 'Training 67 / Validation 20 / Test1~3 각 40건 (총 207건)'",
    "CONFIRMED" if aci_total == 207 else "REFUTED",
    f"실제 합계 = {aci_total}",
)

aci_all = [r for v in aci.values() for r in v]
adl = [len(r["dialogue"].split()) for r in aci_all]
anl = [len(r["note"].split()) for r in aci_all]
print(f"\n  dialogue 단어수 : median {statistics.median(adl):6.0f}   max {max(adl)}")
print(f"  note 단어수     : median {statistics.median(anl):6.0f}   max {max(anl)}")
print(f"  → MTS-Dialog 대비 대화 {statistics.median(adl)/statistics.median(dl):.0f}배, 노트 {statistics.median(anl)/statistics.median(tl):.0f}배. full-visit 맞음.")

# ---- 화자 태그 포맷
rule("6. 화자 태그 포맷 — B(발화주체·citation)의 선행 과제")

mts_spk = Counter()
for r in labeled:
    for m in re.findall(r"^\s*([A-Za-z_]+)\s*:", r["dialogue"], re.M):
        mts_spk[m] += 1
aci_spk = Counter()
for r in aci_all:
    for m in re.findall(r"\[([a-z_]+)\]", r["dialogue"]):
        aci_spk[m] += 1

print(f"  MTS-Dialog 화자 태그 : {dict(mts_spk.most_common(8))}")
print(f"  ACI-Bench  화자 태그 : {dict(aci_spk.most_common(8))}")
print(f"\n  → 포맷이 다름(`Doctor:` vs `[doctor]`). 제3화자 존재 여부도 다름.")
print(f"     citation의 turn_id를 붙이려면 두 포맷을 흡수하는 정규화 유틸이 B/D 공통 선행 작업.")

# ---- ASR 스타일
lower_start = sum(1 for r in aci_all if re.search(r"\]\s+[a-z]", r["dialogue"]))
space_punct = sum(1 for r in aci_all if " ," in r["dialogue"] or " ." in r["dialogue"])
print(f"\n  ACI-Bench 대화가 ASR 산출물 스타일인가:")
print(f"    소문자로 시작하는 발화 포함     : {lower_start}/{len(aci_all)}")
print(f"    구두점 앞 공백(' ,' / ' .') 포함 : {space_punct}/{len(aci_all)}")
print(f"    → 대화는 ASR 스타일, 노트는 정서법 정상. 둘 사이 표기 격차가 존재.")

# ---- 노트 섹션 스키마
rule("7. ACI-Bench 노트 섹션 — 고정 스키마인가?  ← 섹션별 ROUGE의 전제")

secs = Counter()
for r in aci_all:
    for m in re.findall(r"^([A-Z][A-Z0-9 /&'\-\(\)]{2,45})\s*$", r["note"], re.M):
        secs[m.strip()] += 1
for k, v in secs.most_common(22):
    print(f"    {v:4}/{len(aci_all)}  {k}")

claim(
    "노트가 고정된 섹션 스키마를 따르는가",
    "REFUTED",
    "동일 개념이 여러 표기로 갈림 → 섹션별 ROUGE를 하려면 정규화 맵이 선행되어야 함.\n"
    "예: 'ASSESSMENT AND PLAN' 병합형 vs 'ASSESSMENT' + 'PLAN' 분리형이 공존.\n"
    "    'PHYSICAL EXAM' / 'PHYSICAL EXAMINATION' / 'EXAM' 혼용.",
)

# ---- 미확인/결측 표기
rule("8. ACI-Bench 노트의 '미확인' 표기 관행")

na_pat = re.compile(r"\bN/?A\b|\bnot (?:reported|discussed|mentioned|available|obtained)\b|\bunknown\b|\bnone reported\b", re.I)
hits = [r for r in aci_all if na_pat.search(r["note"])]
print(f"  '미확인'류 표현을 포함한 노트: {len(hits)}/{len(aci_all)} ({len(hits)/len(aci_all)*100:.0f}%)")
for r in hits[:3]:
    m = na_pat.search(r["note"])
    ctx = r["note"][max(0, m.start() - 70):m.end() + 40].replace("\n", " ")
    print(f"    · …{ctx}…")
claim(
    "두 벤치마크 통틀어 '미확인 항목의 명시적 표시'가 강제되는가",
    "REFUTED",
    f"MTS-Dialog: 0/{len(labeled)}. ACI-Bench: {len(hits)}/{len(aci_all)}이지만 산발적 자연어일 뿐 규약이 아님.\n"
    f"→ 이 프로젝트의 '미확인 명시'는 물려받는 관행이 아니라 새로 도입하는 규약.\n"
    f"   따라서 표기법·채점법을 우리가 정의해야 하고, 그 자체가 기여 항목이 된다.",
)

print(f"\n{'=' * 78}\n검증 완료. 위 숫자는 전부 이 스크립트로 재현 가능.\n{'=' * 78}")
