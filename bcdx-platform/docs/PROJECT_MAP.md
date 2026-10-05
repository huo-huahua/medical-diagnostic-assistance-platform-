# 项目全貌 · 交付清单与使用索引

> 这份文档回答三个问题：**我做了哪些东西**、**每个文件是干什么的**、**我要怎么用**。
> 适合第一次打开这个项目时通读一遍。

---

## 一、产出物总览

一次交付分成三块：

| # | 产出物 | 位置 | 功能 | 怎么用 |
|---|---|---|---|---|
| **A** | 优化设计报告 v1.0 | `毕设优化/cp16/OPTIMIZATION_1.0.md` | 对原毕设（cp16）的全面体检：40+ 条分级问题、目标架构、P0–P3 路线图 | 当参考资料读；要回看"当年哪些地方有问题"时打开 |
| **B** | BC-Dx Platform | `毕设优化/bcdx-platform/` | **真正可运行的全栈产品**：前端 + 后端 + 机器学习 + 知识库 | 双击 `scripts\dev.bat` → 打开 http://127.0.0.1:5173 |
| **C** | 文档与截图 | 见下面第二、三节 | 说明怎么跑、怎么看、怎么改 | 按需查阅 |

---

## 二、文档的分工（不知道该看哪份时看这里。数字会变，分工不会）

| 文档 | 位置 | 什么时候看 |
|---|---|---|
| **README.md** | 仓库根目录 | 第一次接触项目：这是什么、模型表现、API 一览、环境变量 |
| **docs/QUICKSTART.md** | `docs/` | **想立刻跑起来看前端效果**：启动步骤 + 9 个页面逐页检查清单（含截图与预期结果） |
| **docs/TUTORIAL.md** | `docs/` | 想理解**后端技术原理**：技术栈、分层架构、防泄漏流水线、成本控制 |
| **docs/KNOWLEDGE_BASE.md** | `docs/` | 想了解**知识库与检索**：内容清单、切块策略（含那个 98% 静默截断 bug）、拒答闸门、怎么加内容 |
| **docs/QA_COMPARISON.md** | `docs/` | 想了解**三路径问答对比**：本地 RAG / 外部直答 / 外部 + RAG 的设计、度量口径、成本模型 |
| **docs/LLM_INTEGRATION.md** | `docs/` | 想**接上真实大模型**：8 家服务商怎么选、环境变量优先级（含那个 401 陷阱）、探活与 16 类错误、多模型对比、密钥怎么管 |
| **docs/TESTING.md** | `docs/` | 想**跑测试或看 CI**：427 个用例的分布，以及**每个测试在防哪个真实踩过的 bug** |
| **ARCHITECTURE.md** | 仓库根目录 | 想**改代码**：逐文件职责、分层规则、"想改某处该看哪个文件"速查表 |
| **docs/OPTIMIZATION_BACKLOG.md** | `docs/` | 想知道**还能优化哪些地方**：30 条优化项（现状证据 + 方案 + 成本 + 推荐组合），可按编号勾选 |
| **docs/PROJECT_MAP.md** | `docs/` | **就是本文档**：全局总览与使用索引 |

---

## 三、目录逐项功能说明

### 3.1 顶层（仓库根目录）

