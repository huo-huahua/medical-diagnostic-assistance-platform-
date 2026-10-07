#Requires -Version 5.1
<#
  BC-Dx Platform — Docker 部署后自检（Windows / PowerShell 版）

  用法（先确认你在仓库根目录，即 docker-compose.yml 所在的那一层）：

    cd C:\Users\ASUS\Desktop\毕设优化\bcdx-platform
    powershell -ExecutionPolicy Bypass -File .\scripts\verify-docker.ps1

  如果提示"禁止运行脚本"，就是执行策略的问题 —— 上面命令里的
  -ExecutionPolicy Bypass 已经绕过了，不用去改系统设置。

  为什么需要它：容器里的失败几乎都伪装成别的问题 —— 知识库没进镜像表现为
  "问什么都拒答"，nginx 缺 /health 规则表现为 "Unexpected token '<'"，
  CORS 配错表现为网络错误。这个脚本一项项打出来，让你知道到底哪里断了。

  全部检查都不调用外部大模型，因此不产生任何费用。
  依赖：Windows 自带的 curl.exe（Win10 1803+ 都有）。
#>

[CmdletBinding()]
param(
    [string]$Base   = 'http://localhost:8080',   # 前端（nginx）
    [string]$Direct = 'http://localhost:8000'    # 后端（直连，用于对照）
)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

# curl.exe 输出的 UTF-8（后端的错误消息里有中文）要按 UTF-8 读，否则控制台上是乱码。
# 判断逻辑只依赖 ASCII 字段，所以这纯粹是可读性问题。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$script:PassCount = 0
$script:FailCount = 0

function Write-Ok {
    param([string]$Message)
    Write-Host ('  PASS  ' + $Message) -ForegroundColor Green
    $script:PassCount++
}
function Write-Bad {
    param([string]$Message, [string]$Hint)
    Write-Host ('  FAIL  ' + $Message) -ForegroundColor Red
    $script:FailCount++
    if ($Hint) { Write-Host ('        -> ' + $Hint) -ForegroundColor DarkGray }
}
function Write-Note {
    param([string]$Message)
    Write-Host ('        ' + $Message) -ForegroundColor DarkGray
}

# 统一走这里发请求。--noproxy '*' 是必需的：本机代理会拦 localhost。
function Invoke-Curl {
    param(
        [string]$Url,
        [string]$Method = 'GET',
        [string[]]$Headers = @(),
        [string]$Body = $null,
        [int]$TimeoutSec = 15,
        [switch]$Stream
    )
    $curlArgs = @('-sS', '--noproxy', '*', '--max-time', "$TimeoutSec", '-X', $Method)
    if ($Stream) { $curlArgs += '-N' }
    foreach ($h in $Headers) { $curlArgs += @('-H', $h) }

    # 请求体走临时文件，而不是 -d '{...}' 直接传参。
    #
    # 原因：Windows PowerShell 5.1 把参数交给原生 exe 时，不会为内嵌的双引号做
    # 反斜杠转义，curl.exe 收到的 JSON 引号被剥掉，后端返回
    # "JSON decode error" —— 看起来像后端坏了，其实是 shell 这一层。
    # 写成文件用 @file 传，绕开整条转义链，中文也不会被代码页破坏。
    $bodyFile = $null
    if ($Body) {
        $bodyFile = Join-Path $env:TEMP ("bcdx-verify-{0}-{1}.json" -f $PID, [Guid]::NewGuid().ToString('N').Substring(0, 8))
        [System.IO.File]::WriteAllText($bodyFile, $Body, (New-Object System.Text.UTF8Encoding $false))
        $curlArgs += @('--data-binary', "@$bodyFile")
    }
    $curlArgs += $Url

    try {
        $out = & curl.exe @curlArgs 2>$null
        if ($null -eq $out) { return '' }
        return ($out -join "`n")
    } finally {
        if ($bodyFile -and (Test-Path $bodyFile)) { Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue }
    }
}

