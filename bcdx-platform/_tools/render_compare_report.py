"""Render one real `/api/v1/rag/compare` result as a standalone HTML report.

Why a script rather than hand-written HTML: the whole value of the artefact is
that the three answers are *verbatim* what the running system returned. Typing
them out by hand is where a quote quietly stops matching the source.

Usage:
    python _tools/render_compare_report.py <compare.json> [out.html]

Input is the `data` object of a `POST /api/v1/rag/compare` response (see
`_tools/smoke_all_endpoints.py` for how to produce one, or export it from the
comparison page).
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

#: Keys of `summary` worth showing, in display order.
SUMMARY_ROWS = [
    ("外部调用次数", "external_calls"),
    ("缓存命中", "cache_hits"),
    ("提示 token", "prompt_tokens"),
    ("生成 token", "completion_tokens"),
    ("合计费用（元）", "cost_cny"),
    ("有出处的路径", "grounded_paths"),
    ("无出处的路径", "ungrounded_paths"),
    ("大模型可用", "llm_available"),
    ("演示通道（未真实计费）", "demo_mode"),
]

PATH_ORDER = ["local_rag", "llm_direct", "llm_rag"]


# --------------------------------------------------------------------------- #
# Very small markdown subset -> HTML. The answers use `##`, `-`, `**` and
# `[^cN]` citation markers; a full markdown library is not worth the dependency
# for that.
# --------------------------------------------------------------------------- #

_CITE = re.compile(r"\[\^c(\d+)\]")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def render_inline(text: str) -> str:
    out = html.escape(text)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _CITE.sub(r"<sup class=\"cite\">[\1]</sup>", out)
    return out


def render_answer(text: str) -> str:
    """Turn an answer into HTML: headings, bullet lists, paragraphs."""
    if not text:
        return '<p class="empty">（该路径未产生回答）</p>'

    parts: list[str] = []
    in_list = False

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue

        if line.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h4>{render_inline(line[3:])}</h4>")
        elif line.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{render_inline(line[2:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{render_inline(line[2:])}</li>")
        elif line.startswith("---"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<hr>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p>{render_inline(line)}</p>")

    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def fmt_cost(value: float) -> str:
    return f"¥{value:.6f}".rstrip("0").rstrip(".")


def path_card(path: dict) -> str:
    key = path["key"]
    badge = ""
    if path.get("external_call"):
        badge += '<span class="tag tag-pay">外部付费调用</span>'
    else:
        badge += '<span class="tag tag-free">零成本</span>'
    badge += '<span class="tag tag-ground">有出处</span>' if path.get("citation_count") else '<span class="tag tag-unground">无出处</span>'
    if path.get("is_mock"):
        badge += '<span class="tag tag-demo">演示通道</span>'

    model = path.get("model") or "—"
    provider = path.get("provider") or "本地"
    overlap = path.get("lexical_overlap") or 0.0
    overlaps = f"{overlap:.0%}"
    risk = path.get("risk_phrases") or []

    return f"""
      <article class="card card-{key}">
        <header>
          <h3>{html.escape(path['label'])}</h3>
          <code>{html.escape(key)}</code>
        </header>
        <div class="tags">{badge}</div>
        <p class="desc">{html.escape(path.get('description', ''))}</p>
        <dl class="metrics">
          <div><dt>延迟</dt><dd>{path['latency_ms']} ms</dd></div>
          <div><dt>token</dt><dd>{path['prompt_tokens']} + {path['completion_tokens']}</dd></div>
          <div><dt>费用</dt><dd>{fmt_cost(path.get('cost_cny', 0.0))}</dd></div>
          <div><dt>字数</dt><dd>{path.get('answer_chars', 0)}</dd></div>
          <div><dt>引用</dt><dd>{path.get('citation_count', 0)}</dd></div>
          <div><dt>与检索片段词面重合</dt><dd>{overlaps}</dd></div>
          <div><dt>上游</dt><dd>{html.escape(provider)} / {html.escape(str(model))}</dd></div>
          <div><dt>状态</dt><dd>{html.escape(path.get('status', ''))}</dd></div>
        </dl>
        {f'<p class="risk">命中风险表述：{html.escape("、".join(risk))}</p>' if risk else ''}
        <div class="answer">{render_answer(path.get('answer'))}</div>
      </article>"""


def citations_block(citations: list[dict]) -> str:
    if not citations:
        return ""
    rows = "\n".join(
        f"""<li><span class="idx">[{html.escape(str(c['index']))}]</span>
            <span class="ttl">{html.escape(c['title'])}</span>
            <span class="src">{html.escape(c['source'])}</span>
            <span class="score">{c['score']:.4f}</span></li>"""
        for c in citations
    )
    return f"""
    <section>
      <h2>检索到的出处（三条路径共用同一次检索）</h2>
      <ol class="cites">{rows}</ol>
    </section>"""


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d23;--muted:#5c6472;--line:#e3e6ec;
--accent:#2563eb;--local:#0d9488;--direct:#c2410c;--rag:#7c3aed;}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--bg);color:var(--ink);
font:15px/1.75 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:19px;margin:44px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line)}
h3{font-size:16px;margin:0}
h4{font-size:15px;margin:18px 0 6px;color:var(--accent)}
.sub{color:var(--muted);margin:0 0 22px}
.question{background:#fff;border:1px solid var(--line);border-left:4px solid var(--accent);
border-radius:8px;padding:16px 20px;font-size:18px;font-weight:600;margin-bottom:8px}
.meta{color:var(--muted);font-size:13px;margin-bottom:4px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);
border-radius:8px;overflow:hidden;font-size:14px}
th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--line)}
th{background:#f0f2f6;font-weight:600;width:220px}
tr:last-child td,tr:last-child th{border-bottom:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px;margin-top:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;
display:flex;flex-direction:column;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.card header{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.card header code{font-size:12px;color:var(--muted);background:#f0f2f6;padding:2px 6px;border-radius:4px}
.card-local_rag{border-top:3px solid var(--local)}
.card-llm_direct{border-top:3px solid var(--direct)}
.card-llm_rag{border-top:3px solid var(--rag)}
.tags{margin:10px 0 8px;display:flex;gap:6px;flex-wrap:wrap}
.tag{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
.tag-pay{background:#fff2e8;border-color:#fcd9bd;color:#c2410c}
.tag-free{background:#e9f7f4;border-color:#bfe6de;color:#0d9488}
.tag-ground{background:#f1effd;border-color:#ddd6fb;color:#7c3aed}
.tag-unground{background:#f4f5f7}
.tag-demo{background:#fffbe6;border-color:#fbe38a;color:#8a6100}
.desc{color:var(--muted);font-size:13px;margin:0 0 14px}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;margin:0 0 14px;font-size:13px}
.metrics div{display:flex;justify-content:space-between;gap:8px;border-bottom:1px dotted var(--line);padding-bottom:3px}
.metrics dt{color:var(--muted);margin:0}
.metrics dd{margin:0;font-variant-numeric:tabular-nums;font-weight:600}
.risk{background:#fff8e6;border:1px solid #fbe38a;border-radius:6px;padding:6px 10px;font-size:12px;margin:0 0 12px}
.answer{flex:1;font-size:14px;overflow-wrap:anywhere}
.answer p{margin:8px 0}
.answer ul{margin:8px 0;padding-left:22px}
.answer li{margin:4px 0}
.answer hr{border:0;border-top:1px solid var(--line);margin:14px 0}
.answer h3:first-child,.answer h4:first-child{margin-top:0}
.empty{color:var(--muted);font-style:italic}
sup.cite{font-size:10px;color:var(--accent);font-weight:700}
.cites{list-style:none;padding:0;margin:0;font-size:13px}
.cites li{display:flex;gap:10px;flex-wrap:wrap;align-items:baseline;
padding:8px 0;border-bottom:1px solid var(--line)}
.cites .idx{color:var(--accent);font-weight:700;min-width:26px}
.cites .ttl{font-weight:600;flex:1;min-width:200px}
.cites .src{color:var(--muted);font-size:12px}
.cites .score{font-variant-numeric:tabular-nums;color:var(--muted);font-size:12px}
.note{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px 20px;font-size:14px}
.note ul{margin:8px 0;padding-left:22px}
.note li{margin:6px 0}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px;line-height:1.7}
@media print{body{background:#fff;padding:0}.card{break-inside:avoid}}
"""


