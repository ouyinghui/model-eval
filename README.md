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

# 2. 看计划
python3 run_eval.py --models model-a model-b --judge your-strong-model --dry-run

# 3. 小样本验证 (每类 1 题)
python3 run_eval.py --models model-a --judge your-strong-model --limit 1

# 4. 全量
python3 run_eval.py --models model-a model-b model-c --judge your-strong-model
```

也可用 `config.json`（复制 `config.example.json`）配合 `EVAL_CRED_FILE` 从文件读 key。

## 文件

| 文件 | 说明 |
|------|------|
| `run_eval.py` | 主脚本（无第三方依赖，urllib + OpenAI 兼容 API） |
| `testset.json` | 业务测试集示例（5 类业务，带 rubric 评分要点 + 参考答案） |
| `config.example.json` | 配置模板 |
| `examples/sample_result.json` | 示例输出（模型名已匿名化） |

## 测试集设计

每类业务 1-3 题，每题带：
- `prompt`：题目
- `rubric`：评分要点（含**扣分红线**，让裁判严格）
- `expect`：参考答案（客观题用，供裁判核对）

类别示例：`coding` / `math` / `long_text` / `creative` / `general`

## 裁判设计

- 裁判需是**强模型**（比被测模型强）
- System prompt 强调**严格、拉开差距**，避免都给 9-10
- 客观题有参考答案 → 答案错最高 4 分
- 命中"扣分红线" → 限制上限

## 注意事项

- **自我偏好偏差**：裁判与被测模型同源时，可能偏爱自家模型
- **样本量**：每类 1-2 题偏少，评分有噪声；建议每类 3-5 题
- **超时模型**：慢模型会超时 → 脚本已做"失败排除均分"（超时不记 0 分）
- **成本控制**：模型数 × 题数 × 2（生成 + 裁判）次调用

## 输出

```json
{
  "judge": "judge-model",
  "btypes": ["coding", "math", "..."],
  "table": {
    "model-a": {"coding": 9.3, "math": 10.0, "...": "..."}
  },
  "detail": [{"btype": "...", "model": "...", "score": 9.0, "judge_reason": "..."}]
}
```

## 已知限制

- 单轮评估，未测多轮 / 长上下文 / 工具调用
- 只看质量分，未测延迟 / 稳定性 / 成本
- 评分依赖裁判质量，裁判偏见会传导

## License

MIT
