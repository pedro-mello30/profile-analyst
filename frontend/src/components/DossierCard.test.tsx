import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DossierCard } from './DossierCard'

const mockManifest = {
  handle: 'sample_creator',
  platform: 'instagram',
  follower_count: 12500,
  niche: 'fitness',
  niche_confidence: 0.91,
  engagement_rate: 4.2,
  avg_likes: 520,
  avg_comments: 31,
  sponsored_post_count: 2,
  ftc_disclosure_status: 'partial',
  flagged_posts: ['post_abc', 'post_def'],
  compliance_flags: [
    { label: 'Art.9 risk: health inference', severity: 'art9' as const },
    { label: 'FTC: undisclosed #ad', severity: 'ftc' as const },
  ],
  brand_affinities: ['Nike', 'Whey Protein Co'],
  content_attributes: [
    { label: 'Outdoor sports', confidence: 0.85 },
    { label: 'Nutrition', confidence: 0.72 },
  ],
}

describe('DossierCard', () => {
  it('renders empty state when manifest is null', () => {
    render(<DossierCard manifest={null} />)
    expect(screen.getByText(/no dossier data available/i)).toBeInTheDocument()
  })

  it('renders handle and follower count in profile section', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('@sample_creator')).toBeInTheDocument()
    expect(screen.getByText('12,500')).toBeInTheDocument()
  })

  it('renders niche with confidence', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('fitness')).toBeInTheDocument()
    expect(screen.getByText('91%')).toBeInTheDocument()
  })

  it('renders engagement rate', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('4.2%')).toBeInTheDocument()
  })

  it('renders compliance flags', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('Art.9 risk: health inference')).toBeInTheDocument()
    expect(screen.getByText('FTC: undisclosed #ad')).toBeInTheDocument()
  })

  it('applies amber styling to Art.9 flags and red to FTC flags', () => {
    render(<DossierCard manifest={mockManifest} />)
    // jsdom normalises inline rgba() with spaces: 'rgba(251, 191, 36, 0.06)'
    const art9El = screen.getByText('Art.9 risk: health inference')
    expect(art9El.closest('div')?.style.background).toMatch(/251,?\s*191,?\s*36/)
    const ftcEl = screen.getByText('FTC: undisclosed #ad')
    expect(ftcEl.closest('div')?.style.background).toMatch(/248,?\s*113,?\s*113/)
  })

  it('renders brand affinities', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('Nike')).toBeInTheDocument()
    expect(screen.getByText('Whey Protein Co')).toBeInTheDocument()
  })

  it('renders content attributes with confidence percentages', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('Outdoor sports')).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument()
  })
})
