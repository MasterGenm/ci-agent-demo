# cs-mvp 全操作流程手册

**写给**:项目所有者 / 演示者 / 求职申请人
**写于**:2026-05-22(v1.6.0 之后)
**目的**:无歧义、不跳步的操作步骤,任何时候照着做都能跑通

---

## 🎯 你能用这份文档做的 7 件事

1. [演示前 5 分钟准备 Dashboard](#场景-1演示前-5-分钟启动-dashboard)
2. [跑一次新的真实竞品分析 case](#场景-2跑一次新的真实竞品分析-case)
3. [验证 Langfuse Cloud trace 是否上传成功](#场景-3验证-langfuse-cloud-trace)
4. [截 7 张演示 / README 截图](#场景-4截-7-张演示截图)
5. [跑全量测试 + e2e + coverage](#场景-5跑全量测试--e2e--coverage)
6. [Docker 启动(给评委 / 雇主一键演示)](#场景-6docker-启动)
7. [git 状态检查 + 紧急回滚](#场景-7git-状态检查--紧急回滚)

---

## 🛠️ 前置:一次性环境准备

**这一节只需要做一次**。如果你已经做过(`.env` 文件存在 + Python 装好),直接跳到下面的"场景"。

### Step 0.1:确认 Python 3.11+

打开 PowerShell,输入:

```powershell
python --version
```

**应该看到**:`Python 3.11.x` 或 `Python 3.12.x`。

**如果**:
- ❌ 看到 `Python 3.10.x` 或更低:去 https://python.org 下载 3.11+
- ❌ 看到 "python 不是内部或外部命令":说明 PATH 没配,问 Claude

### Step 0.2:进项目目录 + 装依赖

```powershell
cd F:\claude\genesis\cs-mvp
pip install -e .
```

**应该看到**:`Successfully installed cs-mvp-0.1.0 ...`(或类似)。

**装 dev 依赖**(测试 / lint 用):

```powershell
pip install pytest pytest-asyncio pytest-playwright pytest-cov pre-commit mypy ruff langfuse
```

### Step 0.3:确认 .env 配置

```powershell
notepad .env
```

**应该看到** 4 类 key 至少 3 类有真值:

```
TAVILY_API_KEY=tvly-xxx           # 必须
OPENAI_API_KEY=sk-xxx             # 必须(DashScope 也走这个 key)
ANTHROPIC_API_KEY=sk-ant-xxx      # 可选
LANGFUSE_PUBLIC_KEY=pk-lf-xxx     # 可选(不设则 Langfuse 不工作)
LANGFUSE_SECRET_KEY=sk-lf-xxx     # 可选
LANGFUSE_HOST=https://cloud.langfuse.com  # 可选
```

**如果**:
- ❌ 没有 `.env` 文件:`cp .env.example .env` 然后填 key
- ❌ Langfuse 三个变量缺一:Langfuse 自动关闭,系统正常跑(fail-safe 设计)

### Step 0.4:跑一次 health check

```powershell
python -m cs_mvp.cli --help
```

**应该看到**:打印 4 个子命令 `run / serve / status / export-html / judge`。

到这里**前置准备就完成了**。

---

## 场景 1:演示前 5 分钟启动 Dashboard

这是评委 / 雇主到场前你做的事。

### Step 1.1:打开 PowerShell + 进项目

```powershell
cd F:\claude\genesis\cs-mvp
```

**确认提示符**变成 `PS F:\claude\genesis\cs-mvp>`。

### Step 1.2:确认 git 状态干净(可选,但稳妥)

```powershell
git log --oneline -3
```

**应该看到**(最新 3 条):
```
ded3850 feat(v1.6 batch 2): agent skill professionalization pack
3275e24 feat(v1.6 batch 1): frontend + e2e + infra polish
05b39b3 docs(v1.6): planning layer
```

```powershell
git status
```

**应该看到**:`nothing to commit, working tree clean`。

**如果有 untracked / modified 文件**:不要慌,这些是你后来加的截图 / 笔记之类,不影响演示。

### Step 1.3:启动 Web Dashboard

```powershell
python -m cs_mvp.cli serve --host 127.0.0.1 --port 8765
```

**应该看到**(几行启动日志,最后一行关键):
```
INFO:     Started server process [xxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

⚠️ **这个终端窗口不要关、不要再敲东西、不要按 Ctrl+C**。它是 Dashboard 的"发动机"。

### Step 1.4:打开浏览器

**Chrome 全屏(F11)**地址栏粘贴:

```
http://127.0.0.1:8765
```

**应该看到**首页(v1.6 的 Tailwind 升级版):
- 顶部 Hero:`AI-powered competitive intelligence agent system`
- 9 个 badges(Version / Python / Tests / Coverage / LangGraph / Langfuse / Docker / CI / Lint)
- 4 个能力卡片(Multi-Agent DAG / Evidence-Backed Claims / QA Critic Feedback Loop / Traceable Artifacts)+ Lucide icons
- 系统状态(版本号 / 测试数 / 历史 run 数)
- 快速入口卡片(主 Demo / 备 Demo / Schema 链接)
- 底部历史 run 列表 + 触发新 run 表单

### Step 1.5:确认主 demo 能进

点击 **"查看主 Demo Run"** 卡片(或地址栏粘贴):

```
http://127.0.0.1:8765/runs/T-fa39da6559f14a04ac32fab60842a7ec
```

**应该看到** Run Detail 页:
- 顶部进度条:`9 / 9 nodes · $0.xx · xxxxms`
- 7 个 tab 按钮:**DAG / QA Critic / Revision / Report / Evidence / Schema / Trace**
- 默认在 DAG tab,显示 mermaid 流程图含 8 节点 + qa_critic↔analyst_revise 循环边
- DAG tab 下方"node-list"鼠标 hover 任意节点 → tooltip 显示 role + goal + N skills

**演示流程就从这一页开始**。具体演示话术见 [docs/DEMO_GUIDE.md](DEMO_GUIDE.md)。

### Step 1.6:演示结束关 Dashboard

切回那个 "Uvicorn running" 终端窗口,按 **Ctrl + C**。

**应该看到**:`Shutdown complete` 或提示符回归。可以关窗口。

---

## 场景 2:跑一次新的真实竞品分析 case

**用途**:验证系统能跑通 / 生成新 demo 数据 / 测试某个新行业。

⚠️ **成本警告**:每次 run **真实调用 LLM 和 Tavily**,成本 **$0.05-0.10 / case**,耗时 **5-15 分钟**。**不要随便跑**。

### Step 2.1:在 PowerShell 跑命令

```powershell
cd F:\claude\genesis\cs-mvp
python -m cs_mvp.cli run --query "<你的调研问题>" --competitors "<竞品 1>,<竞品 2>,<竞品 3>"
```

**真实例子**:

```powershell
# 例 1:稳定 case(向量数据库)
python -m cs_mvp.cli run --query "向量数据库竞品分析" --competitors "Milvus,Qdrant,Weaviate"

# 例 2:AI 笔记(可能 Mem 召回不稳)
python -m cs_mvp.cli run --query "AI 笔记竞品" --competitors "Notion,Evernote,Mem.ai"

# 例 3:加 seed_url 防召回污染
python -m cs_mvp.cli run --query "..." --competitors "Mem.ai|seed=https://mem.ai,https://mem.ai/pricing"

# 例 4:启用真闭环 + Langfuse trace
$env:ENABLE_REVISION_LOOP="1"
$env:ENABLE_LLM_RESCUE="1"
python -m cs_mvp.cli run --query "..." --competitors "..."
```

### Step 2.2:跑动期间能看到什么

```
2026-05-22 ... INFO cs_mvp.graph | node task_init started
2026-05-22 ... INFO cs_mvp.graph | node task_init completed
2026-05-22 ... INFO cs_mvp.graph | node collector started
... 大量 httpx 请求日志 ...
2026-05-22 ... INFO cs_mvp.graph | node collector completed
... extractor / analyst / qa_critic / writer / finalize ...

===== Source Quality Summary =====
Total: 18 | fetched: 16 | failed: 0 | empty: 1
Valid: 16 / 18  (...)
...
===== Claim Quality Summary =====
Claims: 14 single + 6 cross = 20 total
Per dimension: features=N, pricing=N, ...
Accepted (support>=0.6): X/20 (Y%)
...
task_id: T-xxxxxxxxx
report: runs/T-xxxxxx/report.md
```

**关键末尾**:`task_id: T-xxx...` 那一行——**这就是这次 run 的唯一标识**。

### Step 2.3:看结果

**方式 A:浏览器**

如果 Dashboard 正在跑,刷新首页,新 run 会出现在历史列表;或直接访问:

```
http://127.0.0.1:8765/runs/T-xxxxxxxxx
```

**方式 B:文件系统**

```powershell
explorer runs\T-xxxxxxxxx
```

会看到 **19+ 个 JSON / MD artifact**:
- `report.md` / `report.html`:最终报告
- `claims.json`:全部 claim(含 accepted + insight_candidate)
- `evidence.json`:全部 evidence
- `qa_audit.json`:QA Critic 反馈
- `revision_history.json`(如果启用了 revision loop)
- `trace.json`:每节点 cost / latency / tokens
- ... 等

### Step 2.4(可选):把新 run 设为主 demo

如果新 run 跑得特别好,想把它当作演示主 demo:

```powershell
notepad demo\demo_manifest.json
```

把 `main_demo.task_id` 改成你新 run 的 task_id,保存。

跑测试确认通过:

```powershell
python -m pytest tests/test_demo_manifest.py -q
```

**应该看到** `7 passed`(如果有 fail 是因为 README / DEMO_GUIDE 还引用旧 task_id,问 Claude 帮你 sync)。

---

## 场景 3:验证 Langfuse Cloud trace

**用途**:确认 LLM 调用真的推到 Langfuse 后台了 / 截 Langfuse 截图。

⚠️ **前提**:`.env` 三个 LANGFUSE_* 变量已填。

### Step 3.1:跑一个轻量验证

```powershell
cd F:\claude\genesis\cs-mvp

python -c "from dotenv import load_dotenv; load_dotenv(); import os; from langfuse import Langfuse; c = Langfuse(public_key=os.environ['LANGFUSE_PUBLIC_KEY'], secret_key=os.environ['LANGFUSE_SECRET_KEY'], host=os.environ.get('LANGFUSE_HOST','https://cloud.langfuse.com')); print('auth_check:', c.auth_check()); t = c.trace(name='manual-smoke', tags=['cs-mvp','smoke']); c.span(name='test-span', trace_id=t.id); c.generation(name='test-gen', trace_id=t.id, model='qwen3.6-plus'); c.flush(); c.shutdown(); print('trace_id:', t.id)"
```

**应该看到**:
```
auth_check: True
trace_id: <uuid>
```

如果看到 `auth_check: False`:keys 不对,回到 Step 0.3 检查 `.env`。

### Step 3.2:去 Langfuse Cloud 看

浏览器开 https://cloud.langfuse.com → 登录 → Tracing 页 → **F5 刷新**。

**应该看到**:Tracing 表格里出现名为 `manual-smoke` 的 trace。

**如果看不到**(已知 free tier 问题):
- 等 30-60 分钟后再刷
- 或扩大时间窗口到 `Past 7 days`
- API 返成功就代表数据已上传,UI 显示延迟是 Langfuse 的事,不是你的代码问题

### Step 3.3:真实端到端 run + Langfuse trace(贵)

跑完整 case + 让所有 LangGraph 节点都推 trace:

```powershell
python -m cs_mvp.cli run --query "..." --competitors "..."
```

跑完后 task_id 出来,过 5-10 分钟去 Langfuse Cloud 看,**应该有 30-50 个 span**(每个 LangGraph 节点 + 每次 LLM 调用)。

---

## 场景 4:截 7 张演示截图

**用途**:填充 `docs/screenshots/` 目录,让 README 视觉完整。

### Step 4.1:准备

按 [场景 1](#场景-1演示前-5-分钟启动-dashboard) Step 1.1-1.5 启动 Dashboard,进到主 demo Run Detail 页。

### Step 4.2:截图工具

Windows:**Win + Shift + S** → 选区域 → 内容到剪贴板。

保存:打开 `mspaint`(画图)→ **Ctrl + V** 粘贴 → 文件 → 另存为 → 选 PNG。

### Step 4.3:7 张截图清单(精确到每张)

每张保存到:`F:\claude\genesis\cs-mvp\docs\screenshots\<filename>.png`

| # | 文件名 | 怎么截 | 关键画面元素 |
|---|--------|--------|------------|
| 01 | `01-home.png` | http://127.0.0.1:8765 全屏滚到顶 | Hero 标题 + 9 badges + 4 能力卡片 |
| 02 | `02-dag.png` | 主 demo Run Detail → DAG tab | mermaid 图 8 节点 + qa_critic→analyst_revise→qa_critic 循环边 |
| 03 | `03-qa-critic.png` | 同上 → QA Critic tab | 顶部 3 类计数(accepted/needs_revision/risky)+ 至少 1 条 needs_revision |
| 04 | `04-revision.png` | 同上 → Revision tab | before/after 表格 + qa_reason 文本 |
| 05 | `05-report.png` | 同上 → Report tab | 报告内容含 "目标用户洞察" / "战略启示" 章节 |
| 06 | `06-schema.png` | 同上 → Schema tab | schema_version + 5 模型字段表 + 3 行业 preset |
| 07 | `07-langfuse.png` | (难)Langfuse Cloud → Tracing → 点开一条 trace | 嵌套 spans 树状视图 |

**注意**:截图 07 看 [场景 3](#场景-3验证-langfuse-cloud-trace),Langfuse UI 可能 30-60 分钟才显示数据(free tier 限制),**不强求**。

### Step 4.4:确认截图被 README 引用

```powershell
git status
```

**应该看到**(你新加的 png):
```
?? docs/screenshots/01-home.png
?? docs/screenshots/02-dag.png
...
```

把它们加进 git:

```powershell
git add docs/screenshots/*.png
git commit -m "docs: add v1.6 dashboard screenshots"
```

README 已经用 `![](docs/screenshots/01-home.png)` 语法引用了这些路径,**截图加进 git 后 GitHub 上 README 就自动显示**。

---

## 场景 5:跑全量测试 + e2e + coverage

**用途**:验证代码没破 / 申请实习时雇主 clone 你仓库后能跑 / CI 验证。

### Step 5.1:单元测试(快,~30 秒)

```powershell
cd F:\claude\genesis\cs-mvp
python -m pytest tests/ -q --ignore=tests/e2e
```

**应该看到**:
```
............................................. [100%]
257 passed in xx.xxs
```

### Step 5.2:e2e 测试(慢,~40 秒,需要 Playwright)

第一次跑要装 Chromium:

```powershell
playwright install chromium
```

如果下载超时(墙的问题):

```powershell
# 用系统 Chrome(Windows)
$env:PLAYWRIGHT_CHROMIUM_USE_SYSTEM_CHROME="1"
```

然后:

```powershell
python -m pytest tests/e2e/ -v
```

**应该看到**:
```
tests/e2e/test_capability_visible.py::test_xxx PASSED
tests/e2e/test_home_loads.py::test_xxx PASSED
...
6 passed in xx.xxs
```

### Step 5.3:测试 + Coverage

```powershell
python -m pytest tests/ -q --cov=cs_mvp --cov-report=term --cov-fail-under=70
```

**应该看到**:
```
...
TOTAL    ...    82.67%
257 passed
```

如果 `Required test coverage of 70% reached. Total coverage: 82.67%` → ✅

### Step 5.4:Lint(可选)

```powershell
python -m ruff check cs_mvp tests
```

**应该看到**:`All checks passed!`(或一些 warning,可忽略)。

### Step 5.5:Type check(可选,部分严格)

```powershell
python -m mypy cs_mvp/agents/skill_card.py cs_mvp/agents/capability_contracts cs_mvp/web/services/artifact_reader.py cs_mvp/observability
```

**应该看到**:`Success: no issues found in N source files`

---

## 场景 6:Docker 启动

**用途**:雇主 clone 仓库后**一行命令**就能看到 Dashboard。

### Step 6.1:确认 Docker Desktop 在跑

PowerShell:

```powershell
docker --version
docker ps
```

**应该看到**:Docker 版本号 + 空容器列表(没报错就行)。

**如果**:
- ❌ "docker 不是内部命令":装 Docker Desktop https://docker.com/products/docker-desktop
- ❌ "Cannot connect to the Docker daemon":Docker Desktop 没启动,点开它的图标

### Step 6.2:构建镜像

```powershell
docker build -t cs-mvp:v1.6 .
```

⏱️ **首次需要 3-5 分钟**(下载 Python 镜像 + pip install 全部依赖)。

**应该看到**(最后几行):
```
Successfully built ...
Successfully tagged cs-mvp:v1.6
```

### Step 6.3:启动容器

**方式 A:docker compose**(推荐):

```powershell
docker compose up
```

**方式 B:docker run**:

```powershell
docker run --rm -p 8765:8765 -v ${PWD}/runs:/app/runs -v ${PWD}/data:/app/data --env-file .env cs-mvp:v1.6
```

**应该看到** Uvicorn 启动日志,最终:
```
INFO:     Uvicorn running on http://0.0.0.0:8765
```

### Step 6.4:浏览器访问

```
http://localhost:8765
```

与场景 1 Step 1.5 看到的页面相同。

### Step 6.5:关掉

PowerShell 中按 **Ctrl + C**。

---

## 场景 7:git 状态检查 + 紧急回滚

**用途**:不小心改了文件想恢复 / 演示前确认仓库干净。

### Step 7.1:看现状

```powershell
git status
git log --oneline -5
git tag -l | tail -5
```

**正常状态**(v1.6.0 已 tag 后):
```
nothing to commit, working tree clean

ded3850 feat(v1.6 batch 2): ...
3275e24 feat(v1.6 batch 1): ...
05b39b3 docs(v1.6): ...
418a570 feat(v1.5 batch 2): ...
54b6318 chore(v1.5): ...

v1.4.1
v1.5.0
v1.6.0
```

### Step 7.2:如果有"乱改"想丢弃

⚠️ **危险操作,会丢未提交的改动**。

**先确认丢的是什么**:

```powershell
git diff
```

**确认要丢**:

```powershell
git checkout -- <文件名>     # 丢单个文件
git checkout -- .             # 丢所有 modified
```

**untracked 文件**(`??`):

```powershell
git clean -n   # dry-run 先看会删什么
git clean -f   # 真删
```

### Step 7.3:回到某个 tag(紧急)

```powershell
git checkout v1.6.0
```

**应该看到**:`HEAD is now at ded3850 ...`

⚠️ **此时是 detached HEAD 状态**,看完代码或 demo 后,**回主分支**:

```powershell
git checkout master   # 或 main,看你的默认分支
```

### Step 7.4:对比版本差异

```powershell
git diff v1.5.0..v1.6.0 --stat
```

会看到 v1.5 → v1.6 改动统计。

---

## 📋 演示前 30 分钟 Checklist

照着勾,确保万无一失:

- [ ] PowerShell 能进项目 `cd F:\claude\genesis\cs-mvp`
- [ ] `git log --oneline -3` 顶部是 `ded3850` 含 `v1.6 batch 2`
- [ ] `git status` 显示 `working tree clean`(或截图等少量 untracked,无 modified)
- [ ] `.env` 有 TAVILY + OPENAI keys
- [ ] `python -m cs_mvp.cli --help` 不报错
- [ ] `python -m pytest tests/ -q --ignore=tests/e2e` 全过(257 passed)
- [ ] `python -m cs_mvp.cli serve --port 8765` 能启动
- [ ] 浏览器 `http://127.0.0.1:8765` 首页正常(Hero + 4 卡片 + 9 badges)
- [ ] 主 demo 页 `http://127.0.0.1:8765/runs/T-fa39da6559f14a04ac32fab60842a7ec` 7 个 tab 都能切换
- [ ] DAG tab hover 节点能看到 tooltip(role + goal + N skills)
- [ ] Revision tab 至少有 1 条 before/after 记录
- [ ] Report tab 含"目标用户洞察"+"战略启示"章节
- [ ] (可选)Langfuse Cloud 有数据 OR README §Langfuse 段已诚实说明 free tier 限制
- [ ] (可选)7 张截图都在 `docs/screenshots/`

---

## 🚨 演示中突发情况应对

### 情况 A:浏览器打开页面慢 / 卡住

**做**:浏览器 F5 刷新。还卡 → 切回 PowerShell 看有没有红色错误。

### 情况 B:某个 tab 显示数据空 / 报错

**做**:**不慌**,继续讲下一个 tab。回答评委:"这是 v1.4 之前的 legacy run 没有这个数据,正好演示我们对老 run 的兼容性"。或者切到备 demo:

```
http://127.0.0.1:8765/runs/T-1cbcb6f3f1b447ab9094fef79f9ea65d
```

### 情况 C:Dashboard 突然没反应

**做**:回 PowerShell,Ctrl + C 关掉。重新 `python -m cs_mvp.cli serve --port 8765`。**1 分钟内能恢复**。

### 情况 D:评委要现场触发新 run

**做**:用首页表单填:

- query: `向量数据库竞品分析`(已验证最快最稳)
- competitors: `Milvus,Qdrant,Weaviate`

**预期 5-6 分钟跑完**。在跑动期间打开 DAG tab,**HTMX every 3s 会自动刷新进度条**,评委能看到节点逐个变绿。

### 情况 E:评委问的问题答不上

**做**:**绝不装懂**。说:

> "好问题,这块我在 docs/ 下有详细记录(指 `docs/AGENT_SKILLS.md` / `docs/AGENT_ROLES.md` / `docs/history/TAROT_*.md`),演示后可以一起看,完整说明取舍逻辑。"

事后查 `docs/QA_DEFENSE.md` 找答案。

---

## 📚 配套文档导航

| 你想做什么 | 看哪份文档 |
|----------|----------|
| 5 分钟演示话术 | [docs/DEMO_GUIDE.md](DEMO_GUIDE.md) |
| 数据契约 / Schema | [docs/SCHEMA.md](SCHEMA.md) |
| 6 Agent 角色卡 | [docs/AGENT_ROLES.md](AGENT_ROLES.md) |
| 6 Agent 能力契约(v1.6) | [docs/AGENT_SKILLS.md](AGENT_SKILLS.md) |
| PromptFamily 设计 | [docs/PROMPT_FAMILY.md](PROMPT_FAMILY.md) |
| 答辩 Q&A 预备 | [docs/QA_DEFENSE.md](QA_DEFENSE.md) |
| 与 14 个开源项目对比 | [docs/COMPARISON_WITH_PEERS.md](COMPARISON_WITH_PEERS.md) |
| 3 个用户场景 | [docs/USE_CASES.md](USE_CASES.md) |
| Langfuse 接入路线 | [docs/LANGFUSE_READY.md](LANGFUSE_READY.md) |
| 已知限制 11 条 | [KNOWN_ISSUES.md](../KNOWN_ISSUES.md) |
| 历次塔罗决策 / 路线图 / 工作报告 | [docs/history/](history/) |

---

## 🆘 真的卡住了

**回到这份文档对应"场景"重新做一遍**。

或者问 Claude:把 PowerShell 红字 + 上一步做了什么发给它。

**不要乱改代码**——v1.6.0 已 tag,代码是稳定的,99% 的问题是环境 / 操作而非代码。
