import { useState } from 'react'
import type { RecordInfo, ValidationError } from '../../types/sped'

const PROHIBITED_FIELDS = ['CST_ICMS', 'CFOP', 'ALIQ_ICMS', 'COD_AJ_APUR']

// Known valid_values for some fields
const KNOWN_VALID_VALUES: Record<string, string[]> = {
  IND_OPER: ['0', '1'],
  IND_EMIT: ['0', '1'],
  COD_SIT: ['00', '01', '02', '03', '04', '05', '06', '07', '08'],
  IND_PGTO: ['0', '1', '2', '9'],
  IND_FRT: ['0', '1', '2', '9'],
  IND_MOV: ['0', '1'],
  COD_FIN: ['0', '1'],
  IND_PERFIL: ['A', 'B', 'C'],
  IND_ATIV: ['0', '1'],
  IND_APUR: ['0', '1'],
}

interface Props {
  record: RecordInfo
  fieldName: string
  error: ValidationError
  onSave: (newValue: string, justification: string) => void
  onCancel: () => void
}

export default function FieldEditor({ record, fieldName, error, onSave, onCancel }: Props) {
  const [newValue, setNewValue] = useState(error.expected_value || error.value || '')
  const [justification, setJustification] = useState('')
  const [saving, setSaving] = useState(false)

  const isProhibited = PROHIBITED_FIELDS.includes(fieldName)
  const validValues = KNOWN_VALID_VALUES[fieldName]
  const hasValidValues = !!validValues

  const justificationValid = justification.trim().length >= 20
  const canSubmit = !isProhibited && newValue.trim() !== '' && justificationValid && !saving

  const handleSave = async () => {
    if (!canSubmit) return
    setSaving(true)
    try {
      await onSave(newValue, justification)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-blue-200 rounded-lg shadow-lg p-4 mt-2 mb-4">
      <h4 className="font-semibold text-sm mb-3 flex items-center gap-2">
        <span className="text-red-500">&#9888;</span>
        Editar campo: <span className="font-mono text-blue-700">{fieldName}</span>
      </h4>

      {/* Field info */}
      <div className="grid grid-cols-2 gap-3 mb-4 text-sm">
        <div>
          <span className="text-gray-500 text-xs">Registro:</span>
          <span className="ml-2 font-mono text-xs">{record.register}</span>
        </div>
        <div>
          <span className="text-gray-500 text-xs">Linha:</span>
          <span className="ml-2 text-xs">{record.line_number}</span>
        </div>
        <div>
          <span className="text-gray-500 text-xs">Valor atual:</span>
          <span className="ml-2 font-mono text-xs text-red-600">{error.value || '(vazio)'}</span>
        </div>
        <div>
          <span className="text-gray-500 text-xs">Tipo esperado:</span>
          <span className="ml-2 text-xs">{error.error_type}</span>
        </div>
      </div>

      {/* Error message */}
      <div className="bg-red-50 border border-red-200 rounded p-3 mb-4 text-sm text-red-800">
        {error.friendly_message || error.message}
      </div>

      {/* Prohibited field */}
      {isProhibited && (
        <div className="bg-yellow-50 border border-yellow-300 rounded p-3 mb-4">
          <div className="flex items-center gap-2 text-sm text-yellow-800">
            <span>&#9888;</span>
            <span className="font-semibold">Alteracao nao permitida automaticamente</span>
          </div>
          <p className="text-xs text-yellow-700 mt-1">
            O campo <span className="font-mono">{fieldName}</span> requer analise especializada.
            Consulte seu contador ou responsavel fiscal.
          </p>
        </div>
      )}

      {/* Input */}
      <div className="mb-4">
        <label className="block text-xs text-gray-500 mb-1">Novo valor</label>
        {hasValidValues && !isProhibited ? (
          <select
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            className="w-full border rounded px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-300 focus:border-blue-500"
          >
            <option value="">Selecione...</option>
            {validValues.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            disabled={isProhibited}
            className={`w-full border rounded px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-300 focus:border-blue-500 ${
              isProhibited ? 'bg-gray-100 text-gray-400 cursor-not-allowed' : ''
            }`}
            placeholder={error.expected_value ? `Sugerido: ${error.expected_value}` : 'Digite o novo valor'}
          />
        )}
        {error.expected_value && !isProhibited && (
          <p className="text-xs text-gray-400 mt-1">
            Valor sugerido: <span className="font-mono text-green-600">{error.expected_value}</span>
          </p>
        )}
      </div>

      {/* Justification */}
      <div className="mb-4">
        <label className="block text-xs text-gray-500 mb-1">
          Justificativa <span className="text-red-500">*</span>
          <span className="text-gray-400 ml-1">(minimo 20 caracteres)</span>
        </label>
        <textarea
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          disabled={isProhibited}
          rows={3}
          className={`w-full border rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-300 focus:border-blue-500 resize-none ${
            isProhibited ? 'bg-gray-100 text-gray-400 cursor-not-allowed' : ''
          } ${justification.length > 0 && !justificationValid ? 'border-red-300' : ''}`}
          placeholder="Descreva o motivo da correcao..."
        />
        {justification.length > 0 && !justificationValid && (
          <p className="text-xs text-red-500 mt-0.5">
            {20 - justification.trim().length} caractere(s) restante(s)
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2 border-t">
        <button
          onClick={handleSave}
          disabled={!canSubmit}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? 'Aplicando...' : 'Aplicar Correcao'}
        </button>
        <button
          onClick={onCancel}
          className="text-gray-500 px-4 py-2 rounded text-sm hover:bg-gray-100"
        >
          Cancelar
        </button>
      </div>
    </div>
  )
}
