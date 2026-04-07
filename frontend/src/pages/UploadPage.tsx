import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

type RegimeTributario = 'auto' | 'normal' | 'simples_nacional'

export default function UploadPage() {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [regime, setRegime] = useState<RegimeTributario>('auto')
  const navigate = useNavigate()

  const handleFile = useCallback(async (file: File) => {
    setUploading(true)
    setError('')
    try {
      const regimeParam = regime === 'auto' ? '' : regime
      const result = await api.uploadFile(file, regimeParam)
      navigate(`/files/${result.file_id}?validate=1`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao fazer upload')
    } finally {
      setUploading(false)
    }
  }, [navigate, regime])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const onFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
  }, [handleFile])

  return (
    <div className="max-w-2xl mx-auto mt-6 md:mt-12 px-2">
      <h2 className="text-xl md:text-2xl font-bold mb-6">Upload de Arquivo SPED EFD</h2>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-lg p-8 md:p-12 text-center transition-colors touch-manipulation ${
          dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        {uploading ? (
          <p className="text-gray-500">Processando arquivo...</p>
        ) : (
          <>
            <p className="text-gray-500 mb-4 text-sm md:text-base">
              Arraste o arquivo SPED aqui ou
            </p>
            <label className="cursor-pointer bg-blue-600 text-white px-6 py-3 md:px-4 md:py-2 rounded hover:bg-blue-700 inline-block text-sm md:text-base">
              Selecionar arquivo
              <input type="file" accept=".txt" onChange={onFileSelect} className="hidden" />
            </label>
          </>
        )}
      </div>

      <div className="mt-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Regime Tributario
        </label>
        <select
          value={regime}
          onChange={(e) => setRegime(e.target.value as RegimeTributario)}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        >
          <option value="auto">Detectar automaticamente (IND_PERFIL)</option>
          <option value="normal">Regime Normal (Lucro Real / Presumido)</option>
          <option value="simples_nacional">Simples Nacional</option>
        </select>
        <p className="mt-1 text-xs text-gray-500">
          {regime === 'auto'
            ? 'O sistema detecta o regime pelo campo IND_PERFIL do registro 0000.'
            : regime === 'simples_nacional'
            ? 'Ativa validacoes CSOSN, CST PIS/COFINS e credito ICMS do Simples.'
            : 'Ativa validacoes CST Tabela A, aliquotas interestaduais e DIFAL.'}
        </p>
      </div>

      {error && (
        <p className="mt-4 text-red-600 bg-red-50 p-3 rounded text-sm">{error}</p>
      )}
    </div>
  )
}
