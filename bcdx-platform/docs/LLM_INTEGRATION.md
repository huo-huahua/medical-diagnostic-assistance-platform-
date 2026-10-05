# 接入外部大模型 · 配置、自检与成本控制

> 这一页回答四个问题：
> **怎么接？接上了没？接错了错在哪？以及——会不会不小心花掉很多钱？**
>
> 对应优化项：[`OPTIMIZATION_BACKLOG.md`](OPTIMIZATION_BACKLOG.md) 第 8 条（`.env.example` 默认密钥）
> 与新增的「可接入任意大模型」能力。

---

## 一、为什么需要这一页

本平台的默认问答**完全本地运行，一次外部 API 都不调用**。所以"接入大模型"这条路一开始是**关着**的：
`.env` 里 `LLM_ENABLED=false`、`LLM_API_KEY` 为空。后果是，问答对比页里的两条外部路径永远是
`skipped` —— 一个**已经写好却从没被真正跑通过**的功能。

更麻烦的是它失败时的样子：以前不管什么原因，界面上都只写"调用失败（网络失败或密钥无效）"。
而这句话至少覆盖了 **六种完全不同的故障**：

| 真实原因 | 该做什么 |
|---|---|
| 没填密钥 | 去申请一个 |
| 密钥过期 / 抄错 | 去控制台换一个 |
| base URL 漏了 `/v1` | 改配置 |
| 模型名不存在 | 查文档核对模型名 |
| 账户欠费 | 充值 |
| 本机没有到服务商的网络 | 换网络或换本地模型 |

这六件事的处理方式互不相干，混成一句话就等于没说。所以这一轮做的不只是"加一个 API 调用"，
而是把**接入、自检、诊断、成本**四件事一起做完。

---

## 二、六十秒接入

### 方式 A：先用免密钥的方式看一遍（推荐）

不需要注册、不需要信用卡、不联网：

```bash
# 仓库根目录的 .env
LLM_ENABLED=true
LLM_PROVIDER=mock
```

重启后端，打开**问答对比**页 → 「测试连接」应显示绿色「连接正常」。
此时两条外部路径会**完整跑通**：真实经历请求构造 → HTTP → 响应解析 → token 统计 → 费用计算 → 缓存，
只是最后一段没有真的出网。

> **它是什么**：内置演示模型用 `httpx.MockTransport` 顶替了网络层，
> 因此除了 socket 之外的所有代码（含 OpenAI SDK 的序列化、重试与异常映射）都是真实执行的。
> **它不是什么**：输出是本地代码生成的**占位文本**，每条都以 `【演示模式】` 开头并明说不是模型回答。
> 它可以用来说明**这套对比机制怎么工作**，不能用来评价任何模型的真实能力。

### 方式 B：接一个真实服务商

```bash
# 仓库根目录的 .env
LLM_ENABLED=true
LLM_PROVIDER=deepseek          # 见下方服务商表
LLM_API_KEY=sk-你的真实密钥
```

重启后端（改 `.env` 不会热加载），然后点「测试连接」。绿色即表示已连通。

### 方式 C：不花钱、也不出本机 —— 用本地 Ollama

```bash
ollama pull qwen2.5:7b
ollama serve
```

```bash
LLM_ENABLED=true
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b        # 必须与 ollama list 里的名字一致
```

数据不出机器、不产生费用，但是**真实模型**。适合做隐私敏感场景的演示。

---

## 三、内置服务商

全部通过 **OpenAI 兼容接口**接入 —— 这是目前的事实标准，DeepSeek、OpenAI、通义、Kimi、GLM、
Ollama、vLLM、LM Studio、LiteLLM、One-API 都提供。所以"换服务商"本质上只是换一个 base URL 加一个模型名。

| `LLM_PROVIDER` | 服务商 | 默认模型 | 需要密钥 | 价格（元/千 token，输入/输出） |
|---|---|---|---|---|
| `deepseek` | DeepSeek 深度求索 | `deepseek-chat` | ✅ | 0.002 / 0.008 |
| `openai` | OpenAI | `gpt-4o-mini` | ✅ | 0.0011 / 0.0043 |
| `qwen` | 阿里云百炼（通义千问） | `qwen-plus` | ✅ | 0.0008 / 0.002 |
| `moonshot` | Moonshot（Kimi） | `moonshot-v1-8k` | ✅ | 0.012 / 0.012 |
| `zhipu` | 智谱 GLM | `glm-4-flash` | ✅ | 免费 |
| `ollama` | 本地 Ollama | `qwen2.5:7b` | ❌ | 0（跑在自己机器上） |
| `mock` | 内置演示模型 | `demo-model` | ❌ | 0（不联网） |
| `custom` | 自定义 / 自建端点 | 由 `.env` 指定 | ✅ | 由 `.env` 指定 |

