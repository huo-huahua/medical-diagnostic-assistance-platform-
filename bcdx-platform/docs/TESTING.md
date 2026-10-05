# 自动化测试与持续集成

> **427 个测试，一次运行约 60–90 秒，全部通过。**（本机实测 86 秒；跑之前先确认没有别的
> 重活在同机争 CPU —— 同一个套件在负载下能跑到 1.5 分钟以上，**别拿那种耗时当基准**。）
> 对应优化项 [`OPTIMIZATION_BACKLOG.md`](OPTIMIZATION_BACKLOG.md) 第 1 条（自动化测试）、第 2 条（CI 流水线）、
> 第 8 条（默认密钥校验）与第 15 条（混合检索 + 重排）。

这份文档不只是"怎么跑测试"，更重要的是**每个测试在防哪个 bug**——因为这里的绝大多数测试都不是为了证明代码能跑，而是为了证明**某类错误不会再回来**。

---

## 一、怎么跑

```bash
cd backend
PYTHONPATH=. pytest
```

Windows 上要指定有依赖的解释器：

```bash
cd C:\Users\ASUS\Desktop\毕设优化\bcdx-platform\backend
set PYTHONPATH=.
C:\Users\ASUS\anaconda3\python.exe -m pytest
```

常用变体：

```bash
pytest -v                                   # 逐条打印
pytest -q                                   # 安静模式
pytest tests/test_chunking.py               # 单文件
pytest -k "refusal or threshold"            # 按名字筛
pytest -m "not slow"                        # 跳过需要真实模型的用例
pytest --cov=app --cov-report=term-missing  # 覆盖率（需装 requirements-dev）
```

首次运行明显更慢，其中大部分花在加载嵌入模型（约 40 秒）和 6 个模型产物上——这是会话级只做一次的固定开销。

> **不会花一分钱外部 API 费用。** `tests/conftest.py` 在导入配置之前就强制设置了 `LLM_ENABLED=false` 且清空密钥，网关的硬开关会让所有外部路径直接返回 `skipped`。
>
> 那"外部路径"到底测了什么？靠**演示通道**。`test_llm_providers.py` 里的用例把 `LLM_PROVIDER` 切到 `mock`，
> 此时 `httpx.MockTransport` 替换掉的只是 socket —— OpenAI SDK 的序列化、重试、错误映射全部照常执行，
> 所以 token 记账、成本估算、缓存与错误分类都是**真的在跑**，只是没出网、没花钱。真实密钥的端到端验证
> 仍然只在人工/演示流程里做（见 [`LLM_INTEGRATION.md`](LLM_INTEGRATION.md)）。

---

## 二、测试分布

| 文件 | 用例数 | 覆盖什么 |
|---|---:|---|
| `tests/test_llm_providers.py` | 146 | 服务商目录与不变量、解析优先级、密钥脱敏、16 类错误分类、演示通道传输、网关多模型与缓存作用域 |
| `tests/test_rag.py` | 52 | 分词、段落合并、三道拒答闸门、问候语、检索范围隔离、HTTP 接口、**混合检索在真实语料上的回归** |
| `tests/test_qa_compare.py` | 42 | 三路径编排、度量函数、费用估算、问候语、落库与越权、多模型列 |
| `tests/test_auth.py` | 41 | 注册 / 登录 / JWT / 账号隔离 / 禁用账号 / 免枚举 / 受保护路由清单 |
| `tests/test_gateway.py` | 36 | 归一化、哈希键、LRU 缓存、语义缓存、硬开关、调用路径、限流器 |
| `tests/test_predict.py` | 34 | 标签语义、冠军阈值、单样本与批量预测、真实样本抽样 |
| `tests/test_retrieval.py` | 30 | **BM25 与 RRF 的单元测试**；用合成语料 + 桩编码器复现"稠密必错、混合修正"；重排的接入与优雅降级 |
| `tests/test_app.py` | 30 | 健康检查、切块统计、运行限额、响应信封（含 422）、校验错误的 JSON 可序列化、鉴权与校验的先后次序、OpenAPI、默认密钥校验 |
| `tests/test_chunking.py` | 16 | 切块结构、窗口约束、重叠回归、真实知识库集成 |
| **合计** | **427** | |

测试分两层：

- **单元层**（`test_gateway.py`、`test_llm_providers.py`、`test_chunking.py` 的大部分）：不启动应用，毫秒级，跑得快；
- **集成层**（其余）：通过 `TestClient` 走完整的 FastAPI 栈，标记为 `integration`。

```bash
pytest -m integration    # 只跑集成测试
pytest -m slow           # 只跑需要真实嵌入模型的用例
```

---

## 三、回归清单：每个测试在防什么

这一节是这份文档的核心。下表里的每一行，都是本项目**真实踩过**的坑。

### 3.1 切块与检索（`test_chunking.py` / `test_rag.py`）

