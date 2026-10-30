import type { ReactNode } from 'react'
import type { AnswerResponse, AnswerStep, Confidence } from '../api'
import { tickerColor } from '../brand'
import { SparkIcon } from './Icons'

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  none: 'No answer',
}

// Page citations [AAPL FY2025 p.23] and XBRL fact citations [XBRL NVDA Total revenue FY2022-FY2025].
const CITATION = /\[(?:([A-Z]{1,5}) FY(\d{4}) p\.([^\]]+)|XBRL ([A-Z]{1,5}) ([^\]]+))\]/g

const INTENT_LABEL: Record<string, string> = {
  lookup: 'Lookup',
  numeric: 'Figure',
  trend: 'Trend',
  comparison: 'Comparison',
}

/** Render inline citations as chips: pages link to the filing, XBRL facts are reported figures. */
function withCitationChips(text: string, urls: Map<string, string>): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(CITATION)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const href = urls.get(m[0])
    const ticker = m[1] ?? m[4]
    const chip = (
      <span className={m[4] ? 'cite cite--xbrl' : 'cite'} style={{ borderColor: tickerColor(ticker) }}
        title={m[4] ? 'Reported figure from the SEC XBRL company facts of this 10-K' : undefined}>
        <span className="ticker-dot" style={{ background: tickerColor(ticker) }} />
        {m[4] ? `${ticker} ${m[5]} · XBRL` : `${ticker} FY${m[2]} p.${m[3]}`}
      </span>
    )
    out.push(
      href ? (
        <a key={m.index} className="cite-link" href={href} target="_blank" rel="noreferrer" title="Open the filing on SEC.gov">
          {chip}
        </a>
      ) : (
        <span key={m.index}>{chip}</span>
      ),
    )
    last = m.index + m[0].length
  }
  out.push(text.slice(last))
  return out
}

interface AnswerPanelProps {
  enabled: boolean
  onToggle: (enabled: boolean) => void
  loading: boolean
  answer: AnswerResponse | null
  error: string | null
  disabledReason: string | null
  hasQuery: boolean
  /** Answers so far in this conversation; follow-ups refer back to them. */
  turns: number
  onNewConversation: () => void
  /** Streamed agent steps while the answer is prepared (empty if not streaming). */
  progress: AnswerStep[]
}

interface Stage {
  label: string
  detail?: string
  state: 'done' | 'active' | 'waiting'
  ms?: number
}

const seconds = (ms?: number) => (ms === undefined ? '' : `${(ms / 1000).toFixed(1)} s`)

/** The agent's stages, filled in from streamed node events. */
function stagesFrom(steps: AnswerStep[]): Stage[] {
  const at = (node: string) => steps.find((s) => s.node === node)
  const analyze = at('analyze'), retrieve = at('retrieve'), xbrl = at('xbrl'), generate = at('generate')
  const verify = at('verify'), refuse = at('refuse')
  const state = (done: unknown, started: boolean): Stage['state'] => (done ? 'done' : started ? 'active' : 'waiting')
  const scope = analyze?.filters ? readAs({ filters: analyze.filters } as AnswerResponse) : ''
  const reading: Stage = {
    label: 'Reading the question',
    detail: analyze && analyze.standalone_query ? [scope, analyze.in_scope === false ? 'out of scope' : ''].filter(Boolean).join(' · ') : undefined,
    state: state(analyze, true), ms: analyze?.elapsed_ms,
  }
  if (refuse) return [reading, { label: 'Outside what the filings cover', state: 'done', ms: refuse.elapsed_ms }]
  const facts = xbrl?.facts?.length ?? 0
  const model = generate?.model ?? retrieve?.answer_model
  return [
    reading,
    {
      label: 'Retrieving evidence',
      detail: retrieve ? `${retrieve.hits} passages${xbrl ? ` · ${facts} XBRL fact${facts === 1 ? '' : 's'}` : ''}` : undefined,
      state: state(retrieve && xbrl, Boolean(analyze)), ms: retrieve && xbrl ? Math.max(retrieve.elapsed_ms, xbrl.elapsed_ms) : undefined,
    },
    { label: model ? `Generating with ${model}` : 'Generating', state: state(generate, Boolean(retrieve && xbrl)), ms: generate?.elapsed_ms },
    {
      label: 'Verifying each claim against its page',
      detail: verify ? `${verify.verified}/${verify.claims} verified` : undefined,
      state: state(verify, Boolean(generate)), ms: verify?.elapsed_ms,
    },
  ]
}

function readAs(a: AnswerResponse): string {
  const f = a.filters
  const scope = [f.tickers.join(', '), f.fiscal_years.map((y) => `FY${y}`).join(', '), f.sections.join(', ')]
  return scope.filter(Boolean).join(' · ')
}

