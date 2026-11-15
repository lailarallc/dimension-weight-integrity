const wholeCurrencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

const centsCurrencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const compactCurrencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumSignificantDigits: 3,
})

export function formatCurrency(value: number): string {
  if (Math.abs(value) >= 100_000) return compactCurrencyFmt.format(value)
  // Whole dollars show no cents; anything else shows both digits, so
  // $10,167.90 never renders as $10,167.9.
  const cents = Math.round(value * 100)
  return cents % 100 === 0
    ? wholeCurrencyFmt.format(cents / 100)
    : centsCurrencyFmt.format(value)
}

/** Annual volume counts. Whole units get thousands separators; the
 *  risk-adjusted chargeback count is fractional and keeps its decimal. */
export function formatCount(value: number): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
  })
}

export function formatWeight(lb: number): string {
  return `${lb.toFixed(2)} lb`
}

export function formatDimension(inches: number): string {
  return `${inches.toFixed(2)}″`
}

export function formatPercent(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`
}

export function formatClass(freightClass: number): string {
  return `Class ${freightClass}`
}