| 曾经的 bug | 症状 | 现在由谁守着 |
|---|---|---|
| **嵌入静默截断** | 原切块只按空行切分（`re.split(r"\n\s*\n", raw)`），不识别标题也不控长度。76 个片段里 75 个（**98%**）超过 128 token 窗口，最长的 305 token。条目尾部对检索完全不可见，且**不报任何错** | `TestRealKnowledgeBase::test_every_real_chunk_fits_the_real_window`——拿**真实 tokenizer** 量**真实知识库** |
| 重叠在放得下判定**之后**才拼接 | 一个刚通过检查的片段被重叠顶回超限（实测 5 个片段卡在 127–141 token） | `test_overlap_is_trimmed_when_the_unit_leaves_no_room` |
| `_split_oversized` 在 token 模式下把 `limit` 当**字符数**用 | 硬切时越界 | 删掉该路径，统一走"每刀重新测量"的 `_clamp`；`test_no_chunk_exceeds_the_budget` 在 40/60/90/140 四个额度上验证 |
| 小节太短产生碎片 | 大量噪声片段挤占检索名额 | `test_short_sections_are_merged`（并断言被吞掉的标题文字仍在正文里） |
| **跨病种问题检索为空** | 过度取回上限 20 被同语料占满，病种过滤后**一个候选都不剩** → 定制越界提示**永远显示不出来**，只给通用兜底 | `TestRetrievalScope::test_scoped_search_never_returns_another_disease_modules_chunks` + `test_cross_disease_question_reaches_the_tailored_refusal`。前者早先断言的是"所有命中都属于当前病种"，**比设计更严**——`general` 语料本来就是每个病种都可用的，它一直通过只是因为没有通用片段进过 top-5。一条**靠运气通过**的测试比没有测试更糟 |
| 切细后答案重复同一标题 | 一个回答里同一标题出现 3 遍 | `TestGroupPassages` 一组用例：兄弟片段合并、排名不变、合并后打标签 |
| 拒答闸门失效 | 语义很接近但词汇完全无关的问题被作答 | `test_weak_lexical_overlap_is_refused`、`test_weak_semantic_match_is_refused` |
| 问候语被当成无法回答的问题 | 对「你好」回"没有检索到相关内容，请前往医院就诊" | `test_greeting_is_answered_without_a_refusal` 及其变体，且断言「你好，乳腺癌怎么筛查」**不会**被误判为问候 |
| 问候语仍走完整链路 | 为一句"你好"白跑一次嵌入检索、给 UI 一串无关的"出处"，且 `use_llm=true` 时**会触发一次付费外部调用** | 在**检索之前**短路；`test_a_greeting_is_labelled_as_such` 断言 `source == "greeting"`、引用为空；`test_a_greeting_is_not_reported_as_ungrounded` 断言问候语不计入 `ungrounded_paths` |
| **纯向量检索把 4 个有据可查的问题拒答了** | 「Youden 指数是怎么用的」被 dense 排到第一的是《概率校准与布里尔分数》——一个**内容词都不重合**的小节（余弦 0.4380，远高于 0.30 的阈值），于是词法覆盖闸门判它无词面依据，用户被告知"知识库中没有相关的内容"。手里有答案却拒答，是这类产品最糟的失败模式 | `TestHybridRetrievalOnTheRealCorpus`：4 个问题 × 2 条断言（**排到第一** + **不再被拒答**），外加 `test_the_hybrid_stack_is_the_one_that_is_live` 守卫这三条只在混合模式下才成立。机制层面的守卫见 §3.8 |

### 3.2 成本控制（`test_gateway.py`）

| 风险 | 现在由谁守着 |
|---|---|
| 硬开关失效，禁用状态下仍然发出请求 | `TestHardSwitch::test_unavailable_gateway_never_calls_out`——把客户端替换成"一调用就抛异常"的假客户端 |
| 占位密钥被当成真密钥（`.env.example` 是 `sk-your-key-here`） | `test_placeholder_key_counts_as_unavailable` |
| 同一个 prompt 被付两次钱 | `test_second_identical_call_is_served_from_cache`——断言假客户端**只被调用 1 次** |
| 标点/空格/全角差异导致缓存穿透 | `test_a_trivial_rephrasing_hits_the_exact_cache` |
| 重新检索导致重复付费 | `test_cache_payload_decouples_from_the_prompt` |
| 语义缓存从不命中 | `test_semantic_cache_avoids_a_second_call` |
| 上游挂了导致接口 500 | `test_api_failure_degrades_to_none_instead_of_raising` |
| **语义缓存跨调用点串味**：`rag` 与 `qa_direct` 的 cache payload 都从同一个问题生成，向量余弦相似度接近 1.0 —— 不做限定的话，"外部直答"会被喂一份**检索增强的答案**，而"有检索和没检索的差别"正是这个功能存在的唯一理由 | `test_the_semantic_cache_does_not_cross_call_sites`——断言换 `purpose` 后同一向量**不命中**，且旧行为（`purpose=None`）保持不变 |
| **模型没进缓存身份**：对比两个模型时第二个模型直接命中第一个的缓存，**根本没被调用**，表格里两列完全相同 | `test_a_different_model_is_not_a_cache_hit`——断言换 `model` 后缓存穿透、假客户端被调用第 2 次 |
| 探活结果被缓存 | `test_the_probe_is_never_cached`——凭据被吊销后，缓存会让探活继续报"健康"，那不叫探活 |
| 切换服务商后请求仍发往旧地址（401 看起来像"密钥过期"，极难排查） | `test_the_client_is_rebuilt_when_the_provider_changes`——断言身份变化后客户端被重建 |

