import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { CorrectionSuggestion, ValidationError } from '../../types/sped'

const CERTEZA_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  objetivo: { bg: 'bg-green-100', text: 'text-green-800', label: 'Objetivo' },
  provavel: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Provavel' },
  indicio: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Indicio' },
}

const IMPACTO_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  critico: { bg: 'bg-red-100', text: 'text-red-800', label: 'Critico' },
  relevante: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'Relevante' },
  informativo: { bg: 'bg-gray-100', text: 'text-gray-600', label: 'Informativo' },
}

interface Props {
  fileId: number
  errors: ValidationError[]
  onReload: () => void
}

function errorToSuggestion(e: ValidationError): CorrectionSuggestion | null {
  if (!e.auto_correctable || e.status !== 'open' || !e.expected_value || !e.record_id || !e.field_no) return null
  return {
    error_id: e.id,
    record_id: e.record_id,
    register: e.register,
    field_no: e.field_no,
    field_name: e.field_name || '',
    old_value: e.value || '',
    expected_value: e.expected_value,
    error_type: e.error_type,
    certeza: e.certeza,
    impacto: e.impacto,
    line_number: e.line_number,
    message: e.message,
    friendly_message: e.friendly_message,
  }
}

export default function CorrectionApprovalPanel({ fileId, errors, onReload }: Props) {
  const [suggestions, setSuggestions] = useState<CorrectionSuggestion[]>([])
  const [decisions, setDecisions] = useState<Record<number, 'approved' | 'rejected' | 'skipped'>>({})
  const [modalOpen, setModalOpen] = useState<number | null>(null)
  const [justificativa, setJustificativa] = useState('')
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const items = errors
      .map(errorToSuggestion)
      .filter((s): s is CorrectionSuggestion => s !== null)
    setSuggestions(items)
  }, [errors])

  const totalSuggestions = suggestions.length
  const totalDecided = Object.keys(decisions).length
  const allDecided = totalSuggestions > 0 && totalDecided >= totalSuggestions

  const handleApprove = useCallback(async (errorId: number) => {
    const suggestion = suggestions.find(s => s.error_id === errorId)
    if (!suggestion) return

    if (justificativa.trim().length < 20) {
      setError('Justificativa deve ter no minimo 20 caracteres')
      return
    }

    setProcessing(true)
    setError('')
    try {
      await api.approveCorrection(fileId, suggestion, justificativa.trim())
      setDecisions(prev => ({ ...prev, [errorId]: 'approved' }))
      setModalOpen(null)
      setJustificativa('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao aprovar correcao')
    } finally {
      setProcessing(false)
    }
  }, [fileId, suggestions, justificativa])

  const handleReject = useCallback(async (errorId: number) => {
    setProcessing(true)
    setError('')
    try {
      await api.dismissError(fileId, errorId)
      setDecisions(prev => ({ ...prev, [errorId]: 'rejected' }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao rejeitar')
    } finally {
      setProcessing(false)
    }
  }, [fileId])

  const handleSkip = useCallback((errorId: number) => {
    setDecisions(prev => ({ ...prev, [errorId]: 'skipped' }))
  }, [])

  const handleExport = useCallback(() => {
    window.open(api.downloadSped(fileId), '_blank')
    onReload()
  }, [fileId, onReload])

  if (totalSuggestions === 0) {
    return (
      <div className="bg-white rounded shadow p-6 text-center text-gray-500">
        Nenhuma correcao pendente de aprovacao.
      </div>
    )
  }

  const progressPct = totalSuggestions > 0 ? Math.round((totalDecided / totalSuggestions) * 100) : 0

  return (
    <div className="space-y-4">
      {/* Progress bar */}
      <div className="bg-white rounded shadow p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold">
            Progresso: {totalDecided}/{totalSuggestions} decididas
          </span>
          <span className="text-sm text-gray-500">{progressPct}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className="bg-blue-600 h-3 rounded-full transition-all duration-300"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Export button */}
      <div className="flex justify-end">
        <button
          onClick={handleExport}
          disabled={!allDecided}
          className={`px-4 py-2 rounded font-semibold text-sm ${
            allDecided
              ? 'bg-green-600 text-white hover:bg-green-700'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
          title={allDecided ? 'Exportar SPED com correcoes aprovadas' : 'Decida todas as correcoes antes de exportar'}
        >
          Exportar SPED Corrigido
        </button>
      </div>

      {error && (
        <p className="text-red-600 bg-red-50 p-3 rounded text-sm">{error}</p>
      )}

      {/* Suggestion cards */}
      <div className="space-y-3">
        {suggestions.map((s) => {
          const decision = decisions[s.error_id]
          const certezaInfo = s.certeza ? CERTEZA_BADGE[s.certeza] : null
          const impactoInfo = s.impacto ? IMPACTO_BADGE[s.impacto] : null

          return (
            <div
              key={s.error_id}
              className={`bg-white rounded shadow p-4 border-l-4 ${
                decision === 'approved' ? 'border-green-500 opacity-70' :
                decision === 'rejected' ? 'border-red-400 opacity-70' :
                decision === 'skipped' ? 'border-gray-300 opacity-70' :
                'border-blue-500'
              }`}
            >
              {/* Header */}
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="font-mono text-sm bg-gray-100 px-2 py-0.5 rounded">
                  {s.register}
                </span>
                <span className="text-sm text-gray-500">Linha {s.line_number}</span>
                <span className="text-xs bg-gray-200 px-2 py-0.5 rounded">{s.error_type}</span>
                {certezaInfo && (
                  <span className={`text-xs px-2 py-0.5 rounded ${certezaInfo.bg} ${certezaInfo.text}`}>
                    {certezaInfo.label}
                  </span>
                )}
                {impactoInfo && (
                  <span className={`text-xs px-2 py-0.5 rounded ${impactoInfo.bg} ${impactoInfo.text}`}>
                    {impactoInfo.label}
                  </span>
                )}
                {decision && (
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded ml-auto ${
                    decision === 'approved' ? 'bg-green-100 text-green-800' :
                    decision === 'rejected' ? 'bg-red-100 text-red-800' :
                    'bg-gray-100 text-gray-600'
                  }`}>
                    {decision === 'approved' ? 'Aprovada' : decision === 'rejected' ? 'Rejeitada' : 'Pulada'}
                  </span>
                )}
              </div>

              {/* Description */}
              <p className="text-sm text-gray-700 mb-3">
                {s.friendly_message || s.message}
              </p>

              {/* Field change */}
              <div className="bg-gray-50 rounded p-3 mb-3 text-sm">
                <div className="flex flex-wrap gap-x-6 gap-y-1">
                  <div>
                    <span className="text-gray-500">Campo:</span>{' '}
                    <span className="font-mono font-semibold">{s.field_name}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Atual:</span>{' '}
                    <span className="font-mono text-red-600">{s.old_value || '(vazio)'}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Sugerido:</span>{' '}
                    <span className="font-mono text-green-700">{s.expected_value}</span>
                  </div>
                </div>
              </div>

              {/* Action buttons */}
              {!decision && (
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => { setModalOpen(s.error_id); setJustificativa(''); setError('') }}
                    disabled={processing}
                    className="bg-green-600 text-white text-sm px-3 py-1.5 rounded hover:bg-green-700 disabled:opacity-50"
                  >
                    Aprovar
                  </button>
                  <button
                    onClick={() => handleReject(s.error_id)}
                    disabled={processing}
                    className="bg-red-500 text-white text-sm px-3 py-1.5 rounded hover:bg-red-600 disabled:opacity-50"
                  >
                    Rejeitar
                  </button>
                  <button
                    onClick={() => handleSkip(s.error_id)}
                    disabled={processing}
                    className="text-gray-600 text-sm px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
                  >
                    Pular
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Approval modal */}
      {modalOpen !== null && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
            <h3 className="text-lg font-semibold mb-4">Aprovar Correcao</h3>

            {(() => {
              const s = suggestions.find(s => s.error_id === modalOpen)
              if (!s) return null
              return (
                <div className="bg-gray-50 rounded p-3 mb-4 text-sm">
                  <p className="font-mono">
                    {s.field_name}: <span className="text-red-600">{s.old_value || '(vazio)'}</span>
                    {' → '}
                    <span className="text-green-700">{s.expected_value}</span>
                  </p>
                </div>
              )
            })()}

            <label className="block text-sm font-medium text-gray-700 mb-1">
              Justificativa (minimo 20 caracteres)
            </label>
            <textarea
              value={justificativa}
              onChange={(e) => setJustificativa(e.target.value)}
              className="w-full border rounded p-2 text-sm h-24 resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Descreva o motivo da aprovacao desta correcao..."
            />
            <p className={`text-xs mt-1 ${justificativa.trim().length >= 20 ? 'text-green-600' : 'text-gray-400'}`}>
              {justificativa.trim().length}/20 caracteres
            </p>

            {error && (
              <p className="text-red-600 text-sm mt-2">{error}</p>
            )}

            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => { setModalOpen(null); setError('') }}
                className="text-sm px-4 py-2 rounded border border-gray-300 hover:bg-gray-50"
              >
                Cancelar
              </button>
              <button
                onClick={() => handleApprove(modalOpen)}
                disabled={processing || justificativa.trim().length < 20}
                className="text-sm px-4 py-2 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {processing ? 'Salvando...' : 'Confirmar Aprovacao'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
