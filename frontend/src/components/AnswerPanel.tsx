import type { ReactNode } from 'react'
import type { AnswerResponse, Confidence } from '../api'
import { tickerColor } from '../brand'
import { SparkIcon } from './Icons'

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  none: 'No answer',
}

const CITATION = /\[([A-Z]{1,5}) FY(\d{4}) p\.([^\]]+)\]/g

/** Render inline [AAPL FY2025 p.23] citations as chips linking to the filing. */
function withCitationChips(text: string, urls: Map<string, string>): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(CITATION)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const href = urls.get(m[0])
    const chip = (
      <span className="cite" style={{ borderColor: tickerColor(m[1]) }}>
        <span className="ticker-dot" style={{ background: tickerColor(m[1]) }} />
        {m[1]} FY{m[2]} p.{m[3]}
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
}

export function AnswerPanel({ enabled, onToggle, loading, answer, error, disabledReason, hasQuery }: AnswerPanelProps) {
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
        <div className="answer__loading" aria-label="Generating answer">
          <span className="line" /><span className="line" /><span className="line line--short" />
          <p className="hint">Retrieving evidence, generating, then verifying each claim against its page…</p>
        </div>
      )}

      {enabled && error && !loading && <p className="answer__error">Couldn't generate an answer: {error}</p>}

      {enabled && answer && !loading && !error && (
        <>
          {answer.abstained ? (
            <div className="answer__abstain">
              <strong>Not enough evidence to answer.</strong>
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
            <span className="pill mono">{answer.model}{answer.cached ? ' · cached' : ''}</span>
            {answer.timings_ms.llm !== undefined && !answer.cached && (
              <span className="pill mono">LLM {Math.round(answer.timings_ms.llm)} ms</span>
            )}
            <span className="pill mono">Total {Math.round(answer.timings_ms.total)} ms</span>
            <span className="pill mono">{answer.sources.length} sources read</span>
          </div>
        </>
      )}
    </section>
  )
}
