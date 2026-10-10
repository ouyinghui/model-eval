# model-eval

LLM-as-a-Judge 模型评估工具 —— 对一组模型跑业务测试集，用强模型当裁判打分，生成评分表。

用于**模型选型**：给路由/调度系统提供真实的模型能力评分数据（替代手工拍脑袋的评分表）。

## 方法

业界标准 **LLM-as-a-Judge**（同 MT-Bench / AlpacaEval 思路）：
1. 各模型跑同一套业务测试集 → 收集回答
2. 强模型（裁判）按每题 rubric 打分 1-10
3. 按任务类别聚合 → 评分表

## 快速开始

```bash
# 1. 配 API (环境变量, 不落盘)
export EVAL_API_BASE="https://your-endpoint/v1"
export EVAL_API_KEY="your-key"

# 2. 可靠模型预检 (分钟级, 过滤超时/失败模型, 省时间)
python3 check_reliability.py --models model-a model-b model-c --max-latency 60
# → reliable.json

# 3. 只对可靠模型跑评估 (低并发 + 429 退避)
python3 run_eval.py --models model-a model-b --judge your-strong-model --workers 3

# 4. 小样本验证 (每类 1 题)
python3 run_eval.py --models model-a --judge your-strong-model --limit 1
```

也可用 `config.json`（复制 `config.example.json`）配合 `EVAL_CRED_FILE` 从文件读 key。

## 文件

| 文件 | 说明 |
|------|------|
| `run_eval.py` | 主脚本（无第三方依赖；含 429/5xx 退避重试；失败排除均分） |
| `check_reliability.py` | 可靠性预检（探活/测速，过滤不可靠模型，省重测时间） |
| `testset.json` | 业务测试集示例（5 类业务，含易题 + 难题；带 rubric + 参考答案） |
| `TUNING.md` | 调参经验（踩坑记录，强烈建议读） |
| `config.example.json` | 配置模板 |
| `examples/sample_result.json` | 示例输出（模型名已匿名化） |

## 测试集设计

每类业务 2-4 题，每题带：
- `prompt`：题目
- `rubric`：评分要点（含**扣分红线**，让裁判严格）
- `expect`：参考答案（客观题用，供裁判核对）

类别：`coding` / `math` / `long_text` / `creative` / `general`

**关键**：必须含**难题**（复杂推理/边界/专业）。易题模型都满分，无区分度。

## 裁判设计

- 裁判需是**强模型**（比被测模型强）
- System prompt 强调**严格、拉开差距**
- 客观题有参考答案 → 答案错最高 4 分
- 命中"扣分红线" → 限制上限

## ⚠️ 重要注意事项（详见 TUNING.md）

- **并发别太高**：`--workers 3` 以内，否则触发 **429 限流**（大批假失败）
- **失败排除均分**：超时不记 0 分（避免污染）
- **题目难度是主杠杆**：易题无区分，难题才拉开
- **自我偏好偏差**：裁判与被测同源时可能偏爱自家模型
- **思考模型**：answer 可能在 `reasoning_content`（脚本已兼容）
- **可靠模型先筛选**：`check_reliability.py` 预检，只评估可靠模型

## 输出

```json
{
  "judge": "judge-model",
  "btypes": ["coding", "math", "..."],
  "table": { "model-a": {"coding": 9.3, "math": 10.0, "...": "..."} },
  "detail": [{"btype": "...", "model": "...", "score": 9.0, "judge_reason": "..."}]
}
```

## 已知限制

- 单轮评估，未测多轮 / 长上下文 / 工具调用
- 只看质量分，未测延迟 / 稳定性 / 成本
- 评分依赖裁判质量，裁判偏见会传导
- 每类题量偏小时评分有噪声（建议每类 ≥3 题）

## License

MIT