### 3.3 标签语义与阈值（`test_predict.py`）

这是本项目**最危险的一类错误**——`sklearn.datasets.load_breast_cancer` 的 `0 = 恶性 / 1 = 良性` 与本项目**正好相反**。当年原始毕设就是栽在这个反向映射上。

| 风险 | 现在由谁守着 |
|---|---|
| 阳性/阴性标签被写反 | `test_positive_and_negative_labels`：乳腺癌 `恶性 / 良性`、心脏病 `患病 / 健康` 写死在测试里 |
| 判定结论与标签不一致 | `test_verdict_agrees_with_the_threshold_and_the_label`：断言 `positive_prob >= threshold` ⟺ `verdict == "positive"` ⟺ `verdict_label == "恶性"` |
| 阈值被默认成 0.5 | `test_champion_thresholds_are_not_one_half`：乳腺癌 **0.1701**、心脏病 **0.6321** |
| **批量汇总用 0.5 计数，但每行按冠军阈值打标签** | `test_summary_tallies_from_each_rows_verdict`——断言汇总数 == 逐行 `verdict` 统计数，并断言阈值 < 0.5（否则这条测试就没意义了） |
| 演示样本全被判成"恶性 100%" | `test_samples_are_balanced_across_labels`（12 条里必须正好 6 正 6 负）+ `test_batch_produces_both_classes`。根因是"在 `[min,max]` 上均匀采样"会**以阳性类为中心**（最大值本就是它的上尾），修复方式改为**从公开数据集抽真实行** |
| 判定方向是否真的没反 | `test_an_extreme_benign_vector_is_a_negative_call`（取所有特征最小值 → 必须判良性）与 `test_mean_filled_vector_is_a_positive_call_at_this_threshold`（均值向量 → 按 0.1701 判恶性，这是**设计**不是 bug） |
| 缺特征/非有限值被静默接受 | `test_missing_feature_names_the_offending_row`（断言错误消息里带行号）、`test_non_finite_values_are_rejected` |
| 采样不可复现 | `test_sampling_is_deterministic_for_a_seed` + `test_different_seeds_give_different_batches` |

### 3.4 问答对比（`test_qa_compare.py`）

| 风险 | 现在由谁守着 |
|---|---|
| 对照组偷偷获得了检索 | `test_the_direct_path_is_the_hallucination_baseline`——`llm_direct.uses_retrieval` 必须恒为 `False` |
| 未配置外部模型时被算成"失败" | `test_unconfigured_external_paths_are_skipped_not_failed`（断言 `status == "skipped"` 且文案解释原因） |
| 未配置却产生了费用 | `test_summary_reports_zero_cost_when_nothing_is_configured`：`external_calls == 0`、`cost_cny == 0.0` |
| 表格缺列，无法逐行对比 | `test_metrics_are_present_on_every_path`：断言每条路径都带齐 12 个度量字段 |
| 越界问题被转交外部模型（拆掉病种隔离） | `test_an_out_of_scope_question_is_refused_everywhere` |
| 度量被误当成正确性/安全性判定 | `TestLexicalOverlap`、`TestRiskPhrases` 把"能说明"和"不能说明"都写成断言（如"低重合 ≠ 答案错误"、"没命中高风险措辞 ≠ 回答安全"） |
| 他人对比可被读取或删除 | `test_one_users_comparison_is_not_visible_to_another` |

### 3.5 认证与账号（`test_auth.py`）

| 风险 | 现在由谁守着 |
|---|---|
| **账号枚举**：用登录接口探测哪些邮箱已注册 | `test_wrong_password_and_unknown_email_are_indistinguishable`——状态码、错误码、**消息文案**三者都必须一致 |
| 口令散列被序列化出去 | `test_returns_a_token_and_the_profile` 断言响应里没有 `hashed_password` / `password` |
| 弱口令通过校验 | `test_password_must_mix_letters_and_digits` + `test_password_must_be_long_enough` |
| 首个账号不是管理员（新部署无法管理） | `test_first_account_becomes_an_admin`——断言**最小 id** 的用户是 admin，且后续用户不是（不依赖测试执行顺序） |
| 已删除账号的 token 仍然有效 | `test_a_token_for_a_deleted_account_is_rejected` |
| 被禁用账号仍然可用 | `test_a_disabled_account_is_forbidden` |
| 新增路由忘了加鉴权 | `test_every_private_get_route_requires_auth` / `..._post_route...`——**参数化清单**，加了新私有路由就往清单里补一行 |
| 公开路由被误加鉴权 | `test_documented_public_routes_need_no_token` |

