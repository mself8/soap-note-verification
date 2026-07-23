# -*- coding: utf-8 -*-
"""발표 그래프 재현 스크립트 — 실험 1(단계 사다리) 5장 + 실험 2(노이즈) 6장 = 11장

두 단계로 나뉜다:
  1) build_data(): outputs/(scores·judge)에서 그래프용 수치를 집계해
     reports/figure_data.json 저장 — outputs/는 gitignore라 GPU 재실행 없이도
     그래프가 재현되도록 집계본을 커밋해 둔다.
  2) render_all(): reports/figure_data.json만 읽어 11장 렌더 → docs/figures/
     (outputs/ 없이 동작. 노트북 notebooks/figures.ipynb가 이 함수들을 사용)

두 실험 모두 같은 5지표(ROUGE-1 · 구역정렬 · 환각률 · 인용 정밀도 · BERTScore) ×
같은 4모델로 평가한다.

  실험 1 (ACI-Bench test 120건): Baseline → 개선1 → 개선2 → 개선3
  실험 2 (김고은 형태노이즈 100건): 개선3 → +노이즈 방어 규칙 → +Few-shot 예시
                                    (세 전략 모두 개선3의 검증기 교정 적용)

실행:  .venv/bin/python scripts/make_figures.py            # 렌더만 (커밋된 json 사용)
       .venv/bin/python scripts/make_figures.py --rebuild  # outputs/에서 json 재집계 후 렌더
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "reports" / "figure_data.json"
FIGDIR = ROOT / "docs" / "figures"

MODELS = ["qwen2.5-7b", "llama3.1-8b", "mistral-7b", "qwen2.5-32b"]
LADDER_SPLITS = ["test1", "test2", "test3"]
# (stage, revise suffix) — 개선3 = 개선2(soap) 출력에 32B 검증기 자동교정
LADDER_STAGES = [("baseline", ""), ("soap_nocite", ""), ("soap", ""), ("soap", "__rev-drop")]
NOISE_STAGES = ["soap", "soap_hard", "soap_fewshot"]  # 전부 __rev-drop(교정) 적용본
NOISE_TYPES = {"N_G": "third_party", "N_M": "asr_mistag", "N_T": "temporal",
               "N_R": "requant", "N_N": "asr_numeric"}

METRICS = [
    ("r1",   "ROUGE-1 F1  (gold 노트 유사도)  ↑",        "{:.3f}", ""),
    ("sec",  "구역정렬  (S/O/A/P 구역별 ROUGE-1 평균)  ↑", "{:.2f}", ""),
    ("hr",   "환각률 (%)  ↓ 낮을수록 좋음",               "{:.1f}", "%"),
    ("cite", "인용 정밀도  ↑",                            "{:.3f}", ""),
    ("bert", "BERTScore F1 (rescaled)  ↑",                "{:.3f}", ""),
]

# 팔레트(검증됨)
INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; BASE = "#c3c2b7"
BLUE = "#2a78d6"; ORANGE = "#eb6834"; AQUA = "#1baf7a"

for _p in ["/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
           "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"]:
    try:
        fm.fontManager.addfont(_p)
    except Exception:  # noqa: BLE001 — 폰트 없으면 기본 폰트로 진행
        pass
plt.rcParams.update({"font.family": "NanumBarunGothic", "axes.unicode_minus": False,
                     "figure.facecolor": "white", "axes.facecolor": "white"})


# ---------------- 1) 집계 ----------------
def _read_one(stem):
    """scores·judge 산출물 한 쌍 → 5지표 튜플. 없으면 None."""
    sc_p = ROOT / f"outputs/scores/{stem}.json"
    jd_p = ROOT / f"outputs/judge/{stem}.summary.json"
    if not (sc_p.exists() and jd_p.exists()):
        return None
    sc, jd = json.load(open(sc_p)), json.load(open(jd_p))
    return {"r1": sc["rouge1"],
            "sec": sum(v["rouge1"] for v in sc["divisions"].values()) / 4,
            "hr": jd["hallucination_rate"] * 100,
            "cite": jd.get("citation_precision"),
            "bert": sc["bertscore_f1"]}


def _avg(vals, key):
    got = [v[key] for v in vals if v is not None and v[key] is not None]
    return sum(got) / len(got) if got else None


def _hr_by_type(stem):
    """judge jsonl → 노이즈 유형별 노트평균 환각률(%)."""
    path = ROOT / f"outputs/judge/{stem}.jsonl"
    if not path.exists():
        return None
    per = {}
    for line in open(path):
        r = json.loads(line)
        if r["grounded"] is None:
            continue
        e = per.setdefault(r["encounter_id"], [0, 0])
        e[1] += 1
        if not r["grounded"]:
            e[0] += 1
    rate = {k: v[0] / v[1] for k, v in per.items() if v[1]}
    if not rate:
        return None
    out = {"overall": sum(rate.values()) / len(rate) * 100}
    for pre, name in NOISE_TYPES.items():
        vals = [v for k, v in rate.items() if k.startswith(pre)]
        out[name] = sum(vals) / len(vals) * 100 if vals else None
    return out


def build_data():
    ladder = {k: {} for k, _, _, _ in METRICS}
    for m in MODELS:
        cols = {k: [] for k, _, _, _ in METRICS}
        for st, rev in LADDER_STAGES:
            vals = [_read_one(f"aci-{sp}__{m}__{st}{rev}") for sp in LADDER_SPLITS]
            for k, _, _, _ in METRICS:
                cols[k].append(_avg(vals, k))
        for k, _, _, _ in METRICS:
            ladder[k][m] = cols[k]

    noise = {k: {} for k, _, _, _ in METRICS}
    noise_by_type = {}
    for m in MODELS:
        cols = {k: [] for k, _, _, _ in METRICS}
        noise_by_type[m] = {}
        for st in NOISE_STAGES:
            stem = f"own-noise100__{m}__{st}__rev-drop"
            v = _read_one(stem)
            for k, _, _, _ in METRICS:
                cols[k].append(v[k] if v else None)
            noise_by_type[m][st] = _hr_by_type(stem)
        for k, _, _, _ in METRICS:
            noise[k][m] = cols[k]

    missing = [m for m in MODELS if all(v is None for v in noise["hr"][m])]
    if missing:
        print(f"[figure_data] 주의: 노이즈 데이터 없는 모델 {missing} (그래프에서 제외됨)")

    data = {"ladder": ladder, "noise": noise, "noise_by_type": noise_by_type,
            "meta": {
                "ladder_eval": "ACI-Bench test 120건 · 4개 모델 · 판정=Qwen2.5-32B Judge · "
                               "전 단계 동일 SOAP 규격",
                "noise_eval": "김고은 형태노이즈 100건 · 4개 모델 · 세 전략 모두 개선3(검증기 교정) 적용",
            }}
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[figure_data] 저장 → {DATA_JSON}")
    return data


def load_data():
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


# ---------------- 2) 렌더 ----------------
LADDER_XLAB = ["Baseline\n(기본 프롬프트)", "개선 1\n프롬프트 엔지니어링",
               "개선 2\n컨텍스트 엔지니어링", "개선 3\nTest-Time Scaling"]
NOISE_XLAB = ["개선 3\n(최종 시스템)", "+ 노이즈 방어 규칙", "+ Few-shot 예시"]


def _style(ax):
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=11)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _line_chart(per_model, xlab, title, subtitle, ylab, fmt, unit=""):
    """4모델 평균(파랑 굵은선) + 개별(회색 얇은선). per_model[m] = 단계별 값 리스트."""
    n = len(xlab)
    models = [m for m in MODELS if m in per_model
              and any(v is not None for v in per_model[m])]
    mean = []
    for i in range(n):
        vs = [per_model[m][i] for m in models if per_model[m][i] is not None]
        mean.append(sum(vs) / len(vs) if vs else None)

    fig, ax = plt.subplots(figsize=(9.2, 5.4), dpi=200)
    for m in models:
        ys = per_model[m]
        xs = [i for i in range(n) if ys[i] is not None]
        ax.plot(xs, [ys[i] for i in xs], color=BASE, lw=1.2, marker="o", ms=3.5, zorder=2)
    xs = [i for i in range(n) if mean[i] is not None]
    ax.plot(xs, [mean[i] for i in xs], color=BLUE, lw=2.6, marker="o", ms=8, zorder=4,
            markeredgecolor="white", markeredgewidth=1.6)
    for i in xs:
        ax.annotate(fmt.format(mean[i]) + unit, (i, mean[i]), textcoords="offset points",
                    xytext=(0, 11), ha="center", fontsize=12.5, color=INK,
                    fontweight="bold", zorder=5)

    ax.set_xticks(range(n)); ax.set_xticklabels(xlab, fontsize=11.5, color=INK2)
    ax.set_xlim(-0.35, n - 0.65)
    allv = [v for m in models for v in per_model[m] if v is not None]
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.18 if hi > lo else max(abs(hi) * 0.1, 0.01)
    # 비율·점수 지표라 음수 영역은 의미가 없다 — 아래 여백은 0 근처에서 잘라낸다.
    bottom = max(lo - pad, -0.05 * hi) if lo >= 0 else lo - pad
    ax.set_ylim(bottom, hi + pad * 2.2)
    ax.set_yticks([t for t in ax.get_yticks() if t >= 0])
    ax.set_ylim(bottom, hi + pad * 2.2)
    ax.set_ylabel(ylab, fontsize=12, color=INK2)
    _style(ax)
    ax.set_title(title, fontsize=16, color=INK, fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.035, subtitle, transform=ax.transAxes, fontsize=10.5, color=MUTED)
    ax.legend(handles=[
        Line2D([], [], color=BLUE, lw=2.6, marker="o", ms=7,
               markeredgecolor="white", label=f"{len(models)}개 모델 평균"),
        Line2D([], [], color=BASE, lw=1.2, marker="o", ms=3.5, label="개별 모델"),
    ], loc="best", frameon=False, fontsize=11)
    fig.tight_layout()
    return fig


NOISE_TYPE_ORDER = ["overall", "third_party", "asr_mistag", "temporal",
                    "asr_numeric", "requant"]
NOISE_TYPE_XLAB = ["전체", "제3화자 발화\n(보호자 진술)", "ASR 화자\n오태깅",
                   "시간 순서\n교란", "ASR 수치\n오류", "수치 정정\n(재질문)"]
NOISE_SERIES = [("soap", "개선 3 (최종 시스템)", BLUE),
                ("soap_hard", "+ 노이즈 방어 규칙", ORANGE),
                ("soap_fewshot", "+ Few-shot 예시", AQUA)]


def fig_noise_by_type(data):
    """전략별 × 노이즈 유형별 환각률 (4모델 평균)."""
    fig, ax = plt.subplots(figsize=(10.4, 5.6), dpi=200)
    used = set()
    for st, label, color in NOISE_SERIES:
        ys = []
        for k in NOISE_TYPE_ORDER:
            vals = [data["noise_by_type"][m][st][k] for m in MODELS
                    if data["noise_by_type"].get(m, {}).get(st)
                    and data["noise_by_type"][m][st].get(k) is not None]
            used.update(m for m in MODELS
                        if data["noise_by_type"].get(m, {}).get(st))
            ys.append(sum(vals) / len(vals) if vals else None)
        xs = [i for i, v in enumerate(ys) if v is not None]
        ax.plot(xs, [ys[i] for i in xs], color=color, lw=2.4, marker="o", ms=7.5,
                zorder=3, markeredgecolor="white", markeredgewidth=1.4, label=label)
        if ys[0] is not None:
            ax.annotate(f"{ys[0]:.1f}%", (0, ys[0]), textcoords="offset points",
                        xytext=(-8, 6), ha="right", fontsize=11.5, color=INK,
                        fontweight="bold", zorder=5)
    ax.axvline(0.5, color=GRID, lw=1.0)
    ax.set_xticks(range(len(NOISE_TYPE_ORDER)))
    ax.set_xticklabels(NOISE_TYPE_XLAB, fontsize=11, color=INK2)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("환각률 (%)  ↓ 낮을수록 좋음", fontsize=12, color=INK2)
    _style(ax)
    ax.set_title("노이즈 유형별 환각률 — 전략 비교", fontsize=16, color=INK,
                 fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.035, f"{data['meta']['noise_eval']} · {len(used)}개 모델 평균",
            transform=ax.transAxes, fontsize=10.5, color=MUTED)
    ax.legend(loc="upper right", frameon=False, fontsize=11.5)
    fig.tight_layout()
    return fig


def render_all(data=None, outdir=FIGDIR):
    data = data or load_data()
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    jobs = []

    # 실험 1 — 단계 사다리 5장
    for key, ylab, fmt, unit in METRICS:
        title = {"r1": "실험 1 · 단계별 ROUGE-1 — 내용 유사도",
                 "sec": "실험 1 · 단계별 구역정렬 — 맞는 내용이 맞는 구역에",
                 "hr": "실험 1 · 단계별 환각률 — 근거 없는 문장 비율",
                 "cite": "실험 1 · 단계별 인용 정밀도 — 인용은 개선 2에서 도입",
                 "bert": "실험 1 · 단계별 BERTScore — 의미 유사도"}[key]
        jobs.append((_line_chart(data["ladder"][key], LADDER_XLAB, title,
                                 data["meta"]["ladder_eval"], ylab, fmt, unit),
                     f"exp1_{key}.png"))

    # 실험 2 — 노이즈 전략 5장
    for key, ylab, fmt, unit in METRICS:
        title = {"r1": "실험 2 · 노이즈 대화 ROUGE-1 — 내용 유사도",
                 "sec": "실험 2 · 노이즈 대화 구역정렬",
                 "hr": "실험 2 · 노이즈 대화 환각률 — 전략별",
                 "cite": "실험 2 · 노이즈 대화 인용 정밀도",
                 "bert": "실험 2 · 노이즈 대화 BERTScore"}[key]
        jobs.append((_line_chart(data["noise"][key], NOISE_XLAB, title,
                                 data["meta"]["noise_eval"], ylab, fmt, unit),
                     f"exp2_{key}.png"))

    # 실험 2 — 유형별 환각률 1장
    jobs.append((fig_noise_by_type(data), "exp2_hr_by_type.png"))

    for fig, name in jobs:
        fig.savefig(outdir / name, bbox_inches="tight")
        plt.close(fig)
        print(f"[figures] 저장 → {outdir / name}")
    print(f"[figures] 총 {len(jobs)}장")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="outputs/에서 reports/figure_data.json 재집계 후 렌더")
    args = ap.parse_args()
    render_all(build_data() if args.rebuild else load_data())
