# 部署：Docker / Compose 一键启动

> 对应优化项 [`OPTIMIZATION_BACKLOG.md`](OPTIMIZATION_BACKLOG.md) 第 3 条。
> 本地开发（不起容器）的启动方式见 [`QUICKSTART.md`](QUICKSTART.md)。

这份文档不只给命令，更重要的是解释**每个看起来奇怪的配置在防什么**。容器里的失败往往表现为
"页面白屏"或"请求失败"，而真正的原因在三层之外——把原因写下来，排障才有方向。

---

## 一、一句话启动

```bash
cp .env.example .env        # 首次需要
docker compose up --build
```

然后打开 <http://localhost:8080>。后端接口文档在 <http://localhost:8000/docs>。

首次启动慢，因为在下载约 470 MB 的句向量模型。之后由命名卷 `hf-cache` 缓存，重启是秒级的。

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 | <http://localhost:8080> | nginx 托管静态产物，并反向代理 `/api/` 与 `/health` |
| 后端 | <http://localhost:8000> | FastAPI；`/health` 可直接开浏览器看 |

常用变体：

```bash
docker compose up --build          # 构建并前台启动（能看日志，Ctrl+C 停）
docker compose up --build -d       # 后台启动
docker compose logs -f backend     # 只看后端日志
docker compose down                # 停并删容器（**数据卷保留**）
docker compose down -v             # 连数据卷一起删（账号与历史会清空）
docker compose build --no-cache    # 依赖换了之后强制重来
```

### 启动之后：跑一次自检

```bash
# Linux / macOS / Git Bash
./scripts/verify-docker.sh
```

```powershell
# Windows PowerShell（推荐用这个，输出是原生彩色）
powershell -ExecutionPolicy Bypass -File .\scripts\verify-docker.ps1
```

它会打 10 项检查：前端首页、`/health` 经 nginx 反代后**是不是 JSON**、知识库片段数与超窗数、
检索模式、演示账号登录、受保护接口、本地问答命中、**SSE 是否在 25 秒内真的流出事件**、后端直连。
全部通过会打印部署地址，有一项失败就退出码 1 并指向下面的排障表。

> Windows 首次使用请先看**第五节**——Docker Desktop 怎么装，以及三个和 Docker 本身无关的坑
> （目录层级、`.sh` 在 PowerShell 里跑不了、PowerShell 传 JSON 给 curl 会坏）。

自检脚本存在的理由和这份文档一样：**容器里的失败几乎都伪装成别的问题**。
比如第 3 项（知识库 190 片段）挂掉，实际原因几乎肯定是构建上下文写错，
但你在页面上只会看到"问什么都拒答"。

> 脚本本身验证过：它的断言逻辑（`count` / `oversize` / `mode` / `access_token` / `data:` 等字段的提取）
> 已在一台真实运行的后端上跑通 9/10。**唯一没验证的是它前面那层 nginx** ——
> 也就是恰恰只有装了 Docker 的机器才能验的那部分。

---

## 二、两个镜像分别在做什么

```
仓库根（构建上下文）
├── backend/Dockerfile   →  python:3.12-slim
│                           装 CPU 版 torch → 装 requirements → 复制代码
│                           → 构建期跑 ml/pipelines/train.py → uvicorn
├── frontend/Dockerfile  →  阶段 1 node:20-alpine（npm ci + npm run build）
│                           阶段 2 nginx:1.27-alpine（只带 dist/）
└── docker-compose.yml      把两者接起来，挂两个卷，做健康检查
```

### 2.1 构建上下文是**仓库根**，不是 `backend/`

这是本项目最容易改错的一处。后端是这样定位自己的资源的：

```python
# backend/app/core/config.py
REPO_ROOT = Path(__file__).resolve().parents[3]     # → 仓库根
registry_path = REPO_ROOT / "ml" / "registry" / "registry.json"
knowledge_dir = REPO_ROOT / "knowledge" / "sources"
```

`train.py` 用的是 `parents[2]`，指向同一个根。也就是说**镜像内部必须复刻仓库的目录形状**：

| 容器内路径 | 宿主机对应 |
|---|---|
| `/app/backend` | `backend/`（运行时工作目录） |
| `/app/ml` | `ml/`（训练流水线 + 模型产物） |
| `/app/knowledge` | `knowledge/`（190 个检索片段的语料） |
| `/app/docs` | `docs/`（训练会写 `MODEL_CARD.md`） |

如果两个 Dockerfile 改成 `context: ./backend`，`parents[3]` 会指到一个不存在的目录，
知识库是空的、模型加载不出来，而报错会表现为"问答全部拒答"——**完全不像路径问题**。

### 2.2 torch 必须**先于** requirements 装