### 3.6 应用层（`test_app.py`）

| 风险 | 现在由谁守着 |
|---|---|
| **`oversize` 悄悄变成非 0** | `test_health_reports_chunking_statistics`——断言 `oversize == 0`，把那条 98% 截断 bug 变成一条断言 |
| 某个路由返回裸 body，前端解包成 `undefined` | `test_success_responses_share_the_envelope` + `test_error_responses_use_the_same_envelope`（这条曾抓出 `/api/v1/meta/limits` 的真实问题） |
| **422 曾经绕过统一信封** —— 前端只能显示一句"请求失败"，**永远不告诉用户哪个字段错了** | `test_a_validation_error_also_uses_the_envelope`——断言 422 也带 `message` 且**点名出错字段**。根因是 FastAPI 自带的 `RequestValidationError` handler **优先级高于通用 `Exception` handler**，只注册 `AppError` / `HTTPException` / `Exception` 会漏掉这一种响应形状，必须显式注册 |
| **错误处理器自己把 422 变成 500** | `test_a_custom_validator_error_is_json_serialisable`——自定义 `field_validator` 抛 `ValueError` 时，pydantic 把**异常对象本身**塞进 `ctx.error`；直接交给 `JSONResponse` 会 `TypeError: Object of type ValueError is not JSON serializable`。`details` 必须过 `jsonable_encoder`（这条是在修上一条时**自己踩出来的**） |
| 鉴权与 body 校验的先后次序被写进文档却没人验证 | `test_a_bad_body_without_a_token_is_401_not_422`——FastAPI **先解依赖再校验 body**，所以未带 token 的坏请求是 401（`AppError`，本来就有信封），校验处理器只会被**已鉴权**的调用触发 |
| `request_id` 缺失，无法追踪链路 | `test_request_ids_are_unique_per_request` |
| 新接口没进 OpenAPI | `test_openapi_schema_is_served` |
| **`.env.example` 的默认密钥长得像真密钥**：`dev-only-secret-please-change-me-in-production-2f8a91c4` 带了随机后缀，一眼看不出是占位值，照抄到生产后**任何人都能伪造任意用户的 JWT** | `TestSecretKeyGuard`——开发环境只告警，**生产环境直接拒绝启动**；其中一条用例**真的去读仓库里的 `.env.example`**，断言它发的到底是什么就检测到什么（防的是"改了模板忘了改检测列表"） |

### 3.7 大模型接入（`test_llm_providers.py`）

这是本轮新增的最大一块。它测的不是"能不能调通真 API"，而是**接入层本身的不变量**——因为真 API 会因为欠费、
换版本、限流而随机失败，那种测试只会变成 flaky 的噪声源。

**服务商目录（`TestProviderCatalogue`）**

| 风险 | 现在由谁守着 |
|---|---|
| 目录被就地修改，一处改动污染全局 | `test_the_catalogue_is_immutable`（`frozen dataclass`） |
| 需要密钥的服务商被标成"开箱可用" | `test_keyless_providers_are_the_expected_ones`（Ollama / 演示通道**只有这两个**免密钥） |
| 公开接口泄露密钥或内部字段 | `test_public_catalogue_leaks_nothing_sensitive`——用**精确字段白名单**而不是子串黑名单（早期版本把无害的 `platform.deepseek.com/api_keys` 误判成泄露），另加一条断言密钥值本身不出现在响应里 |

**解析优先级（`TestResolutionPrecedence`）**

| 风险 | 现在由谁守着 |
|---|---|
| 残留的 `LLM_BASE_URL` 把命名服务商**悄悄重定向**到旧地址 —— 顺着 401 查半天，结论却是"密钥过期" | `test_a_stale_base_url_does_not_redirect_a_named_preset`：命名服务商**保有自己的 base_url**，`LLM_BASE_URL` 只在 `LLM_PROVIDER=custom` 时生效 |
| 演示通道被环境变量改到真实地址（就真的花钱了） | `test_the_demo_provider_ignores_both_overrides` |
| 大小写 / 首尾空格导致服务商"找不到" | `test_provider_id_is_case_and_space_insensitive` |

**密钥脱敏（`TestKeyMasking`）**：短密钥全掩、长密钥只留头 4 尾 4、无密钥返回 `None`（而不是空串——空串会让前端渲染出"已配置"的假象）。边界取 12/13 字符。

**错误分类（`TestErrorTaxonomy`）**：这是把"调用失败"四个字拆成 16 类的地方。

| 风险 | 现在由谁守着 |
|---|---|
| 欠费、密钥错、模型名错、限流、超时全部显示成同一句"调用失败" | 参数化的 `error_kind` 断言：401→`invalid_key`、402→`quota`、403→`forbidden`、404→`endpoint_not_found`、429→`rate_limited`、5xx→`server_error`… |
| 400 里"模型不存在"和"请求格式错"被混为一谈 | `test_bad_request_mentioning_a_model_is_model_not_found`（只靠状态码分不开） |
| 异常对象形态不一（有的是嵌套 `response`，有的只有类名） | 三条兜底：状态码 → 类名（`"Timeout" in name` / `"Connection" in name` / `httpx.*`）→ 消息文本 |
| 只对着自己造的假异常测，真 SDK 一升级就失效 | `test_real_openai_authentication_error` / `test_real_openai_rate_limit_error`——**直接用 `openai` 的真实异常类**构造 |
| 上游返回超长 HTML 把响应体撑爆 | `test_detail_is_truncated`（500 字符上限） |

