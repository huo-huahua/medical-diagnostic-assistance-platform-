# 文件架构说明

> BC-Dx Platform · 全栈目录结构与文件职责
> 最后更新：2026-10-04

---

## 1. 顶层视图

```
毕设优化/
├── bcdx-platform/          ← 全新产品仓库（本次交付物）
└── cp16/                   ← 原始毕业设计（只读参考，已冻结）
```

| 目录 | 性质 | 说明 |
|---|---|---|
| `bcdx-platform/` | **交付物** | 从 0 重建的全栈产品，可直接开源 |
| `cp16/` | 参考资料 | 原毕设代码。保留用于对照，**不参与构建**，可随时归档删除 |

> 两者的差异（三大红线缺陷修复）见 `bcdx-platform/README.md`。

---

## 2. bcdx-platform 完整结构

```
bcdx-platform/
│
├── README.md                          项目说明（含修复对比表、模型表现、API 表）
├── ARCHITECTURE.md                    本文档：目录结构与文件职责
├── LICENSE                            MIT + 医疗用途附加声明
├── .gitignore                         忽略规则（密钥/数据库/模型产物/构建输出/测试产物）
├── .env                               本地配置（已 gitignore，含 SECRET_KEY）
├── .env.example                       配置模板（可提交）
│
├── .github/workflows/ci.yml           CI：后端测试 + 前端类型检查与构建
├── frontend/                          ── 前端：React 18 + TS + Vite 6 + Tailwind
├── backend/                           ── 后端：FastAPI + SQLAlchemy（含 tests/）
├── ml/                                ── 机器学习：训练管线与模型产物
├── knowledge/                         ── 知识库：RAG 检索语料
├── docs/                              ── 文档：模型卡与专题文档
├── scripts/                           ── 脚本：一键启动
└── _tools/                            ── 开发工具（截图脚本，非运行时）
```

---

## 3. frontend/ — 前端

```
frontend/
├── package.json                       依赖与 npm 脚本
├── package-lock.json                  锁定版本（提交）
├── vite.config.ts                     构建配置 + /api → 127.0.0.1:8000 代理
├── tsconfig.json                      TS 配置（含 @ → ./src 路径别名）
├── tsconfig.node.json                 Vite 配置文件的 TS 配置
├── tailwind.config.js                 设计系统：色板/阴影/动画/透明度档
├── postcss.config.js                  PostCSS（Tailwind + Autoprefixer）
├── index.html                         HTML 入口（深色主题、中文标题）
└── src/
    ├── main.tsx                       应用入口：路由、Provider、BootGate 会话恢复
    ├── types/index.ts                 领域类型（与后端 Pydantic schema 一一对应）
    ├── api/index.ts                   HTTP 层：axios 实例、token 存储、统一信封解包、
    │                                  SSE 流式客户端、全部 API 方法
    ├── lib/
    │   ├── store.ts                   Zustand 状态：useAuth / useWorkspace / useUi
    │   └── format.ts                  格式化：百分比、日期、置信度元数据、算法标签
    ├── styles/index.css               全局样式 + 组件层（panel/btn/chip/field/skeleton）
    ├── components/
    │   ├── AppShell.tsx               应用外壳：侧边栏、病种切换、用户菜单、移动导航
    │   ├── ui.tsx                     通用原语：Panel / StatCard / EmptyState / Skeleton
    │   ├── domain.tsx                 领域组件：VerdictHero / ProbabilityDial /
    │   │                              MetricsStrip / RangeWarnings / VerdictBadge
    │   ├── ContributionChart.tsx      SHAP 归因可视化（原生 SVG 发散条形图）+ TopDrivers
    │   └── Toast.tsx                  全局提示（Provider + useToast）
    └── features/                      按页面切分，每页一个目录
        ├── auth/LoginPage.tsx         登录 / 注册
        ├── dashboard/DashboardPage.tsx 总览：统计卡、病种卡片、缓存环形图、AUC 柱状图
        ├── diagnosis/DiagnosisPage.tsx 智能诊断：指标输入 + 判定 + SHAP 归因
        ├── batch/BatchPage.tsx        批量评估：CSV 解析（支持中文列名）、真实样本载入、
        │                              阈值标注直方图、逐行判定与一致性、CSV 导出
        ├── explain/ExplainPage.tsx    可解释分析：多算法归因对比 + 分歧检测
        ├── assistant/AssistantPage.tsx 医学问答：SSE 流式 + 引用折叠 + 拒答提示
        ├── qaCompare/QaComparePage.tsx 问答对比：三路径指标表 + 多模型输入 + 度量口径说明 + 历史
        ├── llm/LlmPanel.tsx           外部模型连接：状态胶囊 / 字段网格 / 8 家服务商目录 / 探活自检
        ├── compare/ComparePage.tsx    模型对比：雷达图 / 稳定性 / 指标表 / 混淆矩阵
        └── records/RecordsPage.tsx    历史记录：筛选 / 分页 / CSV 导出 / 详情抽屉
```