```
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install -r ./backend/requirements.txt
```

`sentence-transformers` 依赖 torch，而 PyPI 上的默认 wheel 带 CUDA，体积是几个 GB。
先从 PyTorch 的 CPU 源装好，后面 `pip install -r` 会发现 torch 已满足而不再替换它。

> 网络访问不了 `download.pytorch.org` 时，把那一行删掉也能构建成功，只是镜像会大很多。

### 2.3 模型在**构建期**训练，不在启动期

```
RUN python ml/pipelines/train.py
```

`ml/registry/models/*.joblib` 是 gitignore 的，所以新克隆的仓库没有任何模型产物。
训练完全离线、有固定随机种子，输入是已提交的 CSV —— 这和 CI 里做的事一模一样。
6 个产物一共约 2.4 MB，这一步只花几秒。

放在构建期而不是启动期，是为了让**镜像自包含**：不依赖宿主机上碰巧存在的文件，
也不会出现"第一次访问要等训练"这种难以解释的延迟。

### 2.4 数据库用**绝对路径**并挂在卷上

```yaml
DATABASE_URL: sqlite+pysqlite:////data/bcdx.db
volumes:
  - bcdx-data:/data
```

注意 `//data/bcdx.db` 里是**四个斜杠**：两个是 `scheme://` 的分隔，剩下两个才是绝对路径的根。
应用自己的默认值是相对的 `./bcdx.db`——在容器里那会落进镜像的可写层，
每次重建容器账号和历史就都没了，而现象只是"我明明注册过"。

### 2.5 `CORS_ORIGINS` 必须和发布端口一致

```yaml
CORS_ORIGINS: http://localhost:8080,http://127.0.0.1:8080
```

浏览器发请求前会先做 CORS 预检。端口不在白名单里的话，请求**根本到不了应用**，
控制台显示的是网络错误而不是 403——这就是它难查的原因。

改端口时两处要同步改：`ports` 里的 `8080:80` 和这里的 `CORS_ORIGINS`。

### 2.6 前端用 nginx 而不是 `npm run dev`

`vite.config.ts` 里那两条代理（`/api` 与 `/health`）**只在 dev server 里存在**。
生产构建产出的是纯静态文件，没有 Node 进程可跑代理，所以这两条路由必须由 nginx 承担：

```nginx
location /api/    { proxy_pass http://backend:8000; proxy_buffering off; ... }
location = /health { proxy_pass http://backend:8000; ... }
location /        { try_files $uri $uri/ /index.html; }   # SPA 回退
```

三个细节：

- **`/health` 必须单独写一条**。它在 `/api/v1` 之外，不会被 `location /api/` 匹配到；
  而它又被 `location /` 的 `try_files` 兜住，于是不转发的话会返回 `index.html`，
  前端的健康检查拿到一段 HTML，报错是 `Unexpected token '<'`。
- **`proxy_buffering off` 是流式问答必需的**。nginx 默认攒够一块才转发，
  SSE 的事件流会被攒住，页面表现为"一直在转圈但一个字都不出"。
- `try_files ... /index.html` 让前端路由（`/qa-compare` 等）在刷新时不 404。

### 2.7 `depends_on` 用 `service_healthy`，不是 `service_started`

后端启动后要花约 30 秒加载嵌入模型并建索引。这段时间它**已经在监听端口**，
但知识库还是空的。`service_started` 只看进程起来了没有，前端会在这半分钟里显示一个坏掉的知识库。

`service_healthy` 读的是 Dockerfile 里的 `HEALTHCHECK`（打 `/health`，有 90 秒宽限期）。

### 2.8 `.env` 不进镜像

`.dockerignore` 的第一行就是 `.env`；运行时由 `env_file` 注入。

这不是洁癖：镜像是分层的，一个 `COPY .` 就算在后面的层里删掉 `.env`，
密钥仍然留在那一层的历史里，`docker history` 就能翻出来。

同理，`.env` 改完**不需要重新构建**，只要 `docker compose restart backend`。

---

## 三、排障表

### 3.1 还没进到容器就失败的（Windows 最常见）

