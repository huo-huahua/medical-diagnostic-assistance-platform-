# BC-Dx Platform

> 面向乳腺癌与心脏病的全栈辅助评估平台 —— 可解释、可复现、低成本的临床决策支持原型。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)

---

## 这是什么

BC-Dx Platform 把一个机器学习毕业设计原型重构成了**可直接开源展示的真实产品**。它解决的不只是「模型能不能预测」，而是「模型凭什么这么预测、运行成本多少、多个用户怎么隔离、结论有多可信」。

三个核心能力：

| 能力 | 说明 |
|---|---|
| **可解释推断** | 每次预测返回结构化的 SHAP 特征贡献值（不是图片），逐项展示每个指标把结论推向阳性还是阴性、推了多少 |
| **零成本问答** | 医学问答默认完全本地运行：`sentence-transformers` 嵌入 + **自实现 BM25** 两路召回、RRF 融合 + 模板作答，不产生任何外部 API 费用 |
| **多用户隔离** | JWT 会话、bcrypt 口令散列、逐用户预测记录与对话历史隔离 |

在此之上还有两个用来"把设计选择讲清楚"的能力：

| 能力 | 说明 |
|---|---|
| **问答路径对比** | 同一个问题，三条路径（本地 RAG / 外部模型直答 / 外部模型 + RAG）并排作答，把「有没有检索」的差异变成可测量的列：引用条数、词面重合度、缓存命中、Token 与费用。默认状态下外部两列标记为 `skipped`，费用为 0 |
| **批量评估** | 上传 CSV（支持中文列名）或载入公开数据集的真实样本，一次评估数百例；直方图标注阈值线，逐行给出判定、概率与「是否与数据集标签一致」，可导出 CSV |
| **可接入任意大模型** | 8 家服务商预设（DeepSeek / OpenAI / 通义 / Kimi / GLM / 本地 Ollama / 内置演示 / 自建端点），一次 16 token 的探活即可诊断六类故障，并支持**多模型并排对比** |

> 详细说明：[`docs/QA_COMPARISON.md`](docs/QA_COMPARISON.md)（问答对比 · 三条路径与成本）、
> [`docs/LLM_INTEGRATION.md`](docs/LLM_INTEGRATION.md)（接入大模型 · 服务商、自检与错误分类）、
> [`docs/KNOWLEDGE_BASE.md`](docs/KNOWLEDGE_BASE.md)（知识库 · 内容、切块与**混合检索**）、
> [`docs/TESTING.md`](docs/TESTING.md)（测试 · 427 个后端 + 39 个前端用例在防哪些 bug）、
> [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)（部署 · 一键启动与每个容器配置的来由）。

## 相比原型的修正

原毕设存在三个红线级缺陷，本项目在架构层面修复：

| # | 原问题 | 修复方式 |
|---|---|---|
| 1 | **诊断方向反转** —— `LabelEncoder` 把 `B→0/M→1`，但应用层写 `pred==0 → 恶性`，恶性被判为良性 | 全局固定标签语义：`0 = 良性/阴性`，`1 = 恶性/阳性`，训练时显式字典映射并用真实样本回归验证 |
| 2 | **数据泄漏** —— 在切分前对全量数据 `fit` 标准化器并落盘，测试指标虚高 | 用 `Pipeline(StandardScaler → Classifier)` 封装，标准化只在每折训练子集上拟合 |
| 3 | **密钥硬编码** —— DeepSeek API Key 明文写在源码里 | 全部改为环境变量注入，`.env` 入 `.gitignore`，密钥缺失时自动降级为纯本地模式 |

此外，原项目的单次划分指标被替换为 **5 折分层交叉验证** + **留出测试集**，并用 `CalibratedClassifierCV` 做概率校准，让输出的概率具备真实意义。

## 模型表现

所有指标来自留出测试集（训练全程未见）与 5 折交叉验证。

**乳腺癌模块**（WDBC，569 样本 / 30 特征）