价格**只用于在对比表上标注预估费用**，永远不会被用来计费。要接的服务商不在表里，
用 `custom`：

```bash
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:8080/v1   # vLLM / LM Studio / LiteLLM / One-API
LLM_MODEL=your-model-name
```

> ⚠️ 通义千问必须走 `compatible-mode` 路径才是 OpenAI 兼容接口：
> `https://dashscope.aliyuncs.com/compatible-mode/v1`。漏掉会返回 404。

在 UI 里可以看到这张表的实时版本（含每一家的控制台链接），见「外部模型连接」面板下方的折叠区。

---

## 四、环境变量与优先级（这里有个坑）

三个变量共同决定请求发往哪里，但**它们的优先级并不一样**：

| `LLM_PROVIDER` | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| 内置服务商（如 `deepseek`） | **忽略**，用预设里已知正确的地址 | 生效，可覆盖模型名 |
| `custom` | 生效 | 生效 |
| `mock`（演示） | 忽略 | 忽略 |

规则看着别扭，但它防的是一个非常难查的故障：

> 你把 `LLM_PROVIDER` 从 A 改成 B，但 `.env` 里还留着 **A 的** `LLM_BASE_URL`。
> "环境变量优先"的实现会把请求发到 A，收到 401，然后你花一小时怀疑自己密钥过期了。

所以：**选内置服务商时，地址由预设负责，不让陈旧配置有机会插手。** 只覆盖**模型名**是允许的，
因为主机、密钥都没变（`LLM_PROVIDER=deepseek` + `LLM_MODEL=deepseek-reasoner` 是正常需求）。
演示服务商两个都忽略——它没有上游可以指，一个不存在的模型名只会误导看表的人。

`/api/v1/llm/providers` 会在 `override_rules` 字段里返回这句话的简短版本，
UI 直接把它显示出来，不用去翻文档。

---

## 五、连通性自检：一次 16 token 的调用

```bash
curl -s --noproxy '*' -X POST http://127.0.0.1:8000/api/v1/llm/test \
  -H "Authorization: Bearer $TOKEN"
```

成功：

```json
{
  "provider": "deepseek", "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com",
  "ok": true, "latency_ms": 812, "reply": "正常",
  "prompt_tokens": 21, "completion_tokens": 2, "cost_cny": 0.000058,
  "error_kind": null, "error_message": null, "error_detail": null
}
```

失败时会给出**可执行的**原因，而不是一句"调用失败"：

```json
{
  "ok": false,
  "error_kind": "endpoint_not_found",
  "error_message": "接口地址不对（404）。常见原因是 base_url 缺少 `/v1` 后缀，或把上一个服务商的地址留在了配置里。",
  "error_detail": "Not Found"
}
```

错误类型全集（`error_kind` 的取值，定义在 `services/llm_providers.ERROR_KINDS`）：

| `error_kind` | 触发条件 | 含义 |
|---|---|---|
| `disabled` | `LLM_ENABLED=false` | 功能被全局关掉。**优先于**其它所有判断 |
| `no_endpoint` | `custom` 但没填 `LLM_BASE_URL` | 没有可用地址 |
| `missing_key` | 需要密钥但未配置 | 去申请一个 |
| `invalid_key` | HTTP 401 | 密钥无效或已过期 |
| `forbidden` | HTTP 403 | 密钥无权访问该模型 |
| `quota` | HTTP 402 | 欠费或额度用尽 |
| `endpoint_not_found` | HTTP 404 | 地址不对（多半缺 `/v1`） |
| `model_not_found` | HTTP 400 且报文提到 model | 模型名不存在 |
| `bad_request` | 其它 HTTP 4xx | 参数不被支持 |
| `rate_limited` | HTTP 429 | 触发服务商限流 |
| `server_error` | HTTP 5xx | 对方的问题，稍后重试 |
| `timeout` | 超时 | 调大 `LLM_TIMEOUT_SECONDS` 或检查网络 |
| `connection` | 连不上 | 本地模型没启动，或没有到服务商的网络 |
| `empty_response` | HTTP 200 但内容为空 | 内容被过滤，或模型只输出了推理过程 |
| `bad_response` | 返回不是预期结构 | 该地址不是 OpenAI 兼容接口 |
| `unknown` | 其它 | 看后端日志里的原始异常 |

