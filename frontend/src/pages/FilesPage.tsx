import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { FileInfo } from '../types/sped'

export default function FilesPage() {
  const [files, setFiles] = useState<FileInfo[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listFiles().then(setFiles).finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-gray-500">Carregando...</p>

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Arquivos Processados</h2>

      {files.length === 0 ? (
        <p className="text-gray-500">Nenhum arquivo processado. <Link to="/" className="text-blue-600 underline">Faça upload</Link></p>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100 text-left text-sm">
              <th className="p-3">Arquivo</th>
              <th className="p-3">Empresa</th>
              <th className="p-3">CNPJ</th>
              <th className="p-3">Periodo</th>
              <th className="p-3">Registros</th>
              <th className="p-3">Erros</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.id} className="border-t hover:bg-gray-50">
                <td className="p-3">
                  <Link to={`/files/${f.id}`} className="text-blue-600 hover:underline">{f.filename}</Link>
                </td>
                <td className="p-3 text-sm">{f.company_name || '-'}</td>
                <td className="p-3 text-sm font-mono">{f.cnpj || '-'}</td>
                <td className="p-3 text-sm">{f.period_start && f.period_end ? `${f.period_start} - ${f.period_end}` : '-'}</td>
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
                  }`}>{f.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