**演示通道（`TestDemoTransport`）**

| 风险 | 现在由谁守着 |
|---|---|
| 演示回答被误当成真实大模型的医学建议 | `test_the_watermark_is_the_first_line`——**首行**必须是那句免责声明；`test_it_makes_no_medical_claims` 另查关键词 |
| 演示回答与检索路径"没区别"，导致对比失去意义 | 演示模型**故意复刻真实效应的方向**：有出处的回答会回显问题关键词，`lexical_overlap` 实测 **0.61 vs 0.07**，表格不是两条一模一样的行 |
| 同一次输入两次结果不同 | `test_it_is_deterministic` |
| 只测通了 happy path，十种故障没人管 | `test_every_declared_fault_is_handled` 覆盖 `invalid_key / endpoint_not_found / rate_limited / quota / forbidden / server_error / bad_request / timeout / connection / garbage / empty`，并断言**每个故障的结果都必须与成功不同** |
| **一个"看起来在测、其实什么都没测"的用例**：早期版本只是给每个故障名构造一次 transport。就算某个故障被静默忽略，它也照样通过 | 同上。这条测试的价值不在覆盖面，而在它**第一次真的断言了行为** |
| 故障名写错，静默变成一次"成功" | `test_an_unknown_fault_is_ignored_but_announced`——断言 warning 里出现那个拼错的名字 |
| 故障注入泄漏到真实服务商，把别人的接入搞坏 | `test_the_fault_setting_is_ignored_by_a_real_provider`——断言非演示服务商的 `mock_fault` 恒为 `null` |
| 错误分类表只能靠"真的欠一次费"来验证 | `test_the_configured_fault_reaches_the_gateway`——`LLM_MOCK_FAULT=quota` 时探活必须返回 `error_kind == "quota"` |
| 分词把 `BI-RADS` 拆坏 | `test_hyphenated_terms_survive`（中文分词里 `-` 是分隔符，故关键词提取特意不按 `-` 切） |

**网关与多模型（`TestGatewayWithDemoProvider` / `TestMultiModelComparison`）**

| 风险 | 现在由谁守着 |
|---|---|
| 测试之间互相污染：网关是**进程级单例**，带着调用计数与缓存，测试 A 跑了外部路径就会让测试 B 的"没有外部调用"断言挂掉（**这个真的发生过**，详见 §4.6） | `conftest.py` 的 `fresh_llm_gateway`（`autouse`）——每个测试拿到全新网关 |
| 探活产生了费用 | `test_probe_costs_nothing_on_the_demo_channel` |
| 模型名列表带空格 / 重名 / 非法字符 / 超长 | `TestModelListCleaning`：去空白、保序去重、`^[A-Za-z0-9._:\-/]{1,64}$` 白名单、上限 `LLM_MAX_COMPARE_MODELS` |
| 被丢弃的模型**没有提示**，表格里少一列却查不出原因 | 接口**回显清洗后的列表**，前端据此提示"将产生 N 条外部链路" |
| 多模型时旧的 `answer_llm_direct` 列变成空值 | `test_history_keeps_the_legacy_column`——多模型下取第一个有答案的路径填旧字段，历史详情不破 |

### 3.8 混合检索与重排（`test_retrieval.py`）

这一节测的是**排序本身**，而排序有一个特殊困难：它很容易"看起来在工作"。检索返回了正确的片段，不能证明融合起了作用；重排接好了，也不能证明它真的改了顺序。所以这里的用例大多是"**把两种模式的输出摆在一起，断言它们不同、且差异是预期的那个方向**"。

**两个输入源，各有各的用处**

| 输入源 | 擅长证明什么 | 不擅长什么 |
|---|---|---|
| `test_rag.py` 的真实语料回归 | 修好的**是这台机器上这份语料**的问题（4 个被误拒答的问题，见 §3.1 下方） | 只能证明"这几个问题好了"，说不出机制 |
| `test_retrieval.py` 的合成语料 + 桩编码器 | 机制本身：BM25 的每一项、RRF 的每一步、重排怎么接入又怎么降级 | 不覆盖真实分词器的边界 |

**BM25（`TestBm25`）**

