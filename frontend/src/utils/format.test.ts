import { describe, it, expect } from 'vitest'
import { formatCurrency, formatWeight, formatDimension, formatPercent, formatClass } from './format'

describe('formatCurrency', () => {
  it('formats small values with full precision', () => {
    expect(formatCurrency(20.28)).toBe('$20.28')
    expect(formatCurrency(1014.28)).toBe('$1,014.28')
  })

  it('keeps the trailing zero when there are cents', () => {
    expect(formatCurrency(10167.9)).toBe('$10,167.90')
    expect(formatCurrency(394)).toBe('$394')
  })

  it('uses compact notation for large values', () => {
    const result = formatCurrency(150000)
    expect(result).toMatch(/\$150K/)
  })
})

describe('formatWeight', () => {
  it('formats with two decimal places and lb suffix', () => {
    expect(formatWeight(21.5)).toBe('21.50 lb')
  })
})

describe('formatDimension', () => {
  it('formats with two decimal places and inch symbol', () => {
    expect(formatDimension(11.25)).toBe('11.25″')
  })
})

describe('formatPercent', () => {
  it('converts ratio to percentage with one decimal', () => {
    expect(formatPercent(0.125)).toBe('12.5%')
  })
})

describe('formatClass', () => {
  it('formats freight class label', () => {
    expect(formatClass(50)).toBe('Class 50')
  })
})