| 算法 | 测试 AUC | 交叉验证 AUC | 灵敏度 | 特异度 |
|---|---|---|---|---|
| 逻辑回归 | 0.9944 | — | — | — |
| 随机森林 | 0.9911 | — | — | — |
| **XGBoost**（默认） | **0.9959** | 0.9935 ± 0.0046 | — | — |

**心脏病模块**（UCI Heart，303 样本 / 13 特征）

| 算法 | 测试 AUC | 交叉验证 AUC |
|---|---|---|
| 逻辑回归 | 0.9556 | — |
| **随机森林**（默认） | **0.9589** | 0.8809 ± 0.0347 |
| XGBoost | 0.9351 | — |

> 指标随数据集与随机种子变化，请以你自己训练产出的 `docs/MODEL_CARD.md` 为准。

## 快速开始

> 📖 **想直接跑起来看效果**：见 **[docs/QUICKSTART.md](docs/QUICKSTART.md)** ——
> 启动步骤 + 8 个页面的逐页检查清单（含截图与预期结果）。
>
> 🗺️ **想知道整个项目有哪些东西、各自怎么用**：见 **[docs/PROJECT_MAP.md](docs/PROJECT_MAP.md)**。
>
> 🎯 **想知道还能优化哪些地方**：见 **[docs/OPTIMIZATION_BACKLOG.md](docs/OPTIMIZATION_BACKLOG.md)** ——
> 30 条优化项（含现状证据、方案、成本、推荐组合），可按编号勾选。
>
> 🏗️ **想了解代码结构**：见 **[ARCHITECTURE.md](ARCHITECTURE.md)**。
>
> 🔬 **想了解算法与成本控制原理**：见 **[docs/TUTORIAL.md](docs/TUTORIAL.md)**。
>
> 🧪 **想跑测试 / 了解 CI**：见 **[docs/TESTING.md](docs/TESTING.md)**。

### 依赖

- Python 3.11+
- Node.js 20+

### 一键启动（Docker，推荐给第一次接触本项目的人）

```bash
cp .env.example .env        # 首次需要；密钥只在这一步之后进容器，不进镜像
docker compose up --build
```

然后打开 <http://localhost:8080>。后端在 <http://localhost:8000/docs>。

> 首次启动会下载约 470 MB 的句向量模型，之后由命名卷 `hf-cache` 缓存；
> 模型产物在**构建镜像时**从已提交的 CSV 训练出来（与 CI 行为一致），所以新克隆的仓库也能直接跑。
>
> 想改端口：改 `docker-compose.yml` 里的 `8080:80`，并同步 `CORS_ORIGINS`——
> 否则浏览器的请求会在到达应用之前就被拒掉，报错看起来却像网络问题。

### 一键启动（Windows，不用 Docker）

双击 `scripts\dev.bat`，会自动探测 Python 环境、按需训练模型、开两个窗口起前后端。

### 1. 训练模型

```bash
cd ml
pip install -r requirements.txt
python pipelines/train.py
```

产出：

```
ml/registry/registry.json          # 模型注册表（前端与后端都读它）
ml/registry/models/*.joblib        # 6 个已校准模型
docs/MODEL_CARD.md                 # 自动生成的模型卡
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env         # 按需修改
uvicorn app.main:app --reload --port 8000
```

接口文档：<http://127.0.0.1:8000/docs>

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。**首个注册的账号自动获得管理员角色。**

### 4. 跑测试（可选）

```bash
cd backend
pip install -r requirements-dev.txt
PYTHONPATH=. pytest
```

**427 个测试，约 60–90 秒**（本机实测 86 秒），其中大部分时间花在加载嵌入模型上。测试强制关闭外部 API，不会产生任何费用；外部调用链路则通过进程内传输覆盖，因此**不需要密钥也能被完整测试**。
用例分布与「每个测试在防哪个 bug」见 [`docs/TESTING.md`](docs/TESTING.md)。

## 项目结构

