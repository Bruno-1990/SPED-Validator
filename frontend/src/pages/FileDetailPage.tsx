import { useCallback, useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ErrorSummary, FileInfo, ValidationError } from '../types/sped'

export default function FileDetailPage() {
  const { fileId } = useParams<{ fileId: string }>()
  const id = Number(fileId)
  const [file, setFile] = useState<FileInfo | null>(null)
  const [summary, setSummary] = useState<ErrorSummary | null>(null)
  const [errors, setErrors] = useState<ValidationError[]>([])
  const [validating, setValidating] = useState(false)
  const [tab, setTab] = useState<'summary' | 'errors' | 'report'>('summary')

  const loadData = useCallback(async () => {
    const f = await api.getFile(id)
    setFile(f)
    if (f.status === 'validated') {
      const [s, e] = await Promise.all([api.getSummary(id), api.getErrors(id)])
      setSummary(s)
      setErrors(e)
    }
  }, [id])

  useEffect(() => { loadData() }, [loadData])

  const handleValidate = async () => {
    setValidating(true)
    await api.validate(id)
    await loadData()
    setValidating(false)
    setTab('summary')
  }

  if (!file) return <p className="text-gray-500">Carregando...</p>

  const conformidade = file.total_records > 0
    ? ((file.total_records - file.total_errors) / file.total_records * 100).toFixed(1)
    : '100.0'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to="/files" className="text-sm text-blue-600 hover:underline">&larr; Voltar</Link>
          <h2 className="text-2xl font-bold">{file.filename}</h2>
          <p className="text-sm text-gray-500">
            {file.company_name} | CNPJ: {file.cnpj} | {file.period_start} a {file.period_end}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleValidate}
            disabled={validating}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {validating ? 'Validando...' : file.status === 'validated' ? 'Revalidar' : 'Validar'}
          </button>
          {file.status === 'validated' && (
            <a
              href={api.downloadSped(id)}
              className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
            >
              Baixar SPED
            </a>
          )}
        </div>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Registros</p>
          <p className="text-2xl font-bold">{file.total_records}</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Erros</p>
          <p className={`text-2xl font-bold ${file.total_errors > 0 ? 'text-red-600' : 'text-green-600'}`}>
            {file.total_errors}
          </p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Conformidade</p>
          <p className="text-2xl font-bold">{conformidade}%</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Status</p>
          <p className="text-2xl font-bold capitalize">{file.status}</p>
        </div>
      </div>

      {/* Tabs */}
      {file.status === 'validated' && (
        <>
          <div className="flex gap-4 border-b mb-4">
            {(['summary', 'errors', 'report'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`pb-2 px-1 text-sm ${tab === t ? 'border-b-2 border-blue-600 font-semibold' : 'text-gray-500'}`}
              >
                {t === 'summary' ? 'Resumo' : t === 'errors' ? 'Erros' : 'Relatorio'}
              </button>
            ))}
          </div>

          {tab === 'summary' && summary && <SummaryTab summary={summary} />}
          {tab === 'errors' && <ErrorsTab errors={errors} />}
          {tab === 'report' && <ReportTab fileId={id} />}
        </>
      )}
    </div>
  )
}

function SummaryTab({ summary }: { summary: ErrorSummary }) {
  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <h3 className="font-semibold mb-2">Por Tipo</h3>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(summary.by_type).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
              <tr key={type} className="border-t">
                <td className="p-2 font-mono">{type}</td>
                <td className="p-2 text-right font-semibold">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="font-semibold mb-2">Por Severidade</h3>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(summary.by_severity).map(([sev, count]) => (
              <tr key={sev} className="border-t">
                <td className="p-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    sev === 'critical' ? 'bg-red-100 text-red-700' :
                    sev === 'warning' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-orange-100 text-orange-700'
                  }`}>{sev}</span>
                </td>
                <td className="p-2 text-right font-semibold">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ErrorsTab({ errors }: { errors: ValidationError[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-100 text-left">
            <th className="p-2">Linha</th>
            <th className="p-2">Registro</th>
            <th className="p-2">Campo</th>
            <th className="p-2">Tipo</th>
            <th className="p-2">Severidade</th>
            <th className="p-2">Mensagem</th>
          </tr>
        </thead>
        <tbody>
          {errors.map((e) => (
            <tr key={e.id} className="border-t hover:bg-gray-50">
              <td className="p-2 font-mono">{e.line_number}</td>
              <td className="p-2 font-mono">{e.register}</td>
              <td className="p-2">{e.field_name || '-'}</td>
              <td className="p-2 font-mono text-xs">{e.error_type}</td>
              <td className="p-2">
                <span className={`px-2 py-0.5 rounded text-xs ${
                  e.severity === 'critical' ? 'bg-red-100 text-red-700' :
                  e.severity === 'warning' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-orange-100 text-orange-700'
                }`}>{e.severity}</span>
              </td>
              <td className="p-2 text-xs max-w-md truncate">{e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReportTab({ fileId }: { fileId: number }) {
  const [report, setReport] = useState('')
  const [format, setFormat] = useState('md')

  useEffect(() => {
    api.getReport(fileId, format).then(setReport)
  }, [fileId, format])

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {['md', 'csv', 'json'].map((f) => (
          <button
            key={f}
            onClick={() => setFormat(f)}
            className={`px-3 py-1 rounded text-sm ${format === f ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
          >
            {f.toUpperCase()}
          </button>
        ))}
      </div>
      <pre className="bg-gray-900 text-gray-100 p-4 rounded overflow-auto text-xs max-h-[600px]">
        {report}
      </pre>
    </div>
  )
}
