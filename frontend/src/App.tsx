import { useCallback, useEffect, useRef, useState } from 'react'
import { answerApi, api, ApiError, type AnswerResponse, type Meta, type SearchResponse } from './api'
import { MODE_LABELS } from './brand'
import { AnswerPanel } from './components/AnswerPanel'
import { Aurora } from './components/Aurora'
import { EvidenceCard } from './components/EvidenceCard'
import { Filters } from './components/Filters'
import { DEFAULT_FILTERS, type FilterState } from './filters'
import { ClockIcon, DocIcon, SearchIcon } from './components/Icons'

interface Example {
  label: string
  query: string
  filters: Partial<FilterState>
}

// Drawn from the evaluation golden set (data/eval/golden_v0.jsonl).
const EXAMPLES: Example[] = [
  { label: 'Apple Services growth', query: "Why did Apple's Services net sales increase in fiscal 2025?", filters: { tickers: ['AAPL'], fiscal_years: [2025] } },
  { label: 'Azure vs AWS', query: 'Compare the growth of Microsoft Azure and Amazon AWS in fiscal 2025', filters: { tickers: ['MSFT', 'AMZN'], fiscal_years: [2025], decompose: true } },
  { label: 'NVIDIA China exposure', query: 'Export controls on data center GPUs sold to China', filters: { tickers: ['NVDA'], fiscal_years: [2024, 2025] } },
  { label: 'Tesla deliveries trend', query: 'How many consumer vehicles did Tesla deliver?', filters: { tickers: ['TSLA'], fiscal_years: [2022, 2023, 2024, 2025], decompose: true } },
  { label: 'JPMorgan NII', query: 'What drove net interest income?', filters: { tickers: ['JPM'], fiscal_years: [2024] } },
  { label: 'Meta capex', query: 'Capital expenditures including finance leases', filters: { tickers: ['META'], fiscal_years: [2025], chunk_types: ['text'] } },
]

const STAGES: [string, string][] = [
  ['bm25', 'BM25'],
  ['embed_query', 'Embed'],
  ['dense', 'Dense'],
  ['rerank', 'Rerank'],
  ['total', 'Total'],
]

// ---- URL state: searches are shareable links ----

function readUrl(): { query: string; filters: FilterState } {
  const p = new URLSearchParams(window.location.search)
  const list = (k: string) => (p.get(k) ? p.get(k)!.split(',').filter(Boolean) : [])
  const mode = p.get('mode')
  return {
    query: p.get('q') ?? '',
    filters: {
      tickers: list('tickers'),
      fiscal_years: list('years').map(Number).filter(Number.isFinite),
      sections: list('sections'),
      chunk_types: list('types').filter((t): t is 'text' | 'table' => t === 'text' || t === 'table'),
      mode: mode && mode in MODE_LABELS ? (mode as FilterState['mode']) : DEFAULT_FILTERS.mode,
      k: Number(p.get('k')) || DEFAULT_FILTERS.k,
      decompose: p.get('decompose') === '1',
    },
  }
}

function writeUrl(query: string, f: FilterState) {
  const p = new URLSearchParams()
  if (query) p.set('q', query)
  if (f.tickers.length) p.set('tickers', f.tickers.join(','))
  if (f.fiscal_years.length) p.set('years', f.fiscal_years.join(','))
  if (f.sections.length) p.set('sections', f.sections.join(','))
  if (f.chunk_types.length) p.set('types', f.chunk_types.join(','))
  if (f.mode !== DEFAULT_FILTERS.mode) p.set('mode', f.mode)
  if (f.k !== DEFAULT_FILTERS.k) p.set('k', String(f.k))
  if (f.decompose) p.set('decompose', '1')
  const qs = p.toString()
  window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)
}

