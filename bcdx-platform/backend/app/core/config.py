"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Values that must never sign a real deployment's tokens. Listed explicitly
#: because every one of them is a string somebody actually shipped.
_INSECURE_SECRET_KEYS = frozenset({
    # The model default, used when `SECRET_KEY` is not set at all.
    "change-me-in-dotenv-this-default-is-insecure",
    # What `.env.example` ships today.
    "change-me-generate-with-openssl-rand-hex-32",
    # What `.env.example` used to ship, and what the author's own `.env` had.
    # It looks random, which is why it survived so long.
    "dev-only-secret-please-change-me-in-production-2f8a91c4",
})

#: Substrings that mark a value as a placeholder regardless of its exact form.
_INSECURE_SECRET_MARKERS = ("change-me", "please-change-me", "dev-only-secret")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- app ----
    app_name: str = "BC-Dx Platform"
    app_version: str = "1.0.0"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    host: str = "127.0.0.1"
    port: int = 8000

    # ---- security ----
    secret_key: str = Field(
        default="change-me-in-dotenv-this-default-is-insecure",
        description="HMAC key for JWT signing. MUST be overridden in production.",
    )
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    jwt_algorithm: str = "HS256"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- database ----
    database_url: str = "sqlite+pysqlite:///./bcdx.db"

    # ---- paths ----
    registry_path: Path = REPO_ROOT / "ml" / "registry" / "registry.json"
    knowledge_dir: Path = REPO_ROOT / "knowledge" / "sources"

    # ---- uploads ----
    max_upload_mb: int = 10

    # ---- rag ----
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    rag_top_k: int = 5
    rag_min_similarity: float = 0.30
    rag_min_token_coverage: float = 0.12
    enable_rag_llm: bool = True

    # Hybrid retrieval: dense vectors fused with BM25, then optionally reranked.
    #
    # Measured with `_tools/eval_retrieval.py` (15 probes over the real corpus,
    # plus 4 probes that must be refused; each probe's expected section derived
    # from the corpus itself rather than typed in by hand):
    #
    #   dense          hit@1  9/15   in top-5 12/15   spurious refusals 4   ~24 ms
    #   hybrid         hit@1 13/15   in top-5 13/15   spurious refusals 0   ~25 ms
    #   hybrid+rerank  hit@1 13/15   in top-5 15/15   spurious refusals 0 ~2241 ms
    #
    # BM25 fusion is on by default because of the third column: the four questions
    # dense got wrong are exactly the four it *refused*. The gate that fires is the
    # lexical one, not the cosine one — those four have best cosines of 0.43-0.61,
    # well clear of the 0.30 threshold, but a coverage of 0.000 against the section
    # dense ranked first, because dense answers a question about "Youden" with
    # 概率校准与布里尔分数. The refusal is the gate correctly declining to answer
    # from a passage that shares no content word with the question; the ranking was
    # what was broken. See `compose_local_answer` for why coverage reads only
    # `hits[0]` while the cosine gate reads the best hit.
    #
    # Fusion fixed all four for about a millisecond. A spurious refusal — "I asked
    # a fair question and the system said it had nothing" — is the worst failure
    # mode this product has.
    #
    # Reranking is off by default, and that is a measurement rather than an
    # omission. It bought two extra top-5 placements, no top-1 improvement, and
    # multiplied query latency by roughly 90x on CPU. The local path is the one
    # this project advertises as fast and free; making it slower than the model
    # call it is being compared against would be a visible regression for no
    # measurable ranking gain. Enable with RAG_RERANK_ENABLED=true when top-5
    # recall matters more than latency, then re-run the harness above.
    #
    # Reranking is also best-effort by construction: if the model cannot be
    # loaded (offline container, empty cache, not enough memory) retrieval
    # degrades to the fused ranking and `/health`'s
    # `rag_retrieval.rerank_unavailable` says so. It is never a hard dependency.
    #
    #   RAG_RRF_K                the RRF constant. 60 is the value from the
    #                            original paper; it only needs changing if the
    #                            candidate pool grows by orders of magnitude.
    #   RAG_RETRIEVE_CANDIDATES  candidates surviving fusion, handed to the
    #                            reranker. Each one is a cross-encoder forward
    #                            pass, so this is the latency lever.
    rag_hybrid_enabled: bool = True
    rag_rrf_k: int = 60
    rag_retrieve_candidates: int = 20
    rag_rerank_enabled: bool = False
    rag_rerank_model: str = "BAAI/bge-reranker-base"
    #: Cross-encoder input cap. Chunks are ~124 tokens by construction, so this
    #: only guards against a mis-sized knowledge file — it is not the latency
    #: lever; `RAG_RETRIEVE_CANDIDATES` is.
    rag_rerank_max_tokens: int = 512

    # Chunking.
    #
    # The embedding model truncates silently at its own `max_seq_length`
    # (128 tokens for the multilingual MiniLM above), so anything past the
    # window is invisible to retrieval with no error raised. At index build
    # time the chunker is therefore given the real tokenizer and budgets in
    # tokens; the values below are only the *fallback* budget used when the
    # model cannot be loaded, plus the shared min/overlap expressed in chars.
    #
    #   max_chars   fallback body size when token counting is unavailable
    #   min_chars   entries smaller than this are merged into the previous one
    #   overlap_chars  trailing context repeated at each split so a fact
    #                  spanning the seam stays retrievable from either side
    rag_chunk_max_chars: int = 160
    rag_chunk_min_chars: int = 60
    rag_chunk_overlap_chars: int = 40

    # ---- llm (cost controlled) ----
    #
    # `LLM_PROVIDER` selects from the catalogue in `services/llm_providers.py`
    # (deepseek / openai / qwen / moonshot / zhipu / ollama / mock / custom).
    # The two values below are *overrides*, not the primary configuration, and
    # they are interpreted narrowly on purpose — see `resolve()` there:
    #
    #   LLM_MODEL      overrides the model for any provider (same host and key,
    #                  so `deepseek-reasoner` on the deepseek preset is normal)
    #   LLM_BASE_URL   used only when LLM_PROVIDER=custom; a named preset always
    #                  keeps its own known-good URL, because letting a stale
    #                  value win produces a 401 that looks like an expired key
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_enabled: bool = True
    llm_cache_size: int = 512
    llm_timeout_seconds: float = 25.0
    llm_max_tokens: int = 700
    llm_min_chars_for_call: int = 150
    #: How many models one comparison may fan out to. Each extra model adds two
    #: paid calls, so the cap is a cost control, not a technical limit.
    llm_max_compare_models: int = 3

    # Fault injection for the offline demo channel only (`LLM_PROVIDER=mock`).
    # It exists because the error taxonomy is otherwise untestable outside unit
    # tests: a successful demo call is the only thing a reader can reproduce, so
    # "the panel tells you *why* it failed" stays an unverified claim. Set it to
    # any kind in `llm_mock.FAULTS` (e.g. `quota`, `rate_limited`,
    # `endpoint_not_found`) and every demo call fails that way on purpose.
    # Ignored by every real provider — it cannot break a real integration.
    llm_mock_fault: str = ""

    # Cost accounting. Prices are CNY per 1K tokens for the configured model
    # (DeepSeek's published standard-tier rates as of 2025). They are used only
    # to *display* an estimate next to each comparison path, never to bill.
    # If the provider changes prices, update these two numbers only.
    llm_price_prompt_per_1k: float = 0.002
    llm_price_completion_per_1k: float = 0.008

    # Side-by-side Q&A path comparison. Off by default: the whole point of the
    # project is that the default path costs nothing. Enabled explicitly per
    # request and additionally gated by `qa_compare_allow_llm`.
    qa_compare_allow_llm: bool = True
    qa_compare_max_question_chars: int = 300

    # ---- rate limiting ----
    rate_limit_predict: str = "60/minute"
    rate_limit_llm: str = "12/minute"
    rate_limit_auth: str = "20/minute"

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def _strip_key(cls, v: object) -> str:
        return (str(v) if v is not None else "").strip()

    @property
    def secret_key_is_placeholder(self) -> bool:
        """Whether `SECRET_KEY` is still something a reader could copy.

        Three ways a deployment ends up signing tokens with a public value:

        * nobody set it, so the model default applies;
        * `.env.example` was copied and the placeholder never replaced — the old
          example shipped `dev-only-secret-...-2f8a91c4`, which *looks* random
          enough to pass a glance, which is exactly what made it dangerous;
        * an older version of this file shipped the same value.

        The consequences are not subtle: anyone who knows this string can mint a
        valid login token for any account, including the admin's.

        The check names the known values explicitly rather than looking for a
        prefix, so it keeps working if the placeholder text changes — and it
        also catches the substrings, so a value that *contains* one of them is
        still rejected.
        """
        value = (self.secret_key or "").strip()
        if not value:
            return True
        if value in _INSECURE_SECRET_KEYS:
            return True
        return any(marker in value for marker in _INSECURE_SECRET_MARKERS)

    @property
    def llm_configured(self) -> bool:
        key = self.llm_api_key
        return bool(key) and not key.startswith("sk-your") and len(key) > 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