**约定**
- `features/` 每个子目录 = 一个路由页面，页面内部再拆组件
- 跨页面复用的东西放 `components/`，纯函数工具放 `lib/`
- 所有类型集中在 `types/index.ts`，不散落
- 路由在 `main.tsx` 注册，侧栏导航在 `components/AppShell.tsx` 的 `NAV` 数组里——**两处都要改**

> `qaCompare/QaComparePage.tsx` 里有一张声明式的 `METRICS` 表：每一行是「标签 + 取值函数 + 说明」，
> 同一行会被施加到**所有**路径上。加指标只需加一行，不会出现"某一列忘了算"的情况。后端有对应的
> 断言（`test_metrics_are_present_on_every_path`）守着这件事。

---

## 4. backend/ — 后端

```
backend/
├── requirements.txt                    Python 运行依赖
├── requirements-dev.txt                测试依赖（pytest / pytest-cov / httpx）
├── pytest.ini                          pytest 配置与标记（slow / integration）
├── tests/                              427 个用例，见 docs/TESTING.md
│   ├── conftest.py                     环境变量前置、会话级 fixture、一次性数据库、
│   │                                   每测试一个全新 LLM 网关（见 TESTING.md §4.6）
│   ├── test_llm_providers.py           服务商目录/解析优先级/错误分类/演示通道/多模型（146）
│   ├── test_rag.py                     分词/段落合并/拒答闸门/检索范围/混合检索真实语料回归（52）
│   ├── test_qa_compare.py              三路径编排/度量/落库/越权/多模型列（42）
│   ├── test_auth.py                    注册/登录/JWT/账号隔离（41）
│   ├── test_gateway.py                 归一化/缓存/硬开关/限流器（36）
│   ├── test_predict.py                 标签语义/阈值/批量预测/真实抽样（34）
│   ├── test_retrieval.py               BM25 与 RRF 单元测试、合成语料复现稠密失败、重排降级（30）
│   ├── test_app.py                     健康检查/限额/信封/OpenAPI/默认密钥（26）
│   └── test_chunking.py                切块结构与窗口约束（16）
└── app/
    ├── main.py                        应用装配：lifespan 预热、中间件、异常处理、路由挂载、
    │                                  生产环境拒启于占位 SECRET_KEY
    │
    ├── api/v1/                        路由层（HTTP 边界，只做参数校验与编排）
    │   ├── auth.py                     注册 / 登录 / 当前用户
    │   ├── models.py                   病种模块与模型指标
    │   ├── predict.py                  单样本 / 批量预测 / 真实样本抽样
    │   ├── rag.py                      问答（含 SSE 流式）、会话、知识源、用量、
    │   │                               三路径对比与历史
    │   ├── llm.py                      服务商目录（公开）/ 连接状态 / 探活自检
    │   └── records.py                  预测历史、统计、详情、删除
    │
    ├── core/                          横切关注点
    │   ├── config.py                   pydantic-settings 配置（读 .env）+ 占位密钥检测
    │   ├── security.py                 bcrypt 口令散列 + JWT 签发/校验
    │   ├── deps.py                     依赖注入：get_current_user、限流器
    │   ├── errors.py                   业务异常 + 错误码分段（1xxx–5xxx）
    │   └── logging.py                  JSON 结构化日志、request_id 上下文
    │
    ├── db/                            持久化
    │   ├── session.py                  Engine / SessionLocal / get_db
    │   └── models.py                   User / PredictionRecord / Conversation /
    │                                   Message / LlmUsage / AuditLog / QaComparison
    │
    ├── schemas/__init__.py            Pydantic v2 请求/响应模型 + 统一信封
    │
    ├── ml/
    │   └── registry.py                模型注册表：加载 joblib、推理、置信度分档
    │
    └── services/                      业务逻辑（可测试、不碰 HTTP）
        ├── prediction.py              预测编排：推理 + SHAP + 可选叙述 + 落库
        ├── explainer.py               SHAP 归因：拆解 CalibratedClassifierCV 包装、
        │                              归一化多形态输出、缓存 explainer
        ├── llm_providers.py           8 家服务商目录 + 解析优先级 + 错误分类 +
        │                              密钥脱敏（OpenAI 兼容协议做统一适配层）
        ├── llm_mock.py                离线演示通道：httpx.MockTransport 换掉 socket，
        │                              真实 SDK 照常运行，无密钥/无网络/零成本
        ├── llm_gateway.py             成本控制核心：四道闸门（硬开关/精确缓存/语义缓存/
        │                              模型入缓存身份）+ 16 类错误分类 + 探活
        ├── rag_service.py             本地 RAG：token 感知切块、疾病标注、FAISS 稠密检索
        │                              + 自实现 BM25 两路召回、RRF 融合、可选 CrossEncoder
        │                              重排、三道闸门拒答、段落合并、模板作答
        ├── qa_compare.py              三路径问答对比：路径目录、度量函数、编排与汇总
        └── datasets.py                从公开数据集按标签均衡抽真实样本
```