| 文件 | 功能 |
|---|---|
| `README.md` | 项目门面：定位、与原型的对比修正表、模型表现、快速开始、API 表、免责声明 |
| `ARCHITECTURE.md` | 代码结构说明书：分层规则 + 逐文件职责 + 编辑速查表 |
| `LICENSE` | MIT + 医疗用途附加声明（本项目非医疗器械） |
| `.gitignore` | 忽略 `.env`、数据库、模型产物、`node_modules/` 等运行时文件 |
| `.env` / `.env.example` | 环境变量。`.example` 是可提交的模板，`.env` 是你的实际配置（**不要提交**） |
| `scripts/dev.bat` | **Windows 一键启动**：探测 Python → 按需训练 → 开两个窗口起前后端 |
| `scripts/dev.sh` | macOS / Linux 版启动脚本（会等后端就绪再起前端） |
| `.github/workflows/ci.yml` | CI 流水线：后端测试 + 前端类型检查与构建 |
| `_tools/shoot-new-pages.cjs` | 开发工具：用 Puppeteer 驱动真实浏览器登录并截图（生成 `docs/screenshots/09`–`16`，桌面 1680×1050）。**不属于运行时**，仅在需要更新截图时手动运行 |
| `_tools/shoot-responsive.cjs` | 开发工具：拍 `17`（平板 820 px，图标窄栏 + 页头病种切换器）与 `18`（手机 390 px）；**会断言页头存在 `[aria-pressed]` 切换器**，布局坏了会直接报错而不是产出一张看着正常的图 |
| `_tools/smoke_all_endpoints.py` | 开发工具：**对后端打 35 条真实请求**，逐个覆盖所有已文档化的端点（公开路由 / 鉴权 / 预测 / RAG 问答 / 记录 / 大模型 / SSE），逐行打印 `OK/FAIL 标签 状态码 耗时`，非预期结果会以退出码 1 结束。用它回答"改完之后原有功能还好不好使"这类问题——**pytest 用的是 `TestClient`，它走的是真 socket**，能顺带暴露序列化、代理、SSE 之类只在真链路上出现的问题 |
| `_tools/eval_retrieval.py` | 开发工具：检索 A/B（dense / hybrid / hybrid+rerank）。建一次索引后只切标志位，输出 top-5 命中数 |
| `_tools/render_compare_report.py` | 开发工具：把一次 `/api/v1/rag/compare` 的返回渲染成自包含 HTML 单页报告。**从 JSON 生成而不是手写**，保证三份回答与真实返回逐字一致——手抄正是引用悄悄对不上的地方 |

### 3.2 `backend/` —— 后端（31 个 Python 文件；另有 9 个测试文件）

| 路径 | 功能 |
|---|---|
| `app/main.py` | 应用入口：注册路由、中间件、统一异常处理、启动时加载模型与 RAG 索引，并校验 `SECRET_KEY` 不是占位值 |
| `app/api/v1/auth.py` | 注册 / 登录 / 当前用户（JWT + bcrypt） |
| `app/api/v1/models.py` | 病种信息、特征 schema、全模型指标 |
| `app/api/v1/predict.py` | 单次推理（可带 SHAP 归因）、**批量推理**、**真实样本抽样** |
| `app/api/v1/rag.py` | 知识问答：同步版 + **SSE 流式版** + **三路径对比与历史** |
| `app/api/v1/llm.py` | **大模型接入**：服务商目录（公开）、连接状态（需登录）、**探活自检**（16 token 一次调用） |
| `app/api/v1/records.py` | 历史记录：分页、筛选、统计 |
| `app/services/prediction.py` | 推理编排：取模型 → 预测 → 阈值判定 → 组装结果 |
| `app/services/explainer.py` | **SHAP 归因**：把归因结果转成结构化数值（不是图片） |
| `app/services/rag_service.py` | **本地检索**：token 感知切块 + 向量检索 + 三道闸门 + 病种隔离 + 拒答 + 段落合并 |
| `app/services/llm_providers.py` | **服务商目录**：8 家的地址/默认模型/价格/控制台链接；解析优先级；密钥脱敏；16 类错误分类 |
| `app/services/llm_mock.py` | **离线演示通道**：`httpx.MockTransport` 只换掉 socket，SDK 照常运行——无密钥、无网络、零成本 |
| `app/services/llm_gateway.py` | **成本控制**：硬开关 + 精确哈希缓存 + 语义缓存 + 模型入缓存身份；探活；失败记忆 |
| `app/services/qa_compare.py` | **三路径问答对比**：路径目录、度量函数、多模型编排与汇总 |
| `app/services/datasets.py` | **真实样本抽样**：从公开数据集按标签均衡抽取（替代有偏的合成采样） |
| `app/ml/registry.py` | 模型注册表：启动时把 6 个模型读进内存 |
| `app/db/models.py` | 数据表：用户 / 预测记录 / 会话 / 消息 / LLM 用量 / 审计日志 / **问答对比**（7 张） |
| `app/db/session.py` | 数据库连接与会话管理 |
| `app/core/config.py` | 配置读取（全部走 `.env`，**无硬编码密钥**；含占位密钥检测） |
| `app/core/security.py` | 口令哈希、JWT 签发与校验 |
| `app/core/errors.py` | 统一错误码与响应信封 |
| `app/core/logging.py` | 结构化 JSON 日志 + `request_id` 串联 |
| `app/core/deps.py` | 依赖注入：当前用户、数据库会话、限流 |
| `app/schemas/__init__.py` | 全部请求/响应契约（Pydantic v2） |
| `tests/` | **427 个 pytest 用例**（10 个文件），覆盖切块、检索与混合排序、网关、服务商接入、预测、对比、认证、应用层 |
| `tests/conftest.py` | 测试基建：环境变量前置、会话级 fixture、一次性数据库、**每测试一个全新网关** |
| `pytest.ini` | pytest 配置与标记（`slow` / `integration`） |
| `requirements.txt` | 后端依赖清单（运行所需） |
| `requirements-dev.txt` | 测试依赖（pytest / pytest-cov / httpx），**跑平台不需要** |
| `bcdx.db` | **运行时生成**的 SQLite 数据库。删掉即重置 |