| 风险 | 现在由谁守着 |
|---|---|
| IDF 用到 `log(1+x)` 变体（导数在 0 附近爆掉），稀有词权重被夸大 | `test_rare_terms_outweigh_common_ones`——用 8 篇文档造出明确的稀有/常见对比 |
| **IDF 不夹到 0**：负 IDF 会让"不含这个常见词的文档"排在"含它的文档"**前面**，方向整个反过来 | `test_idf_is_never_negative`：池子里 8 篇有 7 篇含目标词，断言它的贡献是 0 而不是负数 |
| 长文档靠体量刷分 | `test_longer_documents_are_not_rewarded_for_length`（`b=0.75` 的归一化） |
| 词频无饱和，出现 10 次就比出现 1 次"好 10 倍" | `test_term_frequency_saturates`（`k1=1.5`） |
| 两篇文档的池子 | 单独一条用例把边界**写下来**：`n-df=1` 时每个词的 IDF 都会被夹成 0，整套打分**退化成常量**。这是公式的性质，不是 bug，但必须有人写下来，否则下一个人会以为检索坏了 |
| BM25 与词法闸门读了不同的文本 | `test_bm25_indexes_the_same_text_the_lexical_gate_reads`——两者都走 `lexical_text()`（`breadcrumb + text`）。**这是设计约束**，不是巧合：读不同的文本会让"BM25 排第一的片段被闸门判为没有词面依据" |

**RRF（`TestRrfFusion`）**

| 风险 | 现在由谁守着 |
|---|---|
| 融合吃的是分数而不是排名（BO25 无上界、余弦在 `[-1,1]`，直接加权需要没人验证过的归一化系数） | `TestRrfFusion` 全体：`_rrf_fuse` 的入参就是 `list[list[int]]`（排名），接口层面就传不进分数 |
| 只有一路召回时结果被稀释 | `test_a_document_only_one_retriever_found_still_scores` |
| 两路都空时返回非空 | `test_no_rankings_produces_no_candidates` |
| `k` 被调成"名次差别不重要" | `test_a_larger_k_flattens_the_difference_between_adjacent_ranks`——`k` 变了排序就该变，否则这个参数其实没接进去 |

**端到端（`TestHybridRetrieval`）**

| 风险 | 现在由谁守着 |
|---|---|
| ——**最根本的一条：测试语料自己塌了** | `test_the_fixture_kept_both_breast_sections_separate`——这个 fixture 用桩分词器切成两份乳腺文档，而桩曾经是 `len(text)//2` token，触发切块器的 `_merge_short` 把两节合并成一份。语料一旦只剩 2 篇，**每个词的 IDF 都被夹成 0**，BM25 全体返回同样的分数，`test_hybrid_finds_the_section_dense_missed` 就挂了——挂在一个看起来和它无关的地方。这条守卫测试存在的意义就是让下次的失败**指向真正的原因** |
| 混合检索"好了"只是幻觉 | `test_dense_alone_picks_the_wrong_section` + `test_hybrid_finds_the_section_dense_missed` 成对存在：前者断言稠密在这份语料上**确实会错**，后者断言融合**确实会修**。只有后者的话，一个"两路都对"的语料也能让它通过 |
| 病种过滤被 BM25 绕开 | `test_scope_filter_runs_before_fusion`——过滤在每个召回器**内部**生效，词法通路捞不回别的病种 |
| 融合分被当成相似度返回，闸门阈值失去意义 | `test_a_hit_carries_its_raw_cosine_not_its_ranking_score`——断言**融合冠军的余弦是 0.0、亚军的余弦 > 0.9**，也就是排名与余弦**故意不一致**，而返回的第二个元素仍是余弦 |
| "我们加了混合检索"读 diff 验证不了 | `test_last_retrieval_reports_what_the_query_did`——断言 `last_query` 的 `dense` 与 `lexical` **同时非零**。只看返回的片段对不对，无法区分"融合起了作用"和"稠密自己就够了" |

**重排（`TestReranking`）**

| 风险 | 现在由谁守着 |
|---|---|
| 重排接好了但没接管顺序 | `test_the_reranker_decides_the_final_order` + `test_without_the_rerank_stage_the_order_stays_as_fusion_left_it` |
| 重排只看正文，看不到标题路径 | `test_the_reranker_sees_the_heading_trail_as_well_as_the_body`——断言喂进去的是 `embed_text`（含 breadcrumb）。早先这条**把 `(query, passage)` 解包反了**，因为假重排器按内容而不是按位置打分，它照样通过了；修的是断言方式 |
| **静默降级与功能正常长得一样** | `test_a_missing_model_degrades_the_ranking_instead_of_the_feature`（模型加载失败 → 退回融合排序，`/health` 写明 `rerank_unavailable`）、`test_a_query_time_failure_falls_back_for_good`（查询期失败 → 降级并且**不再重试**，否则每个问题都要等一次超时） |
| 关闭时仍然去加载模型（把一个 1.1 GB 的下载塞进启动路径） | `test_disabling_the_reranker_does_not_even_try_to_load_it` |

**拒答闸门读的是哪个数（`TestRefusalGateReadsCosine` / `TestLexicalGateReadsTheTopHitOnly`）**

