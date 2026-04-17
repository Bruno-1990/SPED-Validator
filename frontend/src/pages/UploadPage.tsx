import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

interface Dados0000 {
  cnpj: string
  dtIni: string
  dtFin: string
  nome: string
}

function extrairDados0000(texto: string): Dados0000 {
  const linhas = texto.split('\n')
  for (const linha of linhas) {
    const campos = linha.split('|')
    if (campos[1] === '0000' && campos.length >= 8) {
      return {
        cnpj: (campos[7] || '').replace(/\D/g, ''),
        dtIni: campos[4] || '',
        dtFin: campos[5] || '',
        nome: campos[6] || '',
      }
    }
  }
  return { cnpj: '', dtIni: '', dtFin: '', nome: '' }
}

function formatarDataSped(data: string): string {
  if (data.length !== 8) return data
  return `${data.slice(0, 2)}/${data.slice(2, 4)}/${data.slice(4)}`
}

const formatarCnpj = (cnpj: string) => {
  if (cnpj.length !== 14) return cnpj
  return cnpj.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5')
}

interface ClienteInfo {
  razao_social: string
  regime_tributario: string
  beneficios_fiscais: string[]
  uf: string
}

const CHUNK_SIZE = 50 // XMLs por chunk
const MAX_XMLS = 10000

