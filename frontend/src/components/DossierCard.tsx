interface ComplianceFlag { label: string; severity: 'art9' | 'ftc' | 'info' }
interface Attribute { label: string; confidence: number }

interface DossierManifest {
  handle?: string
  platform?: string
  follower_count?: number
  niche?: string
  niche_confidence?: number
  engagement_rate?: number
  avg_likes?: number
  avg_comments?: number
  sponsored_post_count?: number
  ftc_disclosure_status?: string
  flagged_posts?: string[]
  compliance_flags?: ComplianceFlag[]
  brand_affinities?: string[]
  content_attributes?: Attribute[]
  [key: string]: unknown
}

interface Props { manifest: DossierManifest | null }

function SectionHeader({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
      <span className="section-label">{label}</span>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  )
}

function ConfBar({ value }: { value: number }) {
  return (
    <div className="conf-track">
      <div className="conf-fill" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

const SEVERITY: Record<string, { bg: string; border: string; color: string; label: string }> = {
  art9: { bg: 'rgba(251,191,36,0.06)', border: 'rgba(251,191,36,0.2)', color: '#FBB924', label: 'ART.9' },
  ftc:  { bg: 'rgba(248,113,113,0.06)', border: 'rgba(248,113,113,0.2)', color: 'var(--red)', label: 'FTC' },
  info: { bg: 'var(--bg-elevated)', border: 'var(--border)', color: 'var(--text-muted)', label: 'INFO' },
}

export function DossierCard({ manifest }: Props) {
  if (!manifest) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-muted)' }}>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 32, marginBottom: 8, opacity: 0.3 }}>∅</div>
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          No dossier data available
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 fade-in">
      {/* ── Profile ── */}
      <div className="surface p-4">
        <SectionHeader label="Profile" />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <p style={{ fontFamily: 'Syne', fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
              @{manifest.handle}
            </p>
            <p style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 2 }}>
              {manifest.platform ?? 'instagram'}
            </p>
          </div>
          {manifest.follower_count != null && (
            <div style={{ textAlign: 'right' }}>
              <p style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: 'var(--amber)' }}>
                {manifest.follower_count.toLocaleString()}
              </p>
              <p style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                followers
              </p>
            </div>
          )}
        </div>
        {manifest.niche && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: 'var(--text-primary)' }}>
                {manifest.niche}
              </span>
              {manifest.niche_confidence != null && (
                <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: 'var(--amber)' }}>
                  {Math.round(manifest.niche_confidence * 100)}%
                </span>
              )}
            </div>
            {manifest.niche_confidence != null && <ConfBar value={manifest.niche_confidence} />}
          </div>
        )}
      </div>

      {/* ── Engagement ── */}
      {(manifest.engagement_rate != null || manifest.avg_likes != null) && (
        <div className="surface p-4">
          <SectionHeader label="Engagement" />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
            {manifest.engagement_rate != null && (
              <div style={{ textAlign: 'center' }}>
                <p style={{ fontFamily: 'Syne', fontSize: 18, fontWeight: 700, color: 'var(--teal)' }}>
                  {manifest.engagement_rate}%
                </p>
                <p style={{ fontFamily: 'JetBrains Mono', fontSize: 8, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 3 }}>
                  ER/Followers
                </p>
              </div>
            )}
            {manifest.avg_likes != null && (
              <div style={{ textAlign: 'center' }}>
                <p style={{ fontFamily: 'Syne', fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {manifest.avg_likes.toLocaleString()}
                </p>
                <p style={{ fontFamily: 'JetBrains Mono', fontSize: 8, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 3 }}>
                  Avg Likes
                </p>
              </div>
            )}
            {manifest.avg_comments != null && (
              <div style={{ textAlign: 'center' }}>
                <p style={{ fontFamily: 'Syne', fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {manifest.avg_comments.toLocaleString()}
                </p>
                <p style={{ fontFamily: 'JetBrains Mono', fontSize: 8, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 3 }}>
                  Avg Comments
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Sponsored Posts ── */}
      <div className="surface p-4">
        <SectionHeader label="Sponsored Posts" />
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: manifest.flagged_posts?.length ? 12 : 0 }}>
          <span style={{ fontFamily: 'Syne', fontSize: 32, fontWeight: 800, color: 'var(--text-primary)' }}>
            {manifest.sponsored_post_count ?? 0}
          </span>
          <div>
            <p style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 5 }}>
              detected
            </p>
            {manifest.ftc_disclosure_status && (
              <span style={{
                fontFamily: 'JetBrains Mono', fontSize: 9, fontWeight: 600,
                letterSpacing: '0.1em', textTransform: 'uppercase',
                padding: '2px 7px', borderRadius: 3, border: '1px solid',
                ...(manifest.ftc_disclosure_status === 'compliant'
                  ? { color: 'var(--teal)', borderColor: 'rgba(45,212,191,0.3)', background: 'var(--teal-dim)' }
                  : { color: '#FBB924', borderColor: 'rgba(251,185,36,0.3)', background: 'rgba(251,185,36,0.06)' })
              }}>
                FTC: {manifest.ftc_disclosure_status}
              </span>
            )}
          </div>
        </div>
        {manifest.flagged_posts && manifest.flagged_posts.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {manifest.flagged_posts.map((p) => (
              <span key={p} style={{
                fontFamily: 'JetBrains Mono', fontSize: 9, color: 'var(--text-muted)',
                background: 'var(--bg-base)', border: '1px solid var(--border)',
                borderRadius: 3, padding: '2px 6px',
              }}>{p}</span>
            ))}
          </div>
        )}
      </div>

      {/* ── Compliance ── */}
      {manifest.compliance_flags && manifest.compliance_flags.length > 0 && (
        <div className="surface p-4">
          <SectionHeader label="Compliance" />
          <div className="flex flex-col gap-2">
            {manifest.compliance_flags.map((flag, i) => {
              const s = SEVERITY[flag.severity] ?? SEVERITY.info
              return (
                <div
                  key={i}
                  className="fade-in"
                  style={{
                    animationDelay: `${i * 0.05}s`,
                    background: s.bg,
                    border: `1px solid ${s.border}`,
                    borderRadius: 5,
                    padding: '7px 12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                  }}
                >
                  <span style={{
                    fontFamily: 'JetBrains Mono', fontSize: 8, fontWeight: 600,
                    letterSpacing: '0.12em', textTransform: 'uppercase',
                    color: s.color, flexShrink: 0,
                  }}>
                    {s.label}
                  </span>
                  <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: s.color }}>
                    {flag.label}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Attributes ── */}
      {(manifest.brand_affinities?.length || manifest.content_attributes?.length) && (
        <div className="surface p-4">
          <SectionHeader label="Attributes" />
          {manifest.brand_affinities && manifest.brand_affinities.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <p className="section-label" style={{ marginBottom: 8 }}>Brand affinities</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {manifest.brand_affinities.map((b) => (
                  <span key={b} style={{
                    fontFamily: 'JetBrains Mono', fontSize: 10,
                    color: 'var(--text-secondary)', background: 'var(--bg-elevated)',
                    border: '1px solid var(--border)', borderRadius: 4, padding: '3px 9px',
                  }}>{b}</span>
                ))}
              </div>
            </div>
          )}
          {manifest.content_attributes && manifest.content_attributes.length > 0 && (
            <div>
              <p className="section-label" style={{ marginBottom: 10 }}>Content attributes</p>
              <div className="flex flex-col gap-3">
                {manifest.content_attributes.map((attr) => (
                  <div key={attr.label}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                      <span style={{ fontFamily: 'Manrope', fontSize: 12, color: 'var(--text-secondary)' }}>
                        {attr.label}
                      </span>
                      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: 'var(--amber)' }}>
                        {Math.round(attr.confidence * 100)}%
                      </span>
                    </div>
                    <ConfBar value={attr.confidence} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