export function AnswerPanel({ enabled, onToggle, loading, answer, error, disabledReason, hasQuery, turns,
  onNewConversation, progress }: AnswerPanelProps) {
  const urls = new Map(answer?.sources.map((s) => [s.citation, s.hit.source_url]) ?? [])
  const verified = answer?.claims.filter((c) => c.status === 'supported').length ?? 0

  return (
    <section className="answer glass" aria-label="Answer" aria-busy={loading}>
      <div className="answer__head">
        <span className="answer__badge"><SparkIcon size={16} /></span>
        Grounded answer
        {answer && !loading && (
          <span className={`confidence confidence--${answer.confidence}`}>{CONFIDENCE_LABEL[answer.confidence]}</span>
        )}
        {enabled && turns > 0 && (
          <button type="button" className="answer__new" onClick={onNewConversation}
            title="Forget earlier questions: the next one starts a new conversation">
            New conversation{turns > 1 ? ` (${turns} turns)` : ''}
          </button>
        )}
        <label className="toggle toggle--compact" title="Generate an answer with an LLM for each search">
          <input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} />
          <span className="toggle__track" />
          <span className="sr-only">Generate answers</span>
        </label>
      </div>

      {!enabled && <p>Answer generation is off. Turn it on to get a cited answer for each search.</p>}

      {enabled && disabledReason && (
        <p>Answers are unavailable: {disabledReason}. Evidence search below still works.</p>
      )}

      {enabled && !disabledReason && !hasQuery && (
        <p>
          Ask a question and FinRAG answers only from the evidence it retrieves. Every claim is checked against the
          page it cites, and it says so when the filings don't support an answer.
        </p>
      )}

      {enabled && loading && (
        <ol className="stages" aria-label="Preparing the answer">
          {stagesFrom(progress).map((st) => (
            <li key={st.label} className={`stage stage--${st.state}`}>
              <span className="stage__mark" aria-hidden="true">{st.state === 'done' ? '✓' : ''}</span>
              <span className="stage__label">
                {st.label}
                {st.detail && <span className="stage__detail mono"> {st.detail}</span>}
              </span>
              {st.ms !== undefined && <span className="stage__ms mono">{seconds(st.ms)}</span>}
            </li>
          ))}
        </ol>
      )}

      {enabled && error && !loading && <p className="answer__error">Couldn't generate an answer: {error}</p>}

      {enabled && answer && !loading && !error && (
        <>
          {(answer.standalone_query !== answer.query || readAs(answer)) && (
            <p className="answer__read">
              {answer.standalone_query !== answer.query ? (
                <>Read as <q>{answer.standalone_query}</q></>
              ) : (
                'Scope'
              )}
              {readAs(answer) && <span className="mono"> · {readAs(answer)}</span>}
            </p>
          )}
          {answer.abstained ? (
            <div className="answer__abstain">
              <strong>{answer.steps.includes('refuse') ? 'Outside what the filings cover.' : 'Not enough evidence to answer.'}</strong>
              <p>{answer.abstain_reason}</p>
            </div>
          ) : (
            <p className="answer__text">{withCitationChips(answer.answer, urls)}</p>
          )}

          {answer.claims.length > 0 && (
            <details className="claims" open={answer.claims.some((c) => c.status !== 'supported' || c.repaired)}>
              <summary>
                {verified}/{answer.claims.length} claims verified against their cited pages
              </summary>
              <ul>
                {answer.claims.map((c, i) => (
                  <li key={i} className={`claim claim--${c.status}`}>
                    <span className="claim__mark" aria-label={c.status === 'supported' ? 'verified' : 'not verified'}>
                      {c.status === 'supported' ? '✓' : '!'}
                    </span>
                    <span>
                      {c.text} <span className="mono claim__cites">{c.citations.join(' ')}</span>
                      {c.status === 'unsupported_number' && (
                        <span className="claim__why"> Figure not found in the cited page: {c.unsupported_numbers.join(', ')}</span>
                      )}
                      {c.repaired && <span className="claim__note"> Citation added by the verifier: the model didn't cite this page.</span>}
                      {c.status === 'invalid_citation' && (
                        <span className="claim__why">
                          {c.citations.length ? " Cites a source that wasn't provided." : ' No source cited, and no provided page states it.'}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="answer__meta">
            {answer.intent && <span className="pill">{INTENT_LABEL[answer.intent] ?? answer.intent}</span>}
            {answer.model && <span className="pill mono">{answer.model}{answer.cached ? ' · cached' : ''}</span>}
            {answer.facts.length > 0 && (
              <span className="pill mono" title={answer.facts.join('\n')}>
                {answer.facts.length} XBRL fact{answer.facts.length > 1 ? 's' : ''}
              </span>
            )}
            {answer.timings_ms.llm !== undefined && !answer.cached && (
              <span className="pill mono">LLM {Math.round(answer.timings_ms.llm)} ms</span>
            )}
            <span className="pill mono">Total {Math.round(answer.timings_ms.total)} ms</span>
            <span className="pill mono">{answer.sources.length} sources read</span>
            <span className="pill mono answer__steps" title="Agent steps">
              {answer.steps.filter((s) => s !== 'respond').join(' › ')}
            </span>
          </div>
        </>
      )}
    </section>
  )
}
