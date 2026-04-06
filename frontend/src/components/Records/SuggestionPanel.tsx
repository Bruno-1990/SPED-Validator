import { useEffect, useState } from 'react'
import type { SearchResult, ValidationError, LegalBasis } from '../../types/sped'

interface Props {
  error: ValidationError
  onSearch: (query: string) => Promise<SearchResult[]>
}

const CERTEZA_CONFIG: Record<string, { label: string; color: string; tooltip: string }> = {
  objetivo:  { label: 'Objetivo',  color: 'bg-green-100 text-green-800', tooltip: 'Erro detectado por regra deterministica — certeza absoluta' },
  provavel:  { label: 'Provavel',  color: 'bg-blue-100 text-blue-800',   tooltip: 'Alta probabilidade baseada em cruzamento de dados' },
  indicio:   { label: 'Indicio',   color: 'bg-yellow-100 text-yellow-800', tooltip: 'Indicativo que requer analise manual para confirmacao' },
}

const IMPACTO_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  critico:      { label: 'Critico',      color: 'bg-red-100 text-red-800',    icon: '\u26A0' },
  relevante:    { label: 'Relevante',    color: 'bg-orange-100 text-orange-800', icon: '\u25CF' },
  informativo:  { label: 'Informativo',  color: 'bg-blue-100 text-blue-700',  icon: '\u2139' },
}

function parseLegalBasis(raw: string | null): LegalBasis | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && parsed.fonte) return parsed as LegalBasis
  } catch { /* */ }
  return null
}

export default function SuggestionPanel({ error, onSearch }: Props) {
  const [docs, setDocs] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const query = `${error.register} ${error.field_name || ''} ${error.error_type}`.trim()
    setLoading(true)
    onSearch(query)
      .then((results) => setDocs(results.slice(0, 3)))
      .catch(() => setDocs([]))
      .finally(() => setLoading(false))
  }, [error.id, error.register, error.field_name, error.error_type, onSearch])

  const legalBasis = parseLegalBasis(error.legal_basis)
  const certeza = error.certeza ? CERTEZA_CONFIG[error.certeza] : null
  const impacto = error.impacto ? IMPACTO_CONFIG[error.impacto] : null

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-4 space-y-4 w-80 flex-shrink-0">
      <h4 className="font-semibold text-sm text-gray-700 border-b pb-2">Painel de Sugestoes</h4>

      {/* Documentacao relevante */}
      <section>
        <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Documentacao relevante</h5>
        {loading ? (
          <p className="text-xs text-gray-400 animate-pulse">Buscando...</p>
        ) : docs.length > 0 ? (
          <div className="space-y-2">
            {docs.map((doc, i) => (
              <div key={i} className="bg-gray-50 rounded p-2 text-xs">
                <p className="font-medium text-gray-700 mb-0.5">{doc.heading}</p>
                <p className="text-gray-500 line-clamp-2">{doc.content}</p>
                <span className="text-gray-400 text-[10px]">Score: {doc.score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-400">Nenhuma documentacao encontrada.</p>
        )}
      </section>

      {/* O que o sistema encontrou */}
      <section>
        <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">O que o sistema encontrou</h5>
        <p className="text-sm text-gray-700">
          {error.friendly_message || error.message}
        </p>
      </section>

      {/* Orientacao de correcao */}
      {error.doc_suggestion && (
        <section>
          <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Orientacao de correcao</h5>
          <div className="text-sm text-gray-700 bg-blue-50 border border-blue-100 rounded p-2 whitespace-pre-line">
            {error.doc_suggestion.replace(/\*\*Como corrigir:\*\*\s*/, '')}
          </div>
        </section>
      )}

      {/* Base legal */}
      {legalBasis && (
        <section>
          <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Base legal</h5>
          <div className="text-xs bg-gray-50 border rounded p-2">
            <p className="font-medium text-gray-700">{legalBasis.fonte}</p>
            {legalBasis.artigo && <p className="text-gray-500">{legalBasis.artigo}</p>}
            {legalBasis.trecho && <p className="text-gray-500 mt-1 italic">{legalBasis.trecho}</p>}
          </div>
        </section>
      )}

      {/* Certeza + Impacto badges */}
      <div className="flex items-center gap-3 pt-2 border-t">
        {certeza && (
          <div className="group relative">
            <span className={`text-xs px-2 py-1 rounded font-medium ${certeza.color}`}>
              {certeza.label}
            </span>
            <div className="absolute bottom-full left-0 mb-1 hidden group-hover:block bg-gray-800 text-white text-[10px] rounded px-2 py-1 w-48 z-10">
              {certeza.tooltip}
            </div>
          </div>
        )}
        {impacto && (
          <span className={`text-xs px-2 py-1 rounded font-medium ${impacto.color}`}>
            {impacto.icon} {impacto.label}
          </span>
        )}
      </div>
    </div>
  )
}