两点设计说明：

- **`disabled` 排在最前面**。否则只会告诉用户"你没配密钥"，把人支去申请一个他并不需要的密钥。
- **探活不走缓存**。缓存住的"成功"会在密钥被吊销之后继续报告健康——一个能被缓存满足的健康检查不是健康检查。
  它消耗的 token 仍然计入总量，因为那笔钱确实花了。

### 5.1 想亲手复现一类错误？用故障注入

上面那张错误表如果只能靠"真的欠一次费"来验证，那就等于没法验证。所以演示通道带了一个开关：

```bash
# 仓库根目录的 .env
LLM_ENABLED=true
LLM_PROVIDER=mock
LLM_MOCK_FAULT=quota        # 任选：invalid_key / endpoint_not_found / rate_limited /
                            #      quota / forbidden / server_error / bad_request /
                            #      timeout / connection / garbage / empty
```

重启后端后，**每一次**演示调用都会按这个错误类型失败。实测：

```bash
curl -s --noproxy '*' -X POST http://127.0.0.1:8000/api/v1/llm/test \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "ok": false,
  "error_kind": "quota",
  "error_message": "额度已用尽或欠费（402/403）。请到服务商控制台检查余额。",
  "error_detail": "Error code: 402 - {'error': {'message': 'Insufficient Balance', 'type': 'quota', 'code': 'quota'}}"
}
```

同时「外部模型连接」面板顶部会出现一条**故障注入**提示，`/llm/status` 的 `mock_fault` 字段也会变成 `quota`——
否则一个人设完忘了，第二天会以为整个接入功能坏了。

三个刻意的边界：

| 边界 | 原因 |
|---|---|
| **只作用于 `LLM_PROVIDER=mock`** | 它不该有能力破坏一个真实的接入。真实服务商时 `mock_fault` 恒为 `null` |
| **写错了会被忽略并记一条 warning** | 悄悄忽略等于让读者看到一次"成功"，然后得出"错误处理没做"的结论 |
| **本地路径完全不受影响** | 故障只影响外部路径；`local_rag` 照常返回，因为它本来就不出网 |

> 配套的测试也重写了。原来那条 `test_every_declared_fault_is_handled` 只是"每个故障名都能构造出 transport"——
> 就算某个故障被静默忽略，它也照样通过。现在它断言**每个故障的结果都必须与成功不同**。

---

## 六、四种状态，不能压成一个布尔值

界面上的状态标签不是一个布尔值，而是四种：

| 标签 | 含义 | 该做什么 |
|---|---|---|
| **已就绪** | 可调用 | 不用管 |
| **演示模式** | 走的是内置演示模型 | 看得见效果，但没有真实模型参与 |
| **未配置密钥** | 开关开着，缺密钥 | 填 `LLM_API_KEY`，或改用 `mock` / `ollama` |
| **已关闭** | `LLM_ENABLED=false` | 这是刻意的选择，不是故障 |

全塞进一个 `available: false` 的话，"我故意关掉的"和"我配错了"就长得一模一样了。

---

## 七、成本是怎么被摁住的

外部调用要花钱，而本项目把"调用次数极少"当作硬约束。四层防线：

### 1. 硬开关

`LLM_ENABLED=false` 会让每个调用点直接返回，连客户端都不构造。密钥缺失、或密钥仍是
`.env.example` 里的占位值（`sk-your-...`）时，也会自动降级为纯本地模式。

> 拒绝占位值这一条是刻意的：否则一份照抄示例的配置会把平台切进"付费模式"，
> 然后每一次对比都以 401 失败。

### 2. 精确缓存

缓存键 = `SHA-256(purpose + 模型 + 规范化后的 payload)`，其中 `normalize_zh` 会抹掉空白、
全半角差异、大小写和标点。因此「乳腺癌，怎么筛查？」和「乳腺癌怎么筛查」算同一个键。

### 3. 语义缓存

对同一调用点的历史提问做余弦相似度匹配（阈值 0.94），所以换了说法的同一个问题也能复用答案。

