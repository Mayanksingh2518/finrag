# FinRAG: instructions for Claude

FinRAG is an agentic RAG system over SEC 10-K filings, built step by step as an AI Engineer
portfolio project. Design: `docs/ARCHITECTURE.md`. State and next task: `progress.md`.
All paths below are relative to this repository root.

## "go" command

When the user's message is just **go** (any case, optionally with extra notes), do this
without asking for clarification:

1. Read `progress.md` and `docs/ARCHITECTURE.md`.
2. Check the machine is set up (see "Machines" and "New machine setup" below); if `.venv`,
   `data/raw`, `data/processed` or the embedding cache are missing, set them up first.
3. Work on the task under "Next task in detail". Complete one phase per "go" (or one
   self-contained step if a phase is too large), following any notes the user added.
4. Verify: run the tests (`python -m pytest` inside the venv) and run the new code on real data
   where possible. Don't mark anything done that wasn't verified.
5. Update `progress.md`: tick the phase, update "Current status", rewrite
   "Next task in detail" for the following phase, record new decisions/environment notes,
   and append a dated session-log entry. Update the README status checklist to match.
6. Stop and give a short summary: what was built, results/metrics, anything the user must do
   (API keys, installs), and what the next "go" will do.

## Conventions

- **Zero cost is a hard requirement.** No paid APIs or services. Use local models
  (sentence-transformers embeddings, local cross-encoder reranker, Ollama) and free tiers
  (Gemini API free tier, Groq free tier, Langfuse/Opik free cloud). Design for free-tier rate
  limits: caching, retries, batching. See "Zero-cost stack" in `progress.md`.
- Production-style code: typed, small modules, tests with fixtures, no notebooks-only logic.
- Add dependencies to `requirements.txt` only when a phase needs them.
- Commit only when the user asks; never push without a remote the user provided.
- If blocked on something only the user can provide (e.g. an API key), do all the work that
  doesn't need it, then say exactly what's missing.

## Machines

The user works on two laptops; detect which one from the platform.

| | Windows laptop | MacBook (Apple M4) |
|---|---|---|
| Compute | CPU only: i7-1165G7 4 cores, 16 GB RAM (MX350 2 GB is unusable) | Apple GPU via PyTorch `mps` (`DEVICE=auto` picks it) |
| Python | `.venv/Scripts/python` | `.venv/bin/python` |
| torch install | CPU wheel: `pip install torch --index-url https://download.pytorch.org/whl/cpu` | plain `pip install torch` (includes MPS) |
| Local LLMs (Ollama) | ≤3–4B models (`qwen2.5:3b`) | 7–8B models are practical (`qwen2.5:7b`, `llama3.1:8b`) |
| Gotchas | Windows throttles long background jobs on battery: plug in, or raise priority | none known yet |

## New machine setup

```bash
python3 -m venv .venv            # Python 3.11+ required
source .venv/bin/activate        # Windows: .venv/Scripts/activate
pip install torch                # Windows: add --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env             # set SEC_USER_AGENT (name + email); API keys from Phase 5
python -m app.ingestion.sec_downloader --years 2022 2023 2024 2025   # 40 filings, ~2 min
python -m app.ingestion.pipeline                                     # chunks, ~1 min
python -m app.retrieval.build_index                                  # embeddings (cached)
python -m pytest
```

`data/raw`, `data/processed` and `data/indexes` are gitignored and fully reproducible with
the commands above.
