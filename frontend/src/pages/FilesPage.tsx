import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { FileInfo } from '../types/sped'

function formatDate(date: string): string {
  if (date.length === 8 && /^\d+$/.test(date)) {
    return `${date.slice(0, 2)}/${date.slice(2, 4)}/${date.slice(4)}`
  }
  return date
}

export default function FilesPage() {
  const [files, setFiles] = useState<FileInfo[]>([])
  const [loading, setLoading] = useState(true)

  const loadFiles = useCallback(() => {
    setLoading(true)
    api.listFiles().then(setFiles).finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadFiles() }, [loadFiles])

  const handleDeleteAll = useCallback(async () => {
    if (!confirm(`Excluir TODOS os ${files.length} arquivos e seus dados?`)) return
    try {
      for (const f of files) {
        await api.deleteFile(f.id)
      }
      loadFiles()
    } catch {
      alert('Erro ao excluir arquivos')
    }
  }, [files, loadFiles])

  if (loading) return <p className="text-gray-500">Carregando...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Arquivos Processados</h2>
        {files.length > 0 && (
          <button
            type="button"
            onClick={handleDeleteAll}
            className="px-4 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700"
          >
            Excluir Todos
          </button>
        )}
      </div>

      {files.length === 0 ? (
        <p className="text-gray-500">Nenhum arquivo processado. <Link to="/" className="text-blue-600 underline">Faça upload</Link></p>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100 text-left text-sm">
              <th className="p-3">Empresa</th>
              <th className="p-3">CNPJ</th>
              <th className="p-3">Periodo</th>
              <th className="p-3">Registros</th>
              <th className="p-3">Apontamentos</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.id} className="border-t hover:bg-gray-50">
                <td className="p-3">
                  <Link to={`/files/${f.id}`} className="text-blue-600 hover:underline font-medium">
                    {f.company_name || f.filename}
                  </Link>
                  {f.company_name && (
                    <p className="text-xs text-gray-400 mt-0.5">{f.filename}</p>
                  )}
                </td>
                <td className="p-3 text-sm font-mono">{f.cnpj || '-'}</td>
                <td className="p-3 text-sm">{f.period_start && f.period_end ? `${formatDate(f.period_start)} - ${formatDate(f.period_end)}` : '-'}</td>
                <td className="p-3 text-sm">{f.total_records}</td>
                <td className="p-3 text-sm">
                  <span className={f.total_errors > 0 ? 'text-red-600 font-semibold' : 'text-green-600'}>
                    {f.total_errors}
                  </span>
                </td>
                <td className="p-3">
                  <span className={`text-xs px-2 py-1 rounded ${
                    f.status === 'validated' ? 'bg-green-100 text-green-700' :
                    f.status === 'parsed' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-gray-100 text-gray-600'
                  }`}>{f.status === 'validated' ? 'Validado' : f.status === 'parsed' ? 'Processado' : f.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
