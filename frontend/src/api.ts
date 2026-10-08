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
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
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

export const answerApi = {
  answer: (body: AnswerRequest, signal?: AbortSignal) =>
    request<AnswerResponse>('/answer', { method: 'POST', body: JSON.stringify(body), signal }),
}