### 3.3 `frontend/` —— 前端（21 个 TS/TSX 文件，约 8600 行）

| 路径 | 功能 |
|---|---|
| `src/main.tsx` | 入口：路由表 + 全局 Provider + 登录守卫 |
| `src/api/index.ts` | **所有后端请求的唯一出口**：axios 实例、token 注入、错误归一化 |
| `src/lib/store.ts` | 全局状态：登录态、病种/算法选择、侧栏折叠 |
| `src/lib/format.ts` | 数值/时间/百分比格式化 |
| `src/types/index.ts` | 与后端对齐的 TypeScript 类型定义 |
| `src/components/AppShell.tsx` | 整体框架：侧栏导航（**8 项**，`md` 图标窄栏 / `lg` 展开）+ 病种切换（侧栏与页头各一处，保证 `lg` 以下也能切）+ 顶部栏 + 跳转到主内容的 skip link + **按路由的 `ErrorBoundary`** + 免责声明 |
| `src/components/ErrorBoundary.tsx` | **错误边界**：捕获子树异常、展示可读错误页、重试 / 返回总览 / 复制错误详情（剪贴板不可用时退化为 textarea 选中） |
| `src/components/domain.tsx` | 业务组件：判定大卡、概率表盘、指标条、范围警告 |
| `src/components/ContributionChart.tsx` | **SHAP 归因图**（纯 SVG 发散条形图，不依赖图表库） |
| `src/components/ui.tsx` | 基础 UI 组件：卡片、面板、加载块、空状态 |
| `src/components/Toast.tsx` | 全局轻提示 |
| `src/features/auth/LoginPage.tsx` | 登录 / 注册页 |
| `src/features/dashboard/DashboardPage.tsx` | 总览页 |
| `src/features/diagnosis/DiagnosisPage.tsx` | **智能诊断页**（核心） |
| `src/features/explain/ExplainPage.tsx` | 可解释分析页（三算法对比） |
| `src/features/assistant/AssistantPage.tsx` | 医学问答页（SSE 流式） |
| `src/features/compare/ComparePage.tsx` | 模型对比页 |
| `src/features/records/RecordsPage.tsx` | 历史记录页 |
| `src/features/batch/BatchPage.tsx` | **批量评估页**：CSV 上传（支持中文列名）、真实样本载入、直方图、逐行判定与一致性、导出 |
| `src/features/qaCompare/QaComparePage.tsx` | **问答对比页**：三路径指标表、**多模型对比输入**、度量口径说明、对比历史 |
| `src/features/llm/LlmPanel.tsx` | **外部模型连接面板**：状态胶囊、字段网格、8 家服务商目录、**探活自检**与错误分类展示 |
| `vite.config.ts` | 开发服务器 + **代理配置**（`/api` 与 `/health` 都转发到 8000） |
| `tailwind.config.js` | 主题色板、字体、透明度档位扩展 |
| `src/styles/index.css` | 全局样式与工具类 |

### 3.4 `ml/` —— 机器学习

| 路径 | 功能 |
|---|---|
| `pipelines/train.py` | **一条命令训练全部模型**：2 病种 × 3 算法 + 交叉验证 + 概率校准 + 阈值寻优，约 30 秒 |
| `registry/registry.json` | 模型注册表：每个模型的指标、阈值、特征 schema（后端启动时读它） |
| `registry/models/*.joblib` | 6 个训练好的模型文件 |
| `data/raw/` | 原始公开数据集（WDBC 乳腺癌、UCI Heart 心脏病） |
| `requirements.txt` | 训练依赖 |

**怎么用**：`cd ml && python pipelines/train.py`。**一般不需要重跑**——模型已训练好，删掉 `registry/` 才会触发重新训练。

### 3.5 `knowledge/` —— 本地知识库

