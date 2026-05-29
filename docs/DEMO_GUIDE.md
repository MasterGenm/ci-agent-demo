# cs-mvp v1.4 评委演示流程

本文档用于 v1.4 评委演示。目标是在 5 分钟内说明：cs-mvp 如何把“AI 驱动的竞品分析 Agent 协作系统”从课题描述落到可运行系统, 并展示企业化收口后的报告深度、Schema 可见化与真闭环。

演示原则：

1. 只演示一主一备。
2. 主 demo 展示 v1.4 继承的 QA Critic 真闭环与新增 Schema tab。
3. 备 demo 只用于兼容性或兜底。
4. 不讲内部实现细节，除非评委追问。
5. 不把 Dashboard 讲成完整产品后台。

## 0. 启动

推荐命令：

```bash
python -m cs_mvp.cli serve --host 127.0.0.1 --port 8765
```

Windows 可用：

```powershell
.\demo\run_demo.ps1
```

Linux/macOS 可用：

```bash
./demo/run_demo.sh
```

主 demo（v1.5 真闭环 + Langfuse trace）：

```text
http://127.0.0.1:8765/runs/T-fa39da6559f14a04ac32fab60842a7ec
```

备 demo（v1.4 真闭环本地路径对照）：

```text
http://127.0.0.1:8765/runs/T-1cbcb6f3f1b447ab9094fef79f9ea65d
```

v1.2 smoke 对照（半闭环）：

```text
http://127.0.0.1:8765/runs/T-v12-b2-smoke-rescue-on
```

legacy 对照（v1.1 baseline）：

```text
http://127.0.0.1:8765/runs/T-50d7bb2f823e444994deac9cc85f0e8e
```

## 1. 5 分钟主线路径

### Step 1: 打开主 demo 的 DAG tab（约 90 秒）

页面：

```text
http://127.0.0.1:8765/runs/T-fa39da6559f14a04ac32fab60842a7ec
```

讲法：

```text
这不是单轮 prompt 生成报告，而是一个多 Agent DAG。
采集、抽取、分析、质检、撰写、汇总各自独立产物。
```

指向点：

1. `collector`
2. `extractor`
3. `analyst`
4. `qa_critic`
5. `writer`
6. `finalize`

对应课题关键词：

1. 多个专职 Agent 协作
2. DAG 式任务流转
3. 系统可观测性

如果评委问“为什么只回流一轮”：

```text
v1.3 已经实现真回流,但用 max_revision_rounds=1 约束爆炸风险。
它证明系统具备交叉审查反馈闭环,同时避免多轮 Agent 协商在评委演示期失控。
```

### Step 2: 打开 QA Critic tab（约 120 秒）

讲法：

```text
QA Critic 是独立质检 Agent。
它读取 analyst 产出的 claims 和 evidence，先产出可审计的 qa_audit；v1.3 中 needs_revision 可触发一次 Analyst Revise。
```

主 demo 数据：

```text
total_claims_audited: 12
accepted_count: 10
needs_revision_count: 2
risky_count: 0
```

演示动作：

1. 指出 accepted、needs_revision、risky 三态。
2. 展开一条 needs_revision。
3. 说明 `issue_tags` 表示问题类型。
4. 说明 `reason` 表示判定依据。
5. 说明结果也会进入 `review_queue.json`，供人工复核。

对应课题关键词：

1. 交叉审查反馈闭环
2. 结果溯源
3. 系统可观测性

### Step 2.5: 打开 Revision tab（约 45 秒）

讲法：

```text
Revision tab 展示一次真实回流的审计记录：原 claim、QA 前标签、修订后 claim、QA 后标签和成本。这里不做复杂 diff viewer，只把闭环证据讲清楚。
```

演示动作：

1. 指出 `qa_critic -> analyst_revise -> qa_critic`。
2. 指出 original_statement 与 revised_statement。
3. 指出 qa_label_before / qa_label_after。
4. 强调 revised_evidence_ids 没有新增 evidence。

### Step 3: 打开 Report tab（约 90 秒）

讲法：

```text
Writer Agent 将结构化 claim 与 evidence 汇总成竞品分析报告。
报告不是孤立文本，背后有 evidence、claim、source、trace artifacts。
```

演示动作：

1. 看报告的竞品分节。
2. 指出 AI 功能、定价、定位、风险等结构。
3. 指出 evidence id 或 source link。
4. 回到 Evidence tab 展示对应证据。

对应课题关键词：

1. 自定义竞品知识 Schema
2. 公开信息采集
3. 结果溯源

### Step 4: 打开 Schema tab（约 45 秒）

讲法：
```text
v1.4 把 Schema 从文档变成 Dashboard 里可见的数据契约。评委可以直接看到 SourceRecord、EvidenceItem、AnalysisClaim、QAFeedback、RevisionRecord 这 5 类核心模型, 以及 schema_version。
```

演示动作：
1. 指出 `schema_version: 1.2.0`。
2. 指出 `AnalysisClaim.dimension` 已包含 `target_users` 与 `strategic_implications`。
3. 指出未来行业 preset 只是示例, 当前不做 YAML 或 Schema 编辑。

对应课题关键词：

1. 自定义竞品知识 Schema
2. 系统可观测性
3. 每个 Agent 的中间产物透明

### Step 5: 打开 Evidence tab（约 45 秒）

讲法：

```text
每条结论都有 evidence 支撑。
Evidence 中保留 quote、source URL、competitor、dimension 等字段。
```

演示动作：

1. 选择一条 evidence。
2. 指出 quote。
3. 指出 source URL。
4. 指出 competitor 与 dimension。

对应课题关键词：

1. 公开信息采集
2. 结果溯源