function Test-Reachable {
    param([string]$Url)
    # curl 对连不上的地址返回非 0；这里只关心"有没有响应体"
    $r = Invoke-Curl -Url $Url -TimeoutSec 5
    return ($r.Length -gt 0)
}

Write-Host ''
Write-Host "BC-Dx 部署自检  ——  $Base"
Write-Host ('-' * 62)

# 前置：先把最容易犯的两个错直接指出来，省得看着 10 个 FAIL 发懵
if (-not (Test-Path '.\docker-compose.yml')) {
    Write-Host '  [X] 当前目录下没有 docker-compose.yml' -ForegroundColor Yellow
    Write-Note ('当前目录: ' + (Get-Location).Path)
    Write-Note '请先进入仓库根目录：cd C:\Users\ASUS\Desktop\毕设优化\bcdx-platform'
    Write-Host ''
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '  [X] 找不到 docker 命令 —— 本机可能还没装 Docker Desktop' -ForegroundColor Yellow
    Write-Note '安装与首次启动步骤见 docs\DEPLOYMENT.md 第五节'
    Write-Host ''
}

# -- 1. 前端首页 ------------------------------------------------------------ #
$html = Invoke-Curl -Url "$Base/" -TimeoutSec 15
if ($html -match 'id="root"') {
    Write-Ok '前端首页可达，且是 SPA 外壳'
} else {
    Write-Bad '前端首页不可达或不是预期内容' '先跑 docker compose ps 看 frontend 容器是否 up'
}

# -- 2. /health 必须是 JSON，不能是 HTML --------------------------------------- #
$health = Invoke-Curl -Url "$Base/health" -TimeoutSec 30
if ($health.Length -eq 0) {
    Write-Bad '/health 无响应' '后端可能还在加载嵌入模型，首次约需 30–90 秒'
} elseif ($health -match '^\s*<') {
    Write-Bad '/health 返回了 HTML' "nginx 的 location = /health 没生效；它在 /api/v1 之外，被 SPA 的 try_files 兜成了 index.html。前端报错会是 Unexpected token '<'"
} elseif ($health -match '^\s*\{') {
    Write-Ok '/health 经 nginx 反代返回 JSON（/health 独立规则生效）'
} else {
    Write-Bad '/health 返回了意外内容' $health.Substring(0, [Math]::Min(120, $health.Length))
}

# -- 3/4/5. 解析 /health ------------------------------------------------------ #
$h = $null
if ($health -match '^\s*\{') {
    try { $h = $health | ConvertFrom-Json } catch { Write-Note 'health JSON 解析失败，跳过第 3–5 项' }
}

if ($h) {
    $count    = if ($h.rag_chunking) { $h.rag_chunking.count }    else { $null }
    $oversize = if ($h.rag_chunking) { $h.rag_chunking.oversize } else { $null }
    $mode     = if ($h.rag_retrieval) { $h.rag_retrieval.mode }    else { $null }

    if ($null -ne $count -and $count -ge 190) {
        Write-Ok "知识库已在容器内建索引（$count 个片段）"
    } else {
        Write-Bad "知识库为空或片段数不足（count=$count）" '构建上下文必须是仓库根；写成 backend/ 时 parents[3] 指不到 /app，现象就是问答全部拒答'
    }
    if ($oversize -eq 0) {
        Write-Ok '切块没有超窗（oversize=0）'
    } else {
        Write-Bad "有 $oversize 个片段超出嵌入窗口会被静默截断" '见 docs\KNOWLEDGE_BASE.md'
    }
    if ($mode -eq 'hybrid') {
        Write-Ok '检索模式 = hybrid（混合检索已启用）'
    } else {
        Write-Bad "检索模式 = $mode，不是 hybrid" '检查 RAG_HYBRID_ENABLED'
    }
}