| 文件 | 病种 | 覆盖内容 | 片段 |
|---|---|---|---:|
| `sources/breast_cancer_zh.md` | breast | 乳腺癌：危险因素、早期表现、BI-RADS 分级、诊断路径、TNM 分期、纤维腺瘤、囊肿与增生、乳腺炎、乳头溢液、男性乳腺癌、遗传咨询、内分泌治疗、前哨淋巴结、乳腺密度 | 61 |
| `sources/breast_imaging_zh.md` | breast | 乳腺超声 / 钼靶 / 磁共振、穿刺活检类型、报告解读、复查节奏、结论不一致、隆胸术后 | 19 |
| `sources/heart_disease_zh.md` | heart | 冠心病、心绞痛、心肌梗死、心力衰竭、心律失常、危险因素、糖尿病、吸烟、运动、饮食、自我管理、急救与 CPR、常见误区 | 52 |
| `sources/cardiac_exam_zh.md` | heart | 静息心电图、动态心电图、运动负荷试验、心脏超声、冠脉 CT、冠脉造影、心肌标志物、常规化验 | 23 |
| `sources/model_literacy_zh.md` | general | 统计风险预测、敏感度/特异度、判定阈值、准确率/精确率/F1、ROC/AUC、校准、混淆矩阵、特征贡献度、交叉验证、数据泄漏 | 25 |
| `sources/disclaimer_zh.md` | general | 系统用途、使用限制、免责说明、外部模型调用说明、问答路径对比说明 | 10 |
| `_archive/` | — | 已归档的重复文件（`breast_basic_zh.txt`）+ 归档原因说明 | — |
| **合计** | | **6 个文件 / 约 49 KB / 84 个小节** | **190** |

**约定：文件名决定病种归属**（含 `breast` → 乳腺癌库，含 `heart`/`cardiac` → 心脏病库，其余为通用），也可用文件头部的 front matter 显式覆盖。

**切块**：在 **token** 单位上进行，窗口大小运行时从嵌入模型读取（当前 128 → 预算 124）。启动时会复核每个片段并暴露 `oversize` 计数到 `/health`——**必须是 0**。详见 [`KNOWLEDGE_BASE.md`](KNOWLEDGE_BASE.md)。

**怎么用**：直接编辑这些 Markdown/txt 文件，**重启后端**即生效，无需重新训练。

### 3.6 `docs/`

| 文件 | 功能 |
|---|---|
| `QUICKSTART.md` | 启动与前端检查指南（9 个页面） |
| `TUTORIAL.md` | 完整教程（含后端技术详解） |
| `KNOWLEDGE_BASE.md` | **知识库与检索**：内容清单、切块策略、拒答闸门、怎么加内容 |
| `QA_COMPARISON.md` | **三路径问答对比**：设计与使用、度量口径、成本模型、多模型对比 |
| `LLM_INTEGRATION.md` | **大模型接入**：8 家服务商、环境变量优先级、探活与错误分类、多模型对比、密钥管理 |
| `TESTING.md` | **测试与 CI**：怎么跑、用例分布、逐条回归清单、还没覆盖的部分 |
| `PROJECT_MAP.md` | 本文档 |
| `MODEL_CARD.md` | **训练时自动生成**的模型卡：指标、混淆矩阵、数据来源 |
| `OPTIMIZATION_BACKLOG.md` | 30 条优化项与完成状态 |
| `screenshots/` | **18 张**真实前端截图（含平板 / 手机两档），可用于 README 展示或对照检查 |
| `samples/` | **真实密钥跑出来的一次问答对比**：`qa-comparison-live.json`（接口原始返回）+ `qa-comparison-live.html`（同一份数据的单页报告，可直接打开 / 打印 / 放进汇报）。用 `_tools/render_compare_report.py` 可把任何一次对比结果渲染成同样的报告 |

### 3.7 仓库根的 CI 配置

| 路径 | 功能 |
|---|---|
| `.github/workflows/ci.yml` | GitHub Actions：**后端测试**（安装 → 重训模型 → 切块前置检查 → pytest + 覆盖率）与**前端类型检查与构建**，两个独立 job |

---

## 四、常用操作索引

