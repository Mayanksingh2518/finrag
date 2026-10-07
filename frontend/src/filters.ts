import type { ChunkType, SearchMode } from './api'

// Filter state shared by the filter panel, the URL and the search request.
export interface FilterState {
  tickers: string[]
  fiscal_years: number[]
  sections: string[]
  chunk_types: ChunkType[]
  mode: SearchMode
  k: number
  decompose: boolean
}

export const DEFAULT_FILTERS: FilterState = {
  tickers: [],
  fiscal_years: [],
  sections: [],
  chunk_types: [],
  mode: 'hybrid_rerank',
  k: 8,
  decompose: false,
}
