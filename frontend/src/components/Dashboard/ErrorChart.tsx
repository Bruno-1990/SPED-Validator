import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import { api } from '../../api/client'
import type { ValidationError } from '../../types/sped'

interface Props {
  fileId: number
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#dc2626',
  error: '#ea580c',
  warning: '#ca8a04',
  info: '#2563eb',
}

const CERTEZA_COLORS: Record<string, string> = {
  objetivo: '#16a34a',
  provavel: '#2563eb',
  indicio: '#ca8a04',
}

const BLOCK_COLOR = '#3b82f6'

export default function ErrorChart({ fileId }: Props) {
  const [blockData, setBlockData] = useState<{ block: string; count: number }[]>([])
  const [severityData, setSeverityData] = useState<{ name: string; value: number }[]>([])
  const [certezaData, setCertezaData] = useState<{ name: string; count: number }[]>([])
  const [topErrorTypes, setTopErrorTypes] = useState<{ name: string; count: number }[]>([])
  const [registerData, setRegisterData] = useState<{ name: string; count: number }[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.getErrors(fileId, { limit: '5000' })
      .then((errors: ValidationError[]) => {
        // By block
        const blocks: Record<string, number> = {}
        errors.forEach((e) => {
          const block = e.register?.charAt(0) || '?'
          blocks[block] = (blocks[block] || 0) + 1
        })
        setBlockData(
          ['C', 'D', 'E', 'H', '0'].filter(b => blocks[b]).map(b => ({ block: `Bloco ${b}`, count: blocks[b] }))
        )

        // By severity
        const sevs: Record<string, number> = {}
        errors.forEach((e) => { sevs[e.severity] = (sevs[e.severity] || 0) + 1 })
        setSeverityData(
          Object.entries(sevs).map(([name, value]) => ({ name: severityLabel(name), value }))
        )

        // By certeza
        const certs: Record<string, number> = {}
        errors.forEach((e) => {
          const c = e.certeza || 'indefinido'
          certs[c] = (certs[c] || 0) + 1
        })
        setCertezaData(
          ['objetivo', 'provavel', 'indicio'].filter(c => certs[c]).map(c => ({ name: certezaLabel(c), count: certs[c] }))
        )

        // Top 10 error types
        const types: Record<string, number> = {}
        errors.forEach((e) => { types[e.error_type] = (types[e.error_type] || 0) + 1 })
        setTopErrorTypes(
          Object.entries(types)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 10)
            .map(([name, count]) => ({ name, count }))
        )

        // By register
        const regs: Record<string, number> = {}
        errors.forEach((e) => { regs[e.register] = (regs[e.register] || 0) + 1 })
        setRegisterData(
          Object.entries(regs)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 10)
            .map(([name, count]) => ({ name, count }))
        )
      })
      .catch(() => { /* */ })
      .finally(() => setLoading(false))
  }, [fileId])

  if (loading) return <p className="text-gray-400 text-sm animate-pulse">Carregando graficos...</p>

  if (blockData.length === 0 && severityData.length === 0) {
    return <p className="text-gray-400 text-sm">Sem dados para graficos.</p>
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Bar chart: erros por bloco */}
      {blockData.length > 0 && (
        <div className="bg-white rounded shadow p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Erros por Bloco</h4>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={blockData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="block" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill={BLOCK_COLOR} radius={[4, 4, 0, 0]} name="Erros" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Pie chart: por severidade */}
      {severityData.length > 0 && (
        <div className="bg-white rounded shadow p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Por Severidade</h4>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={severityData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={75}
                label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                labelLine={false}
              >
                {severityData.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={SEVERITY_COLORS[reverseSeverityLabel(entry.name)] || '#94a3b8'}
                  />
                ))}
              </Pie>
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Bar chart: por certeza */}
      {certezaData.length > 0 && (
        <div className="bg-white rounded shadow p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Por Certeza</h4>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={certezaData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} name="Erros">
                {certezaData.map((entry) => (
                  <Cell key={entry.name} fill={CERTEZA_COLORS[reverseCertezaLabel(entry.name)] || '#94a3b8'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Horizontal bar chart: Top 10 tipos de erro */}
      {topErrorTypes.length > 0 && (
        <div className="bg-white rounded shadow p-4 lg:col-span-2">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Top 10 Tipos de Erro</h4>
          <ResponsiveContainer width="100%" height={Math.max(220, topErrorTypes.length * 28)}>
            <BarChart data={topErrorTypes} layout="vertical" margin={{ left: 120 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10 }} width={120} />
              <Tooltip />
              <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} name="Erros" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Bar chart: apontamentos por registro */}
      {registerData.length > 0 && (
        <div className="bg-white rounded shadow p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Por Registro</h4>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={registerData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#0891b2" radius={[4, 4, 0, 0]} name="Erros" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

function severityLabel(s: string): string {
  return { critical: 'Critico', error: 'Erro', warning: 'Aviso', info: 'Info' }[s] || s
}

function reverseSeverityLabel(label: string): string {
  return { Critico: 'critical', Erro: 'error', Aviso: 'warning', Info: 'info' }[label] || label
}

function certezaLabel(c: string): string {
  return { objetivo: 'Objetivo', provavel: 'Provavel', indicio: 'Indicio' }[c] || c
}

function reverseCertezaLabel(label: string): string {
  return { Objetivo: 'objetivo', Provavel: 'provavel', Indicio: 'indicio' }[label] || label
}
