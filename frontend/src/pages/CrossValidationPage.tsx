import { useCallback, useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import type { CrossValidationItem } from '../types/sped'

const CROSS_TYPES = [
  { value: '', label: 'Todos' },
  { value: 'C_vs_E', label: 'C vs E' },
  { value: '0_vs_C', label: '0 vs C' },
  { value: 'bloco9', label: 'Bloco 9' },
  { value: 'C_vs_H', label: 'C vs H' },
  { value: 'D_vs_E', label: 'D vs E' },
]

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  error: 'bg-orange-100 text-orange-700',
  warning: 'bg-yellow-100 text-yellow-700',
  info: 'bg-blue-100 text-blue-700',
}

export default function CrossValidationPage() {
  const { fileId } = useParams<{ fileId: string }>()
  const id = Number(fileId)
  const [items, setItems] = useState<CrossValidationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getCrossValidation(id, filter || undefined)
      setItems(data)
    } catch {
      setItems([])
    }
    setLoading(false)
  }, [id, filter])

  useEffect(() => { load() }, [load])

  const displayItems = items

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to={`/files/${id}`} className="text-sm text-blue-600 hover:underline">&larr; Voltar ao arquivo</Link>
          <h2 className="text-2xl font-bold mt-1">Cruzamentos entre Blocos</h2>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm text-gray-500">Filtrar:</label>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="border rounded px-3 py-1.5 text-sm focus:ring-2 focus:ring-blue-300 focus:border-blue-500"
          >
            {CROSS_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Total</p>
          <p className="text-2xl font-bold">{displayItems.length}</p>
        </div>
        {['critical', 'error', 'warning'].map((sev) => {
          const count = displayItems.filter(i => i.severity === sev).length
          return (
            <div key={sev} className="bg-white p-4 rounded shadow">
              <p className="text-sm text-gray-500 capitalize">{sev === 'critical' ? 'Criticos' : sev === 'error' ? 'Erros' : 'Avisos'}</p>
              <p className={`text-2xl font-bold ${sev === 'critical' ? 'text-red-600' : sev === 'error' ? 'text-orange-600' : 'text-yellow-600'}`}>{count}</p>
            </div>
          )
        })}
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-gray-500 text-center py-8 animate-pulse">Carregando cruzamentos...</p>
      ) : displayItems.length === 0 ? (
        <p className="text-gray-500 text-center py-8">Nenhum cruzamento encontrado.</p>
      ) : (
        <div className="bg-white rounded shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="p-3">Tipo</th>
                <th className="p-3">Reg. Origem</th>
                <th className="p-3">Linha</th>
                <th className="p-3">Reg. Destino</th>
                <th className="p-3">Linha</th>
                <th className="p-3 text-right">Valor Esperado</th>
                <th className="p-3 text-right">Valor Encontrado</th>
                <th className="p-3 text-right">Diferenca</th>
                <th className="p-3">Severidade</th>
              </tr>
            </thead>
            <tbody>
              {displayItems.map((item) => {
                const diffAboveThreshold = item.difference != null && Math.abs(item.difference) > 0.02
                return (
                  <tr key={item.id} className="border-t hover:bg-gray-50">
                    <td className="p-3 font-mono text-xs">{extractCrossType(item.error_type)}</td>
                    <td className="p-3 font-mono text-xs">{item.register}</td>
                    <td className="p-3 text-xs">{item.line_number}</td>
                    <td className="p-3 font-mono text-xs">{item.dest_register || '-'}</td>
                    <td className="p-3 text-xs">{item.dest_line || '-'}</td>
                    <td className="p-3 text-right font-mono text-xs">{item.expected_value ?? '-'}</td>
                    <td className="p-3 text-right font-mono text-xs">{item.value ?? '-'}</td>
                    <td className={`p-3 text-right font-mono text-xs font-semibold ${diffAboveThreshold ? 'text-red-600' : 'text-gray-600'}`}>
                      {item.difference != null ? formatDiff(item.difference) : '-'}
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[item.severity] || 'bg-gray-100 text-gray-600'}`}>
                        {item.severity === 'critical' ? 'Critico' : item.severity === 'error' ? 'Erro' : item.severity === 'warning' ? 'Aviso' : 'Info'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function extractCrossType(errorType: string): string {
  if (errorType.includes('C190') || errorType.includes('C_VS_E') || errorType.includes('C_vs_E')) return 'C vs E'
  if (errorType.includes('0_VS_C') || errorType.includes('0_vs_C') || errorType.includes('0150')) return '0 vs C'
  if (errorType.includes('BLOCO_9') || errorType.includes('bloco9') || errorType.includes('9900')) return 'Bloco 9'
  if (errorType.includes('C_VS_H') || errorType.includes('C_vs_H') || errorType.includes('H010')) return 'C vs H'
  if (errorType.includes('D_VS_E') || errorType.includes('D_vs_E') || errorType.includes('D190')) return 'D vs E'
  return errorType
}

function formatDiff(diff: number): string {
  const abs = Math.abs(diff)
  const sign = diff >= 0 ? '+' : '-'
  return `${sign}${abs.toFixed(2)}`
}