export default function App() {
  const [initial] = useState(readUrl)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [draft, setDraft] = useState(initial.query)
  const [submitted, setSubmitted] = useState(initial.query)
  const [filters, setFilters] = useState<FilterState>(initial.filters)
  // The latest settled request, tagged with the (query, filters) key it answered.
  const [settled, setSettled] = useState<{ key: string; data?: SearchResponse; error?: string } | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [answersOn, setAnswersOn] = useState<boolean>(() => {
    try {
      return localStorage.getItem('finrag.answers') !== 'off'
    } catch {
      return true
    }
  })
  const [answered, setAnswered] = useState<{ key: string; data?: AnswerResponse; error?: string; disabled?: string } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.meta().then(
      (m) => { setMeta(m); setOnline(true) },
      () => setOnline(false),
    )
  }, [])

  // "/" focuses the search box, like most search UIs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
      if (e.key === '/' && !typing) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Run the search whenever the submitted query or filters change; abort stale requests.
  // Loading/result/error are derived from whether the settled request matches the current key.
  const requestKey = submitted ? JSON.stringify([submitted, filters]) : ''
  useEffect(() => {
    writeUrl(submitted, filters)
    if (!submitted) return
    const key = JSON.stringify([submitted, filters])
    const controller = new AbortController()
    api.search({ query: submitted, ...filters }, controller.signal).then(
      (data) => setSettled({ key, data }),
      (e: Error) => {
        if (e.name !== 'AbortError') setSettled({ key, error: e.message })
      },
    )
    return () => controller.abort()
  }, [submitted, filters])

  // Grounded answer for the same query + filters (mode/k/content type don't apply to answers).
  const answerKey = submitted && answersOn
    ? JSON.stringify([submitted, filters.tickers, filters.fiscal_years, filters.sections, filters.decompose])
    : ''
  useEffect(() => {
    if (!answerKey) return
    // The key is the request: rebuilding it from the key keeps this effect's only input explicit.
    const [query, tickers, fiscal_years, sections, decompose] = JSON.parse(answerKey)
    const controller = new AbortController()
    answerApi
      .answer({ query, tickers, fiscal_years, sections, decompose: decompose ? true : null }, controller.signal)
      .then(
        (data) => setAnswered({ key: answerKey, data }),
        (e: Error) => {
          if (e.name === 'AbortError') return
          if (e instanceof ApiError && e.status === 503) setAnswered({ key: answerKey, disabled: e.message.replace(/^Answers are disabled: /, '') })
          else setAnswered({ key: answerKey, error: e.message })
        },
      )
    return () => controller.abort()
  }, [answerKey])

  const toggleAnswers = (on: boolean) => {
    setAnswersOn(on)
    try {
      localStorage.setItem('finrag.answers', on ? 'on' : 'off')
    } catch {
      /* storage unavailable: the choice just isn't remembered */
    }
  }
  const currentAnswer = answered && answered.key === answerKey ? answered : null

  const current = settled && settled.key === requestKey ? settled : null
  const loading = Boolean(submitted) && current === null
  const result = submitted ? (current?.data ?? null) : null
  const error = current?.error ?? null

  const runExample = (ex: Example) => {
    setDraft(ex.query)
    setSubmitted(ex.query)
    setFilters({ ...DEFAULT_FILTERS, ...ex.filters })
    resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const copy = useCallback((text: string) => {
    navigator.clipboard?.writeText(text).then(
      () => setToast(`Copied ${text}`),
      () => setToast('Copy failed'),
    )
    window.setTimeout(() => setToast(null), 1800)
  }, [])

  const maxRerank = Math.max(0, ...(result?.hits.map((h) => h.stages.rerank ?? 0) ?? [0]))
  const filings = meta ? meta.companies.reduce((n, c) => n + c.fiscal_years.length, 0) : null

  return (
    <>
      <Aurora />
      <div className="app">
        <header className="topbar glass glass--strong">
          <a className="brand" href="/" aria-label="FinRAG home">
            <img className="brand__logo" src="/favicon.svg" alt="" />
            <span className="brand__name">FinRAG</span>
            <span className="brand__tag">Evidence search over SEC 10-K filings</span>
          </a>
          <div className="topbar__stats">
            <span className="pill" role="status">
              <span className={`status-dot${online === false ? ' status-dot--down' : ''}`} />
              {online === null ? 'Connecting…' : online ? 'API online' : 'API offline'}
            </span>
            {meta && <span className="pill mono">{meta.chunks.toLocaleString()} chunks</span>}
            {filings !== null && <span className="pill mono">{filings} filings · FY{meta!.fiscal_years[0]}–{meta!.fiscal_years.at(-1)}</span>}
          </div>
        </header>

        <section className="hero">
          <h1>
            Ask the filings.<br />
            <span className="grad">Get the page it came from.</span>
          </h1>
          <p>
            Hybrid retrieval over 40 annual reports from Apple, Microsoft, NVIDIA, Amazon, Alphabet, Meta,
            Tesla, JPMorgan, Visa and Mastercard, with every result pinned to a printed page.
          </p>

          <form
            className="search glass glass--strong"
            role="search"
            onSubmit={(e) => {
              e.preventDefault()
              setSubmitted(draft.trim())
            }}
          >
            <SearchIcon className="search__icon" size={20} />
            <label htmlFor="q" className="sr-only">Question</label>
            <input
              id="q"
              ref={inputRef}
              className="search__input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="e.g. Why did Visa's international transaction revenue change?"
              autoComplete="off"
              maxLength={500}
            />
            <span className="kbd" aria-hidden="true">/</span>
            <button className="btn" type="submit" disabled={!draft.trim() || loading}>
              {loading ? 'Searching…' : 'Search'}
            </button>
          </form>

          <div className="examples" aria-label="Example questions">
            {EXAMPLES.map((ex) => (
              <button key={ex.label} type="button" className="chip glass" onClick={() => runExample(ex)}>
                {ex.label}
              </button>
            ))}
          </div>
        </section>

        <div className="workspace" ref={resultsRef}>
          <Filters meta={meta} value={filters} onChange={setFilters} />

          <main className="results" aria-live="polite" aria-busy={loading}>
            <AnswerPanel
              enabled={answersOn}
              onToggle={toggleAnswers}
              loading={Boolean(answerKey) && currentAnswer === null}
              answer={currentAnswer?.data ?? null}
              error={currentAnswer?.error ?? null}
              disabledReason={currentAnswer?.disabled ?? null}
              hasQuery={Boolean(submitted)}
            />

            {error && <div className="glass error" role="alert">Search failed: {error}</div>}
            {online === false && !error && (
              <div className="glass error" role="alert">
                Can't reach the API. Start it with <code>uvicorn app.api.main:app --port 8010</code>.
              </div>
            )}

            {result && !loading && (
              <div className="results__bar glass">
                <span className="results__count">
                  <strong>{result.hits.length}</strong> passages · {MODE_LABELS[result.mode]}
                  {result.decomposed ? ' · decomposed' : ''}
                </span>
                <div className="timings" aria-label="Latency by stage">
                  {STAGES.filter(([k]) => result.timings_ms[k] !== undefined).map(([k, label]) => (
                    <span key={k} className="pill timing mono">
                      {k === 'total' && <ClockIcon size={12} />}
                      {label} <b>{result.timings_ms[k] < 10 ? result.timings_ms[k].toFixed(1) : Math.round(result.timings_ms[k])} ms</b>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {loading &&
              Array.from({ length: 3 }, (_, i) => <div key={i} className="skeleton glass" aria-hidden="true" />)}

            {!loading && result?.hits.map((hit, i) => (
              <EvidenceCard key={hit.chunk_id} hit={hit} query={result.query} mode={result.mode} maxRerank={maxRerank} onCopy={copy} index={i} />
            ))}

            {!loading && result && result.hits.length === 0 && (
              <div className="empty glass">
                <DocIcon size={28} />
                <h2>No passages match these filters</h2>
                <p>Try removing a section or year filter, or switch content back to text and tables.</p>
              </div>
            )}

            {!result && !loading && !error && (
              <div className="empty glass">
                <DocIcon size={28} />
                <h2>Search 17,602 passages from 40 annual reports</h2>
                <p>Pick an example above, or ask your own question. Use the filters to focus on companies, years or 10-K sections.</p>
              </div>
            )}
          </main>
        </div>

        <footer className="footer">
          FinRAG · local bge embeddings + BM25 + cross-encoder reranking · data from SEC EDGAR
        </footer>
      </div>

      {toast && <div className="toast glass glass--strong" role="status">{toast}</div>}
    </>
  )
}