```
bcdx-platform/
├── frontend/                     # React 18 + TS + Vite + Tailwind
│   └── src/
│       ├── api/                  # axios 实例、统一信封解包、SSE 流式客户端
│       ├── components/           # AppShell、domain 组件、SHAP 图表、Toast
│       ├── features/             # 按页面切分：auth/dashboard/diagnosis/
│       │                         #   explain/assistant/compare/records/
│       │                         #   batch/qaCompare
│       ├── lib/                  # zustand stores、格式化工具
│       └── types/                # 与后端 schema 对齐的领域类型
├── backend/                      # FastAPI
│   ├── app/
│   │   ├── api/v1/               # auth / models / predict / rag / records
│   │   ├── core/                 # 配置、日志、错误、安全、依赖
│   │   ├── db/                   # SQLAlchemy 模型与会话
│   │   ├── ml/                   # 模型注册表加载与推理
│   │   ├── schemas/              # Pydantic v2 请求/响应模型
│   │   └── services/             # 预测编排、SHAP、LLM 网关、RAG、
│   │                             #   问答对比、数据集采样
│   ├── tests/                    # 427 个 pytest 用例
│   ├── pytest.ini
│   └── requirements-dev.txt      # 测试依赖（运行不需要）
├── ml/                           # 训练管线与模型注册表
│   ├── pipelines/train.py        # 一次运行训练两个病种 × 三个算法
│   ├── data/                     # 原始与处理后数据
│   └── registry/                 # 模型产物
├── knowledge/sources/            # 本地知识库（6 个 Markdown，50 KB）
├── scripts/                      # 便捷启动脚本
├── .github/workflows/ci.yml      # CI：后端测试 + 前端类型检查与构建
└── docs/                         # 模型卡与设计文档
```

> 逐文件的职责说明、分层规则与「想改某处该看哪个文件」的速查表，见
> **[ARCHITECTURE.md](ARCHITECTURE.md)**。

## 架构要点

### 成本控制：四道闸门

外部 LLM 调用被四道闸门约束，默认状态下**一次都不会发生**：

1. **硬开关** —— `LLM_ENABLED=false`，或密钥缺失／仍是 `.env.example` 里的占位值
2. **精确缓存** —— 归一化后的 prompt 做 SHA-256，命中直接返回
3. **语义缓存** —— 嵌入余弦相似度 ≥ 0.94 视为同一问题，但**只在同一调用点内**匹配
4. **模型也是缓存身份的一部分** —— 否则对比两个模型时，第二个根本不会被调用

前端「医学问答」页面的「调用状况」面板会实时显示外部调用次数与缓存命中率，成本完全透明。

> 第 3 条的限定条件不是细节。「本地检索增强」和「外部直答」的 cache payload 都来自同一个问题，向量相似度接近 1.0——不加限定的话，直答路径会被喂一份**检索增强的答案**，而「有检索和没检索的差别」恰恰是这个功能存在的唯一理由。

### 问答路径对比：把「省钱」的代价摆到明面上

「因为省钱所以用本地检索」只是结论的一半。**另一半是：本地路径到底牺牲了什么？**

侧栏「问答对比」页把同一个问题交给三条路径并排作答，并把差异变成可测量的列：

| 路径 | 用检索 | 外部调用 | 作用 |
|---|---|---|---|
| 本地检索增强 | ✅ | ❌ | 默认路径，成本为零，每个结论都带可核查出处 |
| 外部模型直答（无检索） | ❌ | ✅ | **幻觉基线**——完全凭参数化知识作答，没有任何出处 |
| 外部模型 + 检索增强 | ✅ | ✅ | 兼顾出处与流畅度，代价是每次调用付费 |

三条路径**共用同一次检索**，所以表里的差异只能来自"组织方式"——这正是要比较的东西。
度量包括引用条数、词面重合度、绝对化措辞、Token、费用与耗时；每个指标能说明什么、**不能**说明什么，都写在页面和 [`docs/QA_COMPARISON.md`](docs/QA_COMPARISON.md) 里。