**分层规则**
```
api/  →  services/  →  ml/ + db/
  ↑          ↑
schemas/   core/
```
- `api/` 只做「解析请求 → 调 service → 包信封返回」
- 业务逻辑必须在 `services/`，便于单测
- `core/` 不反向依赖 `api/` 或 `services/`
- `tests/` 只依赖 `app/`，通过 `TestClient` 走 HTTP 边界；**不 mock 业务逻辑**，只 mock 外部网络

> 新增业务逻辑时，把可测的部分放进 `services/`。`rag_service` 的切块与 `qa_compare` 的度量函数
> 都是纯函数，因此能在毫秒级的单元测试里覆盖，不必启动应用（见 `docs/TESTING.md` §2）。

---

## 5. ml/ — 机器学习

```
ml/
├── requirements.txt                    训练侧依赖
├── pipelines/
│   └── train.py                        训练管线（约 550 行，一次运行完成全部训练）
├── data/
│   └── raw/                            原始公开数据集（只读，不修改）
│       ├── wdbc_raw.csv                WDBC 乳腺癌 569×31
│       ├── breast_cancer_variables_readable.txt  特征对照表（英文名 → 中文名）
│       ├── heart_features.csv          UCI Heart 特征 303×13
│       └── heart_targets.csv           UCI Heart 标签 303×1
└── registry/                           模型注册表（后端与前端都读这里）
    ├── registry.json                   元数据：指标、阈值、特征 schema、默认值
    └── models/                         6 个已校准模型
        ├── breast_{lr,rf,xgb}_v1.0.joblib
        └── heart_{lr,rf,xgb}_v1.0.joblib
```