> ⚠️ **语义检索必须限定调用点。** 嵌入的文本是 cache payload，而不同调用点是从同一个问题派生出
> 它的——「本地检索增强」和「外部直答」的向量相似度接近 1.0。不加限定的话，直答路径会被喂一份
> **检索增强的答案**，而"有检索和没检索的差别"恰恰是这个功能存在的唯一理由。
> 见 `ResponseCache.get_semantic(..., purpose=...)`。

### 4. 模型也是缓存身份的一部分

`llm_direct@a` 和 `llm_direct@b` 是两个键。否则对比两个模型时，第二个模型根本不会被调用，
表里会显示**同一个模型的答案出现两次**。

### 实测（演示模式，全程 ¥0）

同一问题 + 同一组模型 `[model-x, model-y]`，连跑两次：

| 操作 | `external_calls` | `cache_hits` | 说明 |
|---|---|---|---|
| 第一次（冷启动） | **4** | 0 | 2 个模型 × 2 条外部路径，全部真实走了请求构造与解析 |
| 同一请求再跑一遍 | **0** | **4** | 全部命中缓存，一次都没真调 |
| 换成 `model-c` | 2 | 0 | 正确的行为：新模型是新身份 |

冷启动那 4 次调用的 token 合计 `1920 + 1836`。如果换成真实模型（按 DeepSeek 定价），
这次对比约 **¥0.019**；而**重跑一次是 ¥0**——这正是缓存存在的意义。

### 费用公式

```
费用(¥) = prompt_tokens/1000 × 单价_输入 + completion_tokens/1000 × 单价_输出
```

单价取自当前服务商的预设（`custom` 取 `.env`）。**只用于展示**，从不用于计费。

---

## 八、多模型并排对比

这是"接入大模型"的另一半：不只对比"有检索 / 没检索"，还对比**不同模型之间**。

在问答对比页的「多模型并排对比」里用逗号分隔填模型名（最多 3 个，`llm_max_compare_models`），
两条外部路径就会**按模型各占一列**：

```
local_rag                 ← 始终只跑一次，模型无关
llm_direct@model-a
llm_direct@model-b
llm_rag@model-a
llm_rag@model-b
```

也可以用 API：

```bash
curl -s --noproxy '*' -X POST http://127.0.0.1:8000/api/v1/rag/compare \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"question":"乳腺癌的早期症状和筛查方法有哪些","disease":"breast",
       "models":["deepseek-chat","gpt-4o-mini"]}'
```

设计决定，逐条都是刻意的：

- **检索结果对所有模型完全相同**，所以列与列之间的差异只可能来自模型本身。
- **填了模型就只跑这些模型**，不会自动加上"当前配置的那个"。悄悄多发两次付费调用会让账单不可预测；
  界面的输入框默认就带上了当前模型，所以常见用法不会少东西。
- **模型名要过校验**（`^[A-Za-z0-9._:\-/]{1,64}$`），去重、去空、保序、截到上限，
  并把**清洗后的列表原样回显**在 `models` 里 —— 被丢掉的模型必须看得见，不能只是少了一列。
- **`llm_rag` 在跨病种问题上整列跳过**，多模型也一样。某个模型不应该成为绕过知识库隔离的后门。

### 实测（演示模式，同一问题）

问题就是上面那条 curl，模型 `deepseek-chat` / `gpt-4o-mini`（**冷启动**，`external_calls = 4`）：

| 列 | 状态 | Token | 费用 | 词面重合 | 引用 |
|---|---|---|---|---|---|
| `local_rag` | ok | 0 + 0 | ¥0 | 1.000 | 2 |
| `llm_direct@deepseek-chat` | ok | 214 + 265 | ¥0 | 0.069 | 0 |
| `llm_direct@gpt-4o-mini` | ok | 214 + 265 | ¥0 | 0.069 | 0 |
| `llm_rag@deepseek-chat` | ok | 777 + 804 | ¥0 | 0.611 | 2 |
| `llm_rag@gpt-4o-mini` | ok | 777 + 804 | ¥0 | 0.610 | 2 |

注意 **0.07 → 0.61** 这条差值：演示模型被刻意造成"检索增强的回答会复用原文用词、直答的不会"，
这样即使在没有密钥的环境里，对比表体现的**效果方向**也和真实情况一致。
一张把两列都填成一样数字的演示表，会教会读者完全错误的东西。

> 同一问题换到较短的问题（如 `BI-RADS 分级是什么意思？`）时，直答列会变成 `208 + 258`、
> 重合度 `0.036` —— 这些数字**依赖于问题本身**，因为演示答案会回显提问里的关键词。
> 拿它们做回归基准时，务必连着问题一起记。