> 默认部署没有配置 API Key，外部两列会显示为 `skipped`，费用为 `¥0`。
> 这不是失败，而是"本部署没开启付费调用"——**对比功能依然完整可用**。

### 接入大模型：8 家服务商，一条命令自检

外部路径统一走 **OpenAI 兼容接口**，所以「换服务商」本质上只是换一个 base URL 加一个模型名。
预设覆盖 DeepSeek、OpenAI、阿里云百炼、Moonshot、智谱，以及**两个不需要密钥**的选项：

| 想做什么 | 配置 |
|---|---|
| 零成本看一遍对比效果 | `LLM_ENABLED=true` + `LLM_PROVIDER=mock`（内置演示模型，不联网） |
| 用真实模型但不出本机 | `LLM_PROVIDER=ollama` + `LLM_MODEL=qwen2.5:7b` |
| 接商业服务 | `LLM_PROVIDER=deepseek` + `LLM_API_KEY=sk-...` |
| 自建 / 代理端点 | `LLM_PROVIDER=custom` + `LLM_BASE_URL`（vLLM、LM Studio、LiteLLM、One-API） |

接上之后用侧栏「问答对比」页的 **「测试连接」** 按钮验证，或者：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/llm/test -H "Authorization: Bearer $TOKEN"
```

一次 16 token 的调用，失败时给出**具体是哪一类**原因（密钥无效 / 地址少了 `/v1` /
模型名不存在 / 限流 / 欠费 / 连不上），而不是一句「调用失败」。

在同一个问题下填入多个模型名，两条外部路径会**按模型各占一列**（`llm_direct@模型名`），
检索结果对所有模型完全相同——所以列与列的差异只可能来自模型本身。

演示通道还带**故障注入**：把 `LLM_MOCK_FAULT` 设成 `quota`、`invalid_key`、`rate_limited` 等，
每次演示调用就会按该类型失败，于是那张错误分类表**可以被亲手验证**，而不必真的欠一次费。

> 完整说明含错误分类表与优先级陷阱：[`docs/LLM_INTEGRATION.md`](docs/LLM_INTEGRATION.md)。

### 知识库与切块：一个 98% 的静默 bug

嵌入模型超过窗口长度会**静默截断**，不报错。原先的切块器只用 `re.split(r"\n\s*\n")` 按空行切段，既不看标题层级、也不管长度，一段常到 250–500 字符，而模型窗口只有 128 token——拿真实 tokenizer 量过之后发现：

> **76 个片段里 75 个（98%）超过窗口，最长的 305 token。**

也就是说几乎每条知识条目的后半段都对检索不可见，日志里一行错都没有。现在的做法：

- 切块在**模型真正计数的单位**（token）上进行，窗口大小运行时从模型读取；
- 每个小节的额度会**减去它自己标题路径的 token 消耗**；
- 每切一刀都**重新测量**，不依赖"字符 ≈ token"的比例折算；
- 相邻片段带 40 字符重叠，且重叠长度会被裁剪到剩余空间以内；
- 启动时**再量一遍**每个片段，把 `oversize` 计数暴露在 `/health`——**这个数必须是 0**，CI 里有一条检查专门守着它。

检索用**片段**粒度（每个向量都完整落在窗口内），引用用**段落**粒度（相邻片段按小节拼回一段），
所以一个回答不会出现同一个标题重复三遍。

知识库现状：**6 个文件 / 约 49 KB / 84 个小节 → 190 个检索片段**（乳腺癌 80、心脏病 75、通用 35）。
内容与切块细节见 [`docs/KNOWLEDGE_BASE.md`](docs/KNOWLEDGE_BASE.md)。

### 混合检索：纯向量在缩写和人名面前是弱的

稠密向量有一个系统性盲区，而这个盲区恰好落在这份语料的强项上：**缩写、数字、人名几乎不携带语义质量**。句向量把「Youden 指数」编码成一个靠近"统计学指标"的模糊位置，排序就飘到措辞最像的那一页去了。BM25 的偏差正好相反——它只认这个词出现过没有。

所以现在两路并行，再用 **RRF**（Reciprocal Rank Fusion，`k=60`）融合。两个设计决定值得说明：

- **BM25 是自己写的，不是引依赖。** 三十行公开公式，但它**必须**和词法拒答闸门共用同一个分词器；引库就会有两套分词，两个"词法信号"对同一段文本给出不同判断。
- **融合吃排名，不吃分数。** BM25 无上界、余弦在 `[-1,1]`，加权求和需要一个没人验证过、还会随语料漂移的归一化系数。RRF 不需要标定——这也是 `RAG_MIN_SIMILARITY` 无需重新校准的原因：它是余弦阈值，而检索返回的第二个元素仍然是**原始余弦**。

实测（`_tools/eval_retrieval.py`，15 个探针 + 4 个反向探针，期望小节全部从语料里查出来而非手写）：

| 模式 | hit@1 | 进 top-5 | 误拒答 | 平均耗时 |
|---|---|---|---|---|
| `dense`（旧行为） | 9/15 | 12/15 | **4** | ~24 ms |
| `hybrid`（默认） | **13/15** | 13/15 | **0** | ~25 ms |
| `hybrid+rerank` | 13/15 | 15/15 | 0 | ~2241 ms |

修好的正是那 4 个**被拒答**的问题（`Youden 指数`、`约登指数`、`数据泄漏`、`房颤`），代价约 1 毫秒。重排（CrossEncoder）已接好但**默认关闭**：它买到两格 top-5、**top-1 一格没变**，而延迟涨到约 **90 倍**——本地路径是本项目承诺"快且零成本"的那条路，让它比被对照的真实模型调用还慢是看得见的倒退。一行配置即可打开。

原理、实测与配置见 [`docs/KNOWLEDGE_BASE.md`](docs/KNOWLEDGE_BASE.md) §4。

### RAG 拒答：三道闸门

朴素向量检索会把「今天天气怎么样」匹配到心肌梗死词条。本项目用三道闸门依次判定：

| 闸门 | 条件 | 拒答方式 |
|---|---|---|
| **病种闸门** | 问题里出现**其他病种**的关键词 | 定制文案：说明超出范围 + 指引切换模块 |
| **语义闸门** | 命中里**最高的原始余弦** < 0.30 | 通用兜底 |
| **词法闸门** | **排第一的那个片段**的问题 token 覆盖率 < 12% | 通用兜底 |

两个数值的取法看起来不对称，是刻意的：语义闸门取"命中里最高"，因为词法提升会把一个余弦偏低但关键词命中的片段合法地顶到第一；词法闸门只读 `hits[0]`，因为要作答的正是它。实测若把覆盖率也改成取最大值，上面那 4 个问题会**不再被拒答，而是被自信地答以错误的小节**——误拒答可见、可修，误答隐形。

病种闸门排在最前，因为**当医学词汇高度重合时，"问题提到了另一个病种"是唯一可靠的信号**。
同时每个知识片段带 `disease` 标签，检索时按病种过滤（在**融合之前**，否则 BM25 会把别的病种捞回来），避免跨病种串味。

### 可解释性

`shap.TreeExplainer` / `LinearExplainer` 的输出被归一化为结构化 JSON，前端用原生 SVG 绘制发散条形图。基准值、每项贡献的方向与幅度全部可读，并在多算法对比页面中横向并列 —— 当判定一致但归因分歧时，说明该结论对模型选择敏感。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/auth/register` | 注册（首个用户为管理员） |
| `POST` | `/api/v1/auth/login` | 登录，返回 JWT |
| `GET` | `/api/v1/auth/me` | 当前用户 |
| `GET` | `/api/v1/models` | 全部病种模块与模型指标（**公开**） |
| `GET` | `/api/v1/models/{disease}` | 单个病种详情（含特征 schema） |
| `POST` | `/api/v1/predict` | 单样本预测 + SHAP 归因 |
| `POST` | `/api/v1/predict/batch` | 批量预测（最多 500 行，返回冠军阈值） |
| `GET` | `/api/v1/predict/samples` | 从公开数据集抽取的真实样本（批量页的演示数据） |
| `POST` | `/api/v1/rag/ask` | 知识库问答 |
| `POST` | `/api/v1/rag/ask/stream` | 流式问答（SSE） |
| `GET` | `/api/v1/rag/sources` | 知识库覆盖范围（**公开**） |
| `POST` | `/api/v1/rag/compare` | **问答路径对比**，可选 `models` 做多模型并排 |
| `GET` | `/api/v1/rag/comparisons` | 对比历史（当前用户） |
| `GET` | `/api/v1/rag/comparisons/{id}` | 单次对比全文 |
| `DELETE` | `/api/v1/rag/comparisons/{id}` | 删除一次对比 |
| `GET` | `/api/v1/records` | 预测历史（分页/筛选） |
| `GET` | `/api/v1/records/stats` | 个人统计 |
| `GET` | `/api/v1/rag/usage` | LLM 用量与缓存透明度 |
| `GET` | `/api/v1/llm/providers` | 公开的服务商目录（含价格与控制台链接） |
| `GET` | `/api/v1/llm/status` | 当前生效的服务商、模型、密钥（打码）与最近错误 |
| `POST` | `/api/v1/llm/test` | **连通性自检**：一次极小调用，失败时区分六类原因 |
| `GET` | `/api/v1/meta/limits` | 运行限额（**公开**） |
| `GET` | `/health` | 健康检查，含切块统计 `rag_chunking`（**公开**） |

