"""Chunking: the embedding window must not silently swallow the text.

The bug these tests exist to prevent
------------------------------------
`sentence-transformers` truncates at the model's `max_seq_length` without
raising. The original chunker split on blank lines only
(``re.split(r"\\n\\s*\\n", raw)``) and ignored heading hierarchy entirely, so
fragment length was whatever the source paragraphs happened to be — hundreds of
characters per fragment, against a 128-token window in
`paraphrase-multilingual-MiniLM-L12-v2` (roughly 150 Chinese characters).
Measured against the real knowledge base, **75 of 76 fragments (98%) exceeded
the window**, so the tail of nearly every entry was invisible to retrieval and
no error was ever logged.

These tests pin the properties that make that impossible to reintroduce.
Because the exact token count needs the real tokenizer (slow, and unavailable
in a stripped environment), the fast tests below exercise the same code path
through a `count_tokens` stub that counts characters. The final test runs
against the real tokenizer when it is available.
"""

from __future__ import annotations

import pytest

from app.services.rag_service import (
    Chunk,
    parse_markdown_chunks,
)

DOC = """# 测试知识库

这是文档开头的一段概述文字，长度需要超过最小块阈值，用来验证概述会被单独成块。

## 第一节

第一段内容，讲的是甲。这一段需要足够长以便被测量，至少超过最小块阈值。

第二段内容，讲的是乙，也需要有一定的长度，同样要超过最小块阈值。

## 第二节

第二节的正文内容，也要写得足够长，避免被相邻的小节合并掉。

## 第三节

### 三级标题也要能成为面包屑的一部分

三级标题下的正文内容，同样要写得足够长一些，避免被合并处理。
"""


def _char_counter(text: str) -> int:
    return len(text)


def _budgeted(raw: str, limit: int = 60, **kw):
    # `min_chars=10` keeps the small fixture sections separate; a section shorter
    # than the threshold is intentionally absorbed into the previous chunk.
    kw.setdefault("min_chars", 10)
    return parse_markdown_chunks(
        raw,
        "test_kb",
        max_tokens=limit,
        count_tokens=_char_counter,
        **kw,
    )


class TestStructure:
    def test_headings_become_breadcrumbs(self):
        chunks = _budgeted(DOC, limit=400)
        paths = {c.breadcrumb for c in chunks}
        assert "测试知识库 > 第一节" in paths
        assert "测试知识库 > 第二节" in paths
        # A third-level heading must appear in the trail, not replace it.
        assert "测试知识库 > 第三节 > 三级标题也要能成为面包屑的一部分" in paths

    def test_document_title_is_not_its_own_chunk(self):
        chunks = _budgeted(DOC, limit=400)
        assert all(c.title != "测试知识库" for c in chunks)

    def test_intro_is_kept_when_long_enough(self):
        chunks = _budgeted(DOC, limit=400, min_chars=10)
        assert any(c.title == "概述" for c in chunks)

    def test_disease_inferred_from_filename(self):
        assert parse_markdown_chunks(DOC, "breast_cancer_zh")[0].disease == "breast"
        assert parse_markdown_chunks(DOC, "heart_disease_zh")[0].disease == "heart"
        assert parse_markdown_chunks(DOC, "random_notes")[0].disease == "general"

    def test_front_matter_overrides_filename(self):
        raw = "---\ndisease: heart\n---\n" + DOC
        chunks = parse_markdown_chunks(raw, "breast_looking_name")
        assert all(c.disease == "heart" for c in chunks)
        # The front matter must not leak into the retrievable body.
        assert "disease: heart" not in " ".join(c.text for c in chunks)


