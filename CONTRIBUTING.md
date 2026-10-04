# 贡献指南

> 这个项目的核心主张是：**判定类 AI 的输出必须能被独立验证。**
> 任何贡献都应该让这个主张更站得住，而不是更松。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

python -m pytest -q                 # 265 个测试，不需要 API key，不花钱
python -m engine check --all        # 10 个判定域自检
python -m audit eval --count 100    # 确定性检查器评测
python -m rag eval                  # 检索基线
python -m agent mutate              # 变异测试：验证测试有没有用
```

以上全部**不需要 API key**，因为它们是确定性路径。
只有 `python -m agent eval-semantic` 和 `python -m agent audit`（不加 `--dry-run`）会用模型。

## 提交前请确认

1. `python -m pytest -q` 全绿
2. `python -m agent mutate` 的**变异得分为 100%**（允许存活的旋钮除外）
3. 如果新增了"必须被守住的不变量"，请同时：
   - 在 `agent/mutants.py` 里加一个对应的变异体
   - 在 `tests/` 里加一个能杀死它的测试

第 3 条是这个项目的要求里最特别的一条：

> **不能被杀死的断言，等于没有断言。**
> 光加测试不够，还要证明这个测试在代码被改坏时真的会报警。

## 不要做的事

- **不要把真实数据放进仓库**。体检报告、真实个人信息、企业内网数据一律不许进。
  示例数据必须是程序合成的（见 `audit/synth.py`）。
- **不要让模型参与数值判定**。金额、分级、资格判定一律由 `engine/` 的确定性规则完成。
  模型只负责"听懂人话"和"说人话"。
- **不要把可检测性契约写虚**。往 `agent/mutants.py` 加变异体时，
  `invariant` 字段必须写清"它守住的是什么"，写不出来说明这个变异体没有意义。
- **不要悄悄放宽评测口径**。`audit/evaluate.py` 的匹配规则要求
  "检查器 + 指标"同时一致；放宽它会让乱报的检查器也能刷出高召回率。
  （这个坑变异测试抓到过，见 `tests/test_invariants.py`。）

## 代码风格

- 注释写"**为什么**"，不写"是什么"。代码本身已经说明了"是什么"。
- 踩过的坑要在代码注释里留痕，并指向对应的测试——这是这个项目最有价值的部分之一。
- 中文注释是刻意的：目标读者是中文使用者，术语一致性比迎合工具链更重要。

## 报告问题

请附上：复现命令、实际输出、期望输出。
如果和指标有关，请贴 `reports/` 下对应报告的片段——**没有数字的问题描述很难被处理**。
