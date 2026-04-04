import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

export default function UploadPage() {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleFile = useCallback(async (file: File) => {
    setUploading(true)
    setError('')
    try {
      const result = await api.uploadFile(file)
      navigate(`/files/${result.file_id}?validate=1`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao fazer upload')
    } finally {
      setUploading(false)
    }
  }, [navigate])

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
    <div className="max-w-2xl mx-auto mt-12">
      <h2 className="text-2xl font-bold mb-6">Upload de Arquivo SPED EFD</h2>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
          dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        {uploading ? (
          <p className="text-gray-500">Processando arquivo...</p>
        ) : (
          <>
            <p className="text-gray-500 mb-4">Arraste o arquivo SPED aqui ou</p>
            <label className="cursor-pointer bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
              Selecionar arquivo
              <input type="file" accept=".txt" onChange={onFileSelect} className="hidden" />
            </label>
          </>
        )}
      </div>

      {error && (
        <p className="mt-4 text-red-600 bg-red-50 p-3 rounded">{error}</p>
      )}
    </div>
  )
}
