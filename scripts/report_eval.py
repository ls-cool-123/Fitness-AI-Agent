"""把多个检索评测结果汇总成一张对照表。

用法：
    uv run python scripts/report_eval.py tests/eval/results_b0.json tests/eval/results_zh.json

每个输入文件由 ``run_retrieval_eval.py --output`` 生成，里面是
``{collection, results: {模式: {指标: 值}}}``。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

METRICS = ["召回率@5", "精确率@5", "平均倒数排名", "折损累计增益@5"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    payloads = []
    for path in args.files:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # 文件标签用文件名，避免同一集合被跑多次时分不清是哪一次
        payloads.append((f"{data['collection']} ({Path(path).stem})", data["results"]))

    # 取所有文件里出现过的模式（某次评测可能跳过了重排）
    modes = []
    for _, results in payloads:
        for mode in results:
            if mode not in modes:
                modes.append(mode)
    print(f"{'模式':<22}{'集合':<20}" + "".join(f"{m:>12}" for m in METRICS))
    print("-" * (42 + 12 * len(METRICS)))
    for mode in modes:
        for collection, results in payloads:
            row = results.get(mode)
            if not row:
                continue
            print(
                f"{mode:<22}{collection:<20}"
                + "".join(f"{row[m]:>12.4f}" for m in METRICS)
            )
    print()

    # 同一集合内，Hybrid 相对 Dense 的增益
    print("增益（Hybrid 无重排 vs Dense-only）：")
    for collection, results in payloads:
        dense = results.get("A. Dense-only")
        hybrid = results.get("C. Hybrid (无重排)")
        if not dense or not hybrid:
            continue
        parts = []
        for metric in METRICS:
            delta = hybrid[metric] - dense[metric]
            parts.append(f"{metric} {delta:+.4f}")
        print(f"  {collection}: " + "，".join(parts))


if __name__ == "__main__":
    main()
