#!/usr/bin/env python3
"""模型可靠性预检 — 快速探测各模型是否可用/速度, 过滤不可靠模型后再评估。

目的: 每次全量评估 40 分钟太重。先用 1 条短 prompt 探活, 排除超时/失败/过慢
的模型, 只对可靠模型跑全量, 省时间。

用法:
  export EVAL_API_BASE=... EVAL_API_KEY=...
  python3 check_reliability.py --models model-a model-b model-c
  python3 check_reliability.py --models ... --max-latency 60   # 超过 60s 判为不可靠

输出:
  reliable.json — {reliable: [...], slow: [...], failed: [...]}
  可直接喂给小评估: echo $(jq -r '.reliable[]' reliable.json)

判定:
  reliable — 成功且延迟 <= 阈值
  slow     — 成功但延迟 > 阈值 (建议先调优再评)
  failed   — 报错/超时
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_eval import call_model, load_api_key, API_BASE  # noqa: E402

PROBE_PROMPT = "用 100 字以内解释什么是机器学习，并举一个例子。"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--api-base", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--max-latency", type=int, default=60, help="超过此秒数判为 slow")
    ap.add_argument("--out", default=str(Path(__file__).parent / "reliable.json"))
    args = ap.parse_args()

    key = load_api_key(args.api_key)
    if not key:
        print("✗ 无 api key", file=sys.stderr)
        return 1
    base = args.api_base or API_BASE

    reliable, slow, failed = [], [], []
    print(f"═ 可靠性预检 ({len(args.models)} 模型) ═")
    for m in args.models:
        r = call_model(m, PROBE_PROMPT, key, base_url=base, max_tokens=64, timeout=args.timeout)
        sec = r["ms"] / 1000
        if r["error"]:
            failed.append(m)
            print(f"  ✗ {m:<26} 失败: {r['error'][:50]}")
        elif sec > args.max_latency:
            slow.append(m)
            print(f"  ⚠ {m:<26} 慢: {sec:.1f}s")
        else:
            reliable.append(m)
            print(f"  ✓ {m:<26} {sec:.1f}s")

    out = {"reliable": reliable, "slow": slow, "failed": failed,
           "probe": PROBE_PROMPT, "max_latency": args.max_latency}
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(f"\n  可靠: {len(reliable)}  慢: {len(slow)}  失败: {len(failed)}")
    print(f"  结果: {args.out}")
    print(f"\n  建议: 只用 reliable 跑全量评估 (slow/failed 先修复再评)")
    print(f"  reliable 模型: {' '.join(reliable)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