def build(data: dict) -> str:
    paths = sorted(
        data["paths"],
        key=lambda p: PATH_ORDER.index(p["key"]) if p["key"] in PATH_ORDER else 99,
    )
    cards = "\n".join(path_card(p) for p in paths)

    summary_rows = "\n".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(data['summary'].get(key, '—')))}</td></tr>"
        for label, key in SUMMARY_ROWS
    )

    # `hit_count` is the raw retrieval hits and `passage_count` what survived
    # dedup/merge into the prompt — they differ (5 -> 4 here), so show both
    # rather than picking one under a label that only fits the other.
    def cell(value: object) -> str:
        return html.escape(str(value)) if value is not None else "—"

    retrieval_rows = "\n".join(
        f"<tr><th>{html.escape(label)}</th><td>{cell(data.get(key))}</td></tr>"
        for label, key in (
            ("病种", "disease"),
            ("最高相似度", "top_score"),
            ("总延迟（ms）", "total_latency_ms"),
            ("对比记录 id", "comparison_id"),
        )
    ) + "\n" + (
        f"<tr><th>检索命中 / 送入提示的片段</th>"
        f"<td>{cell(data.get('hit_count'))} / {cell(data.get('passage_count'))}</td></tr>"
    )

    citations_html = citations_block(data.get("citations") or [])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>问答路径对比 · {html.escape(data['question'])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>同一问题，三条路径：本地检索 / 外部直答 / 外部 + 检索</h1>
  <p class="sub">BC-Dx Platform · 问答路径对比实测结果</p>

  <div class="question">{html.escape(data['question'])}</div>
  <p class="meta">病种 {html.escape(str(data.get('disease')))} · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <h2>检索与整体度量</h2>
  <table>{retrieval_rows}</table>

  <h2>三条路径的回答</h2>
  <div class="grid">{cards}
  </div>

  {citations_html}

  <h2>汇总（费用与调用）</h2>
  <table>{summary_rows}</table>

  <h2>怎么读这组结果</h2>
  <div class="note">
    <ul>
      <li><strong>词面重合</strong>衡量回答与检索到的片段有多少字面对应。它低不代表回答错，
          只说明这段话<em>不是从这批资料里来的</em>——直答路径没有出处，重合度通常很低。</li>
      <li><strong>延迟</strong>不可直接横向比较：本地路径不联网，两条外部路径要往返服务商。
          真实网络抖动会以秒为单位影响后者。</li>
      <li><strong>三条路径共用同一次检索</strong>，所以任何差异都来自「怎么组织答案」，
          而不是「拿到了不同的资料」。这是这个对比能说明问题的前提。</li>
      <li><strong>费用</strong>是按配置的单价估算的显示值，不参与实际计费。</li>
    </ul>
  </div>

  <footer>
    本页内容由系统自动生成，回答来自本地知识库与（或）外部大语言模型，<strong>仅供健康科普参考，
    不能替代执业医师的诊断与治疗建议</strong>。身体不适请就医。<br>
    BC-Dx Platform · 非医疗器械 · 数据仅用于技术演示
  </footer>
</div>
</body>
</html>
"""


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".html")
    data = json.loads(src.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build(data).encode("utf-8"))  # bytes: keep LF on Windows
    print(f"已生成 {out} ({out.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
