// Query-term extraction for highlighting matches in evidence passages.

const STOPWORDS = new Set(
  'the and for with what how did does was were are from that this have has had its their into than then when which who why about over under each year fiscal company companies'.split(' '),
)

/** Query words worth highlighting (lowercased, length >= 3, no stopwords). */
export function highlightTerms(query: string): string[] {
  const words = query.toLowerCase().match(/[a-z0-9&$.%-]+/g) ?? []
  return [...new Set(words.map((w) => w.replace(/[.%-]+$/, '')).filter((w) => w.length >= 3 && !STOPWORDS.has(w)))]
}
