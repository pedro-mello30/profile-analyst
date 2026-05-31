import { useHealth } from '@/hooks/useHealth'

export function HealthDot() {
  const { isHealthy, isLoading, data } = useHealth()

  const color = isLoading ? 'var(--text-muted)' : isHealthy ? 'var(--teal)' : 'var(--red)'
  const label = isLoading ? 'Connecting…' : isHealthy ? `neo4j:${data?.neo4j} ollama:${data?.ollama}` : 'API unreachable'

  return (
    <div className="flex items-center gap-2" title={label}>
      <span
        role="status"
        aria-label={label}
        style={{
          display: 'inline-block',
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: color,
          boxShadow: isHealthy ? `0 0 6px ${color}` : 'none',
          transition: 'background 0.4s, box-shadow 0.4s',
        }}
      />
      <span
        style={{
          fontFamily: 'JetBrains Mono',
          fontSize: 10,
          letterSpacing: '0.08em',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
        }}
      >
        {isLoading ? 'connecting' : isHealthy ? 'online' : 'offline'}
      </span>
    </div>
  )
}
