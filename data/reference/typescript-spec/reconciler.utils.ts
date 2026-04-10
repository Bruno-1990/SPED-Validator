// ─────────────────────────────────────────────────────────────────────────────
// reconciler.utils.ts  —  Utilitários compartilhados pelo motor de reconciliação
// ─────────────────────────────────────────────────────────────────────────────

import type { Finding, Severity, SubBlock } from '../types/sped.types';

// ── Arredondamento half-even (ABNT NBR 5891) ─────────────────────────────────
// Evita o viés do arredondamento padrão (half-up). Usado em TODOS os cálculos
// intermediários do motor para reproduzir o comportamento dos sistemas NF-e/SPED.
export function halfEven(value: number, decimals = 2): number {
  const factor = Math.pow(10, decimals);
  const shifted = value * factor;
  const floored = Math.floor(shifted);
  const diff    = shifted - floored;
  if (diff < 0.5) return floored / factor;
  if (diff > 0.5) return (floored + 1) / factor;
  return (floored % 2 === 0 ? floored : floored + 1) / factor;
}

// ── Diferença absoluta com half-even ────────────────────────────────────────
export function absDiff(a: number, b: number): number {
  return halfEven(Math.abs(halfEven(a) - halfEven(b)));
}

// ── Tolerância para reconciliação E110 ───────────────────────────────────────
// Decisão de produto consciente:
//   Reconciliação E110 → tolerância híbrida: máx(R$0,01 ; total × 0,001%).
//   Justificativa: arredondamentos acumulados em arquivos com 50k NFs podem
//   superar R$0,01 mas ainda ficam abaixo de 0,001% do total.
//   C100 vs C170 usa tolerância fixa de R$0,02 por NF (ver c100.validator.ts).
//   Justificativa: cada NF é avaliada individualmente; 2 centavos cobrem
//   arredondamento de frete/seguro sem mascarar erros de IPI/ST.
export function tolerance(
  declared:    number,
  absoluteBrl = 0.01,
  pct         = 0.00001,
): number {
  return Math.max(absoluteBrl, Math.abs(declared) * pct);
}

// ── Classificar severidade pela faixa de diferença ──────────────────────────
export function classifyDiffSeverity(diff: number): Severity {
  if (diff > 10_000) return 'CRÍTICO';
  if (diff > 100)    return 'ALTO';
  return 'MÉDIO';
}

// ── Determinar sourceSubblock dominante a partir do breakdown ───────────────
// Ponto 1: quando a composição é mista (C190+D190+D590), sourceSubblock deve
// refletir o maior componente — o que mais contribui para o total calculado.
// Isso torna o campo semanticamente coerente para relatório e analytics.
export function dominantSubblock(breakdown: {
  c190: number;
  d190: number;
  d590?: number;
}): SubBlock {
  const d590 = breakdown.d590 ?? 0;
  const max  = Math.max(breakdown.c190, breakdown.d190, d590);
  if (max === breakdown.d190 && breakdown.d190 > 0) return 'D190';
  if (max === d590            && d590 > 0)          return 'D590';
  return 'C190';
}

// ── Fábrica de Finding ───────────────────────────────────────────────────────
export function makeFinding(
  partial: Omit<Finding, 'difference'> & { found: number; expected: number },
): Finding {
  return { ...partial, difference: absDiff(partial.found, partial.expected) };
}

// ── Alerta de falta de parametrização ───────────────────────────────────────
// Ponto 2: sourceSubblock recebe o subbloco correto para o contexto da regra,
// não 'C190' fixo. Caller passa o subbloco; default mantém compatibilidade.
export function makeParamAlert(
  ruleId:         string,
  period:         string,
  uf:             string,
  code:           string,
  message:        string,
  sourceSubblock: SubBlock = 'C190',
): Finding {
  return {
    ruleId,
    severity:      'ALERTA',
    situationType: 'FALTA_PARAMETRIZACAO',
    errorCode:     code,
    sourceSubblock,
    period, uf,
    found:         null,
    expected:      null,
    difference:    null,
    description:   message,
    correctionHint:'Popular tabela auxiliar no SQLite antes de reprocessar.',
    legalBasis:    'Premissa P5 — tabelas auxiliares externas ao código-fonte.',
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Tabelas de CST por tipo de registro
//
// Ponto 8: D590 (comunicação) tem funções próprias mesmo que o conjunto de
// CSTs seja hoje idêntico ao C190. Evita acoplamento semântico entre
// mercadoria, transporte e comunicação — cada categoria pode divergir no
// futuro por regulamentação estadual específica (ex.: alíquota 25% em NFSC).
// ─────────────────────────────────────────────────────────────────────────────

// C190 — Notas Fiscais de mercadoria (Bloco C)
export const CST_C190_DEBITO  = new Set(['00', '10', '20', '51', '70', '90']);
export const CST_C190_CREDITO = new Set(['00', '20', '90']);

// D190 — CT-e / NFST (Bloco D — transporte)
// CST 10/30/70 geram débito ST no E210, não débito próprio no E110.
export const CST_D190_DEBITO  = new Set(['00', '20', '51', '70', '90']);
export const CST_D190_CREDITO = new Set(['00', '20', '90']);

// D590 — NFSC (Bloco D — comunicação)
// Alíquota diferenciada (25% alguns estados); sem ST; conjunto igual hoje mas
// mantido separado para evolução independente.
export const CST_D590_DEBITO  = new Set(['00', '20', '51', '70', '90']);
export const CST_D590_CREDITO = new Set(['00', '20', '90']);

export const isCstDebitoC190  = (cst: string) => CST_C190_DEBITO.has(cst);
export const isCstCreditoC190 = (cst: string) => CST_C190_CREDITO.has(cst);
export const isCstDebitoD190  = (cst: string) => CST_D190_DEBITO.has(cst);
export const isCstCreditoD190 = (cst: string) => CST_D190_CREDITO.has(cst);
export const isCstDebitoD590  = (cst: string) => CST_D590_DEBITO.has(cst);
export const isCstCreditoD590 = (cst: string) => CST_D590_CREDITO.has(cst);