| 风险 | 现在由谁守着 |
|---|---|
| 词法提升把低余弦片段顶到第一 → 闸门读 `hits[0]` 的余弦 → **因为 BM25 干了它该干的事而拒答了一个有据可查的问题** | `test_a_lexical_promotion_does_not_cause_a_false_refusal` |
| 反过来，闸门改读融合分（排序用的数，量纲不符） | `test_a_genuinely_weak_retrieval_is_still_refused`——真正弱的命中**必须**仍然被拒 |
| **有人"顺手统一"两个闸门**：余弦闸门取命中里的最大值，词法闸门却只读 `hits[0]`，看起来像不一致 | `test_coverage_is_measured_against_the_top_hit_not_the_best_hit`——断言覆盖率只按 `hits[0]` 算。统一成取最大值后，真实语料上那 4 个问题的覆盖率会达到 0.125–0.333（阈值 0.12），于是它们**不再被拒答，而是被自信地答以错误的小节**。误拒答可见、可修；误答隐形。这个不对称是承重的 |

---

## 四、测试基建的几个决定

`tests/conftest.py` 里有些看起来绕的地方，都是踩过之后的结论。

### 4.1 环境变量必须在导入配置**之前**设置

```python
os.environ["DATABASE_URL"] = ...   # 必须在这里
os.environ["LLM_ENABLED"] = "false"
...
import pytest                       # noqa: E402 —— 故意放在后面
```

原因：`app.core.config` 里的 `settings` 是**在导入时构建并缓存的**。一旦先 import 了 `app`，再改环境变量就来不及了，测试会写到开发者的 `bcdx.db` 上。`# noqa: E402` 是给 lint 看的，不是疏忽。

### 4.2 一次性数据库，跑完自动删

```env
DATABASE_URL=sqlite+pysqlite:///<系统临时目录>/bcdx_pytest_<pid>.db
```

不用 `/tmp/` 字面量——Windows 上 SQLite 打不开 `/tmp/e2e.db`（报 `unable to open database file`），所以走 `tempfile.gettempdir()`，拿到的是原生 Windows 路径。文件名带 **pid**，并发跑两套测试不会抢同一个文件。

放**系统临时目录**而不是测试目录：清理钩子（`pytest_sessionfinish` 删掉 `-journal` / `-wal` / `-shm` 附属文件）在绝大多数环境里都能成功，但万一被拦（某些沙箱会拦截文件删除），落在仓库外的临时目录只是无害垃圾，落在 `backend/tests/` 就会变成一个 100 KB 的碍眼文件。`.gitignore` 里的 `*.db` 兜底，两种情况下都不会进版本库。

### 4.3 会话级 fixture

```python
@pytest.fixture(scope="session")
def client(): ...
```

应用启动要加载 6 个模型产物并构建嵌入索引，约 40 秒。**做成 per-test 会让整个套件多花十几分钟**，所以整个会话只启动一次。

### 4.4 提升限流阈值

```env
RATE_LIMIT_PREDICT=100000/minute
RATE_LIMIT_LLM=100000/minute
RATE_LIMIT_AUTH=100000/minute
```

限流器是**模块级单例，跨整个会话共享**。用生产默认值（RAG 12/分钟）跑测试，套件光靠正常执行就会把自己限流掉。限流逻辑本身改成**直接对 `RateLimiter` 做单元测试**，不绕 HTTP。

### 4.5 为什么测试邮箱用 `example.com`

一开始用 `pytest-xxx@bcdx.test`，被 `email-validator` 拒绝：

> The part after the @-sign is a special-use or reserved name that cannot be used with email.

`.test` 是 RFC 保留 TLD，`bcdx.local` 同理。`example.com` 是 RFC 2606 专门为此保留的域名，可以通过校验。

### 4.6 每个测试一个全新网关

```python
@pytest.fixture(autouse=True)
def fresh_llm_gateway(monkeypatch):
    from app.services import llm_gateway
    monkeypatch.setattr(llm_gateway, "_gateway", llm_gateway.LlmGateway())
```

`LlmGateway` 是**进程级单例**，身上带着调用计数、累计 token、成本合计和响应缓存。这在生产里正是我们想要的
（缓存要跨请求共享），但在测试里是个陷阱：

> `test_usage_reports_the_llm_as_disabled` 单独跑通过，跑全量套件却挂——因为前面某个用例把 `LLM_PROVIDER`
> 切成演示通道、还调了 4 次外部路径。于是这条断言"外部调用次数为 0"的用例，看到的计数是 4。

这不是"测试写得不好"，是**测试之间真的有共享可变状态**。挨个断言前重置计数只是治标；`autouse` 地给每个测试
发一个新实例，才是把这类错误一次性关掉。代价是每个测试多构造一个对象，而它本身是轻量的。

> 反过来的教训也成立：**如果一个"单元测试"需要小心地按顺序跑才通过，那它测的就不是单元。**

---

## 五、持续集成

配置文件：`.github/workflows/ci.yml`。两个**互相独立**的 job——后端坏了和前端坏了是两件事，不该互相掩盖。

### 5.1 `backend` —— 测试