| 我想…… | 怎么做 |
|---|---|
| **把项目跑起来看效果** | 双击 `scripts\dev.bat` → 打开 http://127.0.0.1:5173 |
| 登录进去看看 | 点「填入演示账号」（`demo@bcdx.dev` / `demo12345`）→ 登录 |
| 手动启动 | 终端 1：`cd backend && python -m uvicorn app.main:app --reload --port 8000`<br>终端 2：`cd frontend && npm run dev` |
| 看后端接口文档 | http://127.0.0.1:8000/docs |
| 检查后端是否健康 | http://127.0.0.1:8000/health（含切块统计 `rag_chunking`） |
| **跑自动化测试** | `cd backend && set PYTHONPATH=. && pytest`（427 个用例，约 60–90 秒，不产生 API 费用） |
| **看每个测试在防哪个 bug** | 打开 [`TESTING.md`](TESTING.md) 第三节的回归清单 |
| **看问答路径对比** | 侧栏「问答对比」→ 输入问题 → 三列并排；原理见 [`QA_COMPARISON.md`](QA_COMPARISON.md) |
| **接入真实大模型** | 在 `.env` 里设 `LLM_ENABLED=true` + `LLM_PROVIDER` + `LLM_API_KEY` → 重启后端 → 页面顶部「外部模型连接」点「测试连接」自检；全流程见 [`LLM_INTEGRATION.md`](LLM_INTEGRATION.md) |
| **零成本体验大模型对比** | `.env` 里设 `LLM_PROVIDER=mock`，不填密钥、不出网、不花钱，但整条链路照常运行 |
| **一次对比多个模型** | 「问答对比」页的「使用的模型」输入框填多个模型名（逗号或空格分隔，上限 3 个） |
| **检查大模型连通性（命令行）** | 登录拿 token 后 `curl -H "Authorization: Bearer <token>" -X POST http://127.0.0.1:8000/api/v1/llm/test` |
| **批量评估一批样本** | 侧栏「批量评估」→ 点「载入 12 份真实样本」或上传 CSV → 运行 |
| **重新训练模型** | 删掉 `ml/registry/`，再 `cd ml && python pipelines/train.py` |
| **给知识库加内容** | 编辑 `knowledge/sources/*.md` → 重启后端；细节见 [`KNOWLEDGE_BASE.md`](KNOWLEDGE_BASE.md) |
| 确认切块没超窗 | `curl http://127.0.0.1:8000/health` → `rag_chunking.oversize` 必须是 `0` |
| **确认混合检索真的在跑** | `curl http://127.0.0.1:8000/health` → `rag_retrieval.mode` 应为 `hybrid`，且问过一句后 `last_query.dense` 与 `last_query.lexical` **同时非零**（只看 `dense` 非零 = 融合没起作用） |
| **复跑检索 A/B（dense / hybrid / hybrid+rerank）** | `PYTHONPATH=backend python _tools/eval_retrieval.py`（约 90 秒，会建一次索引；重排模式需已下载模型） |
| **换 / 加一个模型算法** | 改 `ml/pipelines/train.py` 的 `make_models()` → 重训 |
| 调判定阈值策略 | 改 `ml/pipelines/train.py` 里阈值那段 → 重训 |
| **改界面文案 / 布局** | 改 `frontend/src/features/<页面>/*.tsx`（开发模式热更新，存盘即生效） |
| 改主题配色 | 改 `frontend/tailwind.config.js` |
| 改接口地址 / 加请求 | 改 `frontend/src/api/index.ts` |
| **加一个后端接口** | 在 `backend/app/api/v1/` 新建路由 → 在 `main.py` 注册 → **往 `test_auth.py` 的受保护路由清单里补一行** |
| 换数据库（SQLite → PostgreSQL） | 改 `.env` 的 `DATABASE_URL` + `backend/requirements.txt` |
| 改端口 | 后端：`.env` 的 `PORT`；前端：`frontend/vite.config.ts` 的 `server.port`（改完记得同步代理目标） |
| **重置所有数据** | 删 `backend/bcdx.db` → 重启后端（下个注册账号会重新成为管理员） |
| 确认没花 API 钱 | 打开总览页看「LLM 调用次数」，应为 **0**；或看「问答对比」页的 `费用(¥)` 列 |
| **换一家大模型服务商** | 改 `.env` 的 `LLM_PROVIDER`（8 家可选：`deepseek`/`openai`/`qwen`/`moonshot`/`zhipu`/`ollama`/`mock`/`custom`）+ 对应的 `LLM_API_KEY` → 重启后端 |
| **用本地 Ollama 跑模型** | `.env`：`LLM_PROVIDER=ollama`、`LLM_ENABLED=true`，密钥留空（本地服务不需要） |
| 停止服务 | 关掉那两个命令行窗口 |

