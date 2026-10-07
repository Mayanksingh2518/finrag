// Per-company accent gradients for avatars and filter dots.
const COLORS: Record<string, [string, string]> = {
  AAPL: ['#e2e8f0', '#64748b'],
  MSFT: ['#38bdf8', '#2563eb'],
  NVDA: ['#a3e635', '#16a34a'],
  AMZN: ['#fbbf24', '#ea580c'],
  GOOGL: ['#60a5fa', '#10b981'],
  META: ['#818cf8', '#2563eb'],
  TSLA: ['#fb7185', '#dc2626'],
  JPM: ['#a8a29e', '#57534e'],
  V: ['#818cf8', '#ca8a04'],
  MA: ['#fb923c', '#e11d48'],
}

const FALLBACK: [string, string] = ['#a78bfa', '#06b6d4']

export function tickerGradient(ticker: string): string {
  const [a, b] = COLORS[ticker] ?? FALLBACK
  return `linear-gradient(135deg, ${a}, ${b})`
}

export function tickerColor(ticker: string): string {
  return (COLORS[ticker] ?? FALLBACK)[0]
}

// Short, readable names for the most-used 10-K items (full titles come from /api/meta).
export const SECTION_SHORT: Record<string, string> = {
  'Item 1': 'Business',
  'Item 1A': 'Risk factors',
  'Item 1C': 'Cybersecurity',
  'Item 3': 'Legal',
  'Item 5': 'Market & buybacks',
  'Item 7': 'MD&A',
  'Item 7A': 'Market risk',
  'Item 8': 'Financials',
}

export const MODE_LABELS: Record<string, string> = {
  bm25: 'BM25',
  dense: 'Dense',
  hybrid: 'Hybrid',
  hybrid_rerank: 'Hybrid + Rerank',
}