```
checkout → setup-python 3.11（带 pip 缓存）
  → pip install -r requirements.txt -r requirements-dev.txt
  → 缓存 ~/.cache/huggingface（嵌入模型约 470 MB，缓存后从 1 分钟降到几秒）
  → python ml/pipelines/train.py          # 重建模型产物
  → 打印切块统计，oversize 非 0 直接失败
  → pytest --cov=app --cov-report=term-missing --cov-report=xml
  → 上传覆盖率报告
```

### 5.2 为什么 CI 里要重新训练

`ml/registry/models/*.joblib` 是 `.gitignore` 掉的，所以 CI 里没有模型文件。让它从仓库里已提交的原始 CSV 重建，有三重好处：

1. CI 不需要二进制产物也能跑；
2. **训练管线本身被持续验证**——它坏了 CI 会红；
3. 同时验证了训练的**可复现性**。

可复现性是实测过的：`ml/pipelines/train.py` 全程固定 `RANDOM_STATE`，重跑一遍后 `registry.json` **除了 `generated_at` 之外逐字节相同**，全部阈值精确复现：

| 病种 | lr | rf | **冠军** |
|---|---|---|---|
| 乳腺癌 | 0.2443 | 0.5166 | xgb **0.1701** |
| 心脏病 | 0.6633 | **0.6321** | xgb 0.6834 |

> 顺带一提，同一病种不同算法的阈值差异很大（0.1701 vs 0.5166），这本身就是"不能把 0.5 当默认阈值"的最好证据。

> **"逐字节相同"有一个前提**：`train.py` 写 `registry.json` 与 `MODEL_CARD.md` 时显式传了 `newline="\n"`。
> `Path.write_text()` 在 Windows 上默认会把 `\n` 翻成 `\r\n`，不传这个参数就会出现
> **本地 CRLF、CI（Linux）LF** —— 同一条命令、两种字节，于是"重跑后 diff"这条校验在跨平台时直接失效。
> 仓库里所有 `.md` / `.env*` / `LICENSE` 也统一是 **LF**。

### 5.3 为什么 CI 里有一条"提前失败"的切块检查

```python
if stats.get("oversize"):
    sys.exit(f"{stats['oversize']} chunk(s) exceed the embedding window")
```

同一条不变量在测试里也断言了，为什么还要单独写一步？因为**在 pytest 之前失败，日志更短、指向更明确**。当这条断言挂掉时，你看到的第一行就是原因，而不是埋在 427 个用例输出里的某一行。

### 5.4 `frontend` —— 类型检查 + 构建

```
checkout → setup-node 20（带 npm 缓存）→ npm ci → npm run typecheck → npm run build
```

`build` 本身就是 `tsc -b && vite build`，所以 `typecheck` 那一步看起来重复——它重复是为了**让失败原因一眼可辨**：类型错误就是类型错误，不会和打包错误混在一起。

> CI 里**没有** lint 步骤。`package.json` 原先有一个 `lint` 脚本，指向既未安装、也未在 `devDependencies` 里声明的 `eslint`——它是跑不起来的死脚本，已经删掉。**与其在 CI 里放一个没人验证过的步骤，不如不放。**

### 5.5 其他

- `permissions: contents: read` —— 最小权限，CI 不写仓库；
- `concurrency` 按 ref 分组 + `cancel-in-progress` —— 新推送会取消同一分支上还在跑的旧任务。

---

## 六、还没覆盖的部分（如实说明）

| 缺口 | 说明 |
|---|---|
| **前端没有自动化测试** | 三个页面（批量评估、问答对比、外部模型连接面板）目前靠 Puppeteer 截图脚本做人工核对，没有组件测试或 E2E。这是当前最大的缺口。 |
| **没有 lint / 格式化检查** | Python 侧无 ruff/flake8，前端无 eslint。 |
| **真实密钥的端到端调用不在 CI 里** | CI 与本地测试都强制 `LLM_ENABLED=false`；外部路径的**真调用**靠演示通道（`httpx.MockTransport`）覆盖 SDK 序列化 / 重试 / 错误映射，但真密钥、真限流、真计费只在人工流程里验证。这是刻意的：把真 API 放进 CI 会引入 flaky 与费用。 |
| **数据库迁移未测试** | 表结构由 `Base.metadata.create_all` 创建，还没接入 Alembic。 |
| **并发 / 压力未测** | 限流器是单进程内存实现，多 worker 下的行为未验证。 |
| **覆盖率未设门槛** | 装了 `pytest-cov` 就能出数字，但没设 `--cov-fail-under`。先有数字，再谈门槛。 |

---

## 七、相关文件

| 文件 | 职责 |
|---|---|
| `backend/pytest.ini` | pytest 配置、标记（`slow` / `integration`）、`testpaths` |
| `backend/requirements-dev.txt` | 测试依赖（pytest / pytest-cov / httpx） |
| `backend/tests/conftest.py` | 环境变量、会话级 fixture、一次性数据库清理 |
| `.github/workflows/ci.yml` | CI 流水线 |
| `.gitignore` | 忽略 `.pytest_cache/`、`.coverage`、`htmlcov/`、`coverage.xml` |