---

## 五、项目规模

| 维度 | 数量 |
|---|---|
| 后端代码 | 31 个 Python 文件 |
| 后端测试 | 10 个文件 · **427 个用例** |
| 前端代码 | 21 个 TS/TSX 文件 · 约 8600 行 |
| 训练脚本 | 1 个 · 550 行 |
| 前端页面 | 9 个（登录 + 8 个业务页） |
| 后端接口 | 28+ 个 |
| 数据表 | 7 张 |
| 训练模型 | 6 个（2 病种 × 3 算法） |
| 可接入的大模型服务商 | 8 家（1 家离线演示 + 1 家本地 Ollama + 6 家云端） |
| 知识库 | 6 个源文件 · 49 KB · 84 小节 → **190 个检索片段** |
| 文档 | 11 份 |
| 截图 | 18 张 |
| CI | 2 个 job（后端测试 / 前端构建） |

### 技术栈

| 层 | 选型 |
|---|---|
| 前端 | React 18 · TypeScript · Vite 6 · TailwindCSS 3.4 · Zustand · TanStack Query · Recharts |
| 后端 | FastAPI · Pydantic v2 · SQLAlchemy 2.0 · SQLite · PyJWT · bcrypt |
| 机器学习 | scikit-learn Pipeline · XGBoost · CalibratedClassifierCV · SHAP |
| 检索 | sentence-transformers · FAISS（全本地，零 API 费用） |

### 模型表现

| 病种 | 冠军模型 | 测试 AUC | 交叉验证 AUC | 判定阈值 |
|---|---|---|---|---|
| 乳腺癌 | `breast_xgb_v1.0` | **0.9959** | 0.9935 ± 0.0046 | 0.1701 |
| 心脏病 | `heart_rf_v1.0` | **0.9589** | 0.8809 ± 0.0347 | 0.6321 |

---

## 六、当前状态与注意事项

### 现在就能用

前后端服务已在运行：后端 `http://127.0.0.1:8000`、前端 `http://127.0.0.1:5173`。

可用账号：

| 账号 | 密码 | 说明 |
|---|---|---|
| `demo@bcdx.dev` | `demo12345` | 演示账号（登录页有一键填入按钮） |
| `tutorial1790502762@bcdx.dev` | `tutorial12345` | 预置 6 条预测记录，适合看历史记录页 |
| `arch1790498911@bcdx.dev` | `arch12345` | 管理员 |

### 相对于原始毕设（cp16），修掉的三条红线

| 原始问题 | 现在的处理 |
|---|---|
| 诊断标签映射**反向**（把良性判成恶性） | 全局固定 `0 = 良性 / 1 = 恶性`，并用真实样本回归验证方向正确 |
| **数据泄漏**（全量数据 fit scaler 后再切分） | 改成 `Pipeline(StandardScaler → 分类器)`，标准化只在每折训练子集内 fit |
| API Key **明文硬编码** 在源码里 | 全部走 `.env`，仓库只提交 `.env.example` |

### 另外修掉的三个实际运行 Bug

| Bug | 症状 | 修复 |
|---|---|---|
| Vite 只代理 `/api`，没代理 `/health` | 总览页**整页白屏** | 补 `/health` 代理项 + 组件判空收紧 |
| SSE 生成器在数据库会话关闭后才执行 | 问答接口返回 200 但**空响应**，页面卡在"正在检索知识库…" | 在返回响应前把所需值快照成普通变量 |
| `dev.bat` 用裸 `python` | 可能命中没装依赖的解释器导致启动失败 | 改成自动探测有依赖的解释器（优先 Anaconda） |

### 三个容易误判的点

1. **「填充均值」后提交会得到「恶性」（概率约 44%）** —— 这是阈值策略（0.1701，偏筛查、重灵敏度）的正常结果，**不是模型判反**。想验证方向，见 `QUICKSTART.md` 的「验证判定方向」配方。
2. **`sklearn.datasets.load_breast_cancer` 的 0/1 含义与本项目相反**（sklearn：0=恶性；本项目：0=良性）。拿 sklearn 样本自行标类比对时极易误判。
3. **问答对比页里外部两列显示 `skipped` 不是失败** —— 它的意思是"本部署没配密钥，付费路径按设计没有执行"。想看到内容有两条路：填真密钥，或把 `LLM_PROVIDER` 设成 `mock` 走离线演示通道。

