// Typed client for the FastAPI backend (app/api/schemas.py is the source of truth).

export type SearchMode = 'bm25' | 'dense' | 'hybrid' | 'hybrid_rerank'
export type ChunkType = 'text' | 'table'

export interface CompanyInfo {
  ticker: string
  name: string
  sector: string
  fiscal_year_end: string
  fiscal_years: number[]
}

export interface SectionInfo {
  section: string
  title: string
  chunks: number
}

export interface Meta {
  companies: CompanyInfo[]
  fiscal_years: number[]
  sections: SectionInfo[]
  modes: SearchMode[]
  chunks: number
}

export interface SearchRequest {
  query: string
  tickers: string[]
  fiscal_years: number[]
  sections: string[]
  chunk_types: ChunkType[]
  mode: SearchMode
  k: number
  decompose: boolean
}

export interface Hit {
  rank: number
  chunk_id: string
  ticker: string
  company: string
  fiscal_year: number
  section: string
  section_title: string
  subsection: string | null
  page_start: number
  page_end: number
  page_label: string | null
  chunk_type: ChunkType
  text: string
  source_url: string
  score: number
  stages: Record<string, number>
}

export interface SearchResponse {
  query: string
  mode: SearchMode
  decomposed: boolean
  hits: Hit[]
  timings_ms: Record<string, number>
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw await errorFrom(res)
  return res.json() as Promise<T>
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = `${res.status} ${res.statusText}`
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail)
}

export const api = {
  meta: () => request<Meta>('/meta'),
  search: (body: SearchRequest, signal?: AbortSignal) =>
    request<SearchResponse>('/search', { method: 'POST', body: JSON.stringify(body), signal }),
}

/** Citation in the format answers will use: [AAPL FY2025 p.23] */
export function citation(hit: Pick<Hit, 'ticker' | 'fiscal_year' | 'page_label' | 'page_start'>): string {
  return `[${hit.ticker} FY${hit.fiscal_year} p.${hit.page_label ?? `#${hit.page_start}`}]`
}

// ---- Grounded answers (POST /api/answer) ----

export type Confidence = 'high' | 'medium' | 'low' | 'none'
export type ClaimStatus = 'supported' | 'unsupported_number' | 'invalid_citation'

export interface AnswerRequest {
  query: string
  tickers: string[]
  fiscal_years: number[]
  sections: string[]
  decompose: boolean | null
  /** Same id across requests = one conversation, so follow-ups ("And in 2024?") are understood. */
  thread_id: string | null
}

export interface AnswerClaim {
  text: string
  status: ClaimStatus
  citations: string[]
  unsupported_numbers: string[]
  repaired: boolean
}

export interface AnswerSource {
  id: string
  citation: string
  cited: boolean
  hit: Hit
}

export interface AnswerResponse {
  query: string
  /** The question as the agent read it (follow-ups rewritten to stand alone). */
  standalone_query: string
  filters: { tickers: string[]; fiscal_years: number[]; sections: string[] }
  intent: string | null
  steps: string[]
  /** XBRL facts given to the model, as citations: [XBRL NVDA Total revenue FY2025] */
  facts: string[]
  thread_id: string | null
  answer: string
  abstained: boolean
  abstain_reason: string
  confidence: Confidence
  claims: AnswerClaim[]
  sources: AnswerSource[]
  provider: string
  model: string
  cached: boolean
  timings_ms: Record<string, number>
  usage: Record<string, number>
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** One agent node finished (POST /api/answer/stream `step` event); fields depend on the node. */
export interface AnswerStep {
  node: string
  elapsed_ms: number
  standalone_query?: string
  in_scope?: boolean
  filters?: AnswerResponse['filters']
  hits?: number
  intent?: string | null
  answer_model?: string | null
  facts?: string[]
  model?: string | null
  sources?: number
  claims?: number
  verified?: number
  abstained?: boolean
}

/** The stream ended without an answer or error event (connection dropped, proxy buffering...). */
export class StreamBrokenError extends Error {}

/** Read Server-Sent Events from a POST (EventSource can only GET). */
async function streamAnswer(body: AnswerRequest, onStep: (step: AnswerStep) => void,
  signal?: AbortSignal): Promise<AnswerResponse> {
  const res = await fetch('/api/answer/stream', {
    method: 'POST', body: JSON.stringify(body), signal, headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw await errorFrom(res)
  if (!res.body) throw new StreamBrokenError('No response body')
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) throw new StreamBrokenError('The answer stream ended early')
    buffer += value
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const kind = /^event: (.*)$/m.exec(block)?.[1]
      const data = /^data: (.*)$/m.exec(block)?.[1]
      if (!kind || data === undefined) continue
      const payload = JSON.parse(data)
      if (kind === 'step') onStep(payload as AnswerStep)
      else if (kind === 'answer') return payload as AnswerResponse
      else if (kind === 'error') throw new ApiError(payload.status ?? 500, payload.detail ?? 'Answer failed')
    }
  }
}

export const answerApi = {
  answer: (body: AnswerRequest, signal?: AbortSignal) =>
    request<AnswerResponse>('/answer', { method: 'POST', body: JSON.stringify(body), signal }),
  /** Streams progress; falls back to the plain endpoint if streaming isn't available or breaks. */
  stream: async (body: AnswerRequest, onStep: (step: AnswerStep) => void, signal?: AbortSignal) => {
    try {
      return await streamAnswer(body, onStep, signal)
    } catch (e) {
      const unavailable = e instanceof StreamBrokenError || (e instanceof ApiError && e.status === 404) || e instanceof TypeError
      if (!unavailable || signal?.aborted) throw e
      return answerApi.answer(body, signal)
    }
  },
}
