import { useCallback, useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'

interface CruzamentoItem {
  id: number
  chave_nfe: string
  rule_id: string
  severity: string
  campo_xml: string
  valor_xml: string
  campo_sped: string
  valor_sped: string
  diferenca: number | null
  message: string
}

interface UploadStats {
  total: number
  autorizadas: number
  canceladas: number
  duplicadas: number
  invalidos: number
}

interface CruzamentoResult {
  xmls_analisados: number
  divergencias: number
  por_severidade: Record<string, number>
}

const SEV_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-300',
  error: 'bg-orange-100 text-orange-800 border-orange-300',
  warning: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  info: 'bg-blue-100 text-blue-800 border-blue-300',
}

export default function XMLCrossPage() {
  const { fileId } = useParams<{ fileId: string }>()
  const fid = Number(fileId)

  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [cruzando, setCruzando] = useState(false)
  const [error, setError] = useState('')

  const [uploadStats, setUploadStats] = useState<UploadStats | null>(null)
  const [cruzResult, setCruzResult] = useState<CruzamentoResult | null>(null)
  const [items, setItems] = useState<CruzamentoItem[]>([])
  const [xmlCount, setXmlCount] = useState(0)
  const [tab, setTab] = useState<'divergencias' | 'ausentes_sped' | 'ausentes_xml'>('divergencias')
  const [filtroSev, setFiltroSev] = useState('')
  const [filtroRegra, setFiltroRegra] = useState('')

  // Carregar dados existentes
  const loadData = useCallback(async () => {
    try {
      const list = await api.listXmls(fid)
      setXmlCount(list.total)
      const cruz = await api.getCruzamento(fid)
      setItems(cruz.divergencias as CruzamentoItem[])
    } catch { /* sem dados ainda */ }
  }, [fid])

  useEffect(() => { loadData() }, [loadData])

  // Upload XMLs
  const handleUpload = useCallback(async (files: FileList | File[]) => {
    setError('')
    setUploading(true)
    try {
      const xmlFiles = Array.from(files).filter(f => f.name.endsWith('.xml'))
      if (xmlFiles.length === 0) { setError('Nenhum arquivo .xml selecionado'); return }
      const stats = await api.uploadXmls(fid, xmlFiles)
      setUploadStats(stats)
      setXmlCount(prev => prev + stats.autorizadas + stats.canceladas)
    } catch (e: any) {
      setError(e.message || 'Erro no upload')
    } finally {
      setUploading(false)
    }
  }, [fid])

  // Cruzar
  const handleCruzar = useCallback(async () => {
    setError('')
    setCruzando(true)
    try {
      const result = await api.cruzarXml(fid)
      setCruzResult(result)
      const cruz = await api.getCruzamento(fid)
      setItems(cruz.divergencias as CruzamentoItem[])
    } catch (e: any) {
      setError(e.message || 'Erro no cruzamento')
    } finally {
      setCruzando(false)
    }
  }, [fid])

  // Filtros
  const filtered = items.filter(i => {
    if (filtroSev && i.severity !== filtroSev) return false
    if (filtroRegra && i.rule_id !== filtroRegra) return false
    if (tab === 'ausentes_sped' && i.rule_id !== 'XML001') return false
    if (tab === 'ausentes_xml' && i.rule_id !== 'XML002') return false
    if (tab === 'divergencias' && (i.rule_id === 'XML001' || i.rule_id === 'XML002')) return false
    return true
  })

  const regras = [...new Set(items.map(i => i.rule_id))].sort()

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Cruzamento NF-e (XML) x SPED</h1>
          <p className="text-sm text-gray-500 mt-1">
            Arquivo SPED #{fid} &middot; {xmlCount} XMLs vinculados
          </p>
        </div>
        <Link to={`/files/${fid}`} className="text-sm text-blue-600 hover:underline">&larr; Voltar ao arquivo</Link>
      </div>

      {/* Dropzone */}
      <div
        className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer ${
          dragging ? 'border-green-500 bg-green-50' : 'border-gray-300 bg-gray-50 hover:border-green-400'
        }`}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); handleUpload(e.dataTransfer.files) }}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'
          input.accept = '.xml'
          input.multiple = true
          input.onchange = () => { if (input.files) handleUpload(input.files) }
          input.click()
        }}
      >
        {uploading ? (
          <p className="text-green-600 font-medium animate-pulse">Processando XMLs...</p>
        ) : (
          <>
            <p className="text-lg font-medium text-gray-700">
              Arraste XMLs de NF-e aqui ou clique para selecionar
            </p>
            <p className="text-sm text-gray-500 mt-1">Aceita multiplos arquivos .xml</p>
          </>
        )}
      </div>

      {/* Upload stats */}
      {uploadStats && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm">
          <strong>Upload concluido:</strong> {uploadStats.total} XMLs processados
          &middot; {uploadStats.autorizadas} autorizadas
          &middot; {uploadStats.canceladas} canceladas
          {uploadStats.duplicadas > 0 && <> &middot; {uploadStats.duplicadas} duplicadas (ignoradas)</>}
          {uploadStats.invalidos > 0 && <> &middot; <span className="text-red-600">{uploadStats.invalidos} invalidos</span></>}
        </div>
      )}

      {/* Error */}
      {error && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>}

      {/* Botao cruzar */}
      {xmlCount > 0 && (
        <div className="flex items-center gap-4">
          <button
            onClick={handleCruzar}
            disabled={cruzando}
            className="px-6 py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-400 transition-colors"
          >
            {cruzando ? 'Cruzando...' : 'Cruzar com SPED'}
          </button>
          {cruzResult && (
            <span className="text-sm text-gray-600">
              {cruzResult.xmls_analisados} XMLs analisados &middot; {cruzResult.divergencias} divergencias
              {cruzResult.por_severidade.critical > 0 && <> &middot; <span className="text-red-600 font-bold">{cruzResult.por_severidade.critical} criticos</span></>}
            </span>
          )}
        </div>
      )}

      {/* Tabs + resultados */}
      {items.length > 0 && (
        <>
          <div className="flex gap-1 border-b">
            {(['divergencias', 'ausentes_sped', 'ausentes_xml'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  tab === t ? 'border-green-600 text-green-700' : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'divergencias' && `Divergencias (${items.filter(i => i.rule_id !== 'XML001' && i.rule_id !== 'XML002').length})`}
                {t === 'ausentes_sped' && `Ausentes no SPED (${items.filter(i => i.rule_id === 'XML001').length})`}
                {t === 'ausentes_xml' && `Ausentes nos XMLs (${items.filter(i => i.rule_id === 'XML002').length})`}
              </button>
            ))}
          </div>

          {/* Filtros */}
          <div className="flex gap-4 text-sm">
            <select value={filtroSev} onChange={e => setFiltroSev(e.target.value)} className="border rounded px-2 py-1">
              <option value="">Todas severidades</option>
              <option value="critical">Critico</option>
              <option value="error">Erro</option>
              <option value="warning">Alerta</option>
            </select>
            <select value={filtroRegra} onChange={e => setFiltroRegra(e.target.value)} className="border rounded px-2 py-1">
              <option value="">Todas regras</option>
              {regras.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <span className="text-gray-500 self-center">{filtered.length} resultados</span>
          </div>

          {/* Tabela */}
          <div className="overflow-x-auto border rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-3 py-2 text-left">Regra</th>
                  <th className="px-3 py-2 text-left">Sev.</th>
                  <th className="px-3 py-2 text-left">Chave NF-e</th>
                  <th className="px-3 py-2 text-left">Campo XML</th>
                  <th className="px-3 py-2 text-right">Valor XML</th>
                  <th className="px-3 py-2 text-left">Campo SPED</th>
                  <th className="px-3 py-2 text-right">Valor SPED</th>
                  <th className="px-3 py-2 text-right">Dif.</th>
                  <th className="px-3 py-2 text-left">Mensagem</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {filtered.map(item => (
                  <tr key={item.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs">{item.rule_id}</td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded border ${SEV_COLORS[item.severity] || 'bg-gray-100'}`}>
                        {item.severity}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs" title={item.chave_nfe}>
                      {item.chave_nfe?.substring(0, 15)}...
                    </td>
                    <td className="px-3 py-2 text-xs">{item.campo_xml}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{item.valor_xml}</td>
                    <td className="px-3 py-2 text-xs">{item.campo_sped}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{item.valor_sped}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs text-red-600">
                      {item.diferenca != null ? item.diferenca.toFixed(2) : '-'}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600 max-w-xs truncate" title={item.message}>
                      {item.message}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={9} className="px-3 py-8 text-center text-gray-400">Nenhuma divergencia encontrada</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
