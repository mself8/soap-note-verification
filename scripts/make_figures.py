# -*- coding: utf-8 -*-
"""발표 그래프 재현 스크립트 (docs/figures/fig1·fig1b·fig1c·fig2)

두 단계로 나뉜다:
  1) build_data(): outputs/(scores·judge)와 reports/comparison.csv에서 그래프용 수치를
     집계해 reports/figure_data.json 저장 — outputs/는 gitignore라 GPU 재실행 없이도
     그래프가 재현되도록 집계본을 커밋해 둔다.
  2) render_all(): reports/figure_data.json만 읽어 5장 렌더 → docs/figures/
     (outputs/ 없이 동작. 노트북 notebooks/figures.ipynb가 이 함수들을 사용)

실행:  .venv/bin/python scripts/make_figures.py            # 렌더만 (커밋된 json 사용)
       .venv/bin/python scripts/make_figures.py --rebuild  # outputs/에서 json 재집계 후 렌더
"""
import argparse
import csv
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
NOISE_MODELS = ["qwen2.5-32b", "qwen2.5-7b"]
NOISE_STAGES = ["soap", "soap_hard", "soap_fewshot"]
NOISE_TYPES = {"N_G": "third_party", "N_M": "asr_mistag", "N_T": "temporal",
               "N_R": "requant", "N_N": "asr_numeric"}

# 팔레트(검증됨): 파랑/주황/청록 + 잉크·회색 계열
INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; BASE = "#c3c2b7"
BLUE = "#2a78d6"; ORANGE = "#eb6834"; AQUA = "#1baf7a"

for _p in ["/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
           "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"]:
    try:
        fm.fontManager.addfont(_p)
    except Exception:  # noqa: BLE001 — 폰트 없으면 기본 폰트로 진행(한글 깨짐만 감수)
        pass
plt.rcParams.update({"font.family": "NanumBarunGothic", "axes.unicode_minus": False,
                     "figure.facecolor": "white", "axes.facecolor": "white"})


# ---------------- 1) 집계 ----------------
def _secmean(path):
    d = json.load(open(path))
    return sum(v["rouge1"] for v in d["divisions"].values()) / 4


def build_data():
    """outputs/·reports/에서 그래프 수치 집계 → reports/figure_data.json"""
    rows = {}
    with open(ROOT / "reports" / "comparison.csv") as f:
        for row in csv.DictReader(f):
            if row["run"] == "aci-valid":
                rows[(row["model"], row["stage"])] = row

    ladder = {m: {} for m in ["r1", "sec", "hr", "cite"]}
    for m in MODELS:
        r1s, hrs, cps, secs = [], [], [], []
        for s in ["baseline", "improve1", "improve2"]:
            r = rows[(m, s)]
            r1s.append(float(r["rouge1"]))
            hrs.append(float(r["hallucination_rate"]) * 100)
            cps.append(float(r["citation_precision"]) if r["citation_precision"] else None)
            secs.append(_secmean(ROOT / f"outputs/scores/aci-valid__{m}__{s}.json"))
        # 개선3 = 개선2 출력 + 32B 검증기 교정(rev-rewrite)
        sc = json.load(open(ROOT / f"outputs/scores/aci-valid__{m}__improve2__rev-rewrite.json"))
        jd = json.load(open(ROOT / f"outputs/judge/aci-valid__{m}__improve2__rev-rewrite.summary.json"))
        r1s.append(sc["rouge1"])
        secs.append(sum(v["rouge1"] for v in sc["divisions"].values()) / 4)
        hrs.append(jd["hallucination_rate"] * 100)
        cps.append(jd["citation_precision"])
        ladder["r1"][m], ladder["sec"][m] = r1s, secs
        ladder["hr"][m], ladder["cite"][m] = hrs, cps

    noise = {}
    for m in NOISE_MODELS:
        noise[m] = {}
        for st in NOISE_STAGES:
            per = {}
            for line in open(ROOT / f"outputs/judge/own-noise100__{m}__{st}.jsonl"):
                r = json.loads(line)
                if r["grounded"] is None:
                    continue
                e = per.setdefault(r["encounter_id"], [0, 0])
                e[1] += 1
                if not r["grounded"]:
                    e[0] += 1
            rate = {k: v[0] / v[1] for k, v in per.items() if v[1]}
            out = {"overall": sum(rate.values()) / len(rate) * 100}
            for pre, name in NOISE_TYPES.items():
                vals = [v for k, v in rate.items() if k.startswith(pre)]
                out[name] = sum(vals) / len(vals) * 100
            noise[m][st] = out

    data = {"ladder": ladder, "noise": noise,
            "meta": {"ladder_eval": "ACI-Bench valid 20건, judge=Qwen2.5-32B, "
                                    "개선3=개선2 출력+32B 검증기 교정(rev-rewrite)",
                     "noise_eval": "김고은 형태노이즈 100건, 노트별 평균 환각률(%)"}}
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[figure_data] 저장 → {DATA_JSON}")
    return data