响应统一为信封格式：

```json
{ "code": 0, "message": "ok", "data": { }, "request_id": "a1b2c3d4" }
```

> 例外：`/` 与 `/health` 返回裸对象（运维端点，不参与前端解包）。`/api/v1` 下的**所有**路由都走信封——
> `test_app.py` 里有一条断言守着这件事，它曾经抓出 `/api/v1/meta/limits` 返回裸 body 的问题。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `SECRET_KEY` | dev 占位值 | **生产环境必须替换** |
| `DATABASE_URL` | `sqlite+pysqlite:///./bcdx.db` | 数据库连接串 |
| `LLM_ENABLED` | `false` | 外部 LLM 总开关 |
| `LLM_PROVIDER` | `deepseek` | 服务商预设：`deepseek`/`openai`/`qwen`/`moonshot`/`zhipu`/`ollama`/`mock`/`custom` |
| `LLM_API_KEY` | 空 | 留空则纯本地运行（外部路径返回 `skipped`）；`ollama` 与 `mock` 无需密钥 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | **仅在 `LLM_PROVIDER=custom` 时生效**，用于 vLLM / LM Studio / LiteLLM 等自建端点 |
| `LLM_MODEL` | `deepseek-chat` | 模型名，可覆盖任意服务商的默认模型 |
| `LLM_MAX_COMPARE_MODELS` | `3` | 一次对比最多并排几个模型（每个模型 = 2 次付费调用） |
| `LLM_MOCK_FAULT` | 空 | **只作用于 `LLM_PROVIDER=mock`**：让演示调用按指定类型失败，用来亲手复现错误分类。真实服务商忽略它 |
| `LLM_MIN_CHARS_FOR_CALL` | `150` | 上下文短于此值则跳过检索增强调用 |
| `LLM_PRICE_PROMPT_PER_1K` | `0.002` | 仅用于费用估算 |
| `LLM_PRICE_COMPLETION_PER_1K` | `0.008` | 仅用于费用估算 |
| `RAG_TOP_K` | `5` | 检索片段数（三路径共用一次检索） |
| `RAG_HYBRID_ENABLED` | `true` | 稠密检索与 BM25 用 RRF 融合。置 `false` 可复现旧的纯向量排序（含 4 个误拒答） |
| `RAG_RRF_K` | `60` | RRF 常数，取原论文值 |
| `RAG_RETRIEVE_CANDIDATES` | `20` | 融合后交给重排的候选数；**这是延迟的杠杆** |
| `RAG_RERANK_ENABLED` | `false` | CrossEncoder 重排。默认关是实测结论：约 90× 延迟、top-1 无收益 |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-base` | 重排模型，开启后首次运行需下载约 1.1 GB |
| `RAG_MIN_SIMILARITY` | `0.30` | 语义闸门阈值（读**原始余弦**，不读融合分） |
| `RAG_MIN_TOKEN_COVERAGE` | `0.12` | 词法闸门阈值（只读排第一的片段） |
| `RAG_CHUNK_MAX_CHARS` | `160` | **仅在 tokenizer 不可用时的退化预算** |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | 换模型时窗口大小会自动重新读取 |
| `QA_COMPARE_ALLOW_LLM` | `true` | 置 `false` 则对比只跑本地路径 |
| `QA_COMPARE_MAX_QUESTION_CHARS` | `300` | 对比时的问题截断长度 |

完整清单见 [`.env.example`](.env.example)（含中文注释）。

## 安全与隐私

- 口令使用 bcrypt 散列，从不落库明文
- JWT HS256，默认 24 小时有效期
- 逐用户数据隔离，访问他人记录返回 403
- 统一错误信封不泄露堆栈
- 安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`
- 每个请求带 `X-Request-ID`，便于链路追踪
- 数据库**不存储**任何可直接识别个人身份的信息

