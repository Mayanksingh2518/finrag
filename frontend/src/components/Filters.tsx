import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Meta, SearchMode } from '../api'
import type { FilterState } from '../filters'
import { MODE_LABELS, SECTION_SHORT, tickerColor } from '../brand'

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

interface GroupProps {
  label: string
  onClear?: () => void
  children: ReactNode
}

function Group({ label, onClear, children }: GroupProps) {
  return (
    <section className="filters__group" aria-label={label}>
      <h2 className="filters__label">
        {label}
        {onClear && (
          <button type="button" className="filters__clear" onClick={onClear}>
            Clear
          </button>
        )}
      </h2>
      {children}
    </section>
  )
}

interface FiltersProps {
  meta: Meta | null
  value: FilterState
  onChange: (next: FilterState) => void
}

export function Filters({ meta, value, onChange }: FiltersProps) {
  const [open, setOpen] = useState(false) // only matters on narrow screens; always open on desktop
  const set = (patch: Partial<FilterState>) => onChange({ ...value, ...patch })
  const active = value.tickers.length + value.fiscal_years.length + value.sections.length + value.chunk_types.length
  const multiEntity = value.tickers.length > 1 || value.fiscal_years.length > 1
  const mainSections = (meta?.sections ?? []).filter((s) => s.section in SECTION_SHORT)

  return (
    <aside className={`filters glass${open ? ' filters--open' : ''}`} aria-label="Search filters">
      <button type="button" className="filters__toggle" aria-expanded={open} aria-controls="filter-groups" onClick={() => setOpen((o) => !o)}>
        <span>Filters{active ? ` · ${active} active` : ''}</span>
        <span className="mono">{value.mode === 'hybrid_rerank' ? 'Hybrid + Rerank' : value.mode}</span>
        <span aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      <div id="filter-groups" className="filters__groups">
      <Group label="Companies" onClear={value.tickers.length ? () => set({ tickers: [] }) : undefined}>
        <div className="chips">
          {(meta?.companies ?? []).map((c) => (
            <button
              key={c.ticker}
              type="button"
              className="chip"
              aria-pressed={value.tickers.includes(c.ticker)}
              title={`${c.name} · ${c.sector} · FY ends ${c.fiscal_year_end}`}
              onClick={() => set({ tickers: toggle(value.tickers, c.ticker) })}
            >
              <span className="ticker-dot" style={{ background: tickerColor(c.ticker) }} />
              {c.ticker}
            </button>
          ))}
        </div>
      </Group>

      <Group label="Fiscal year" onClear={value.fiscal_years.length ? () => set({ fiscal_years: [] }) : undefined}>
        <div className="chips">
          {(meta?.fiscal_years ?? []).map((y) => (
            <button
              key={y}
              type="button"
              className="chip mono"
              aria-pressed={value.fiscal_years.includes(y)}
              onClick={() => set({ fiscal_years: toggle(value.fiscal_years, y) })}
            >
              FY{y}
            </button>
          ))}
        </div>
        <p className="hint">Fiscal years follow each company's own label (NVIDIA FY2025 ended Jan 2025).</p>
      </Group>

      <Group label="10-K section" onClear={value.sections.length ? () => set({ sections: [] }) : undefined}>
        <div className="chips">
          {mainSections.map((s) => (
            <button
              key={s.section}
              type="button"
              className="chip"
              aria-pressed={value.sections.includes(s.section)}
              title={`${s.section}: ${s.title}`}
              onClick={() => set({ sections: toggle(value.sections, s.section) })}
            >
              {SECTION_SHORT[s.section]}
            </button>
          ))}
        </div>
      </Group>

      <Group label="Content">
        <div className="segmented" role="group" aria-label="Content type">
          {(['text', 'table'] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={value.chunk_types.includes(t)}
              onClick={() => set({ chunk_types: value.chunk_types.includes(t) ? [] : [t] })}
            >
              {t === 'text' ? 'Text only' : 'Tables only'}
            </button>
          ))}
        </div>
      </Group>

      <Group label="Retrieval">
        <div className="segmented" role="group" aria-label="Retrieval mode">
          {(meta?.modes ?? Object.keys(MODE_LABELS)).map((m) => (
            <button key={m} type="button" aria-pressed={value.mode === m} onClick={() => set({ mode: m as SearchMode })}>
              {MODE_LABELS[m] ?? m}
            </button>
          ))}
        </div>
        <p className="hint">
          {value.mode === 'hybrid_rerank'
            ? 'BM25 + embeddings fused with RRF, then a cross-encoder reranks the top 30 (best quality, ~2 s).'
            : value.mode === 'hybrid'
              ? 'BM25 + embeddings fused with reciprocal rank fusion (~10 ms).'
              : value.mode === 'dense'
                ? 'bge-small embeddings, exact FAISS search.'
                : 'Keyword search with a finance-aware tokenizer.'}
        </p>
      </Group>

      <Group label="Options">
        <label className="toggle">
          <input type="checkbox" checked={value.decompose} onChange={(e) => set({ decompose: e.target.checked })} />
          <span className="toggle__track" />
          <span className="toggle__text">
            <strong>Per-entity decomposition</strong>
            One search per company × year, merged so each gets a slot.
            {multiEntity && !value.decompose && ' Recommended for this selection.'}
          </span>
        </label>
        <label className="filters__label" htmlFor="k" style={{ marginTop: 16 }}>
          Results <span className="mono">{value.k}</span>
        </label>
        <input
          id="k"
          className="range"
          type="range"
          min={3}
          max={20}
          value={value.k}
          onChange={(e) => set({ k: Number(e.target.value) })}
        />
      </Group>
      </div>
    </aside>
  )
}