def load_data():
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


# ---------------- 2) 렌더 ----------------
XLAB = ["Baseline\n(기본 프롬프트)", "개선 1\n프롬프트 엔지니어링",
        "개선 2\n컨텍스트 엔지니어링", "개선 3\nTTS · 검증기 자동교정"]
XS = ["Baseline", "개선 1", "개선 2", "개선 3"]


def _style(ax):
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=11)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _ladder_series(data, metric):
    """metric별 (모델→값4, 평균4). grounded는 hr에서 유도."""
    if metric == "grounded":
        per = {m: [100 - v for v in data["ladder"]["hr"][m]] for m in MODELS}
    else:
        per = data["ladder"][metric]
    mean = []
    for i in range(4):
        vs = [per[m][i] for m in MODELS if per[m][i] is not None]
        mean.append(sum(vs) / len(vs) if vs else None)
    return per, mean


def _single(data, metric, title, ylab, fmt, unit=""):
    per, mean = _ladder_series(data, metric)
    fig, ax = plt.subplots(figsize=(9.2, 5.4), dpi=200)
    for m in MODELS:
        ax.plot(range(4), per[m], color=BASE, lw=1.2, marker="o", ms=3.5, zorder=2)
    ax.plot(range(4), mean, color=BLUE, lw=2.6, marker="o", ms=8, zorder=4,
            markeredgecolor="white", markeredgewidth=1.6)
    for x, y in zip(range(4), mean):
        ax.annotate(fmt.format(y) + unit, (x, y), textcoords="offset points",
                    xytext=(0, 11), ha="center", fontsize=12.5, color=INK,
                    fontweight="bold", zorder=5)
    ax.set_xticks(range(4)); ax.set_xticklabels(XLAB, fontsize=11.5, color=INK2)
    allv = [v for m in MODELS for v in per[m] if v is not None]
    lo, hi = min(allv), max(allv); pad = (hi - lo) * 0.18
    ax.set_ylim(lo - pad, hi + pad * 2.2)
    ax.set_ylabel(ylab, fontsize=12, color=INK2)
    _style(ax)
    ax.set_title(title, fontsize=16, color=INK, fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.035, data["meta"]["ladder_eval"], transform=ax.transAxes,
            fontsize=10.5, color=MUTED)
    ax.legend(handles=[
        Line2D([], [], color=BLUE, lw=2.6, marker="o", ms=7, markeredgecolor="white", label="4개 모델 평균"),
        Line2D([], [], color=BASE, lw=1.2, marker="o", ms=3.5, label="개별 모델"),
    ], loc="lower right", frameon=False, fontsize=11)
    fig.tight_layout()
    return fig


def fig1(data):
    return _single(data, "r1", "프롬프트 단계별 SOAP 노트 품질 향상",
                   "ROUGE-1 F1  (gold 노트 유사도)", "{:.3f}")


def fig1c(data):
    return _single(data, "grounded", "단계별 근거율 향상 — 모든 문장이 대화에 근거하는가",
                   "근거율 (%)  = 근거 있는 문장 비율  ↑", "{:.1f}", "%")


def fig1b(data):
    panels = [("r1", "ROUGE-1 F1  (gold 유사도)  ↑", "{:.3f}"),
              ("sec", "구역정렬  (S/O/A/P 구역별 ROUGE-1 평균)  ↑", "{:.2f}"),
              ("hr", "환각률 (%)  ↓ 낮을수록 좋음", "{:.1f}"),
              ("cite", "인용 정밀도  ↑  (개선 2에서 인용 도입)", "{:.3f}")]
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 7.2), dpi=200)
    for ax, (metric, title, fmt) in zip(axes.flat, panels):
        per, mean = _ladder_series(data, metric)
        for m in MODELS:
            ax.plot(range(4), per[m], color=BASE, lw=1.0, marker="o", ms=3, zorder=2)
        ax.plot(range(4), mean, color=BLUE, lw=2.4, marker="o", ms=6.5, zorder=4,
                markeredgecolor="white", markeredgewidth=1.3)
        for x, y in zip(range(4), mean):
            if y is None:
                continue
            ax.annotate(fmt.format(y), (x, y), textcoords="offset points", xytext=(0, 9),
                        ha="center", fontsize=10.5, color=INK, fontweight="bold", zorder=5)
        if metric == "cite":
            ax.annotate("인용 없음", (0.22, 0.45), xycoords="axes fraction",
                        ha="center", fontsize=10, color=MUTED)
        _style(ax)
        ax.tick_params(labelsize=9.5)
        ax.set_xticks(range(4)); ax.set_xticklabels(XS, fontsize=10.5, color=INK2)
        ax.set_title(title, fontsize=12, color=INK, loc="left", pad=8)
        allv = [v for m in MODELS for v in per[m] if v is not None]
        allv += [v for v in mean if v is not None]
        lo, hi = min(allv), max(allv); pad = (hi - lo) * 0.22 + 1e-9
        ax.set_ylim(max(0, lo - pad), hi + pad * 1.6)
    fig.suptitle("프롬프트 단계별 성능 — 4개 지표 모두 개선", fontsize=16, color=INK,
                 fontweight="bold", x=0.065, ha="left", y=0.985)
    fig.text(0.065, 0.935, "ACI-Bench valid 20건 · 4개 모델 평균(파랑)+개별(회색) · "
             "개선1=프롬프트 · 개선2=컨텍스트 · 개선3=TTS(검증기 자동교정)",
             fontsize=10, color=MUTED)
    fig.legend(handles=[
        Line2D([], [], color=BLUE, lw=2.4, marker="o", ms=6, markeredgecolor="white", label="4개 모델 평균"),
        Line2D([], [], color=BASE, lw=1.0, marker="o", ms=3, label="개별 모델"),
    ], loc="upper right", bbox_to_anchor=(0.985, 1.0), frameon=False, fontsize=10.5)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    return fig