### Step 6: 打开 Trace tab（约 45 秒）

讲法：

```text
系统可观测性不是只看最终报告。
每个节点的状态、耗时、成本、token 和中间产物都能查。
```

演示动作：

1. 指出每个 node 的 status。
2. 指出 duration/cost/token 字段。
3. 指出失败或 warning 会进入 artifact，而不是被吞掉。

对应课题关键词：

1. 系统可观测性
2. Agent 决策过程透明

## 2. 10 分钟扩展路径

如果评委愿意继续看，可以追加两段。

### 扩展 A: review_queue

打开 artifact：

```text
http://127.0.0.1:8765/runs/T-fa39da6559f14a04ac32fab60842a7ec/artifact/review_queue
```

讲法：

```text
review_queue 把 QA Critic、召回问题、insight candidate 等人工复核项聚合起来。
它是 Human Review 的轻量前置；v1.3 仍不做完整人审状态机。
```

### 扩展 B: legacy 备 demo

打开：

```text
http://127.0.0.1:8765/runs/T-50d7bb2f823e444994deac9cc85f0e8e
```

讲法：

```text
这是早期真实 case 4 run。
它没有 QA Critic，但 Dashboard 可以兼容读取旧 artifact。
这说明 Web 层是叠加层，没有破坏 CLI 历史产物。
```

## 3. 课题 7 关键词对齐表

| 课题关键词 | 演示动作 | 系统证据 |
| --- | --- | --- |
| 多个专职 Agent 协作 | DAG tab 展示 Collector/Extractor/Analyst/QA Critic/Writer | LangGraph 节点与 node_summary |
| DAG 式任务流转 | 展示前向 7 节点流程 | `trace.json`、`dag.json` |
| 交叉审查反馈闭环 | DAG tab 展示回流边,Revision tab 展示修订记录 | `qa_audit.json`、`revision_history.json`、`review_queue.json` |
| 自定义竞品知识 Schema | 打开 Schema tab, 说明 claims/evidence/source/qa_audit/revision 类型契约 | Dashboard Schema tab 与 `docs/SCHEMA.md` |
| 公开信息采集 | Evidence tab 展示 source URL 与 quote | `sources.json`、`evidence.json` |
| 结果溯源 | 从 report 跳到 evidence，或从 evidence 回看 claim | evidence_id/source_url |
| 系统可观测性 | Trace tab 展示 status/cost/token/latency | `trace.json`、`run_summary.json` |

## 4. 评委常见问题

### Q1: 这是不是只是一个大 prompt？

不是。系统按 DAG 拆成多个节点，每个节点都有独立输入、输出、artifact 和 trace。最终报告只是最后一个可读产物。

### Q2: QA Critic 会自动改报告吗？

v1.3 会在 `ENABLE_REVISION_LOOP=1` 且 QA 给出 `needs_revision` 时触发一次受控 Analyst Revise。它不会多轮协商，也不会为 `risky` 自动改写。

### Q3: 为什么不做完整 Web 产品？

v1.4 的目标是课题验收演示和企业化收口，不是多用户 SaaS。Dashboard 只服务可观测性、Schema 可见化和演示，不做权限、任务队列、PDF、对比报告等产品功能。

### Q4: 每条结论怎么溯源？

claim 绑定 evidence_id，evidence 绑定 source URL 与 quote。Report、Evidence、Trace 三个 tab 可以交叉验证。

### Q5: 公开信息采集靠什么？

Tavily 搜索、seed URL、httpx 抓取、BeautifulSoup 解析。采集结果写入 `sources.json`，证据片段写入 `evidence.json`。

### Q6: 如果采集结果很差怎么办？

系统不会假装完整。低召回、弱证据、QA 质疑会进入 warning 或 review_queue。

### Q7: v1.4 最重要的新增是什么？

两个新增最关键：报告新增 `target_users` / `strategic_implications` 两个轻量商业维度, 以及 Web Dashboard 的 Schema tab 可视化。QA Critic 真回流来自 v1.3, v1.4 保持不破坏。

### Q8: 备 demo 为什么没有 QA Critic？

备 demo 是 legacy case 4 run，用于证明 Dashboard 能兼容旧产物。主 demo 才是当前完整路径。

### Q9: 现在还缺什么？

核心课题阶段已经收口。后续优先做答辩材料冻结、录屏脚本、固定 demo 数据和稳定性验收，而不是继续扩大结构。

## 5. 演示禁区

不要承诺以下能力：

1. 自动发现全部竞品。
2. 多用户权限与企业账号体系。
3. QA Critic 自动重写报告。
4. Langfuse 深度集成。
5. PDF/PPTX 一键导出。
6. 4 case 全量演示包。
7. 长期监控竞品变化。

准确表述：

```text
v1.4 已经完成课题对齐演示所需的 Agent 协作、DAG、质检真闭环、Schema 可见化、公开采集、溯源、可观测性与轻量商业分析加厚。
平台化能力放在后续版本。
```

## 6. 收口检查

演示前检查：

1. `python -m cs_mvp.cli serve --host 127.0.0.1 --port 8765` 能启动。
2. 主 demo 页面返回 200。
3. 主 demo QA Critic tab 有数据。
4. 主 demo Report tab 有报告内容。
5. 主 demo Evidence tab 有 source URL。
6. 主 demo Trace tab 有节点信息。
7. 备 demo 页面返回 200。
8. 备 demo Report tab 能展示 legacy 报告。

如果主 demo 不可用：

1. 切换备 demo。
2. 明确说明它是 legacy 对照。
3. 不演示 QA Critic tab 的完整能力。
4. 后续用 `demo/main_case.json` 重新跑主 demo。