class TestWindowFit:
    """The invariant that matters: nothing exceeds the budget it was given."""

    def test_no_chunk_exceeds_the_budget(self):
        for limit in (40, 60, 90, 140):
            chunks = _budgeted(DOC, limit=limit)
            for c in chunks:
                assert _char_counter(c.text) <= limit, (
                    f"limit={limit} {c.breadcrumb!r} text={len(c.text)}"
                )

    def test_long_section_is_split_with_overlap(self):
        para = "这是一段用于测试的说明文字。" * 12  # ~170 chars
        raw = f"# T\n\n## 长小节\n\n{para}\n\n{para}\n"
        chunks = _budgeted(raw, limit=80, overlap_chars=20, min_chars=10)
        assert len(chunks) > 1
        assert [c.part for c in chunks] == list(range(1, len(chunks) + 1))
        assert all(c.parts == len(chunks) for c in chunks)

        # Consecutive parts must share a tail so a fact on the seam is still
        # reachable from either side.
        first, second = chunks[0], chunks[1]
        shared = 0
        for n in range(min(len(first.text), len(second.text)), 0, -1):
            if first.text[-n:] == second.text[:n]:
                shared = n
                break
        assert shared > 0, "expected an overlap between consecutive parts"

    def test_overlap_is_trimmed_when_the_unit_leaves_no_room(self):
        """The overlap must never push a chunk back over the budget.

        Regression: the overlap was prepended *after* the fit check, so
        `tail + unit` could exceed the limit it had just been measured against.
        """
        unit = "甲" * 38
        raw = f"# T\n\n## S\n\n{unit}\n\n{unit}\n\n{unit}\n"
        for c in _budgeted(raw, limit=40, overlap_chars=30, min_chars=5):
            assert _char_counter(c.text) <= 40

    def test_short_sections_are_merged(self):
        raw = "# T\n\n## A\n\n" + ("甲" * 50) + "\n\n## B\n\n短。\n"
        chunks = _budgeted(raw, limit=200, min_chars=40)
        assert len(chunks) == 1
        # The absorbed heading stays in the text so its topic is still findable.
        assert "B" in chunks[0].text

    def test_paragraph_without_punctuation_is_still_split(self):
        raw = "# T\n\n## S\n\n" + ("甲" * 200)
        for c in _budgeted(raw, limit=50, overlap_chars=5, min_chars=5):
            assert _char_counter(c.text) <= 50


class TestEmbedText:
    def test_embed_text_includes_the_heading_trail(self):
        chunks = _budgeted(DOC, limit=400)
        target = next(c for c in chunks if c.title == "第一节")
        assert "测试知识库" in target.embed_text
        assert "第一节" in target.embed_text

    def test_citation_title_labels_split_parts(self):
        para = "内容。" * 60
        raw = f"# T\n\n## 分块\n\n{para}\n"
        chunks = _budgeted(raw, limit=60, overlap_chars=10, min_chars=5)
        assert len(chunks) > 1
        assert all("/" in c.citation_title for c in chunks)

    def test_single_part_has_no_part_suffix(self):
        chunks = _budgeted(DOC, limit=400)
        single = next(c for c in chunks if c.title == "第二节")
        assert "（" not in single.citation_title


REAL_KB = None


class TestRealKnowledgeBase:
    """Integration check against the actual KB and tokenizer.

    This is the test that would have caught the original truncation, so it is
    worth its runtime.
    """

    @staticmethod
    def _chunks_and_counter():
        global REAL_KB
        if REAL_KB is None:
            pytest.importorskip("sentence_transformers")
            from sentence_transformers import SentenceTransformer

            from app.core.config import REPO_ROOT
            from app.services.rag_service import (
                _make_token_counter,
                load_knowledge_dir,
            )

            model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            window = int(model.max_seq_length)
            count = _make_token_counter(model)
            chunks = load_knowledge_dir(
                REPO_ROOT / "knowledge" / "sources",
                max_tokens=max(window - 4, 24),
                count_tokens=count,
            )
            REAL_KB = (chunks, count, window)
        return REAL_KB

    def test_every_real_chunk_fits_the_real_window(self):
        chunks, count, window = self._chunks_and_counter()
        assert chunks, "knowledge base should not be empty"
        oversize = [
            (c.citation_title, count(c.embed_text))
            for c in chunks
            if count(c.embed_text) > window - 2
        ]
        assert not oversize, f"{len(oversize)} chunk(s) exceed the {window}-token window: {oversize[:3]}"

    def test_knowledge_base_is_substantial(self):
        chunks, _, _ = self._chunks_and_counter()
        assert len(chunks) >= 100, f"only {len(chunks)} chunks"

    def test_every_chunk_has_a_breadcrumb_and_scope(self):
        chunks, _, _ = self._chunks_and_counter()
        for c in chunks:
            assert c.path, f"missing breadcrumb: {c.title}"
            assert c.disease in {"breast", "heart", "general"}, c.disease
