import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { AuditScope } from '../../types/sped'

interface Props {
  fileId: number
}

const STATUS_ICONS: Record<string, { icon: string; color: string }> = {
  ok:      { icon: '\u2713', color: 'text-green-600' },
  partial: { icon: '\u26A0', color: 'text-yellow-600' },
  not_run: { icon: '\u2717', color: 'text-red-500' },
}

export default function AuditScopePanel({ fileId }: Props) {
  const [scope, setScope] = useState<AuditScope | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    setLoading(true)
    setError(false)
    api.getAuditScope(fileId)
      .then(setScope)
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [fileId])

  if (loading) return null
  if (error || !scope) return null

  const coverage = scope.coverage_pct
  const bannerColor = coverage < 80
    ? 'bg-red-50 border-red-300 text-red-800'
    : coverage < 100
    ? 'bg-yellow-50 border-yellow-300 text-yellow-800'
    : 'bg-green-50 border-green-300 text-green-800'

  const barColor = coverage < 80 ? 'bg-red-500' : coverage < 100 ? 'bg-yellow-500' : 'bg-green-500'

  return (
    <div className={`rounded-lg border p-4 mb-6 ${bannerColor}`}>
      {/* Coverage header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">Escopo da Auditoria</h3>
        <span className="text-lg font-bold">{coverage.toFixed(0)}% de cobertura</span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-2 mb-4">
        <div className={`h-2 rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${Math.min(coverage, 100)}%` }} />
      </div>

      {/* Checks */}
      {scope.checks.length > 0 && (
        <div className="mb-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide mb-2 opacity-70">Verificacoes</h4>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {scope.checks.map((check, i) => {
              const cfg = STATUS_ICONS[check.status] || STATUS_ICONS.not_run
              return (
                <div key={i} className="flex items-center gap-2 text-xs bg-white bg-opacity-50 rounded px-2 py-1.5">
                  <span className={`font-bold ${cfg.color}`}>{cfg.icon}</span>
                  <span className="text-gray-700">{check.name}</span>
                  {check.detail && (
                    <span className="text-gray-400 ml-auto truncate max-w-[100px]" title={check.detail}>
                      {check.detail}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Missing tables */}
      {scope.missing_tables.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide mb-1 opacity-70">Tabelas externas ausentes</h4>
          <div className="flex flex-wrap gap-1">
            {scope.missing_tables.map((t) => (
              <span key={t} className="text-xs font-mono bg-white bg-opacity-60 px-2 py-0.5 rounded border border-current border-opacity-20">
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