**train.py 做了什么**（一次运行 ≈ 24 秒）
1. 加载两个数据集，显式固定标签语义 `0=良性/阴性`、`1=恶性/阳性`
2. 构建 `Pipeline(StandardScaler → Classifier)` —— 标准化只在每折训练子集拟合
3. 5 折分层交叉验证 + 留出测试集
4. `CalibratedClassifierCV` 概率校准（乳腺 isotonic / 心脏 sigmoid）
5. Youden's J 确定判定阈值
6. 选出各病种 champion，写入 `registry.json` 与 6 个 `.joblib`
7. 生成 `docs/MODEL_CARD.md`

> `registry/models/*.joblib` 已加入 `.gitignore`（体积大、可复现）。克隆后跑一次 `train.py` 即可生成。

---

## 6. knowledge/ — 知识库

```
knowledge/
├── sources/                            检索语料（Markdown / 纯文本，按标题切块）
│   ├── breast_cancer_zh.md             乳腺癌 23 小节 · 61 片段
│   ├── breast_imaging_zh.md            乳腺影像与检查流程 9 小节 · 19 片段
│   ├── heart_disease_zh.md             心脏病 22 小节 · 52 片段
│   ├── cardiac_exam_zh.md              心脏检查项目 10 小节 · 23 片段
│   ├── model_literacy_zh.md            模型素养（AUC/阈值/校准等）12 小节 · 25 片段
│   └── disclaimer_zh.md                免责与使用限制 8 小节 · 10 片段
└── _archive/                           已归档的重复文件 + 归档原因说明
```

共 **6 个源文件 / 约 49 KB / 84 个小节 → 190 个检索片段**，启动时自动构建 FAISS 稠密索引与 BM25 稀疏索引。

**关键约定**：文件名决定疾病归属。`_infer_disease()` 按文件名子串匹配：

| 文件名包含 | 归属 |
|---|---|
| `breast` | `breast` |
| `heart` / `cardiac` | `heart` |
| `disclaimer` | `general` |
| 其他 | `general` |

也可以在文件顶部用 `---` front matter 显式覆盖（`disease: heart`），front matter 会被剥离，不会进入可检索正文。

**切块在 token 单位上进行**，窗口大小运行时从嵌入模型读取（当前 `128 → 124`）。
启动时会复核每个片段并把 `oversize` 计数暴露到 `/health`——**这个数必须是 0**。
内容清单、切块算法与拒答闸门的完整说明见 [`docs/KNOWLEDGE_BASE.md`](docs/KNOWLEDGE_BASE.md)。

---

## 7. docs/ 与 scripts/

```
docs/
├── MODEL_CARD.md                       模型卡（由 train.py 自动生成，勿手改）
├── QUICKSTART.md                       启动与 8 个页面的逐页检查清单
├── TUTORIAL.md                         后端技术教程
├── KNOWLEDGE_BASE.md                   知识库内容、切块策略、拒答闸门
├── QA_COMPARISON.md                    三路径问答对比的设计与度量口径
├── LLM_INTEGRATION.md                  大模型接入：8 家服务商、优先级、探活、错误分类、多模型
├── TESTING.md                          测试与 CI、逐条回归清单
├── OPTIMIZATION_BACKLOG.md             30 条优化项与状态
├── PROJECT_MAP.md                      全局总览与使用索引
└── screenshots/                        18 张真实前端截图（含平板/手机档）

scripts/
├── dev.bat                             Windows 一键启动（自动检查/训练模型）
└── dev.sh                              Unix 一键启动（含健康检查）

_tools/
├── shoot-new-pages.cjs                 Puppeteer 截图脚本，桌面 1680×1050（开发者手动运行）
└── shoot-responsive.cjs               Puppeteer 截图脚本，平板/手机档 + 布局断言

.github/workflows/
└── ci.yml                              后端测试 + 前端类型检查与构建
```

---

## 8. 已清理的临时文件

本次删除的内容，均为空目录或可再生成的临时产物：