| 现象 | 原因与去处 |
|---|---|
| `docker : 无法将"docker"项识别为 cmdlet、函数、脚本文件或可运行程序的名称` | **没装 Docker Desktop**，或装了但**没有重开终端**（PATH 没刷新）。见 §5.1 |
| `无法将"./scripts/verify-docker.sh"项识别为...` | PowerShell 不认识 `.sh`。用 `& "C:\Program Files\Git\bin\bash.exe" scripts/verify-docker.sh`，或改用 `.ps1` 版。见 §5.3 |
| `无法加载文件 ... 因为在此系统上禁止运行脚本` | PowerShell 执行策略。用 `powershell -ExecutionPolicy Bypass -File .\scripts\verify-docker.ps1`，不要改系统设置。见 §5.3 |
| `no configuration file provided: not found` | **当前目录不是仓库根**。`docker compose` 只找当前目录的 `docker-compose.yml`，先 `cd ...\bcdx-platform`。见 §5.2 |
| Docker Desktop 起不来，报 WSL2 / 虚拟化相关错误 | BIOS 里的虚拟化（VT-x / AMD-V）没开。任务管理器 → 性能 → CPU → 右下角"虚拟化"。见 §5.1 |
| 手动 curl 调接口收到 `JSON decode error` | PowerShell 向原生 exe 传参时不转义内嵌双引号。改用 `Invoke-RestMethod` 或 `--data-binary "@文件"`。见 §5.4 |

### 3.2 进了容器之后失败的

| 现象 | 最常见的原因 |
|---|---|
| 页面能开，但所有问答都"没有找到依据" | 构建上下文不是仓库根 → `knowledge/` 没进镜像。看日志里有没有 `RAG index built: 190 vectors` |
| 控制台 `Unexpected token '<'` | nginx 的 `location = /health` 规则没生效，健康检查拿到了 `index.html` |
| 请求在 Network 面板里显示失败、无响应 | `CORS_ORIGINS` 和浏览器实际访问的端口不一致（改过 `8080` 的话先查这个） |
| 流式问答一直转圈不出字 | nginx 缺 `proxy_buffering off` |
| 重启容器后账号没了 | `DATABASE_URL` 是相对路径，或 `bcdx-data` 卷没挂上 |
| 首次启动卡很久 | 在下载 470 MB 的嵌入模型，正常的；第二次开始由 `hf-cache` 卷缓存 |
| `docker compose up` 报找不到 `.env` | 还没 `cp .env.example .env` |
| 预测页报"模型不存在" | 构建期训练没跑成功；`docker compose logs backend` 里搜 `train` |

---

## 四、改配置与数据

| 想改什么 | 怎么做 |
|---|---|
| 端口 | `docker-compose.yml` 的 `8080:80` **和** `CORS_ORIGINS` 一起改 |
| 大模型密钥 | 编辑仓库根 `.env` → `docker compose restart backend`（不用重新构建） |
| 用演示通道（不花钱、不出网） | `.env` 里 `LLM_PROVIDER=mock` + `LLM_ENABLED=true` → 重启后端 |
| 清空账号与历史 | `docker compose down -v`（删卷） |
| 只重建一个服务 | `docker compose up --build backend` |
| 进容器里看 | `docker compose exec backend bash` |

---

## 五、Windows：装 Docker Desktop 与前三个必踩的坑

这一节是针对"在 Windows 上第一次跑"写的。前两个坑与 Docker 本身无关，但在你看到任何容器错误之前就会先撞上。

### 5.1 先装 Docker Desktop

Windows 上 `docker` 不是系统自带的，要先装 **Docker Desktop**（它同时提供 `docker` 命令、compose v2 和 Linux 虚拟机）：

1. 下载：<https://www.docker.com/products/docker-desktop/>（选 Windows / AMD64）
2. 安装时勾选 **Use WSL 2 instead of Hyper-V**（推荐）
3. 装完**重启**，然后启动 Docker Desktop，等左下角鲸鱼图标变成 **Engine running**
4. 开一个新终端验证：

```powershell
docker --version
docker compose version
```

> 装之前先确认虚拟化是开的。任务管理器 → 性能 → CPU，右下角"虚拟化"应为**已启用**。
> 显示"已禁用"的话要进 BIOS/UEFI 打开 VT-x / AMD-V，否则 Docker Desktop 起不来，
> 而它的报错会是"WSL2 安装不完整"这类看不出根因的话。
>
> Docker Desktop 对个人使用、教育用途免费。公司规模超过一定门槛需要付费订阅，自己拿捏。

### 5.2 坑一：必须在**仓库根目录**执行

`docker compose` 只在**当前目录**找 `docker-compose.yml`。仓库根是 `bcdx-platform\`，不是它的父目录：

```powershell
cd C:\Users\ASUS\Desktop\毕设优化\bcdx-platform      # 注意要进到 bcdx-platform
docker compose up --build -d
```

在 `C:\Users\ASUS\Desktop\毕设优化` 这一层执行会报 `no configuration file provided: not found`。
看到这个错误先 `Get-Location` 确认自己在哪一层。

### 5.3 坑二：PowerShell 里不能直接 `./scripts/xxx.sh`

PowerShell 不认识 `.sh`。两种跑法，任选一种：

```powershell
# 方式 A —— 用 Git 自带的 bash（本机已装，路径固定）
& "C:\Program Files\Git\bin\bash.exe" scripts/verify-docker.sh

