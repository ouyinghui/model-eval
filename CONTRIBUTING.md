# 协作约定

## 角色
- 开发主责: 狂野小子 (ouyinghui 主力开发)
- 安全/纠偏: 锚 (oh CLI 侧, 核心系统维稳, 见 memory/operation_guides/)

## 提交规范
- commit: `<type>: <说明>`, type ∈ feat/fix/docs/refactor/test
- 分支: 直接 main (单项目, 简单优先)
- 双远端: github + gitee 同 commit (国内网络稳定性)

## 文件约定
- `run_eval.py` — 主脚本 (无第三方依赖)
- `check_reliability.py` — 可靠性预检
- `testset.json` — 业务测试集 (含 rubric + 参考答案)
- `TUNING.md` — 调参经验
- `examples/` — 示例输出 (模型名匿名化)

## 脱敏红线 (硬约束)
- **不得**提交: API key / 端点 / 私有路径 / 凭据文件
- 端点/密钥走环境变量 (EVAL_API_BASE / EVAL_API_KEY / EVAL_CRED_FILE)
- 示例输出的模型名**匿名化**
- 提交前 grep 自查: `grep -rn "gcable\|GLM\|playground\|/opt/data\|sk-\|Bearer" .`

## 测试
- 小样本: `python3 run_eval.py --models <m> --judge <j> --limit 1`
- 全量: `python3 run_eval.py --models <all> --judge <j> --workers 3`
- 预检: `python3 check_reliability.py --models <all> --max-latency 60`
