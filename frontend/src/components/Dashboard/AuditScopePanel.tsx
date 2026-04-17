import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { AuditScope } from '../../types/sped'

interface Props {
  fileId: number
}

const STATUS_ICONS: Record<string, { icon: string; color: string }> = {
  ok:             { icon: '\u2713', color: 'text-green-600' },
  partial:        { icon: '\u26A0', color: 'text-yellow-600' },
  not_run:        { icon: '\u2717', color: 'text-red-500' },
  not_applicable: { icon: '\u2014', color: 'text-gray-400' },
}

export default function AuditScopePanel({ fileId }: Props) {
  const [scope, setScope] = useState<AuditScope | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [expanded, setExpanded] = useState(false)

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

  const okCount = scope.checks.filter(c => c.status === 'ok').length
  const totalChecks = scope.checks.length

  return (
    <div className={`rounded-lg border mb-4 ${bannerColor} transition-all`}>
      {/* Header compacto — sempre visivel */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:opacity-90 transition-opacity"
      >
        <div className="flex-1 min-w-0 flex items-center gap-3">
          <span className="text-sm font-semibold">Cobertura</span>
          <div className="flex-1 max-w-[200px] bg-gray-200 rounded-full h-1.5">
            <div className={`h-1.5 rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${Math.min(coverage, 100)}%` }} />
          </div>
          <span className="text-sm font-bold">{coverage.toFixed(0)}%</span>
          <span className="text-xs opacity-60">({okCount}/{totalChecks} verificacoes)</span>
        </div>
        <span className="text-xs opacity-50">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      {/* Conteudo expandido */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-current border-opacity-10">
          {/* Checks */}
          {scope.checks.length > 0 && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold tracking-wide mb-2 opacity-70">Verificacoes realizadas</h4>
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
            <div className="mb-3">
              <h4 className="text-xs font-semibold tracking-wide mb-1 opacity-70">Tabelas nao carregadas</h4>
              <div className="flex flex-wrap gap-1">
                {scope.missing_tables.map((t) => (
                  <span key={t} className="text-xs font-mono bg-white bg-opacity-60 px-2 py-0.5 rounded border border-current border-opacity-20">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Scope limitations */}
          <details className="mt-2">
            <summary className="text-xs font-semibold cursor-pointer opacity-70 hover:opacity-100">
              O que ainda nao e verificado
            </summary>
            <ul className="mt-2 text-xs text-gray-700 space-y-1.5 ml-4 list-disc">
              <li>Beneficios fiscais — precisam de ato concessivo ou convenio</li>
              <li>Cruzamento com EFD-Contribuicoes — arquivo separado</li>
              <li>Protocolos de ICMS-ST por estado e NCM</li>
              <li>Escrituracoes de outros periodos</li>
            </ul>
          </details>
        </div>
      )}
    </div>
  )
}
