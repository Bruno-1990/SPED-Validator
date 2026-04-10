import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { GeneratedRule, RuleSummary } from '../types/sped'

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  error: 'bg-orange-100 text-orange-700',
  warning: 'bg-yellow-100 text-yellow-700',
  info: 'bg-blue-100 text-blue-700',
}

const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critico',
  error: 'Erro',
  warning: 'Aviso',
  info: 'Info',
}

const CORRIGIVEL_COLORS: Record<string, string> = {
  automatico: 'bg-green-100 text-green-700',
  proposta: 'bg-blue-100 text-blue-700',
  investigar: 'bg-yellow-100 text-yellow-700',
  impossivel: 'bg-red-100 text-red-700',
}

const CORRIGIVEL_LABELS: Record<string, string> = {
  automatico: 'Automatico',
  proposta: 'Proposta',
  investigar: 'Investigar',
  impossivel: 'Impossivel',
}

export default function RulesPage() {
  const [rules, setRules] = useState<RuleSummary[]>([])
  const [description, setDescription] = useState('')
  const [generating, setGenerating] = useState(false)
  const [implementing, setImplementing] = useState(false)
  const [generatedRule, setGeneratedRule] = useState<GeneratedRule | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [filterBlock, setFilterBlock] = useState<string>('')

  const loadRules = useCallback(async () => {
    try {
      const data = await api.listRules()
      setRules(data)
    } catch {
      // silently fail
    }
  }, [])

  useEffect(() => { loadRules() }, [loadRules])

  const handleGenerate = async () => {
    if (!description.trim()) return
    setGenerating(true)
    setError(null)
    setSuccess(null)
    setGeneratedRule(null)

    try {
      const rule = await api.generateRule(description.trim())
      setGeneratedRule(rule)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao gerar regra')
    } finally {
      setGenerating(false)
    }
  }

  const handleImplement = async () => {
    if (!generatedRule) return
    setImplementing(true)
    setError(null)

    try {
      await api.implementRule(generatedRule)
      setSuccess(`Regra "${generatedRule.id}" adicionada ao rules.yaml com sucesso!`)
      setGeneratedRule(null)
      setDescription('')
      loadRules()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao implementar regra')
    } finally {
      setImplementing(false)
    }
  }

  const blocks = [...new Set(rules.map(r => r.block))]
  const filtered = filterBlock ? rules.filter(r => r.block === filterBlock) : rules
  const implementedCount = rules.filter(r => r.implemented).length
  const pendingCount = rules.filter(r => !r.implemented).length

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Regras de Validacao</h2>

      {/* Score cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Total</p>
          <p className="text-2xl font-bold">{rules.length}</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Implementadas</p>
          <p className="text-2xl font-bold text-green-600">{implementedCount}</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Pendentes</p>
          <p className={`text-2xl font-bold ${pendingCount > 0 ? 'text-yellow-600' : 'text-green-600'}`}>
            {pendingCount}
          </p>
        </div>
      </div>

      {/* Nova Regra */}
      <div className="bg-white rounded shadow p-6 mb-6">
        <h3 className="font-semibold mb-4">Criar Nova Regra</h3>
        <p className="text-sm text-gray-500 mb-3">
          Descreva a regra em linguagem livre. O sistema vai buscar base legal na documentacao
          e estruturar a regra automaticamente.
        </p>

        {/* Input do usuario */}
        <div className="mb-4">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Ex: Quando o NCM indicar produto farmaceutico e o CST de PIS for 01 (tributacao normal), alertar que deveria ser CST 04 (monofasico)..."
            className="w-full border rounded p-3 text-sm h-28 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={generating}
          />
          <div className="flex justify-end mt-2">
            <button
              onClick={handleGenerate}
              disabled={generating || !description.trim()}
              className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {generating ? 'Gerando...' : 'Gerar Regra'}
            </button>
          </div>
        </div>

        {/* Erro */}
        {error && (
          <div className="bg-red-50 text-red-700 text-sm p-3 rounded mb-4">
            {error}
          </div>
        )}

        {/* Sucesso */}
        {success && (
          <div className="bg-green-50 text-green-700 text-sm p-3 rounded mb-4">
            {success}
          </div>
        )}

        {/* Regra gerada (nao editavel) */}
        {generatedRule && (
          <div className="border-t pt-4">
            <h4 className="font-semibold text-sm mb-3 text-gray-700">Regra Estruturada (gerada pelo sistema)</h4>
            <div className="bg-gray-50 rounded p-4 space-y-3">
              {/* Header */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs bg-gray-200 px-2 py-1 rounded">{generatedRule.id}</span>
                <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[generatedRule.severity] || 'bg-gray-100'}`}>
                  {SEVERITY_LABELS[generatedRule.severity] || generatedRule.severity}
                </span>
                <span className="text-xs text-gray-500">Bloco: {generatedRule.block}</span>
                <span className="text-xs text-gray-500">Registro: {generatedRule.register}</span>
              </div>

              {/* Detalhes */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-gray-500 font-semibold">Campos:</span>{' '}
                  <span className="font-mono">{generatedRule.fields.join(', ')}</span>
                </div>
                <div>
                  <span className="text-gray-500 font-semibold">Tipo Erro:</span>{' '}
                  <span className="font-mono">{generatedRule.error_type}</span>
                  {generatedRule.error_type_exists ? (
                    <span className="ml-1 text-green-600" title="Tipo de erro existe no codigo">&#10003;</span>
                  ) : (
                    <span className="ml-1 text-orange-500" title="Tipo de erro nao existe no codigo">&#9888;</span>
                  )}
                </div>
                <div>
                  <span className="text-gray-500 font-semibold">Modulo:</span>{' '}
                  <span className="font-mono">{generatedRule.module}</span>
                </div>
                {generatedRule.legislation && (
                  <div>
                    <span className="text-gray-500 font-semibold">Legislacao:</span>{' '}
                    <span className="text-blue-700">{generatedRule.legislation}</span>
                  </div>
                )}
              </div>

              {/* Warning error_type nao existe */}
              {!generatedRule.error_type_exists && (
                <div className="bg-orange-50 border border-orange-200 rounded p-2 text-xs text-orange-700">
                  <span className="font-semibold">Atencao:</span> O tipo de erro <span className="font-mono">{generatedRule.error_type}</span> ainda nao existe no codigo.
                  {generatedRule.error_type_suggestion && (
                    <> Tipo similar existente: <span className="font-mono font-semibold">{generatedRule.error_type_suggestion}</span></>
                  )}
                  {' '}A regra sera salva como pendente de implementacao.
                </div>
              )}

              {/* Objecoes — regras existentes que ja abrangem */}
              {generatedRule.objections && generatedRule.objections.length > 0 && (
                <div className="bg-amber-50 border border-amber-300 rounded p-3 text-xs">
                  <div className="flex items-center gap-1.5 mb-2">
                    <span className="text-amber-700 text-base">&#9888;</span>
                    <span className="font-semibold text-amber-800">
                      Objecao: {generatedRule.objections.length === 1
                        ? '1 regra existente ja abrange este cenario'
                        : `${generatedRule.objections.length} regras existentes ja abrangem este cenario`}
                    </span>
                  </div>
                  <p className="text-amber-700 mb-2">
                    Verifique se a nova regra realmente adiciona cobertura que nao existe. Voce ainda pode implementa-la se julgar necessario.
                  </p>
                  <div className="space-y-2">
                    {generatedRule.objections.map((obj, i) => (
                      <div key={i} className="bg-white border border-amber-200 rounded p-2.5">
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs bg-amber-100 px-1.5 py-0.5 rounded font-semibold">{obj.rule_id}</span>
                            <span className={`px-1.5 py-0.5 rounded text-xs ${SEVERITY_COLORS[obj.severity] || 'bg-gray-100'}`}>
                              {SEVERITY_LABELS[obj.severity] || obj.severity}
                            </span>
                            <span className="text-gray-500">{obj.register}</span>
                          </div>
                          <span className="text-amber-600 font-mono text-xs">{Math.round(obj.match_score * 100)}% similar</span>
                        </div>
                        <p className="text-gray-700 text-xs mb-1">{obj.description}</p>
                        <div className="flex flex-wrap gap-1 mb-1">
                          {obj.fields.map((f, fi) => (
                            <span key={fi} className="font-mono text-xs bg-gray-100 px-1 rounded">{f}</span>
                          ))}
                        </div>
                        <p className="text-amber-600 text-xs italic">{obj.match_reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Condicao logica */}
              <div className="text-xs">
                <span className="text-gray-500 font-semibold">Condicao:</span>{' '}
                <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">{generatedRule.condition}</span>
              </div>

              {/* Governanca */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs border-t pt-3 mt-1">
                <div>
                  <span className="text-gray-500 font-semibold">Corrigivel:</span>{' '}
                  <span className={`px-2 py-0.5 rounded ${CORRIGIVEL_COLORS[generatedRule.corrigivel] || 'bg-gray-100'}`}>
                    {CORRIGIVEL_LABELS[generatedRule.corrigivel] || generatedRule.corrigivel}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 font-semibold">Certeza:</span>{' '}
                  <span className={generatedRule.certeza === 'objetivo' ? 'text-green-700' : 'text-yellow-700'}>
                    {generatedRule.certeza === 'objetivo' ? 'Objetivo' : 'Subjetivo'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 font-semibold">Impacto:</span>{' '}
                  <span className={generatedRule.impacto === 'relevante' ? 'text-red-700' : 'text-blue-700'}>
                    {generatedRule.impacto === 'relevante' ? 'Relevante' : 'Informativo'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 font-semibold">Vigencia:</span>{' '}
                  <span>{generatedRule.vigencia_de || 'hoje'}</span>
                </div>
              </div>
              {generatedRule.corrigivel_nota && (
                <div className="text-xs text-gray-500 italic mt-1">
                  {generatedRule.corrigivel_nota}
                </div>
              )}

              {/* Base legal encontrada */}
              {generatedRule.legal_sources && generatedRule.legal_sources.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-semibold text-gray-500 mb-2">Base Legal Encontrada:</p>
                  <div className="space-y-2">
                    {generatedRule.legal_sources.map((src, i) => (
                      <div key={i} className="bg-white border rounded p-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-blue-800">{src.fonte}</span>
                          <span className="text-xs text-gray-400">score: {src.score}</span>
                        </div>
                        {src.heading && (
                          <p className="text-xs text-gray-600 font-semibold">{src.heading}</p>
                        )}
                        <p className="text-xs text-gray-500 mt-1 line-clamp-3">
                          {src.content.length > 300 ? src.content.substring(0, 300) + '...' : src.content}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Botao implementar */}
              <div className="flex justify-end pt-3 border-t">
                <button
                  onClick={handleImplement}
                  disabled={implementing}
                  className="bg-green-600 text-white px-6 py-2 rounded hover:bg-green-700 disabled:opacity-50 font-semibold"
                >
                  {implementing ? 'Implementando...' : 'Implementar Regra Fiscal'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Lista de regras existentes */}
      <div className="bg-white rounded shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold">Regras Cadastradas</h3>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Filtrar:</span>
            <select
              value={filterBlock}
              onChange={(e) => setFilterBlock(e.target.value)}
              className="text-sm border rounded px-2 py-1"
            >
              <option value="">Todos os blocos</option>
              {blocks.map(b => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>
        </div>

        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-50 text-left text-xs text-gray-500">
              <th className="p-2">ID</th>
              <th className="p-2">Bloco</th>
              <th className="p-2">Registro</th>
              <th className="p-2">Descricao</th>
              <th className="p-2">Severidade</th>
              <th className="p-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id} className="border-t hover:bg-gray-50">
                <td className="p-2 font-mono text-xs">{r.id}</td>
                <td className="p-2 text-xs text-gray-500">{r.block}</td>
                <td className="p-2 font-mono text-xs">{r.register}</td>
                <td className="p-2 text-xs">{r.description.length > 80 ? r.description.substring(0, 80) + '...' : r.description}</td>
                <td className="p-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[r.severity] || 'bg-gray-100'}`}>
                    {SEVERITY_LABELS[r.severity] || r.severity}
                  </span>
                </td>
                <td className="p-2">
                  <span className={`text-xs font-semibold ${r.implemented ? 'text-green-600' : 'text-yellow-600'}`}>
                    {r.implemented ? 'OK' : 'Pendente'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <p className="text-gray-400 text-center py-6 text-sm">Nenhuma regra encontrada.</p>
        )}
      </div>
    </div>
  )
}
