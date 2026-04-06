import { useState } from 'react'
import { api } from '../../api/client'
import type { RecordInfo, ValidationError, SearchResult } from '../../types/sped'

interface Props {
  record: RecordInfo
  errors: ValidationError[]
  onClose: () => void
  onFieldClick?: (fieldName: string, error: ValidationError) => void
}

interface ParsedField {
  name: string
  value: string
  index: number
}

// Known field definitions per register (common ones)
const REGISTER_FIELDS: Record<string, string[]> = {
  '0000': ['REG', 'COD_VER', 'COD_FIN', 'DT_INI', 'DT_FIN', 'NOME', 'CNPJ', 'CPF', 'UF', 'IE', 'COD_MUN', 'IM', 'SUFRAMA', 'IND_PERFIL', 'IND_ATIV'],
  'C100': ['REG', 'IND_OPER', 'IND_EMIT', 'COD_PART', 'COD_MOD', 'COD_SIT', 'SER', 'NUM_DOC', 'CHV_NFE', 'DT_DOC', 'DT_E_S', 'VL_DOC', 'IND_PGTO', 'VL_DESC', 'VL_ABAT_NT', 'VL_MERC', 'IND_FRT', 'VL_FRT', 'VL_SEG', 'VL_OUT_DA', 'VL_BC_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'VL_ICMS_ST', 'VL_IPI', 'VL_PIS', 'VL_COFINS', 'VL_PIS_ST', 'VL_COFINS_ST'],
  'C170': ['REG', 'NUM_ITEM', 'COD_ITEM', 'DESCR_COMPL', 'QTD', 'UNID', 'VL_ITEM', 'VL_DESC', 'IND_MOV', 'CST_ICMS', 'CFOP', 'COD_NAT', 'VL_BC_ICMS', 'ALIQ_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'ALIQ_ST', 'VL_ICMS_ST', 'IND_APUR', 'CST_IPI', 'COD_ENQ', 'VL_BC_IPI', 'ALIQ_IPI', 'VL_IPI', 'CST_PIS', 'VL_BC_PIS', 'ALIQ_PIS', 'QUANT_BC_PIS', 'ALIQ_PIS_QUANT', 'VL_PIS', 'CST_COFINS', 'VL_BC_COFINS', 'ALIQ_COFINS', 'QUANT_BC_COFINS', 'ALIQ_COFINS_QUANT', 'VL_COFINS', 'COD_CTA'],
  'C190': ['REG', 'CST_ICMS', 'CFOP', 'ALIQ_ICMS', 'VL_OPR', 'VL_BC_ICMS', 'VL_ICMS', 'VL_BC_ICMS_ST', 'VL_ICMS_ST', 'VL_RED_BC', 'VL_IPI', 'COD_OBS'],
  'E110': ['REG', 'VL_TOT_DEBITOS', 'VL_AJ_DEBITOS', 'VL_TOT_AJ_DEBITOS', 'VL_ESTORNOS_CRED', 'VL_TOT_CREDITOS', 'VL_AJ_CREDITOS', 'VL_TOT_AJ_CREDITOS', 'VL_ESTORNOS_DEB', 'VL_SLD_CREDOR_ANT', 'VL_SLD_APURADO', 'VL_TOT_DED', 'VL_ICMS_RECOLHER', 'VL_SLD_CREDOR_TRANSPORTAR', 'DEB_ESP'],
}

function parseFields(record: RecordInfo): ParsedField[] {
  try {
    const json = JSON.parse(record.fields_json)
    if (Array.isArray(json)) {
      const fieldNames = REGISTER_FIELDS[record.register] || []
      return json.map((value, i) => ({
        name: fieldNames[i] || `Campo_${i}`,
        value: String(value ?? ''),
        index: i,
      }))
    }
    // Object format
    return Object.entries(json).map(([name, value], i) => ({
      name,
      value: String(value ?? ''),
      index: i,
    }))
  } catch {
    // Fallback: pipe-delimited raw line
    const parts = record.raw_line.split('|').filter((_, i, arr) => i > 0 && i < arr.length - 1)
    const fieldNames = REGISTER_FIELDS[record.register] || []
    return parts.map((value, i) => ({
      name: fieldNames[i] || `Campo_${i}`,
      value,
      index: i,
    }))
  }
}

export default function RecordDetail({ record, errors, onClose, onFieldClick }: Props) {
  const fields = parseFields(record)
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)

  const errorByField = new Map<string, ValidationError>()
  const errorByFieldNo = new Map<number, ValidationError>()
  for (const err of errors) {
    if (err.field_name) errorByField.set(err.field_name, err)
    if (err.field_no !== null) errorByFieldNo.set(err.field_no, err)
  }

  const correctedFields = new Set<string>()
  for (const err of errors) {
    if (err.status === 'corrected' && err.field_name) correctedFields.add(err.field_name)
  }

  const getFieldError = (field: ParsedField): ValidationError | undefined => {
    return errorByField.get(field.name) || errorByFieldNo.get(field.index)
  }

  const getFieldStatus = (field: ParsedField): 'error' | 'corrected' | 'normal' => {
    const err = getFieldError(field)
    if (err && err.status === 'open') return 'error'
    if (correctedFields.has(field.name)) return 'corrected'
    return 'normal'
  }

  const handleSearchDocs = async () => {
    setSearching(true)
    try {
      const results = await api.searchDocs(record.register, undefined, record.register)
      setSearchResults(results)
    } catch {
      setSearchResults([])
    }
    setSearching(false)
  }

  return (
    <div className="bg-white border rounded-lg shadow-lg mt-2 mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-gray-50">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm font-semibold bg-blue-100 text-blue-800 px-2 py-0.5 rounded">
            {record.register}
          </span>
          <span className="text-sm text-gray-500">Linha {record.line_number}</span>
          <span className="text-xs text-gray-400">ID: {record.id}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSearchDocs}
            disabled={searching}
            className="text-xs px-3 py-1 rounded bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-50"
          >
            {searching ? 'Buscando...' : 'Ver documentacao'}
          </button>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg px-2"
            title="Fechar"
          >
            &times;
          </button>
        </div>
      </div>

      {/* Fields table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b bg-gray-50">
              <th className="px-4 py-2 w-8">#</th>
              <th className="px-4 py-2">Campo</th>
              <th className="px-4 py-2">Valor</th>
              <th className="px-4 py-2 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => {
              const status = getFieldStatus(field)
              const fieldError = getFieldError(field)
              const isClickable = status === 'error' && fieldError && onFieldClick

              const rowBg = status === 'error'
                ? 'bg-red-50 hover:bg-red-100'
                : status === 'corrected'
                ? 'bg-green-50'
                : 'hover:bg-gray-50'

              return (
                <tr
                  key={field.index}
                  className={`border-b ${rowBg} ${isClickable ? 'cursor-pointer' : ''}`}
                  onClick={() => isClickable && onFieldClick!(field.name, fieldError!)}
                >
                  <td className="px-4 py-1.5 text-xs text-gray-400">{field.index}</td>
                  <td className="px-4 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs">{field.name}</span>
                      {status === 'error' && (
                        <span className="text-red-500" title="Campo com erro">&#9888;</span>
                      )}
                      {status === 'corrected' && (
                        <span className="text-green-600" title="Campo corrigido">&#10003;</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-1.5 font-mono text-xs">
                    {field.value || <span className="text-gray-300 italic">vazio</span>}
                  </td>
                  <td className="px-4 py-1.5">
                    {isClickable && (
                      <span className="text-xs text-blue-600">Editar</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Search results */}
      {searchResults !== null && (
        <div className="border-t px-4 py-3">
          <h4 className="text-sm font-semibold mb-2 text-gray-700">Documentacao - {record.register}</h4>
          {searchResults.length === 0 ? (
            <p className="text-xs text-gray-400">Nenhum resultado encontrado.</p>
          ) : (
            <div className="space-y-2">
              {searchResults.map((r, i) => (
                <div key={i} className="text-xs bg-blue-50 border border-blue-100 rounded p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-blue-800">{r.heading}</span>
                    {r.register && <span className="font-mono text-blue-600">{r.register}</span>}
                    <span className="text-gray-400 ml-auto">{(r.score * 100).toFixed(0)}%</span>
                  </div>
                  <p className="text-gray-700 whitespace-pre-line line-clamp-3">{r.content}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Raw line (collapsible) */}
      <details className="border-t px-4 py-2">
        <summary className="text-xs text-gray-400 cursor-pointer">Linha original</summary>
        <pre className="text-xs font-mono text-gray-500 mt-1 overflow-x-auto whitespace-pre-wrap break-all">
          {record.raw_line}
        </pre>
      </details>
    </div>
  )
}
