import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { RecordInfo, ValidationError } from '../../types/sped'

// Field definitions per register
const REGISTER_FIELDS: Record<string, string[]> = {
  '0000': ['REG', 'COD_VER', 'COD_FIN', 'DT_INI', 'DT_FIN', 'NOME', 'CNPJ', 'CPF', 'UF', 'IE', 'COD_MUN', 'IM', 'SUFRAMA', 'IND_PERFIL', 'IND_ATIV'],
  '0150': ['REG', 'COD_PART', 'NOME', 'COD_PAIS', 'CNPJ', 'CPF', 'IE', 'COD_MUN', 'SUFRAMA', 'END', 'NUM', 'COMPL', 'BAIRRO'],
  'C100': ['REG', 'IND_OPER', 'IND_EMIT', 'COD_PART', 'COD_MOD', 'COD_SIT', 'SER', 'NUM_DOC', 'CHV_NFE', 'DT_DOC', 'DT_E_S', 'VL_DOC', 'IND_PGTO', 'VL_DESC', 'VL_ABAT_NT', 'VL_MERC', 'IND_FRT', 'VL_FRT', 'VL_SEG', 'VL_OUT_DA', 'VL_BC_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'VL_ICMS_ST', 'VL_IPI', 'VL_PIS', 'VL_COFINS', 'VL_PIS_ST', 'VL_COFINS_ST'],
  'C170': ['REG', 'NUM_ITEM', 'COD_ITEM', 'DESCR_COMPL', 'QTD', 'UNID', 'VL_ITEM', 'VL_DESC', 'IND_MOV', 'CST_ICMS', 'CFOP', 'COD_NAT', 'VL_BC_ICMS', 'ALIQ_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'ALIQ_ST', 'VL_ICMS_ST', 'IND_APUR', 'CST_IPI', 'COD_ENQ', 'VL_BC_IPI', 'ALIQ_IPI', 'VL_IPI', 'CST_PIS', 'VL_BC_PIS', 'ALIQ_PIS', 'QUANT_BC_PIS', 'ALIQ_PIS_QUANT', 'VL_PIS', 'CST_COFINS', 'VL_BC_COFINS', 'ALIQ_COFINS', 'QUANT_BC_COFINS', 'ALIQ_COFINS_QUANT', 'VL_COFINS', 'COD_CTA'],
  'C190': ['REG', 'CST_ICMS', 'CFOP', 'ALIQ_ICMS', 'VL_OPR', 'VL_BC_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'VL_ICMS_ST', 'VL_RED_BC', 'VL_IPI', 'COD_OBS'],
  'E110': ['REG', 'VL_TOT_DEBITOS', 'VL_AJ_DEBITOS', 'VL_TOT_AJ_DEBITOS', 'VL_ESTORNOS_CRED', 'VL_TOT_CREDITOS', 'VL_AJ_CREDITOS', 'VL_TOT_AJ_CREDITOS', 'VL_ESTORNOS_DEB', 'VL_SLD_CREDOR_ANT', 'VL_SLD_APURADO', 'VL_TOT_DED', 'VL_ICMS_RECOLHER', 'VL_SLD_CREDOR_TRANSPORTAR', 'DEB_ESP'],
  'E210': ['REG', 'IND_MOV_ST', 'VL_SLD_CRED_ANT_ST', 'VL_DEVOL_ST', 'VL_RESSARC_ST', 'VL_OUT_CRED_ST', 'VL_AJ_CREDITOS_ST', 'VL_RETENCAO_ST', 'VL_OUT_DEB_ST', 'VL_AJ_DEBITOS_ST', 'VL_SLD_DEV_ANT_ST', 'VL_DEDUCOES_ST', 'VL_ICMS_RECOL_ST', 'VL_SLD_CRED_ST_TRANSPORTAR', 'DEB_ESP_ST'],
}

// Fields that CANNOT be edited (structural/identity fields)
const READONLY_FIELDS = new Set([
  'REG', 'COD_VER', 'COD_FIN', 'CNPJ', 'CPF', 'CHV_NFE', 'NUM_DOC', 'SER',
  'COD_PART', 'COD_MOD', 'COD_ITEM', 'NUM_ITEM', 'COD_NAT', 'COD_ENQ', 'COD_CTA',
  'CST_ICMS', 'CFOP', 'CST_IPI', 'CST_PIS', 'CST_COFINS',
  'COD_AJ_APUR', 'COD_MUN', 'COD_PAIS',
])

// Fields that are monetary (for formatting hints)
const MONETARY_FIELDS = new Set([
  'VL_DOC', 'VL_MERC', 'VL_DESC', 'VL_ABAT_NT', 'VL_FRT', 'VL_SEG', 'VL_OUT_DA',
  'VL_BC_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'VL_ICMS_ST', 'VL_IPI',
  'VL_PIS', 'VL_COFINS', 'VL_PIS_ST', 'VL_COFINS_ST',
  'VL_ITEM', 'VL_OPR', 'VL_RED_BC', 'VL_BC_IPI', 'VL_BC_PIS', 'VL_BC_COFINS',
  'VL_TOT_DEBITOS', 'VL_TOT_CREDITOS', 'VL_SLD_APURADO', 'VL_ICMS_RECOLHER',
  'VL_RETENCAO_ST', 'VL_ICMS_RECOL_ST', 'VL_SLD_DEV_ANT_ST',
  'ALIQ_ICMS', 'ALIQ_ST', 'ALIQ_IPI', 'ALIQ_PIS', 'ALIQ_COFINS',
])

interface ParsedField {
  name: string
  value: string
  index: number
  isReadonly: boolean
  isMonetary: boolean
  error?: ValidationError
  status: 'error' | 'corrected' | 'normal'
}

interface Props {
  fileId: number
  error: ValidationError
  onClose: () => void
  onSaved: () => void
}

export default function RecordEditModal({ fileId, error, onClose, onSaved }: Props) {
  const [record, setRecord] = useState<RecordInfo | null>(null)
  const [allErrors, setAllErrors] = useState<ValidationError[]>([])
  const [loading, setLoading] = useState(true)
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  // Load record data
  useEffect(() => {
    if (!error.record_id) { setLoading(false); return }
    setLoading(true)
    api.getRecord(fileId, error.record_id)
      .then(r => {
        setRecord(r)
        // Load all errors for this record to highlight affected fields
        api.getErrors(fileId, { page_size: '500' }).then(res => {
          const recErrors = (res as unknown as ValidationError[]).filter(
            (e: ValidationError) => e.record_id === error.record_id
          )
          setAllErrors(recErrors)
        }).catch(() => {})
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [fileId, error.record_id])

  const parseFields = useCallback((rec: RecordInfo): ParsedField[] => {
    let entries: [string, string][] = []
    try {
      const json = JSON.parse(rec.fields_json)
      if (Array.isArray(json)) {
        const names = REGISTER_FIELDS[rec.register] || []
        entries = json.map((v: string, i: number) => [names[i] || `Campo_${i}`, String(v ?? '')])
      } else {
        entries = Object.entries(json).map(([k, v]) => [k, String(v ?? '')])
      }
    } catch {
      const parts = rec.raw_line.split('|').filter((_: string, i: number, arr: string[]) => i > 0 && i < arr.length - 1)
      const names = REGISTER_FIELDS[rec.register] || []
      entries = parts.map((v: string, i: number) => [names[i] || `Campo_${i}`, v])
    }

    const errorByField = new Map<string, ValidationError>()
    const errorByNo = new Map<number, ValidationError>()
    for (const e of allErrors) {
      if (e.field_name) errorByField.set(e.field_name, e)
      if (e.field_no !== null) errorByNo.set(e.field_no, e)
    }

    return entries.map(([name, value], index) => {
      // Priorizar match por nome (mais confiavel). field_no=0 ignorado (REG)
      const fieldError = errorByField.get(name) || (index > 0 ? errorByNo.get(index) : undefined)
      const isError = fieldError?.status === 'open'
      const isCorrected = fieldError?.status === 'corrected'
      return {
        name, value, index,
        isReadonly: READONLY_FIELDS.has(name),
        isMonetary: MONETARY_FIELDS.has(name),
        error: fieldError,
        status: isError ? 'error' : isCorrected ? 'corrected' : 'normal',
      }
    })
  }, [allErrors])

  const handleStartEdit = (field: ParsedField) => {
    if (field.isReadonly) return
    setSaveError('')
    setEditingField(field.name)
    setEditValue(field.error?.expected_value || field.value)
  }

  const handleSave = async () => {
    if (!record || !editingField) return
    setSaving(true)
    setSaveError('')

    const field = parseFields(record).find(f => f.name === editingField)
    if (!field) { setSaving(false); return }

    try {
      await api.updateRecord(fileId, record.id, {
        field_no: field.index,
        field_name: editingField,
        new_value: editValue,
        error_id: field.error?.id,
        rule_id: field.error?.error_type || 'MANUAL',
        correction_type: 'manual',
        justificativa: `Correcao manual: ${editingField} de "${field.value}" para "${editValue}"`,
      })
      // Reload record to see updated value
      const updated = await api.getRecord(fileId, record.id)
      setRecord(updated)
      setEditingField(null)
      onSaved()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Erro ao salvar')
    }
    setSaving(false)
  }

  const handleCancelEdit = () => {
    setEditingField(null)
    setSaveError('')
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
        <div className="relative bg-white rounded-2xl shadow-2xl p-8">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto" />
          <p className="text-sm text-gray-500 mt-3">Carregando registro...</p>
        </div>
      </div>
    )
  }

  if (!record) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
        <div className="relative bg-white rounded-2xl shadow-2xl p-8">
          <p className="text-sm text-gray-500">Registro nao encontrado</p>
          <button onClick={onClose} className="mt-4 text-sm text-blue-600 hover:underline">Fechar</button>
        </div>
      </div>
    )
  }

  const fields = parseFields(record)
  const errorFields = fields.filter(f => f.status === 'error')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b bg-gray-50 rounded-t-2xl">
          <div>
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-bold bg-blue-100 text-blue-800 px-2.5 py-1 rounded">
                {record.register}
              </span>
              <span className="text-sm text-gray-600">Linha {record.line_number}</span>
              {errorFields.length > 0 && (
                <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
                  {errorFields.length} campo{errorFields.length !== 1 ? 's' : ''} com erro
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none px-2">&times;</button>
        </div>

        {/* Error banner */}
        {error.friendly_message && (
          <div className="px-6 py-3 bg-red-50 border-b border-red-100 text-sm text-red-800">
            {error.friendly_message}
          </div>
        )}

        {/* Fields table */}
        <div className="flex-1 overflow-y-auto px-2">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white">
              <tr className="text-left text-xs text-gray-500 border-b">
                <th className="px-4 py-2 w-8">#</th>
                <th className="px-4 py-2 w-40">Campo</th>
                <th className="px-4 py-2">Valor</th>
                <th className="px-4 py-2 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => {
                const isEditing = editingField === field.name
                const hasError = field.status === 'error'
                const isCorrected = field.status === 'corrected'

                const rowBg = isEditing ? 'bg-blue-50' :
                  hasError ? 'bg-red-50' :
                  isCorrected ? 'bg-green-50' : ''

                return (
                  <tr key={field.index} className={`border-b ${rowBg} transition-colors`}>
                    <td className="px-4 py-2 text-xs text-gray-400">{field.index}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-medium">{field.name}</span>
                        {hasError && <span className="text-red-500 text-xs">&#9888;</span>}
                        {isCorrected && <span className="text-green-600 text-xs">&#10003;</span>}
                        {field.isReadonly && <span className="text-gray-300 text-xs" title="Somente leitura">&#128274;</span>}
                        {field.isMonetary && <span className="text-gray-300 text-xs" title="Valor monetario">R$</span>}
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      {isEditing ? (
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={editValue}
                            onChange={e => setEditValue(e.target.value)}
                            autoFocus
                            className="flex-1 border border-blue-300 rounded px-2 py-1 text-sm font-mono focus:ring-2 focus:ring-blue-400 focus:border-blue-500"
                            onKeyDown={e => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') handleCancelEdit() }}
                          />
                          <button
                            onClick={handleSave}
                            disabled={saving}
                            className="text-xs bg-green-600 text-white px-2.5 py-1 rounded hover:bg-green-700 disabled:opacity-50"
                          >
                            {saving ? '...' : 'Salvar'}
                          </button>
                          <button
                            onClick={handleCancelEdit}
                            className="text-xs text-gray-500 px-2 py-1 rounded hover:bg-gray-100"
                          >
                            Cancelar
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span className={`font-mono text-xs ${hasError ? 'text-red-700 font-medium' : 'text-gray-700'}`}>
                            {field.value || <span className="text-gray-300 italic">vazio</span>}
                          </span>
                          {hasError && field.error?.expected_value && (
                            <span className="text-xs text-green-600 font-mono" title="Valor sugerido">
                              &rarr; {field.error.expected_value}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {!isEditing && !field.isReadonly && (
                        <button
                          onClick={() => handleStartEdit(field)}
                          className={`text-xs px-2 py-1 rounded ${
                            hasError
                              ? 'bg-blue-600 text-white hover:bg-blue-700'
                              : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                          }`}
                        >
                          {hasError ? 'Corrigir' : 'Editar'}
                        </button>
                      )}
                      {field.isReadonly && (
                        <span className="text-xs text-gray-300">bloqueado</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Save error */}
        {saveError && (
          <div className="px-6 py-2 bg-red-50 border-t border-red-200 text-sm text-red-700">
            {saveError}
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-3 border-t bg-gray-50 rounded-b-2xl flex items-center justify-between">
          <details className="text-xs text-gray-400">
            <summary className="cursor-pointer hover:text-gray-600">Linha original</summary>
            <pre className="mt-1 font-mono text-xs text-gray-500 max-w-full overflow-x-auto whitespace-pre-wrap break-all">
              {record.raw_line}
            </pre>
          </details>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  )
}