| 路径 | 类型 | 删除理由 |
|---|---|---|
| `assets/` | 空目录 | 骨架遗留，从未使用 |
| `infra/` | 空目录 | 原计划放 Docker Compose，当前未使用 |
| `ml/data/processed/` | 空目录 | 训练脚本不使用该路径 |
| `frontend/src/hooks/` | 空目录 | 未产出自定义 hook |
| `frontend/src/locales/` | 空目录 | 未做国际化 |
| `frontend/dist/` | 构建产物 | `npm run build` 可再生成 |
| `backend/bcdx.db` | 运行时数据库 | 含测试账号，首次启动自动重建 |

> `bcdx.db` 删除后，下次启动后端会自动建表。**首个注册的账号将获得管理员角色**。
> 演示账号 `demo@bcdx.dev` / `demo12345` 也随之失效，需重新注册或重新创建。

---

## 9. 启动后的运行时产物

这些文件在运行时会自动出现，均已在 `.gitignore` 中：

| 路径 | 何时生成 |
|---|---|
| `backend/bcdx.db` | 后端首次启动 |
| `frontend/dist/` | 执行 `npm run build` |
| `frontend/node_modules/` | 执行 `npm install` |
| `backend/app/**/__pycache__/` | Python 导入模块时 |
| `.vite/` | 前端开发服务器缓存 |
| `<系统临时目录>/bcdx_pytest_<pid>.db` | 跑 pytest 时创建，结束时删除（放仓库外，清理被拦也不会留脏文件） |
| `backend/.pytest_cache/`、`.coverage`、`htmlcov/` | 跑测试 / 覆盖率时生成 |

---

## 10. 文件职责速查

| 我想改… | 去看 |
|---|---|
| 页面布局 / 视觉 | `frontend/src/features/<页面>/`、`frontend/tailwind.config.js` |
| 调接口 | `frontend/src/api/index.ts` |
| 全局状态 | `frontend/src/lib/store.ts` |
| 加新接口 | `backend/app/api/v1/` + `backend/app/schemas/__init__.py`，**并往 `tests/test_auth.py` 的受保护路由清单补一行** |
| 改业务逻辑 | `backend/app/services/` |
| 换模型 / 调参 | `ml/pipelines/train.py`，重跑生成 registry |
| 加医学知识 | `knowledge/sources/*.md`（文件名带病种关键词），见 `docs/KNOWLEDGE_BASE.md` |
| **调切块策略** | `backend/app/services/rag_service.py` 的 `parse_markdown_chunks` / `Budget` / `_clamp`；改完必须跑 `pytest tests/test_chunking.py` |
| **改拒答策略** | `backend/app/services/rag_service.py` 的 `_DISEASE_TERMS`、`compose_local_answer` 与 `.env` 里的两个阈值 |
| **改问答对比的度量** | `backend/app/services/qa_compare.py`；加指标时记得同步前端 `QaComparePage.tsx` 的 `METRICS` |
| **改批量预测口径** | `backend/app/api/v1/predict.py` 的 `predict_batch`（阈值从冠军模型取，**不要写死 0.5**） |
| **改归因展示** | `frontend/src/components/ContributionChart.tsx` |
| **控制 API 成本** | `backend/app/services/llm_gateway.py` + `.env` 中 `LLM_ENABLED` / `LLM_API_KEY`；四道闸门见 `README.md` |
| **换 / 接一家大模型** | `backend/app/services/llm_providers.py` 的 `PROVIDERS` 表；环境变量优先级与那个 401 陷阱见 `docs/LLM_INTEGRATION.md` |
| **调大模型错误提示** | `llm_providers.py` 的 `classify_error` / `explain_error`；想在运行中复现某类错误，用演示通道的 `LLM_MOCK_FAULT` |
| **加 / 改测试** | `backend/tests/`；先读 `docs/TESTING.md` 的回归清单，避免重复覆盖 |
| **改 CI** | `.github/workflows/ci.yml`；本地跑 `cd backend && PYTHONPATH=. pytest` 对齐 |