# -- 6. 登录（验证数据库卷与认证链路） ------------------------------------------ #
$loginBody = '{"email":"demo@bcdx.dev","password":"demo12345"}'
$login = Invoke-Curl -Url "$Base/api/v1/auth/login" -Method POST `
    -Headers @('Content-Type: application/json') -Body $loginBody -TimeoutSec 30

# 注意：/api/v1 下所有响应都在统一信封里，token 在 data.access_token，
# 不是顶层 access_token。/health 是例外，它是裸的（所以上面直接取 rag_chunking）。
$token = $null
if ($login -match '^\s*\{') {
    try { $token = ($login | ConvertFrom-Json).data.access_token } catch { }
}
if ($token) {
    Write-Ok '演示账号可登录（数据卷挂载正常）'
} else {
    Write-Bad '登录失败' $login.Substring(0, [Math]::Min(160, $login.Length))
    Write-Note '若是首次启动，演示账号由后端初始化，等 /health 返回 200 后再试'
}

# -- 7/8/9. 需要 token 的三项 -------------------------------------------------- #
if ($token) {
    $authHeader = "Authorization: Bearer $token"

    $me = Invoke-Curl -Url "$Base/api/v1/auth/me" -Headers @($authHeader) -TimeoutSec 20
    if ($me -match 'demo@bcdx\.dev') {
        Write-Ok '带 token 的受保护接口可用（鉴权链路通）'
    } else {
        Write-Bad '受保护接口调用失败' $me.Substring(0, [Math]::Min(160, $me.Length))
    }

    $askBody = '{"question":"乳腺癌筛查应该多久做一次？","disease":"breast"}'
    $ask = Invoke-Curl -Url "$Base/api/v1/rag/ask" -Method POST `
        -Headers @($authHeader, 'Content-Type: application/json') -Body $askBody -TimeoutSec 40

    if ($ask -match 'knowledge_base') {
        Write-Ok '本地知识库问答命中（source=knowledge_base，费用 0）'
    } elseif ($ask -match 'refusal') {
        Write-Bad '问答被拒答 —— 知识库可能没进容器' $ask.Substring(0, [Math]::Min(160, $ask.Length))
    } else {
        Write-Bad '问答返回意外结果' $ask.Substring(0, [Math]::Min(160, $ask.Length))
    }

    # SSE：nginx 默认攒够一块才转发。开着缓冲的话，这次请求会一直挂到超时。
    $sse = Invoke-Curl -Url "$Base/api/v1/rag/ask/stream" -Method POST `
        -Headers @($authHeader, 'Content-Type: application/json') -Body $askBody `
        -TimeoutSec 25 -Stream
    if ($sse -match 'data:') {
        Write-Ok 'SSE 流式事件在 25 秒内到达（proxy_buffering off 生效）'
    } else {
        Write-Bad 'SSE 在 25 秒内没收到任何事件' 'nginx 缺 proxy_buffering off 时会攒住整段流，页面表现为一直转圈不出字'
    }
}

# -- 10. 后端直连（对照组） ----------------------------------------------------- #
$d = Invoke-Curl -Url "$Direct/health" -TimeoutSec 10
if ($d -match '"status"') {
    Write-Ok '后端直连 :8000 也健康（nginx 与后端都在）'
} else {
    Write-Note '后端直连 :8000 无响应 —— 如果只打算通过 8080 访问，这可以忽略'
}

# -- 汇总 --------------------------------------------------------------------- #
Write-Host ('-' * 62)
Write-Host ("  $script:PassCount 项通过，$script:FailCount 项失败")
Write-Host ''
if ($script:FailCount -gt 0) {
    Write-Host '  排障对照表见 docs\DEPLOYMENT.md 第三节' -ForegroundColor Yellow
    exit 1
}
Write-Host "  部署验证通过。打开 $Base 即可使用（演示账号 demo@bcdx.dev / demo12345）" -ForegroundColor Green
Write-Host ''
exit 0
