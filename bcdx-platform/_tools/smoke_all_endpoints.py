"""End-to-end smoke test over every documented endpoint.

Prints one line per request with status, latency and a short verdict, then a
summary of failures. Intended to be read by a human, not asserted on — the
pytest suite is the thing that asserts.

Request contracts worth remembering (they are asymmetric, which is easy to get
wrong):

  POST /api/v1/predict           features: list[float]   positional, in the
                                 order of the disease's `feature_keys`
  POST /api/v1/predict/batch     rows: list[dict[str, float]]  named keys

Run from the repository root:
    C:/Users/ASUS/anaconda3/python.exe _tools/smoke_all_endpoints.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
APP = "http://127.0.0.1:5173"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TOKEN: str | None = None
RESULTS: list[tuple[str, str, int, float, str, bool]] = []


def call(method, path, payload=None, token=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read(), (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as e:
        return e.code, e.read(), (time.perf_counter() - started) * 1000
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode(), (time.perf_counter() - started) * 1000


def check(label, method, path, payload=None, token=None, expect=200, wanted=""):
    """`expect` may be several acceptable codes, e.g. (200, 201)."""
    wanted_codes = expect if isinstance(expect, tuple) else (expect,)
    status, body, ms = call(method, path, payload, token)
    ok = status in wanted_codes
    detail = wanted
    if ok and not wanted:
        try:
            parsed = json.loads(body)
            d = parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
            if isinstance(d, dict):
                detail = "keys=" + ",".join(list(d)[:6])
            elif isinstance(d, list):
                detail = f"list[{len(d)}]"
        except Exception:  # noqa: BLE001
            detail = f"{len(body)} bytes"
    elif not ok:
        detail = body[:200].decode("utf-8", "replace").replace("\n", " ")
    RESULTS.append((label, f"{method} {path}", status, ms, detail, ok))
    print(f"  {'OK ' if ok else 'FAIL'} {label:<32} {status:>3} {ms:7.0f}ms  {detail}")
    return status, body


print("=" * 112)
print("  0. 服务可达性")
print("=" * 112)
for label, url in (("后端 /health", f"{BASE}/health"), ("前端首页", f"{APP}/")):
    try:
        with OPENER.open(url, timeout=8) as r:
            print(f"  OK  {label:<32} {r.status:>3} {len(r.read()):>8} bytes")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {label:<32} ---  {e}")

print()
print("=" * 112)
print("  1. 公开接口（无需登录）")
print("=" * 112)
check("健康检查", "GET", "/health")
check("运行限额", "GET", "/api/v1/meta/limits")
check("模型目录", "GET", "/api/v1/models")
check("乳腺模型详情", "GET", "/api/v1/models/breast")
check("心脏模型详情", "GET", "/api/v1/models/heart")
check("非法病种被拒", "GET", "/api/v1/models/nonexistent", expect=400)
check("知识库来源", "GET", "/api/v1/rag/sources")
check("服务商目录", "GET", "/api/v1/llm/providers")

print()
print("=" * 112)
print("  2. 认证")
print("=" * 112)
st, body = check("登录（演示账号）", "POST", "/api/v1/auth/login",
                 {"email": "demo@bcdx.dev", "password": "demo12345"})
if st == 200:
    TOKEN = json.loads(body)["data"]["access_token"]
    print(f"       -> 拿到 token（{len(TOKEN)} 字符）")
check("错误密码被拒（不泄露账号是否存在）", "POST", "/api/v1/auth/login",
      {"email": "demo@bcdx.dev", "password": "wrong-password"}, expect=401)
check("弱口令被拒", "POST", "/api/v1/auth/register",
      {"email": "smoke-weak@example.com", "password": "short"}, expect=422)
check("当前用户", "GET", "/api/v1/auth/me", token=TOKEN)
check("无 token 访问受保护路由", "GET", "/api/v1/records", expect=401)

print()
print("=" * 112)
print("  3. 预测（核心功能）")
print("=" * 112)

samples_by_disease: dict[str, dict] = {}
for disease in ("breast", "heart"):
    st, body = check(f"真实样本（{disease}）", "GET",
                     f"/api/v1/predict/samples?disease={disease}&n=12", token=TOKEN,
                     wanted=f"rows[{disease}]")
    if st == 200:
        d = json.loads(body)["data"]
        samples_by_disease[disease] = d
        rows = d["rows"]
        pos = sum(1 for r in rows if r["true_label"] == 1)
        print(f"       字段 {len(d['feature_keys'])} 个 · {len(rows)} 行 · "
              f"真标签 阳性 {pos} / 阴性 {len(rows) - pos} · 来源 {d['source']}")

for disease, d in samples_by_disease.items():
    if not d["rows"]:
        continue
    keys = d["feature_keys"]
    row = d["rows"][0]
    vector = [row["features"][k] for k in keys]
    st, body = check(f"单样本预测 + SHAP（{disease}）", "POST", "/api/v1/predict",
                     {"disease": disease, "features": vector}, token=TOKEN)
    if st == 200:
        out = json.loads(body)["data"]
        expl = out.get("explanation") or {}
        print(f"       verdict={out.get('verdict')} "
              f"prob={out.get('positive_prob'):.4f} "
              f"threshold={out.get('threshold')} "
              f"label={out.get('verdict_label')} "
              f"SHAP 贡献 {len(expl.get('contributions') or [])} 项 "
              f"({expl.get('method')})")
        expected = "positive" if row["true_label"] == 1 else "negative"
        match = "一致" if out.get("verdict") == expected else "**不一致**"
        print(f"       与数据集标签（true_label={row['true_label']}）比对：{match}")

    # Batch takes named dicts, not positional lists — the two endpoints differ.
    check(f"批量预测（{disease}）", "POST", "/api/v1/predict/batch",
          {"disease": disease, "rows": [r["features"] for r in d["rows"]]},
          token=TOKEN)

st, body = check("缺特征被拒", "POST", "/api/v1/predict",
                   {"disease": "breast", "features": [1.0]}, token=TOKEN, expect=422)
if st == 422:
    b = json.loads(body)
    print(f"       信封 keys={sorted(b)} · code={b.get('code')} · message={b.get('message')!r}")
check("非有限值被拒", "POST", "/api/v1/predict",
      {"disease": "breast", "features": [float("inf")]}, token=TOKEN, expect=422)

print()
print("=" * 112)
print("  4. 知识库问答")
print("=" * 112)
check("正常提问", "POST", "/api/v1/rag/ask",
      {"question": "BI-RADS 分级是什么意思？", "disease": "breast"}, token=TOKEN)
check("混合检索修复题（Youden）", "POST", "/api/v1/rag/ask",
      {"question": "Youden 指数是怎么用的？", "disease": "breast"}, token=TOKEN)
check("跨病种拒答", "POST", "/api/v1/rag/ask",
      {"question": "冠心病应该如何诊断？", "disease": "breast"}, token=TOKEN)
check("越界拒答", "POST", "/api/v1/rag/ask",
      {"question": "今天天气怎么样？", "disease": "breast"}, token=TOKEN)
check("问候语短路", "POST", "/api/v1/rag/ask",
      {"question": "你好", "disease": "breast"}, token=TOKEN)
check("问答对比（本地路径）", "POST", "/api/v1/rag/compare",
      {"question": "乳腺癌的早期症状有哪些？", "disease": "breast"}, token=TOKEN)
check("对比历史", "GET", "/api/v1/rag/comparisons", token=TOKEN)
check("LLM 用量", "GET", "/api/v1/rag/usage", token=TOKEN)

# History detail + delete, using the newest comparison so it stays self-contained.
st, body, _ = call("GET", "/api/v1/rag/comparisons", token=TOKEN)
if st == 200:
    items = json.loads(body)["data"]
    if items:
        cid = items[0]["id"]
        check("对比详情", "GET", f"/api/v1/rag/comparisons/{cid}", token=TOKEN)

print()
print("=" * 112)
print("  5. 历史记录与大模型接入")
print("=" * 112)
check("预测历史", "GET", "/api/v1/records", token=TOKEN)
check("个人统计", "GET", "/api/v1/records/stats", token=TOKEN)
check("LLM 状态", "GET", "/api/v1/llm/status", token=TOKEN)
st, body = check("LLM 探活", "POST", "/api/v1/llm/test", token=TOKEN)
if st == 200:
    d = json.loads(body)["data"]
    print(f"       ok={d.get('ok')} provider={d.get('provider')} "
          f"error_kind={d.get('error_kind')} error_message={d.get('error_message')}")

print()
print("=" * 112)
print("  6. 流式问答（SSE）")
print("=" * 112)
try:
    req = urllib.request.Request(
        f"{BASE}/api/v1/rag/ask/stream",
        data=json.dumps({"question": "乳腺癌有哪些早期表现？",
                         "disease": "breast"}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with OPENER.open(req, timeout=60) as r:
        chunks, started = [], time.perf_counter()
        while len(chunks) < 40 and time.perf_counter() - started < 30:
            line = r.readline()
            if not line:
                break
            chunks.append(line)
        data_lines = sum(1 for c in chunks if c.startswith(b"data:"))
        events = [c.decode().strip() for c in chunks if c.startswith(b"event:")]
        print(f"  OK  流式问答{'':<29} {r.status:>3}  "
              f"{len(chunks)} 行 · data: {data_lines} · events {events}")
        RESULTS.append(("流式问答", "POST /api/v1/rag/ask/stream", r.status, 0.0,
                        f"{data_lines} data 行", True))
except Exception as e:  # noqa: BLE001
    print(f"  FAIL 流式问答{'':<29} ---  {e}")
    RESULTS.append(("流式问答", "POST /api/v1/rag/ask/stream", 0, 0.0, str(e)[:150], False))

print()
print("=" * 112)
print("  总结")
print("=" * 112)
bad = [r for r in RESULTS if not r[5]]
print(f"  共 {len(RESULTS)} 条请求，非预期结果 {len(bad)} 条")
for label, path, status, ms, detail, _ in bad:
    print(f"    FAIL {label:<30} {path:<42} {status}  {detail}")
if not bad:
    print("  全部符合预期。")
sys.exit(1 if bad else 0)