export default function UploadPage() {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [cnpj, setCnpj] = useState('')
  const [dtIni, setDtIni] = useState('')
  const [dtFin, setDtFin] = useState('')
  const [nomeEmpresa, setNomeEmpresa] = useState('')
  const [cliente, setCliente] = useState<ClienteInfo | null>(null)
  const [clienteNaoEncontrado, setClienteNaoEncontrado] = useState(false)
  const [buscandoCliente, setBuscandoCliente] = useState(false)
  const [regime, setRegime] = useState('')
  const [beneficios, setBeneficios] = useState<string[]>([])
  const navigate = useNavigate()

  // Etapa do fluxo: 'sped' | 'xml_choice' | 'xml_upload' | 'sending'
  const [etapa, setEtapa] = useState<'sped' | 'xml_choice' | 'xml_upload' | 'sending'>('sped')
  const [fileId, setFileId] = useState<number | null>(null)

  // XMLs
  const [xmlFiles, setXmlFiles] = useState<File[]>([])
  const [xmlDragging, setXmlDragging] = useState(false)
  const [xmlUploading, setXmlUploading] = useState(false)
  const [xmlProgress, setXmlProgress] = useState({ enviados: 0, total: 0 })
  const [xmlStats, setXmlStats] = useState<{ autorizadas: number; canceladas: number; duplicadas: number; invalidos: number } | null>(null)

  // Cruzamento automatico
  const [cruzandoXml, setCruzandoXml] = useState(false)
  const [cruzPct, setCruzPct] = useState(0)
  const [cruzLog, setCruzLog] = useState<string[]>([])
  const [cruzResult, setCruzResult] = useState<{ divergencias: number; por_severidade: Record<string, number> } | null>(null)

  // Modal de periodo
  const [periodoModal, setPeriodoModal] = useState<{
    fora: { filename: string; chave_nfe: string; dh_emissao: string }[]
    chunkFiles: File[]
    remainingChunks: File[][]
    periodStart: string
    periodEnd: string
    statsAccum: { autorizadas: number; canceladas: number; duplicadas: number; invalidos: number }
  } | null>(null)

  // ── SPED processing ──

  const processarArquivo = useCallback(async (file: File) => {
    setArquivo(file)
    setError('')
    setCliente(null)
    setClienteNaoEncontrado(false)
    setRegime('')
    setBeneficios([])
    setEtapa('sped')

    const slice = file.slice(0, 8192)
    const buffer = await slice.arrayBuffer()
    const texto = new TextDecoder('latin1').decode(buffer)
    const dados = extrairDados0000(texto)
    setCnpj(dados.cnpj)
    setDtIni(dados.dtIni)
    setDtFin(dados.dtFin)
    setNomeEmpresa(dados.nome)

    if (!dados.cnpj) {
      setError('Nao foi possivel extrair o CNPJ do registro 0000.')
      return
    }

    setBuscandoCliente(true)
    try {
      const c = await api.buscarCliente(dados.cnpj)
      setCliente(c)
      setRegime(c.regime_tributario)
      setBeneficios(c.beneficios_fiscais)
      setClienteNaoEncontrado(false)
    } catch {
      setClienteNaoEncontrado(true)
    } finally {
      setBuscandoCliente(false)
    }
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) processarArquivo(file)
  }, [processarArquivo])

  const onFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) processarArquivo(file)
  }, [processarArquivo])

  // ── Upload SPED → abre escolha de XML ──

  const uploadSped = useCallback(async () => {
    if (!arquivo) return
    setUploading(true)
    setError('')
    try {
      let regimeParam = ''
      const regimeLower = regime.toLowerCase()
      if (regimeLower.includes('simples')) regimeParam = 'simples_nacional'
      else if (regimeLower.includes('normal') || regimeLower.includes('lucro')) regimeParam = 'normal'

      const result = await api.uploadFile(arquivo, regimeParam)
      setFileId(result.file_id)
      setEtapa('xml_choice')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao fazer upload')
    } finally {
      setUploading(false)
    }
  }, [arquivo, regime])

  // ── XML file selection ──

  const addXmlFiles = useCallback((files: FileList | File[]) => {
    const xmls = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.xml'))
    if (xmls.length === 0) { setError('Nenhum arquivo .xml selecionado'); return }
    setXmlFiles(prev => {
      const combined = [...prev, ...xmls]
      if (combined.length > MAX_XMLS) {
        setError(`Limite de ${MAX_XMLS.toLocaleString()} XMLs. ${combined.length - MAX_XMLS} ignorados.`)
        return combined.slice(0, MAX_XMLS)
      }
      setError('')
      return combined
    })
  }, [])

  // ── Upload XMLs em chunks (com validacao de periodo e cruzamento automatico) ──

  const processChunks = useCallback(async (
    chunks: File[][],
    statsAccum: { autorizadas: number; canceladas: number; duplicadas: number; invalidos: number },
    enviados: number,
    totalFiles: number,
    modoPeriodo?: string,
  ) => {
    for (let i = 0; i < chunks.length; i++) {
      const chunk = chunks[i]
      const result = await api.uploadXmls(fileId!, chunk, modoPeriodo)

      // Se ha NF-e fora de periodo, pausar e perguntar
      if (result.status === 'periodo_pendente' && result.fora_periodo?.length) {
        setPeriodoModal({
          fora: result.fora_periodo,
          chunkFiles: chunk,
          remainingChunks: chunks.slice(i + 1),
          periodStart: result.period_start_fmt || '',
          periodEnd: result.period_end_fmt || '',
          statsAccum: { ...statsAccum },
        })
        return // pausa — usuario decide no modal
      }

      statsAccum.autorizadas += result.autorizadas
      statsAccum.canceladas += result.canceladas
      statsAccum.duplicadas += result.duplicadas
      statsAccum.invalidos += result.invalidos

      enviados += chunk.length
      setXmlProgress({ enviados, total: totalFiles })
    }

    // Upload completo — executar cruzamento automatico
    setXmlStats(statsAccum)
    setXmlUploading(false)

    // Rodar cruzamento se teve XMLs novos OU se já existem XMLs vinculados (duplicatas de re-upload)
    const temXmlsVinculados = statsAccum.autorizadas + statsAccum.canceladas + statsAccum.duplicadas > 0
    if (temXmlsVinculados) {
      setCruzandoXml(true)
      setCruzPct(0)
      setCruzLog(['Iniciando cruzamento XML x SPED...'])

      await new Promise<void>((resolve) => {
        api.cruzarXmlStream(
          fileId!,
          (pct, msg) => {
            setCruzPct(pct)
            setCruzLog(prev => {
              if (prev.length > 0 && prev[prev.length - 1] === msg) return prev
              return [...prev, msg]
            })
          },
          (result) => {
            setCruzPct(100)
            setCruzLog(prev => [...prev, `Concluido: ${result.divergencias.toLocaleString()} divergencias XML + ${(result.total_erros_fiscal ?? 0).toLocaleString()} erros fiscais.`])
            setCruzResult(result)
            setCruzandoXml(false)
            // Pipeline ja rodou no backend — navegar direto para resultados (sem validate=1)
            navigate(`/files/${fileId}?mode=sped_xml`)
            resolve()
          },
          (err) => {
            setCruzLog(prev => [...prev, `Erro no cruzamento: ${err}`])
            setError(`Cruzamento XML falhou: ${err}`)
            setCruzandoXml(false)
            resolve()
          },
        )
      })
    }
  }, [fileId, navigate])

  const uploadXmlsChunked = useCallback(async () => {
    if (!fileId || xmlFiles.length === 0) return
    setXmlUploading(true)
    setCruzResult(null)
    setError('')

    const totalFiles = xmlFiles.length
    setXmlProgress({ enviados: 0, total: totalFiles })

    // Dividir em chunks
    const chunks: File[][] = []
    for (let i = 0; i < totalFiles; i += CHUNK_SIZE) {
      chunks.push(xmlFiles.slice(i, i + CHUNK_SIZE))
    }

    try {
      await processChunks(chunks, { autorizadas: 0, canceladas: 0, duplicadas: 0, invalidos: 0 }, 0, totalFiles)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro no upload de XMLs')
      setXmlUploading(false)
    }
  }, [fileId, xmlFiles, processChunks])

  const handleDecisaoPeriodo = useCallback(async (decisao: 'importar_todos' | 'pular_fora') => {
    if (!periodoModal || !fileId) return
    const { chunkFiles, remainingChunks, statsAccum } = periodoModal
    setPeriodoModal(null)

    try {
      // Reenviar o chunk pausado com a decisao do usuario
      const result = await api.uploadXmls(fileId, chunkFiles, decisao)
      statsAccum.autorizadas += result.autorizadas
      statsAccum.canceladas += result.canceladas
      statsAccum.duplicadas += result.duplicadas
      statsAccum.invalidos += result.invalidos

      const totalFiles = xmlFiles.length
      const enviados = totalFiles - remainingChunks.reduce((sum, c) => sum + c.length, 0)
      setXmlProgress({ enviados, total: totalFiles })

      // Continuar processando os chunks restantes com a mesma decisao
      await processChunks(remainingChunks, statsAccum, enviados, totalFiles, decisao)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro no upload de XMLs')
      setXmlUploading(false)
    }
  }, [periodoModal, fileId, xmlFiles, processChunks])

  // ── Navegar ──

  const irParaValidacao = useCallback(() => {
    if (!fileId) return
    // Com XML: pipeline ja rodou no backend (encadeado no cruzamento) — ir direto.
    // Sem XML: disparar pipeline via validate=1.
    const comXml = xmlStats !== null || cruzResult !== null
    navigate(
      comXml
        ? `/files/${fileId}?mode=sped_xml`
        : `/files/${fileId}?validate=1`,
    )
  }, [fileId, navigate, xmlStats, cruzResult])

  // ── Reset ──

  const resetAll = () => {
    setArquivo(null); setCnpj(''); setDtIni(''); setDtFin(''); setNomeEmpresa('')
    setCliente(null); setClienteNaoEncontrado(false); setRegime(''); setBeneficios([])
    setEtapa('sped'); setFileId(null)
    setXmlFiles([]); setXmlStats(null); setXmlProgress({ enviados: 0, total: 0 })
    setCruzResult(null); setCruzandoXml(false); setCruzPct(0); setCruzLog([]); setPeriodoModal(null)
    setError('')
  }

  return (
    <div className="max-w-2xl mx-auto mt-6 md:mt-12 px-2">
      <h2 className="text-xl md:text-2xl font-bold mb-6">Upload de Arquivo SPED EFD</h2>

      {/* ══════ ETAPA 1: SPED ══════ */}
      {etapa === 'sped' && (
        <>
          {/* Dropzone SPED */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`border-2 border-dashed rounded-lg p-8 md:p-12 text-center transition-colors touch-manipulation ${
              dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
            }`}
          >
            {arquivo ? (
              <div>
                <p className="text-gray-700 font-medium">{nomeEmpresa || arquivo.name}</p>
                <p className="text-gray-400 text-sm mt-1">
                  {(arquivo.size / 1024 / 1024).toFixed(1)} MB
                  {cnpj && ` — CNPJ: ${formatarCnpj(cnpj)}`}
                </p>
                {dtIni && dtFin && (
                  <p className="text-gray-500 text-sm mt-1 font-medium">
                    Periodo: {formatarDataSped(dtIni)} a {formatarDataSped(dtFin)}
                  </p>
                )}
                <button onClick={resetAll} className="text-sm text-blue-600 hover:underline mt-2">
                  Trocar arquivo
                </button>
              </div>
            ) : (
              <>
                <p className="text-gray-500 mb-4 text-sm md:text-base">Arraste o arquivo SPED aqui ou</p>
                <label className="cursor-pointer bg-blue-600 text-white px-6 py-3 md:px-4 md:py-2 rounded hover:bg-blue-700 inline-block text-sm md:text-base">
                  Selecionar arquivo
                  <input type="file" accept=".txt" onChange={onFileSelect} className="hidden" />
                </label>
              </>
            )}
          </div>

          {buscandoCliente && <p className="mt-4 text-blue-600 text-sm">Consultando cadastro do cliente...</p>}

          {arquivo && !buscandoCliente && (cliente || clienteNaoEncontrado) && (
            <div className="mt-6 space-y-4">
              {cliente && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                  <p className="text-green-800 font-medium text-sm">Cliente encontrado: {cliente.razao_social}</p>
                  <p className="text-green-600 text-xs mt-1">UF: {cliente.uf}</p>
                </div>
              )}
              {clienteNaoEncontrado && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                  <p className="text-yellow-800 font-medium text-sm">Cliente nao encontrado (CNPJ: {formatarCnpj(cnpj)})</p>
                  <p className="text-yellow-600 text-xs mt-1">O sistema detectara o regime pelo SPED.</p>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Regime Tributario</label>
                <input
                  type="text" value={regime} onChange={(e) => setRegime(e.target.value)}
                  placeholder="Ex: Lucro Presumido, Simples Nacional"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {beneficios.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Beneficios Fiscais</label>
                  <div className="flex flex-wrap gap-2">
                    {beneficios.map((b, i) => (
                      <span key={i} className="inline-flex items-center bg-blue-100 text-blue-800 text-xs font-medium px-2.5 py-1 rounded-full">
                        {b}
                        <button onClick={() => setBeneficios(prev => prev.filter((_, idx) => idx !== i))} className="ml-1 text-blue-600 hover:text-blue-900">×</button>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <button
                onClick={uploadSped} disabled={uploading}
                className={`w-full py-3 rounded-lg font-medium text-white transition-colors ${uploading ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'}`}
              >
                {uploading ? 'Enviando SPED...' : 'Enviar SPED'}
              </button>
            </div>
          )}
        </>
      )}

      {/* ══════ ETAPA 2: ESCOLHA XML ══════ */}
      {etapa === 'xml_choice' && (
        <div className="space-y-6">
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
            <p className="text-green-800 font-medium">SPED enviado com sucesso!</p>
            <p className="text-green-600 text-sm mt-1">Arquivo #{fileId} — {nomeEmpresa}</p>
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-6 text-center space-y-4">
            <p className="text-gray-700 font-medium text-lg">Deseja anexar XMLs de NF-e para cruzamento?</p>
            <p className="text-gray-500 text-sm">
              O cruzamento XML x SPED detecta notas ausentes, valores divergentes e NF-e canceladas escrituradas.
              Limite: {MAX_XMLS.toLocaleString()} XMLs.
            </p>

            <div className="flex gap-4 justify-center pt-2">
              <button
                onClick={() => setEtapa('xml_upload')}
                className="px-8 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
              >
                Sim, anexar XMLs
              </button>
              <button
                onClick={irParaValidacao}
                className="px-8 py-3 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition-colors border border-gray-300"
              >
                Continuar sem XMLs
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ══════ ETAPA 3: UPLOAD XMLs ══════ */}
      {etapa === 'xml_upload' && (
        <div className="space-y-6">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
            SPED #{fileId} — {nomeEmpresa} — CNPJ: {formatarCnpj(cnpj)}
          </div>

          {/* Dropzone XML */}
          <div
            onDragOver={e => { e.preventDefault(); setXmlDragging(true) }}
            onDragLeave={() => setXmlDragging(false)}
            onDrop={e => { e.preventDefault(); setXmlDragging(false); addXmlFiles(e.dataTransfer.files) }}
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'; input.accept = '.xml'; input.multiple = true
              input.setAttribute('webkitdirectory', '')
              input.onchange = () => {
                if (input.files) {
                  // Filtrar apenas .xml da pasta selecionada
                  const xmls = Array.from(input.files).filter(f => f.name.toLowerCase().endsWith('.xml'))
                  if (xmls.length > 0) {
                    const dt = new DataTransfer()
                    xmls.forEach(f => dt.items.add(f))
                    addXmlFiles(dt.files)
                  }
                }
              }
              input.click()
            }}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              xmlDragging ? 'border-green-500 bg-green-50' : 'border-gray-300 bg-gray-50 hover:border-green-400'
            }`}
          >
            <p className="text-lg font-medium text-gray-700">Arraste XMLs de NF-e aqui</p>
            <p className="text-sm text-gray-500 mt-1">ou clique para selecionar a pasta contendo os XMLs</p>
          </div>

          {/* Lista de XMLs selecionados */}
          {xmlFiles.length > 0 && (
            <div className="bg-white border rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">
                  {xmlFiles.length.toLocaleString()} XMLs selecionados
                  {xmlFiles.length >= MAX_XMLS && <span className="text-red-600 ml-2">(limite atingido)</span>}
                </span>
                <button onClick={() => { setXmlFiles([]); setXmlStats(null) }} className="text-xs text-red-500 hover:underline">
                  Limpar todos
                </button>
              </div>

              {/* Barra em 3 fases: envio (0–33%) + cruzamento (33–100%). A auditoria completa é outra tela. */}
              {(xmlUploading || cruzandoXml) && (() => {
                const pctUpload = xmlProgress.total > 0
                  ? Math.round((xmlProgress.enviados / xmlProgress.total) * (100 / 3))
                  : 0
                const pctTotal = xmlUploading
                  ? pctUpload
                  : Math.min(100, Math.round(100 / 3 + (cruzPct / 100) * (200 / 3)))
                const faseLabel = xmlUploading
                  ? `Passo 1 de 3: Enviando XMLs (${xmlProgress.enviados.toLocaleString()} / ${xmlProgress.total.toLocaleString()})`
                  : 'Passo 2 de 3: Cruzando XML x SPED'
                return (
                  <div className="mb-3 bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-700 flex items-center gap-2">
                        {cruzandoXml && (
                          <svg className="animate-spin h-4 w-4 text-blue-600" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                        )}
                        {faseLabel}
                      </span>
                      <span className="text-sm font-semibold text-blue-600">{pctTotal}%</span>
                    </div>
                    <p className="text-xs text-slate-600">
                      Passo 3 de 3 (próxima tela): auditoria fiscal completa do SPED — só inicia depois que o cruzamento acima terminar e você for redirecionado.
                    </p>
                    <div className="w-full bg-slate-200 rounded-full h-2">
                      <div
                        className={`h-2 rounded-full transition-all duration-300 ${xmlUploading ? 'bg-green-500' : 'bg-blue-500'}`}
                        style={{ width: `${pctTotal}%` }}
                      />
                    </div>
                    {cruzandoXml && cruzLog.length > 0 && (
                      <div className="bg-slate-900 rounded-md p-3 max-h-32 overflow-y-auto flex flex-col-reverse">
                        {[...cruzLog].reverse().map((msg, i) => (
                          <p key={i} className={`font-mono text-xs leading-5 ${i === 0 ? 'text-green-400' : 'text-slate-500'}`}>
                            <span className="text-slate-600 mr-1.5">{'>'}</span>{msg}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* Stats após upload (antes ou depois do cruzamento concluir) */}
              {xmlStats && !xmlUploading && !cruzandoXml && (
                <div className="text-sm text-gray-600 space-y-1 bg-green-50 border border-green-200 rounded p-3">
                  <p className="font-medium text-green-800">Upload concluido!</p>
                  <p>Autorizadas: {xmlStats.autorizadas} | Canceladas: {xmlStats.canceladas}</p>
                  {xmlStats.duplicadas > 0 && <p className="text-yellow-700">Duplicadas (ignoradas): {xmlStats.duplicadas}</p>}
                  {xmlStats.invalidos > 0 && <p className="text-red-600">Invalidos: {xmlStats.invalidos}</p>}
                </div>
              )}

              {cruzResult && (
                <div className={`text-sm rounded-lg p-4 border ${cruzResult.divergencias > 0 ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-green-50 border-green-200 text-green-800'}`}>
                  <p className="font-semibold">Cruzamento concluido</p>
                  {cruzResult.divergencias > 0 ? (
                    <div className="mt-1 space-y-0.5">
                      <p>{cruzResult.divergencias.toLocaleString()} divergencias encontradas:</p>
                      <div className="flex gap-3 mt-1">
                        {cruzResult.por_severidade.critical > 0 && (
                          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full font-medium">
                            {cruzResult.por_severidade.critical} criticas
                          </span>
                        )}
                        {cruzResult.por_severidade.error > 0 && (
                          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full font-medium">
                            {cruzResult.por_severidade.error} erros
                          </span>
                        )}
                        {cruzResult.por_severidade.warning > 0 && (
                          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-yellow-100 text-yellow-700 rounded-full font-medium">
                            {cruzResult.por_severidade.warning} avisos
                          </span>
                        )}
                      </div>
                    </div>
                  ) : (
                    <p className="mt-1">Nenhuma divergencia encontrada entre XML e SPED.</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Botoes */}
          <div className="flex gap-4">
            {!xmlStats && !cruzandoXml ? (
              <>
                <button
                  onClick={uploadXmlsChunked}
                  disabled={xmlUploading || xmlFiles.length === 0}
                  className={`flex-1 py-3 rounded-lg font-medium text-white transition-colors ${
                    xmlUploading || xmlFiles.length === 0 ? 'bg-gray-400 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700'
                  }`}
                >
                  {xmlUploading ? `Enviando... ${xmlProgress.enviados}/${xmlProgress.total}` : `Enviar ${xmlFiles.length.toLocaleString()} XMLs`}
                </button>
                <button
                  onClick={irParaValidacao} disabled={xmlUploading}
                  className="px-6 py-3 bg-gray-100 text-gray-600 rounded-lg font-medium hover:bg-gray-200 border border-gray-300"
                >
                  Pular
                </button>
              </>
            ) : xmlStats && !cruzandoXml ? (
              <button
                type="button"
                onClick={() => {
                  if (cruzResult !== null) navigate(`/files/${fileId}?validate=1&mode=sped_xml`)
                  else irParaValidacao()
                }}
                className="flex-1 py-3 rounded-lg font-medium text-white bg-blue-600 hover:bg-blue-700 transition-colors"
              >
                Continuar para Validacao
              </button>
            ) : null}
          </div>
        </div>
      )}

      {error && <p className="mt-4 text-red-600 bg-red-50 p-3 rounded text-sm">{error}</p>}

      {/* Modal de NF-e fora do periodo */}
      {periodoModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl max-w-lg w-full p-6 space-y-4 max-h-[80vh] overflow-y-auto mx-4">
            <h3 className="text-lg font-semibold text-amber-800">NF-e fora do periodo do SPED</h3>
            <p className="text-sm text-gray-600">
              O SPED cobre o periodo <strong>{periodoModal.periodStart}</strong> a <strong>{periodoModal.periodEnd}</strong>.
              {' '}{periodoModal.fora.length} NF-e estao com data de emissao fora deste periodo:
            </p>
            <div className="max-h-48 overflow-y-auto border rounded">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="text-left p-2">Arquivo</th>
                    <th className="text-left p-2">Chave</th>
                    <th className="text-left p-2">Emissao</th>
                  </tr>
                </thead>
                <tbody>
                  {periodoModal.fora.map((nf, i) => (
                    <tr key={i} className="border-t">
                      <td className="p-2 truncate max-w-[120px]" title={nf.filename}>{nf.filename}</td>
                      <td className="p-2 font-mono" title={nf.chave_nfe}>...{nf.chave_nfe.slice(-12)}</td>
                      <td className="p-2">{nf.dh_emissao}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => handleDecisaoPeriodo('importar_todos')}
                className="flex-1 py-2.5 bg-amber-500 text-white rounded-lg font-medium hover:bg-amber-600 transition-colors text-sm"
              >
                Importar mesmo assim
              </button>
              <button
                onClick={() => handleDecisaoPeriodo('pular_fora')}
                className="flex-1 py-2.5 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-gray-300 transition-colors text-sm"
              >
                Pular estas NF-e
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
