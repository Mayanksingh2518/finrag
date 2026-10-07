import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { citation, type Hit, type SearchMode } from '../api'
import { SECTION_SHORT, tickerGradient } from '../brand'
import { highlightTerms } from '../text'
import { CopyIcon, ExternalIcon, TableIcon, TextIcon } from './Icons'

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function highlight(text: string, terms: string[]): ReactNode {
  if (!terms.length) return text
  const re = new RegExp(`\\b(${terms.map(escapeRegExp).join('|')})\\w*`, 'gi')
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(<mark key={m.index}>{m[0]}</mark>)
    last = m.index + m[0].length
  }
  out.push(text.slice(last))
  return out
}

interface Score {
  label: string
  value: string
  fraction: number // 0..1 for the meter
}

function stageScores(hit: Hit, mode: SearchMode, maxRerank: number): Score[] {
  const s = hit.stages
  const scores: Score[] = []
  if (s.rerank !== undefined)
    scores.push({ label: 'Rerank', value: s.rerank.toFixed(3), fraction: maxRerank > 0 ? Math.max(0, s.rerank) / maxRerank : 0 })
  if (s.rrf !== undefined && mode !== 'hybrid_rerank') scores.push({ label: 'RRF', value: s.rrf.toFixed(4), fraction: Math.min(1, s.rrf / (2 / 61)) })
  if (s.bm25_rank !== undefined) scores.push({ label: 'BM25', value: `#${s.bm25_rank}`, fraction: 1 / Math.sqrt(s.bm25_rank) })
  if (s.dense_rank !== undefined) scores.push({ label: 'Dense', value: `#${s.dense_rank}`, fraction: 1 / Math.sqrt(s.dense_rank) })
  return scores
}

interface EvidenceCardProps {
  hit: Hit
  query: string
  mode: SearchMode
  maxRerank: number
  onCopy: (text: string) => void
  index: number
}

export function EvidenceCard({ hit, query, mode, maxRerank, onCopy, index }: EvidenceCardProps) {
  const [expanded, setExpanded] = useState(false)
  const terms = useMemo(() => highlightTerms(query), [query])
  const long = hit.text.length > 700
  const cite = citation(hit)
  const page = hit.page_label ?? `#${hit.page_start}`
  const sectionName = SECTION_SHORT[hit.section]

  return (
    <article className="card glass" style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }} aria-label={`Result ${hit.rank}: ${cite}`}>
      <header className="card__head">
        <div className="avatar" style={{ background: tickerGradient(hit.ticker) }}>
          {hit.ticker}
        </div>
        <div className="card__title">
          <div className="card__company">
            <span>{hit.company}</span>
            <span className="card__rank mono">#{hit.rank}</span>
          </div>
          <div className="card__meta">
            <span className="pill mono">FY{hit.fiscal_year}</span>
            <span className="pill mono">p.{page}</span>
            <span className="pill">
              {hit.section}
              {sectionName ? ` · ${sectionName}` : ''}
            </span>
            <span className="pill">
              {hit.chunk_type === 'table' ? <TableIcon size={13} /> : <TextIcon size={13} />}
              {hit.chunk_type}
            </span>
          </div>
          {hit.subsection && <div className="card__section" title={hit.subsection}>{hit.subsection}</div>}
        </div>
        <div className="card__actions">
          <button type="button" className="btn btn--ghost" onClick={() => onCopy(cite)} title="Copy citation">
            <CopyIcon size={14} />
            <span className="mono">{cite}</span>
          </button>
        </div>
      </header>

      <div className={`card__body${long && !expanded ? ' card__body--clamped' : ''}`}>
        {hit.chunk_type === 'table' ? (
          <div className="table-scroll">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{hit.text}</ReactMarkdown>
          </div>
        ) : (
          hit.text.split(/\n+/).map((para, i) => <p key={i}>{highlight(para, terms)}</p>)
        )}
      </div>

      <footer className="card__foot">
        <div className="scores">
          {stageScores(hit, mode, maxRerank).map((s) => (
            <div className="score" key={s.label}>
              <span className="score__label">{s.label}</span>
              <span className="score__value mono">{s.value}</span>
              <div className="meter" aria-hidden="true">
                <span style={{ width: `${Math.round(s.fraction * 100)}%` }} />
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
          {long && (
            <button type="button" className="btn btn--ghost" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>
              {expanded ? 'Show less' : 'Show full passage'}
            </button>
          )}
          {hit.source_url && (
            <a className="link-btn" href={hit.source_url} target="_blank" rel="noreferrer">
              SEC filing <ExternalIcon size={14} />
            </a>
          )}
        </div>
      </footer>
    </article>
  )
}
