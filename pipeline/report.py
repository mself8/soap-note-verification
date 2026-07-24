"""비교 리포트 (E1·E4) — {model × stage × dataset} 격자 + 실패사례 덤프.

  python -m pipeline.report

outputs/scores/*.json(metrics) + outputs/judge/*.summary.json(judge)를 stem으로 조인해
reports/comparison.{csv,md} 격자표 생성. judge jsonl의 환각(grounded=false) 문장은 실패사례로 덤프.
파일 stem 규약: <dataset>-<split>__<model>__<stage>
"""
import json

import pandas as pd

from . import config

COLS = ["run", "model", "stage", "n",
        "rouge1", "rouge2", "rougeL", "bertscore_f1",
        "grounded_rate", "hallucination_rate", "citation_precision"]


def _parse_stem(stem):
    run, model, stage = (stem.split("__") + ["", "", ""])[:3]
    return run, model, stage


def _to_md(df):
    """tabulate 의존 없이 마크다운 표 생성."""
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def collect():
    rows = []
    for sp in sorted(config.SCORES.glob("*.json")):
        stem = sp.stem
        m = json.loads(sp.read_text(encoding="utf-8"))
        run, model, stage = _parse_stem(stem)
        row = {"run": run, "model": model, "stage": stage, "n": m.get("n")}
        for k in ["rouge1", "rouge2", "rougeL", "bertscore_f1"]:
            row[k] = m.get(k)
        jp = config.JUDGE_OUT / f"{stem}.summary.json"
        if jp.exists():
            j = json.loads(jp.read_text(encoding="utf-8"))
            for k in ["grounded_rate", "hallucination_rate", "citation_precision"]:
                row[k] = j.get(k)
        rows.append(row)
    return rows


def dump_failures(max_per_run=15):
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS / "failures.md"
    lines = ["# 실패사례 — judge가 근거없음(hallucination)으로 판정한 문장\n"]
    for jp in sorted(config.JUDGE_OUT.glob("*.jsonl")):
        bad = []
        for ln in jp.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            if r.get("grounded") is False:
                bad.append(r)
        if not bad:
            continue
        lines.append(f"\n## {jp.stem}  ({len(bad)}건)\n")
        for r in bad[:max_per_run]:
            lines.append(f"- `{r.get('encounter_id')}` cited={r.get('cited_turns')}: {r['sent']}")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main():
    rows = collect()
    if not rows:
        print("[report] outputs/scores/ 가 비었음 — 먼저 generate + metrics 실행")
        return
    df = pd.DataFrame(rows)
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df = df[COLS].sort_values(["run", "stage", "model"])

    config.REPORTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.REPORTS / "comparison.csv", index=False)
    md = "# 비교 격자 (model × stage × dataset)\n\n" + _to_md(df)
    md += ("\n\n> 자동지표(ROUGE/BERTScore)=유사도·누락 대리. "
           "환각은 hallucination_rate(judge)가 주지표(1일차 결론).\n")
    (config.REPORTS / "comparison.md").write_text(md, encoding="utf-8")
    fp = dump_failures()

    print(df.to_string(index=False))
    print(f"\n[report] → {config.REPORTS/'comparison.md'} / .csv, 실패사례 → {fp}")


if __name__ == "__main__":
    main()
