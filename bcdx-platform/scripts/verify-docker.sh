#!/usr/bin/env bash
# --------------------------------------------------------------------------- #
# BC-Dx Platform — Docker 部署后自检
#
#   docker compose up --build -d
#   ./scripts/verify-docker.sh
#
# 为什么需要它：容器里的失败几乎都伪装成别的问题——知识库没进镜像表现为
# "问答全部拒答"，nginx 缺 /health 规则表现为 "Unexpected token '<'"，
# CORS 配错表现为网络错误。这个脚本一项一项打出来，让你知道到底哪里断了。
#
# 依赖：bash + curl（Windows 用 Git Bash 即可）
# 全部检查都不调用外部大模型，因此不产生任何费用。
# --------------------------------------------------------------------------- #

set -uo pipefail

BASE=${BASE:-http://localhost:8080}     # 前端（nginx）
DIRECT=${DIRECT:-http://localhost:8000} # 后端（直连，用于对照）
CURL="curl -sS --noproxy '*'"

PASS=0
FAIL=0

ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$1";
        [ -n "${2:-}" ] && printf '        -> %s\n' "$2"; FAIL=$((FAIL + 1)); }
note() { printf '        %s\n' "$1"; }

echo
echo "BC-Dx 部署自检  ——  $BASE"
echo "--------------------------------------------------------------"

# -- 1. 前端首页 ------------------------------------------------------------ #
html=$($CURL --max-time 15 "$BASE/" 2>/dev/null)
if printf '%s' "$html" | grep -q 'id="root"'; then
  ok "前端首页可达，且是 SPA 外壳"
else
  bad "前端首页不可达或不是预期内容" "先跑 docker compose ps 看 frontend 容器是否 up"
fi

# -- 2. /health 必须是 JSON，不能是 HTML --------------------------------------- #
health=$($CURL --max-time 30 "$BASE/health" 2>/dev/null)
case "$health" in
  ""      ) bad "/health 无响应" "后端可能还在加载嵌入模型，首次约需 30–90 秒" ;;
  "<"*    ) bad "/health 返回了 HTML" \
              "nginx 的 location = /health 没生效；它在 /api/v1 之外，被 SPA 的 try_files 兜成了 index.html。前端报错会是 Unexpected token '<'" ;;
  "{"*    ) ok "/health 经 nginx 反代返回 JSON（/health 独立规则生效）" ;;
  *       ) bad "/health 返回了意外内容" "$(printf '%s' "$health" | head -c 120)" ;;
esac

# -- 3. 知识库真的进了镜像 ---------------------------------------------------- #
count=$(printf '%s' "$health" | grep -o '"count":[0-9]*' | head -1 | grep -o '[0-9]*')
oversize=$(printf '%s' "$health" | grep -o '"oversize":[0-9]*' | head -1 | grep -o '[0-9]*')
if [ -n "${count:-}" ] && [ "$count" -ge 190 ] 2>/dev/null; then
  ok "知识库已在容器内建索引（$count 个片段）"
else
  bad "知识库为空或片段数不足（count=${count:-?}）" \
      "构建上下文必须是仓库根；上下文写成 backend/ 时 parents[3] 指不到 /app，现象就是问答全部拒答"
fi
if [ "${oversize:-1}" = "0" ]; then
  ok "切块没有超窗（oversize=0）"
else
  bad "有 $oversize 个片段超出嵌入窗口会被静默截断" "见 docs/KNOWLEDGE_BASE.md"
fi

# -- 4. 混合检索是不是真的在跑 ------------------------------------------------- #
mode=$(printf '%s' "$health" | grep -o '"mode":"[a-z]*"' | head -1 | cut -d'"' -f4)
if [ "$mode" = "hybrid" ]; then
  ok "检索模式 = hybrid（混合检索已启用）"
else
  bad "检索模式 = ${mode:-?}，不是 hybrid" "检查 RAG_HYBRID_ENABLED"
fi

# -- 5. 登录（验证数据库卷与认证链路） ------------------------------------------ #
login=$($CURL --max-time 30 -X POST "$BASE/api/v1/auth/login" \
          -H 'Content-Type: application/json' \
          -d '{"email":"demo@bcdx.dev","password":"demo12345"}' 2>/dev/null)
token=$(printf '%s' "$login" | grep -o '"access_token":"[^"]*' | head -1 | cut -d'"' -f4)
if [ -n "$token" ]; then
  ok "演示账号可登录（数据卷挂载正常）"
else
  bad "登录失败" "$(printf '%s' "$login" | head -c 160)"
  note "若是首次启动，演示账号由后端初始化，等 /health 返回 200 后再试"
fi

# -- 6. 受保护接口（验证鉴权链路） ---------------------------------------------- #
if [ -n "$token" ]; then
  me=$($CURL --max-time 20 -H "Authorization: Bearer $token" \
         "$BASE/api/v1/auth/me" 2>/dev/null)
  if printf '%s' "$me" | grep -q 'demo@bcdx.dev'; then
    ok "带 token 的受保护接口可用（鉴权链路通）"
  else
    bad "受保护接口调用失败" "$(printf '%s' "$me" | head -c 160)"
  fi

  # -- 7. 本地问答（验证检索真能答，且零成本） ---------------------------------- #
  ask=$($CURL --max-time 40 -X POST "$BASE/api/v1/rag/ask" \
          -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
          -d '{"question":"乳腺癌筛查应该多久做一次？","disease":"breast"}' 2>/dev/null)
  if printf '%s' "$ask" | grep -q 'knowledge_base'; then
    ok "本地知识库问答命中（source=knowledge_base，费用 0）"
  elif printf '%s' "$ask" | grep -q 'refusal'; then
    bad "问答被拒答 —— 知识库可能没进容器" "$(printf '%s' "$ask" | head -c 160)"
  else
    bad "问答返回意外结果" "$(printf '%s' "$ask" | head -c 160)"
  fi

  # -- 8. SSE 流式：nginx 有没有缓冲 ------------------------------------------- #
  #  nginx 默认攒够一块才转发。开着缓冲的话，这次请求会一直挂到超时。
  sse=$(timeout 25 $CURL -N --max-time 25 -X POST "$BASE/api/v1/rag/ask/stream" \
          -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
          -d '{"question":"乳腺癌筛查应该多久做一次？","disease":"breast"}' 2>/dev/null)
  if printf '%s' "$sse" | grep -q 'data:'; then
    ok "SSE 流式事件在 25 秒内到达（proxy_buffering off 生效）"
  else
    bad "SSE 在 25 秒内没收到任何事件" \
        "nginx 缺 proxy_buffering off 时会攒住整段流，页面表现为一直转圈不出字"
  fi
fi

# -- 9. 后端直连（对照组） ------------------------------------------------------ #
d=$($CURL --max-time 10 "$DIRECT/health" 2>/dev/null)
if printf '%s' "$d" | grep -q '"status"'; then
  ok "后端直连 :8000 也健康（nginx 与后端都在）"
else
  note "后端直连 :8000 无响应——如果只打算通过 8080 访问，这可以忽略"
fi

# -- 汇总 --------------------------------------------------------------------- #
echo "--------------------------------------------------------------"
printf '  %d 项通过，%d 项失败\n' "$PASS" "$FAIL"
echo
if [ "$FAIL" -gt 0 ]; then
  echo "  排障对照表见 docs/DEPLOYMENT.md 第三节"
  exit 1
fi
echo "  部署验证通过。打开 $BASE 即可使用（演示账号 demo@bcdx.dev / demo12345）"
echo