### 这几轮做完的事

| 编号 | 事项 | 结果 |
|---|---|---|
| **#1** | 自动化测试与工程化 | **427 个 pytest 用例** + GitHub Actions CI（后端测试 / 前端类型检查与构建）。详情见 [`TESTING.md`](TESTING.md) |
| **#8** | 修掉默认密钥 | `.env.example` 换成明显占位符；**开发环境告警、生产环境拒绝启动**；有测试真的去读模板文件守着 |
| **#13** | 扩充知识库 | 从 20 KB / 33 片段 → **49 KB / 84 小节 / 190 片段**；新增乳腺影像、心脏检查、**模型素养**三个专题。详情见 [`KNOWLEDGE_BASE.md`](KNOWLEDGE_BASE.md) |
| **#14** | 改进切块策略 | 改为 **token 感知切块**，修掉"98% 片段超窗被静默截断"的 bug；`oversize` 现在是 0，且有测试与 CI 双重守着 |
| **#15** | **混合检索 + 重排** | **自实现 BM25 与稠密检索用 RRF 融合（默认开）**，实测修掉 4 个"手里有答案却拒答"的问题，代价约 1 ms；CrossEncoder 重排**已接好但默认关闭**（实测约 90× 延迟、top-1 无收益）。详情见 [`KNOWLEDGE_BASE.md`](KNOWLEDGE_BASE.md) §4 |
| **#20** | 全局错误边界 | 两层 `ErrorBoundary`（应用外壳 + 按路由），含重试 / 返回总览 / 复制错误详情；路由级必须带 `key`，否则出错后切页仍是错误页 |
| **#22** | 补 `md` 断点 | 侧栏在 `md` 收成图标窄栏、`lg` 展开；**顺带修掉一个真实功能缺失**——病种切换器原先只存在于 `lg` 侧栏，`lg` 以下根本无法切换病种 |
| **#25** | 批量预测页面 | 新增「批量评估」页：CSV 上传（支持中文列名）、**真实数据集样本**（替代有偏的合成采样）、阈值标注直方图、逐行判定与标签一致性、CSV 导出 |
| 新增 | 问答路径对比 | 本地 RAG / 外部直答 / 外部 + RAG 三路径并排对比，含费用、缓存、出处与度量口径说明。详情见 [`QA_COMPARISON.md`](QA_COMPARISON.md) |
| 新增 | **大模型接入 + 多模型对比** | **8 家服务商**一套 OpenAI 兼容适配层；**离线演示通道**（无密钥、无网络、零成本）让外部路径第一次可被测试；16 类错误分类 + 探活自检；同一问题可并排对比最多 3 个模型。详情见 [`LLM_INTEGRATION.md`](LLM_INTEGRATION.md) |

### 另外顺带修掉的问题