# 方式 B —— 直接用 PowerShell 版（推荐，输出是原生彩色，字段解析更严）
powershell -ExecutionPolicy Bypass -File .\scripts\verify-docker.ps1
```

**为什么要带 `-ExecutionPolicy Bypass`**：Windows 默认禁止运行 `.ps1` 脚本，
直接双击或 `.\scripts\verify-docker.ps1` 会报"在此系统上禁止运行脚本"。
上面的写法只对**这一次调用**放行，不改系统设置——比 `Set-ExecutionPolicy Unrestricted` 安全得多。

两个脚本做的事完全一样（10 项检查），任选其一即可。

### 5.4 坑三：PowerShell 传 JSON 给 curl 会坏掉

这条不影响你执行命令，但值得知道——因为它是**我自己写脚本时踩到的**，而且报错极具误导性。

用 `curl -d '{"email":"..."}'` 在 PowerShell 里发请求，后端会回：

```json
{"code":1001,"message":"Validation failed: ... JSON decode error"}
```

看起来像后端坏了，实际是 **Windows PowerShell 5.1 把参数交给原生 exe 时，不为内嵌的双引号做转义**，
curl.exe 收到的 JSON 引号被剥掉了。

`verify-docker.ps1` 里的处理办法是：**把请求体写进临时文件，用 `--data-binary "@文件"` 传**，
绕开整条转义链。所以你在脚本输出里看到中文请求（"乳腺癌筛查应该多久做一次？"）也能正常发出去。

> 如果你自己想用 PowerShell 手敲 curl 调接口，记得走同样的路子，
> 或者干脆用 `Invoke-RestMethod`（PowerShell 原生，没有这个引号问题）。

### 5.5 完整操作顺序（复制粘贴即可）

```powershell
# 1. 进仓库根
cd C:\Users\ASUS\Desktop\毕设优化\bcdx-platform

# 2. 准备配置（.env 是 gitignore 的，新克隆没有）
Copy-Item .env.example .env

# 3. 构建并后台启动（首次约 3–8 分钟，含下载 470 MB 模型）
docker compose up --build -d

# 4. 等后端就绪（约 30–90 秒），然后自检
powershell -ExecutionPolicy Bypass -File .\scripts\verify-docker.ps1

# 5. 打开 http://localhost:8080   （演示账号 demo@bcdx.dev / demo12345）

# 用完停掉（数据卷保留）
docker compose down
```

如果第 4 步有 FAIL，把整段输出贴给我，我照着第三节的排障表逐条看。

---

## 六、已知限制（如实说明）

- **这套配置在本机没有实机构建过** —— 写它的机器上没有安装 Docker。
  已完成的是静态校验：Compose 文件能被 YAML 解析、nginx 配置的括号与四条关键指令齐全、
  并用脚本模拟过容器内 `REPO_ROOT` 的解析结果（确认 `config.py` 的 `parents[3]` 与
  `train.py` 的 `parents[2]` 在 `/app` 布局下都指向 `/app`）。
  **第一次 `docker compose up --build` 请在一台装了 Docker 的机器上跑，并把输出留着对照。**
- SQLite + 单 uvicorn 进程。够用，但**不适合多副本**（限流器是进程内内存实现）。
  要横向扩展就得换数据库和共享缓存，不在本项目范围内。
- 镜像里跑的是 CPU 推理；`faiss-cpu` + `sentence-transformers` 在小语料上完全够（检索约 25 ms）。
- 没有 HTTPS。放到公网前面需要再加一层反代或隧道。

---

## 七、相关文件

| 文件 | 职责 |
|---|---|
| `scripts/verify-docker.sh` | **部署后自检（bash 版）**：10 项检查，一项失败就退出码 1。Linux / macOS / Git Bash |
| `scripts/verify-docker.ps1` | **部署后自检（PowerShell 版）**：同样 10 项，给 Windows 用。UTF-8 BOM + CRLF，中文输出不乱码 |
| `docker-compose.yml` | 两个服务、两个卷、端口与健康检查依赖 |
| `backend/Dockerfile` | 后端镜像：CPU torch → 依赖 → 构建期训练 → uvicorn |
| `frontend/Dockerfile` | 前端镜像：node 构建 → nginx 托管 |
| `frontend/nginx.conf` | `/api/` 与 `/health` 反代、SPA 回退、SSE 不缓冲、静态资源缓存 |
| `.dockerignore` | 把 `.env`、模型产物、截图与开发工具挡在构建上下文之外 |
| `.env.example` | 配置模板（`SECRET_KEY` 在生产环境会用占位检测拒绝启动） |