NOISE_ORDER = ["overall", "third_party", "asr_mistag", "temporal", "asr_numeric", "requant"]
NOISE_XLAB = ["전체", "제3화자 발화\n(보호자 진술)", "ASR 화자\n오태깅", "시간 순서\n교란",
              "ASR 수치\n오류", "수치 정정\n(재질문)"]
NOISE_SERIES = [("soap", "기존 ACI 프롬프트", BLUE),
                ("soap_hard", "+ 노이즈 방어 규칙", ORANGE),
                ("soap_fewshot", "+ Few-shot 예시", AQUA)]


def fig2(data, model, model_label, ymax):
    d = data["noise"][model]
    fig, ax = plt.subplots(figsize=(10.4, 5.6), dpi=200)
    for st, label, color in NOISE_SERIES:
        ax.plot(range(len(NOISE_ORDER)), [d[st][k] for k in NOISE_ORDER], color=color,
                lw=2.4, marker="o", ms=7.5, zorder=3, markeredgecolor="white",
                markeredgewidth=1.4, label=label)
    for st, _, _ in NOISE_SERIES:
        dy = -18 if st == "soap" else 10
        ax.annotate(f"{d[st]['overall']:.1f}%", (0, d[st]["overall"]),
                    textcoords="offset points", xytext=(-2, dy), ha="right",
                    fontsize=12, color=INK, fontweight="bold", zorder=5)
    for i, k in enumerate(NOISE_ORDER[1:], start=1):
        ax.annotate(f"{d['soap_fewshot'][k]:.1f}", (i, d["soap_fewshot"][k]),
                    textcoords="offset points", xytext=(10, 7), ha="left",
                    fontsize=10, color=INK2, zorder=5)
    peak = max(NOISE_ORDER[1:], key=lambda k: d["soap"][k])
    ax.annotate(f"{d['soap'][peak]:.1f}%", (NOISE_ORDER.index(peak), d["soap"][peak]),
                textcoords="offset points", xytext=(-9, 4), ha="right",
                fontsize=11, color=INK, fontweight="bold")
    ax.axvline(0.5, color=GRID, lw=1.0)
    ax.set_xticks(range(len(NOISE_ORDER)))
    ax.set_xticklabels(NOISE_XLAB, fontsize=11, color=INK2)
    ax.set_ylim(0, ymax)
    ax.set_ylabel("환각률 (%)  ↓ 낮을수록 좋음", fontsize=12, color=INK2)
    _style(ax)
    ax.set_title("노이즈 대화에서의 프롬프트 전략별 환각률", fontsize=16, color=INK,
                 fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.035, f"{data['meta']['noise_eval']} · {model_label} · LLM Judge 문장 판정",
            transform=ax.transAxes, fontsize=10.5, color=MUTED)
    ax.legend(loc="upper right", frameon=False, fontsize=11.5)
    fig.tight_layout()
    return fig


def render_all(data=None, outdir=FIGDIR):
    data = data or load_data()
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    jobs = [(fig1(data), "fig1_stage_performance.png"),
            (fig1c(data), "fig1c_stage_grounded.png"),
            (fig1b(data), "fig1b_stage_metrics_2x2.png"),
            (fig2(data, "qwen2.5-32b", "Qwen2.5-32B", 16), "fig2_noise_prompts_32b.png"),
            (fig2(data, "qwen2.5-7b", "Qwen2.5-7B (보조)", 28), "fig2_noise_prompts_7b.png")]
    for fig, name in jobs:
        fig.savefig(outdir / name, bbox_inches="tight")
        plt.close(fig)
        print(f"[figures] 저장 → {outdir / name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="outputs/에서 reports/figure_data.json 재집계 후 렌더")
    args = ap.parse_args()
    render_all(build_data() if args.rebuild else load_data())
