#!/usr/bin/env python3
"""LLM-as-a-Judge 模型评估 — 对一组模型跑业务测试集, 裁判打分, 生成评分表。

方法: 业界标准 LLM-as-a-Judge (同 MT-Bench / AlpacaEval 思路)。
  - 各模型跑测试集 → 收集回答
  - 强模型当裁判, 按 rubric 打分 1-10
  - 按任务类别聚合 → 评分表

配置 (环境变量, 或用 config.json):
  EVAL_API_BASE   兼容 OpenAI 的 API 端点 (默认 https://api.openai.com/v1)
  EVAL_API_KEY    API key (或用 EVAL_CRED_FILE + EVAL_CRED_PROFILE)
  EVAL_CRED_FILE  可选: 从 JSON 文件读 key (格式 {"profile:<name>": {"api_key": "..."}})
  EVAL_CRED_PROFILE 可选: 从文件读取的 profile 名

无第三方依赖 (urllib)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).parent

# ---- 配置 (env 优先) ----
API_BASE = os.environ.get("EVAL_API_BASE", "https://api.openai.com/v1")
API_KEY_ENV = os.environ.get("EVAL_API_KEY", "")
CRED_FILE = os.environ.get("EVAL_CRED_FILE", "")
CRED_PROFILE = os.environ.get("EVAL_CRED_PROFILE", "default")

DEFAULT_JUDGE = os.environ.get("EVAL_JUDGE", "")


def load_api_key(cli_key: str = "") -> str:
    if cli_key:
        return cli_key
    if API_KEY_ENV:
        return API_KEY_ENV
    if CRED_FILE and Path(CRED_FILE).exists():
        c = json.load(open(CRED_FILE))
        v = c.get(f"profile:{CRED_PROFILE}") or c.get(CRED_PROFILE)
        if isinstance(v, dict):
            return v.get("api_key", "")
        return v or ""
    return ""


def call_model(model: str, prompt: str, api_key: str, *, base_url: str = "",
               system: str = "", max_tokens: int = 2048, timeout: int = 180,
               retries: int = 3) -> dict:
    """调一次 chat completion, 返回 {text, error, ms}。429/5xx 自动退避重试。"""
    import time
    base = (base_url or API_BASE).rstrip("/")
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens}
    t0 = time.time()
    last_err = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            msg = data["choices"][0]["message"]
            text = msg.get("content") or ""
            # 思考模型: reasoning 占满 token 时 content 可能为空, 回退 reasoning_content
            if not text.strip() and msg.get("reasoning_content"):
                text = msg["reasoning_content"]
            return {"text": text, "error": None, "ms": int((time.time() - t0) * 1000)}
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read()[:150].decode(errors='ignore')}"
            # 429(限流) / 5xx(服务端): 退避重试
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt * 2)  # 2,4,8s
                continue
            break
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            break
    return {"text": "", "error": last_err, "ms": int((time.time() - t0) * 1000)}


JUDGE_SYSTEM = """你是严格的 AI 模型质量评估裁判。给你一个任务、评分要点(rubric)、可选的参考答案(expect)、以及模型的回答。

## 打分规则 (1-10)
- 严格、客观。不要因为回答"看起来完整"就给高分。
- 客观题(有参考答案): 答案错误 → 最高 4 分; 部分正确 → 5-7; 完全正确 → 8-10。
- 主观题(写作/创意): 按 rubric 逐条对照, 平庸/套路化 → 5-6; 有亮点 → 7-9。
- rubric 里的"扣分红线"命中 → 按红线限制上限。
- 空回答/答非所问 → 0-1 分。
- 分数要拉开差距, 不要都给 9-10。

只输出 JSON，格式:
{"score": <1-10 的数字>, "reason": "<40字内理由, 指出扣分点>"}
不要输出其它任何内容。"""


def judge_one(task_prompt: str, rubric: str, answer: str, judge: str, api_key: str,
              expect: str = "", base_url: str = "") -> dict:
    """裁判给一个回答打分"""
    if not answer.strip():
        return {"score": 0.0, "reason": "空回答/调用失败"}
    expect_block = f"\n## 参考答案(客观题)\n{expect}\n" if expect else ""
    user = f"""## 任务
{task_prompt}

## 评分要点
{rubric}
{expect_block}
## 模型回答
{answer}

