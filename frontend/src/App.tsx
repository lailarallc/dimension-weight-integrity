import { useState } from 'react'
import type { Chapter } from './types'
import { CHAPTER_ORDER, chapterIndex } from './types'
import { heroData, allSkusData } from './data'
import { formatCurrency } from './utils/format'
import ChapterNav from './components/ChapterNav'
import QuizView from './components/QuizView'
import CostReveal from './components/CostReveal'
import ParadoxToggle from './components/ParadoxToggle'
import GovernanceResolution from './components/GovernanceResolution'
import PortfolioView from './components/PortfolioView'

export default function App() {
  const [active, setActive] = useState<Chapter>('quiz')
  const [furthest, setFurthest] = useState<Chapter>('quiz')

  function navigate(chapter: Chapter) {
    setActive(chapter)
    if (chapterIndex(chapter) > chapterIndex(furthest)) {
      setFurthest(chapter)
    }
  }

  function advance() {
    const idx = chapterIndex(active)
    const next = CHAPTER_ORDER[idx + 1]
    if (next) {
      navigate(next)
    }
  }

  // Mismatched SKUs whose freight reclass costs money. A shift to a cheaper
  // class is still a mismatch, but its freight cost floors at zero.
  const freightCostSkus = allSkusData.skus.filter(
    (s) => (s.cost.drivers.ltl_reclass?.annual_cost ?? 0) > 0,
  ).length

  return (
    <div className="app">
      <header className="app-header">
        <p className="brand-subtitle">Cinderhaven Provisions</p>
        <h1 className="brand-title">Dimension &amp; Weight Integrity</h1>

        <div className="hero-stat">
          <p className="hero-stat-eyebrow">Annual cost of divergence</p>
          <span className="hero-stat-value">
            {formatCurrency(Math.round(allSkusData.aggregate.total_annual_cost))}
          </span>
          <p className="hero-stat-label">
            leaks from this 50-SKU portfolio every year.
          </p>
          <p className="hero-stat-range">
            Modeled on revenue spread evenly across the catalog.{' '}
            {allSkusData.aggregate.skus_with_class_mismatch} of the{' '}
            {allSkusData.aggregate.total_skus} SKUs have a freight class
            mismatch, and {freightCostSkus} of those carry a freight cost.
            Concentrating volume on those {freightCostSkus} raises this to
            $565K; concentrating it on the other SKUs lowers it to $64.4K.
          </p>
          <p className="hero-stat-disclosure">
            Synthetic dataset &mdash; a modeled ~$25M specialty food portfolio.
            Data is synthetic; methodology and cost models are real.
          </p>
        </div>

        <p className="app-lede">
          Four systems &mdash; NetSuite, the WMS, GDSN, and Shopify &mdash;
          disagree on what each product weighs and measures. The mismatches
          reclassify freight, trigger parcel reweigh back-bills, and draw
          retailer chargebacks.
        </p>

        <div className="why-diverge">
          <p className="why-diverge__q">Why would four systems disagree?</p>
          <p className="why-diverge__body">
            Because each was built to answer a different question. NetSuite
            records a weight at item setup; the warehouse measures the physical
            case at receiving; the GDSN feed publishes a padded outer box for
            retailers; Shopify carries the weight of a single unit as it ships
            to a customer. Every value is right for its own purpose &mdash;
            which is exactly why no one team ever reconciles them, and the gap
            keeps costing money.
          </p>
        </div>
      </header>
      <ChapterNav active={active} furthest={furthest} onNavigate={navigate} />
      <main className="chapter-content">
        {active === 'quiz' && <QuizView data={heroData} onComplete={advance} />}
        {active === 'cost' && <CostReveal data={heroData} onComplete={advance} />}
        {active === 'paradox' && <ParadoxToggle data={heroData} onComplete={advance} />}
        {active === 'resolution' && (
          <>
            <GovernanceResolution data={heroData} />
            <div style={{ textAlign: 'center', marginTop: 40 }}>
              <button className="btn-primary" onClick={advance}>Continue</button>
            </div>
          </>
        )}
        {active === 'portfolio' && <PortfolioView data={allSkusData} />}
      </main>
      <footer className="site-disclosure">
        <p>
          Built on the Cinderhaven synthetic dataset. Cost models are computed
          from physics and published rate benchmarks, not asserted.
        </p>
      </footer>
    </div>
  )
}