### 界面上的一点便利：演示模式下开关默认打开

对比页有一个「同时运行两条外部模型路径」的开关，它的职责是**授权花钱**。所以：

| 部署形态 | 开关默认 | 原因 |
|---|---|---|
| 演示通道（`mock`） | **打开** | 不花钱。把它关着只会让"这个功能长什么样"被藏起来——三列变一列，这个页面就没有可看的了 |
| 真实服务商 | 关闭 | 打开就是真的要付费，必须显式同意 |

> 这个默认值是被一个真实问题逼出来的：接入演示通道之后，`available` 从 `false` 变成 `true`，
> 于是默认请求从"三条路径"缩成"只有本地路径"——页面看上去**功能变少了**。
> 代码里 `paths` 的条件因此多了一个 `demoMode`（`allowExternal || !externalAvailable || demoMode`），
> 即使状态查询还没返回、开关还没渲染成打开，请求本身也是对的。

---

## 九、密钥是怎么被对待的

| 场景 | 处理 |
|---|---|
| 对外返回 | 永不出现在任何响应里。`/llm/status` 只返回 `key_masked`，形如 `sk-a****91c4` |
| 短密钥 | 全部打码。10 个字符的密钥只露两头就基本等于明文了 |
| 日志 | 只记录 `provider` / `model` / token 数 / 耗时 / 失败类型，不记录密钥 |
| 版控 | `.env` 在 `.gitignore` 里；仓库里只有 `.env.example` |
| 前端 | 密钥从不进入浏览器。所有调用都在服务端发出 |

`GET /api/v1/llm/providers` 是**公开**的——它只有公开的 base URL 和说明文字，不需要登录就能看，
这样还没配置的人也能先了解有哪些选择。`/llm/status` 和 `/llm/test` 需要登录：
前者暴露部署的配置形状，后者会花掉真实的（虽然极少的）token。

---

## 十、代码地图

| 文件 | 职责 |
|---|---|
| `backend/app/services/llm_providers.py` | 服务商预设表、`resolve()` 优先级规则、密钥打码、`classify_error()` 错误分类全景 |
| `backend/app/services/llm_mock.py` | 进程内 OpenAI 兼容传输：请求/响应格式、演示答案生成、故障注入（`LLM_MOCK_FAULT`） |
| `backend/app/services/llm_gateway.py` | 唯一出口。客户端按配置变化重建、四道闸门、用量记账、`probe()` 探活 |
| `backend/app/api/v1/llm.py` | `/llm/providers`、`/llm/status`、`/llm/test` |
| `backend/app/core/config.py` | `LLM_PROVIDER` / `LLM_MAX_COMPARE_MODELS` / `LLM_MOCK_FAULT`，以及 `SECRET_KEY` 占位值检测 |
| `backend/app/services/qa_compare.py` | `_clean_models()`、按模型分发、每列带上 `provider` / `model` / `is_mock` |
| `backend/tests/test_llm_providers.py` | 146 个用例：预设与优先级、错误分类、演示传输、缓存作用域、多模型对比、三个端点 |

---

## 十一、别搞混的几件事

| 容易误判的现象 | 真相 |
|---|---|
| 外部路径 `skipped`、费用 ¥0 | 没配密钥是**设计行为**，不是故障。`llm_direct` 是永远不带检索的对照组 |
| 看到「演示」标记但指标齐全 | 演示传输走的是真实代码路径，只有网络层被替换。指标是真的，文字不是模型生成的 |
| 探活失败但 `curl` 能通服务商 | 检查 `LLM_BASE_URL` 是不是还留着上一个服务商的值（见第四节） |
| 换了模型但表里两列一样 | 不该发生。若真出现，检查模型名是否被清洗掉了（`models` 回显里能看到） |
| `external_calls` 比模型数少 | 命中缓存了。看 `summary.cache_hits` |
| 用 `zhipu` 时费用显示 ¥0 | `glm-4-flash` 目前免费，不是计算错误 |
| 演示模式下"外部路径"开关默认是打开的 | 故意的：它不花钱，关着只会把功能藏起来。真实服务商时默认关闭 |
| 所有调用都失败，配置却没问题 | 看是否有 `LLM_MOCK_FAULT`（面板会提示）。清空后重启即可 |
| `LLM_BASE_URL` 改了但请求还发往老地址 | 命名服务商**忽略**它（见第四节）。要自定义地址请设 `LLM_PROVIDER=custom` |
