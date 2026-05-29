# 真实案例：国内主流 AI 写作助手竞品分析

> **Run ID**：T-ddea58d0e40c4d7080252fded3ab6f7d  
> **完成时间**：2026-05-25 04:40:45  
> **版本**：cs-mvp v1.2.1

---

## 任务输入

| 字段 | 值 |
| --- | --- |
| 分析问题 | 国内主流 AI 写作助手竞品分析：功能差异、定价策略、目标用户对比 |
| 竞品范围 | 秘塔写作猫 / 讯飞星火 / 豆包 |
| 分析维度 | features / pricing / target_users / positioning / swot / strategic_implications |

---

## 执行结果一览

| 指标 | 数值 |
| --- | --- |
| 总耗时 | **320 秒** |
| 总成本 | **$0.059**（预算 $0.50，使用率 11.9%） |
| 采集来源数 | 18 条（有效 8 条，成功率 44%） |
| 提取 Evidence | 25 条有效证据 |
| 生成 Claim | 31 条（QA 审查通过 31/31） |
| 报告最终 Claim | 27 条（23 单竞品 + 4 跨竞品对比） |
| QA 通过率 | **100%**（0 条 needs_revision，0 条 risky） |
| Analyst Revise | 触发（Claim support_score 提升后重新审查） |
| Claim 平均支持分 | 0.732 |

---

## Pipeline 执行追踪

```
task_init → Collector → Extractor → Analyst → QA Critic
                                                  ↓
                                          Analyst Revise（1轮反馈）
                                                  ↓
                                              Writer → Finalize
```

| 节点 | 耗时 | LLM 成本 |
| --- | --- | --- |
| Collector | 含在总耗时 | $0.000（仅 Tavily API） |
| Extractor | — | $0.020 |
| Analyst | — | $0.004 |
| QA Critic | — | $0.033 |
| Analyst Revise | — | $0.002 |
| Writer | — | $0.001 |

---

## 采集层表现

- **Playwright 回退触发**：讯飞星火官网 httpx 返回 empty（155字），Playwright 渲染后获取 3620 字
- **搜索词扩展效果**：每个竞品生成 4-5 条查询（含"定价 收费 功能"、"官网 产品介绍"、英文 pricing features review）
- **难点**：秘塔写作猫有较强反爬，最终有效来源仅 2 条（vs 讯飞星火 2 条、豆包 4 条）

---

## 关键发现（摘要）

### 定价策略对比

| 竞品 | 模式 | 价格点 |
| --- | --- | --- |
| 秘塔写作猫 | 免费 + 付费订阅 | 免费版 8000字/天纠错；付费 24元/月起 |
| 豆包 | 按量计费（API） | Lite-32k 输入 0.3元/百万token；pro-32k 低至 0.001元/千token |
| 讯飞星火 | 用户基数（未披露定价） | Android 端累计 1.31 亿次下载 |

### 功能差异

| 竞品 | 核心定位 | 技术亮点 |
| --- | --- | --- |
| 秘塔写作猫 | 轻量 web-based 写作平台 | 零安装，浏览器插件 |
| 讯飞星火 | 通用 AI 助手 + 垂直扩展 | V4.0 超越 GPT-4 Turbo（文本/推理）；内容溯源降低幻觉 |
| 豆包 | 高并发企业 API | Sparse MoE、256K token 上下文、10K RPM |

### 目标用户分化

- **秘塔写作猫**：16 亿汉语使用者中的学生、职场人士、内容创作者（低门槛日常写作）
- **讯飞星火**：对可信度和逻辑推理要求高的专业用户（内容溯源是差异化点）
- **豆包**：需要大规模复杂文档分析的企业客户（高 TPM 限额、低价 API）

---

## 跨竞品对比矩阵（4条）

1. **[features]** 秘塔写作猫 browser-based + 插件 vs 豆包 Sparse MoE + 多模态，技术路线差异显著
2. **[features]** 豆包 256K token 上下文 + 10K RPM vs 讯飞星火 V4.0 超 GPT-4 Turbo 但多模态仍有差距
3. **[pricing]** 豆包按量计费 0.3元/百万token vs 秘塔写作猫订阅制 24元/月
4. **[swot]** 三者优势分别来自易用性（秘塔）、用户规模（讯飞，1.31亿下载）、推理性能（豆包，BBH 91.6）

---

## 工程观测指标

- **LLM 模型**：DeepSeek Chat（全节点）
- **Token 消耗**：70,891 tokens
- **预算使用率**：11.9%（$0.059 / $0.50）
- **QA 反馈循环**：Analyst Revise 节点触发，revision_history.json 记录修订前后对比
- **报告风格审查**：report_style_audit.json 自动检查章节覆盖率、引用密度、证据溯源

---

## 如何复现

```bash
python -m cs_mvp.cli run \
  --query "国内主流 AI 写作助手竞品分析：功能差异、定价策略、目标用户对比" \
  --competitors "秘塔写作猫,讯飞星火,豆包"
```

运行后访问 Dashboard 查看：
- **Report Tab**：完整 HTML 报告含 ECharts 图表
- **QA 审查 Tab**：31 条 Claim 的 QA 结论（全部 accepted）
- **证据库 Tab**：25 条 Evidence，含原文引用和来源 URL
- **执行追踪 Tab**：每节点耗时、Token、成本

---

## 本案例用于展示

1. **8 节点 DAG 完整跑通**：从 task_init 到 Finalize，所有节点正常执行
2. **QA 反馈闭环**：Analyst Revise 节点触发并完成修订
3. **证据链可溯源**：每条 Claim 携带 evidence_id，可追溯到具体来源 URL 和原文片段
4. **Playwright 采集增强**：讯飞星火 empty→fetched 的实证（v1.2.1 新增功能）
5. **成本可控**：真实任务总成本 $0.059，远低于 $0.25 目标