| 问题 | 症状 | 修复 |
|---|---|---|
| **批量汇总用 0.5 计数** | 每行按冠军阈值（乳腺癌 0.1701）打标签，汇总却按 0.5 计数，**总数和逐行结论自相矛盾** | 改为从每行的 `verdict` 统计，并在响应里返回 `threshold` |
| **演示样本全判"恶性 100%"** | 在 `[min,max]` 上均匀采样会以阳性类为中心（最大值本就是它的上尾） | 改为从公开数据集**按标签均衡抽真实行**（`services/datasets.py`） |
| **跨病种提问返回通用拒答** | 过度取回上限被同语料占满，病种过滤后候选为空，定制越界提示**永远显示不出来** | 指定病种时扫全量语料（内存 190 个向量，毫秒级） |
| **对比耗时被记成 43 秒** | 冷启动的索引构建被算进了单次回答的耗时 | 索引构建移到计时开始之前；现在稳定在 30–60 ms |
| **`/api/v1/meta/limits` 返回裸 body** | 前端 `unwrap` 取 `res.data.data`，会拿到 `undefined` | 补齐统一信封（测试抓出来的） |
| **问候语被当成无法回答的问题** | 对「你好」回"没有检索到相关内容，请前往医院就诊" | 加问候语分支并首尾锚定（「你好，乳腺癌怎么筛查」仍是正常问题）；同时在**检索之前**短路，避免白跑一次嵌入、给出无关"出处"，以及 `use_llm=true` 时**为一句寒暄触发付费调用** |
| **`npm run lint` 是死脚本** | 指向既未安装也未声明的 `eslint`，一跑就报错 | 删除，换成可用的 `npm run typecheck` |
| **422 响应绕过统一信封** | 表单填错时界面只弹一句"请求失败"，**看不出是哪个字段错了**——而服务端其实已经算出精确字段 | 根因是 FastAPI 自带的 `RequestValidationError` handler **优先级高于通用 `Exception` handler**，于是 422 成了唯一不带 `{code,message,data,request_id}` 的响应形状。显式注册 `validation_exception_handler` 把字段路径写进 `message`；前端 `explain()` 补上 `detail` / 超时 / 连不上三种兜底文案 |
| **修上面那条时把 422 改成了 500** | 自定义 `field_validator` 抛 `ValueError`（如口令强度）时，pydantic 把**异常对象本身**放进 `ctx.error`，`JSONResponse` 序列化时炸 `TypeError: Object of type ValueError is not JSON serializable`，**在错误处理器里抛错** | `details` 过一遍 `jsonable_encoder`——这正是 FastAPI 自带 handler 一直在做的事，重写它就得把这一步补回来；有 3 条既有测试立刻抓出了它 |
| **前端错误文案是写死的一句话** | `interceptor` 里 `message` 取不到就直接 `return '请求失败'`，把后端的解释全丢了 | `explain()` 按 `message` → `detail`（字符串或 FastAPI 的 `{loc,msg}[]`）→ 超时 → 连不上 → 带状态码兜底依次降级，**任何一层有信息就不会退化到"请求失败"** |

### 接大模型时抓出来的四个坑

这四个都是"写的时候觉得对、跑起来才发现不对"，全部已修，并且各有测试钉住：

| 问题 | 症状 | 修复 |
|---|---|---|
| **模型没进缓存身份** | 一次对比两个模型，第二个模型直接命中第一个的缓存 —— **它根本没被调用**，表格两列一模一样，看上去"两个模型答案一样" | 缓存 key 改成 `purpose@model`；测试断言换模型后**必须**产生第 2 次调用 |
| **语义缓存跨调用点串味** | 「本地检索增强」和「外部直答」的 cache payload 都来自同一个问题，向量相似度接近 1.0 —— 直答路径被喂了一份**检索增强的答案**，而"有检索和没检索的差别"正是这个功能唯一的卖点 | 语义缓存按调用点（`purpose`）分组匹配；测试断言换 `purpose` 后不命中 |
| **网关单例污染测试** | 某条测试单独跑通过、跑全量却挂 —— 前面的用例已经把进程级网关的调用计数改了 | `conftest.py` 给每个测试发一个全新网关（`autouse`） |
| **占位密钥可被照抄** | `.env.example` 里的默认值**够长、还带随机后缀**，一眼看不出是占位值，照抄到生产后任何人都能伪造 JWT | 占位清单 + 关键词双重检测；**生产环境拒绝启动**；测试直接读模板文件校验 |

### 尚未完成 / 可继续的方向

完整清单（30 条，含现状证据、方案、成本与推荐组合）见 **[OPTIMIZATION_BACKLOG.md](OPTIMIZATION_BACKLOG.md)**。速览：

- **工程化**：Docker / Compose 一键部署、依赖锁版本（`#3`、`#4` 仍未做）
- **测试缺口**：**前端没有自动化测试**（当前靠 Puppeteer 截图脚本人工核对）、无 lint / 格式化检查；
  真实密钥的端到端调用也不在 CI 里（外部路径由离线演示通道覆盖）
- **安全**：审计日志只覆盖登录（`#9`）、Token 无刷新 / 无吊销（`#10`）；默认密钥的坑**已堵**（`#8` ✅）
- **RAG**：混合检索（稠密 + BM25 + RRF）已完成（`#15` ✅）；语料继续扩容、按语料上量换 ANN 索引仍是可做项
- **产品化**：数据库迁移（Alembic 已声明未用）、数据漂移监控；无障碍（`#21`）已补图表替代文本，键盘 / 焦点审计未做；响应式（`#22`）已完成
- **LLM 相关**：真实调用的成本/延迟没有长期统计、没有多轮对话上下文、没有按用户维度的额度控制

---

**免责声明**：本项目为科研与教学演示用途，**非医疗器械**，未取得任何医疗器械注册证，不用于临床诊断、治疗决策或任何医疗用途。