## 工程化与测试

| 项 | 状态 |
|---|---|
| 后端自动化测试 | **427 个 pytest 用例**，约 60–90 秒跑完，全部通过 |
| 前端自动化测试 | **39 个 Vitest 用例**（`npm run test`），覆盖统一响应信封、错误文案降级链、SSE 流式解析、错误边界与格式化工具 |
| 前端类型检查与构建 | `npm run typecheck` / `npm run build`（CI 中强制） |
| 一键部署 | `docker compose up --build`（后端多阶段构建 + 前端 node→nginx，含健康检查与数据卷） |
| 持续集成 | GitHub Actions：后端测试 + 前端构建，两个独立 job |
| 响应信封一致性 | 有断言覆盖——`/api/v1` 下所有路由必须走统一信封，**包括 422**（`RequestValidationError` 要显式注册，否则它自带的 handler 会绕开信封） |
| 错误信息可操作 | 校验失败时 `message` 会**点名出错字段**（如 `Validation failed: password — Value error, Password must mix letters and digits`），而不是笼统的"请求失败"；前端按 `message → detail → 超时 → 连不上` 逐级降级 |
| 切块窗口约束 | `oversize` 必须是 0，`/health` 暴露，CI 前置检查 + 测试双重守着 |
| 模型产物可复现 | 训练全程固定随机种子，重跑后 `registry.json` 除时间戳外逐字节一致 |

这份测试的重点不是"证明代码能跑"，而是"证明某类错误不会再回来"。用例分布与**逐条回归清单**（每个测试在防哪个真实踩过的坑）见 [`docs/TESTING.md`](docs/TESTING.md)。

> CI 会从仓库里已提交的原始 CSV **重新训练**模型产物（`ml/registry/models/*.joblib` 不入库），
> 因此 CI 同时验证了训练管线本身仍然可用。

## 数据来源

两个数据集都是公开数据集，可自由使用：

- **乳腺癌**：Wisconsin Diagnostic Breast Cancer (WDBC) —— UCI Machine Learning Repository
- **心脏病**：UCI Heart Disease Dataset (Cleveland)

## 免责声明

⚠️ **本平台是科研与教学演示原型，不是医疗器械，未经过任何监管审批。**

模型输出反映的是群体统计规律，**不能作为个体诊断依据**，不能替代执业医师的专业判断。任何健康问题请携带完整检查报告咨询正规医疗机构。

## 许可

[MIT](LICENSE)