请严格打分。"""
    r = call_model(judge, user, api_key, base_url=base_url, system=JUDGE_SYSTEM, max_tokens=800)
    if r["error"]:
        return {"score": 0.0, "reason": f"裁判出错: {r['error'][:60]}"}
    txt = r["text"].strip()
    try:
        if "```" in txt:
            txt = txt.split("```")[1].replace("json", "", 1).strip()
        start, end = txt.find("{"), txt.rfind("}")
        obj = json.loads(txt[start:end+1])
        return {"score": float(obj.get("score", 0)), "reason": str(obj.get("reason", ""))[:60]}
    except Exception:
        import re
        m = re.search(r"\d+(?:\.\d+)?", txt)
        return {"score": float(m.group()) if m else 0.0, "reason": f"(解析异常) {txt[:40]}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM-as-a-Judge 模型评估")
    ap.add_argument("--models", nargs="*", required=True, help="要评估的模型列表")
    ap.add_argument("--judge", default=DEFAULT_JUDGE, help="裁判模型 (需强模型)")
    ap.add_argument("--testset", default=str(HERE / "testset.json"))
    ap.add_argument("--api-base", default="", help=f"API 端点 (默认 {API_BASE})")
    ap.add_argument("--api-key", default="", help="API key (或用 env EVAL_API_KEY)")
    ap.add_argument("--limit", type=int, help="每类别最多跑几题")
    ap.add_argument("--workers", type=int, default=3, help="并发数 (太高会触发 429 限流, 建议 2-3)")
    ap.add_argument("--timeout", type=int, default=180, help="单次调用超时秒")
    ap.add_argument("--out", default=str(HERE / "eval_result.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true", help="把评分表写进 router_config.json (需 --config)")
    ap.add_argument("--config", default="", help="router_config.json 路径 (--apply 用)")
    ap.add_argument("--version", default="", help="评估批次号 (如 v4, 写入 capabilities_meta)")
    args = ap.parse_args()

    if not args.judge:
        print("✗ 需指定 --judge (强模型, 或用 env EVAL_JUDGE)", file=sys.stderr)
        return 1

    testset = json.load(open(args.testset))
    btypes = [k for k in testset if not k.startswith("_")]
    models = args.models

    tasks = []
    for bt in btypes:
        items = testset[bt]
        if args.limit:
            items = items[:args.limit]
        for it in items:
            for m in models:
                tasks.append({"btype": bt, "id": it["id"], "prompt": it["prompt"],
                              "rubric": it["rubric"], "expect": it.get("expect", ""), "model": m})

    print(f"═ LLM-as-a-Judge 评估 ═")
    print(f"  模型: {len(models)} 个")
    print(f"  类别: {btypes}")
    print(f"  裁判: {args.judge}")
    print(f"  任务: {len(tasks)} 生成 + 同数裁判")
    if args.dry_run:
        print("  [dry-run]")
        return 0

    api_key = load_api_key(args.api_key)
    if not api_key:
        print("✗ 无 api key (设 EVAL_API_KEY 或 EVAL_CRED_FILE, 或 --api-key)", file=sys.stderr)
        return 1

    base = args.api_base or API_BASE

    print(f"\n阶段1: 生成回答 ({args.workers} 并发)...")
    results, done = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(call_model, t["model"], t["prompt"], api_key,
                          base_url=base, max_tokens=2048, timeout=args.timeout): t for t in tasks}
        for f in as_completed(futs):
            t = futs[f]; r = f.result()
            err = r["error"]
            if not err and not (r["text"] or "").strip():
                err = "empty response (无内容)"
            t.update({"answer": r["text"], "gen_error": err, "gen_ms": r["ms"]})
            results.append(t); done += 1
            if done % 10 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)}")

    print(f"\n阶段2: 裁判打分...")
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_one, t["prompt"], t["rubric"], t["answer"], args.judge,
                          api_key, t.get("expect", ""), base): t for t in results}
        for f in as_completed(futs):
            t = futs[f]; j = f.result()
            t.update({"score": j["score"], "judge_reason": j["reason"]})
            done += 1
            if done % 10 == 0 or done == len(results):
                print(f"  {done}/{len(results)}")

    # 聚合 (失败排除)
    table = {}
    for m in models:
        table[m] = {}
        for bt in btypes:
            sc = [r["score"] for r in results if r["model"] == m and r["btype"] == bt and not r["gen_error"]]
            table[m][bt] = round(sum(sc)/len(sc), 1) if sc else None

    out = {"judge": args.judge, "btypes": btypes, "table": table,
           "detail": [{k: r[k] for k in ("btype","id","model","score","judge_reason","gen_error")} for r in results]}
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)

    print(f"\n═ 评分表 (1-10) ═")
    print(f"{'model':<24}" + "".join(f"{bt:>11}" for bt in btypes))
    for m in models:
        print(f"{m:<24}" + "".join(f"{(table[m][bt] if table[m][bt] is not None else 0):>11.1f}" for bt in btypes))
    print(f"\n  结果: {args.out}")
    # 可靠性
    fails = {m: sum(1 for r in results if r["model"]==m and r["gen_error"]) for m in models}
    if any(fails.values()):
        print("  超时/失败:", {m: n for m, n in fails.items() if n})

    # --apply: 写进 router_config + capabilities_meta
    if args.apply:
        if not args.config:
            print("✗ --apply 需 --config <router_config.json>", file=sys.stderr)
            return 1
        import copy
        cfg = json.load(open(args.config))
        if "models" not in cfg:
            print("✗ config 无 models 字段", file=sys.stderr)
            return 1
        applied, skipped = [], []
        for m, row in table.items():
            if m not in cfg["models"]:
                skipped.append(f"{m}(不在config)"); continue
            if any(v is None for v in row.values()):
                skipped.append(f"{m}(有空格/不可靠)"); continue
            cfg["models"][m]["capabilities"] = {bt: v for bt, v in row.items()}
            applied.append(m)
        # capabilities_meta 元信息
        version = args.version or f"v{datetime.now().strftime('%y%m%d')}"
        cfg["capabilities_meta"] = {
            "source": "model-eval",
            "version": version,
            "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "judge": args.judge,
            "testset": f"{len(btypes)}类/{sum(1 for _ in [t for bt in btypes for t in testset[bt]])}题",
            "models_count": len(applied),
            "excluded": skipped,
        }
        json.dump(cfg, open(args.config, "w"), ensure_ascii=False, indent=2)
        print(f"\n  ✓ --apply: 写入 {args.config}")
        print(f"    applied {len(applied)} 模型, meta.version={version}")
        if skipped:
            print(f"    skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
