// ─────────────────────────────────────────────────────────────────────────────
// c100.validator.ts
//
// Validação: C100.VL_DOC vs componentes do C170
//
// Fórmula:
//   VL_DOC_esperado = Σ C170.VL_ITEM
//                   - Σ C170.VL_DESC
//                   + Σ C170.VL_FRT
//                   + Σ C170.VL_SEG
//                   + Σ C170.VL_OUTRO
//                   + Σ C170.VL_IPI
//                   + Σ C170.VL_ICMS_ST
//
// Tolerância: R$0,02 por NF (decisão consciente — ver reconciler.utils.ts).
// Base legal: GP-317 Reg.C100 campo VL_DOC · Ato COTEPE-44 Reg.C170
// ─────────────────────────────────────────────────────────────────────────────

import type { C100, C170, Finding } from '../types/sped.types';
import { halfEven, absDiff, makeFinding } from '../utils/reconciler.utils';

const TOLERANCE_BRL = 0.02;
const SITUACOES_CANCELADAS = new Set(['02', '03', '04', '05', '06', '07']);

// ─────────────────────────────────────────────────────────────────────────────
// Tipos
// ─────────────────────────────────────────────────────────────────────────────

export interface C170Breakdown {
  vlProd:   number;
  vlDesc:   number;
  vlFrt:    number;
  vlSeg:    number;
  vlOutro:  number;
  vlIpi:    number;
  vlIcmsSt: number;
}

export interface C100ValidationResult {
  numDoc:     string;
  vlDoc:      number;
  vlEsperado: number;
  diferenca:  number;
  breakdown:  C170Breakdown;
  finding?:   Finding;
}

// ─────────────────────────────────────────────────────────────────────────────
// Calcular VL_DOC esperado a partir dos C170
// ─────────────────────────────────────────────────────────────────────────────

export function calcularVlDocEsperado(itens: C170[]): {
  vlEsperado: number;
  breakdown:  C170Breakdown;
} {
  let vlProd = 0, vlDesc = 0, vlFrt = 0, vlSeg = 0,
      vlOutro = 0, vlIpi = 0, vlIcmsSt = 0;

  for (const item of itens) {
    vlProd   = halfEven(vlProd   + (item.vlItem   ?? 0));
    vlDesc   = halfEven(vlDesc   + (item.vlDesc   ?? 0));
    vlFrt    = halfEven(vlFrt    + (item.vlFrt    ?? 0));
    vlSeg    = halfEven(vlSeg    + (item.vlSeg    ?? 0));
    vlOutro  = halfEven(vlOutro  + (item.vlOutro  ?? 0));
    vlIpi    = halfEven(vlIpi    + (item.vlIpi    ?? 0));
    vlIcmsSt = halfEven(vlIcmsSt + (item.vlIcmsSt ?? 0));
  }

  return {
    vlEsperado: halfEven(vlProd - vlDesc + vlFrt + vlSeg + vlOutro + vlIpi + vlIcmsSt),
    breakdown:  { vlProd, vlDesc, vlFrt, vlSeg, vlOutro, vlIpi, vlIcmsSt },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Validar uma única NF
// ─────────────────────────────────────────────────────────────────────────────

export function validarC100VsC170(
  c100:   C100,
  period: string,
  uf:     string,
): C100ValidationResult {

  const numDoc = c100.numDoc ?? '(sem número)';

  if (SITUACOES_CANCELADAS.has(c100.codSit)) {
    const { vlEsperado, breakdown } = calcularVlDocEsperado(c100.children.c170);
    return { numDoc, vlDoc: c100.vlDoc, vlEsperado, diferenca: 0, breakdown };
  }

  if (!c100.children.c170 || c100.children.c170.length === 0) {
    const empty: C170Breakdown = { vlProd:0, vlDesc:0, vlFrt:0, vlSeg:0, vlOutro:0, vlIpi:0, vlIcmsSt:0 };
    return {
      numDoc, vlDoc: c100.vlDoc, vlEsperado: 0, diferenca: c100.vlDoc,
      breakdown: empty,
      finding: {
        ruleId: 'C100-VL-DOC', severity: 'ALTO',
        situationType: 'ERRO_ESTRUTURAL', errorCode: 'C100-001',
        sourceSubblock: 'C100', period, uf,
        found: 0, expected: c100.vlDoc, difference: c100.vlDoc,
        description:    `NF ${numDoc}: C100 sem itens C170. Impossível reconciliar VL_DOC.`,
        correctionHint: 'Verificar se os registros C170 foram gerados pelo ERP para esta NF.',
        legalBasis:     'GP-317 Reg.C100/C170 · COTEPE-44 hierarquia obrigatória.',
      },
    };
  }

  const { vlEsperado, breakdown } = calcularVlDocEsperado(c100.children.c170);
  const diferenca = absDiff(c100.vlDoc, vlEsperado);

  if (diferenca <= TOLERANCE_BRL) {
    return { numDoc, vlDoc: c100.vlDoc, vlEsperado, diferenca, breakdown };
  }

  const severity = diferenca > 100 ? 'ALTO' : 'MÉDIO';

  const finding = makeFinding({
    ruleId: 'C100-VL-DOC', severity,
    situationType: 'INCONSISTENCIA_NUMERICA',
    errorCode: diferenca > 1000 ? 'C100-003' : 'C100-002',
    sourceSubblock: 'C100', period, uf,
    found:    c100.vlDoc,
    expected: vlEsperado,
    breakdown: {
      'VL_DOC declarado':  c100.vlDoc,
      'VL_PROD (C170)':    breakdown.vlProd,
      '(-) Desconto':      -breakdown.vlDesc,
      '(+) Frete':         breakdown.vlFrt,
      '(+) Seguro':        breakdown.vlSeg,
      '(+) Outros':        breakdown.vlOutro,
      '(+) IPI':           breakdown.vlIpi,
      '(+) ICMS-ST':       breakdown.vlIcmsSt,
      'VL_DOC esperado':   vlEsperado,
      'Diferenca':         diferenca,
    },
    description:    buildC100Description(numDoc, c100.vlDoc, vlEsperado, diferenca, breakdown),
    correctionHint: buildC100Hint(c100, vlEsperado, breakdown),
    legalBasis:     'GP-317 Reg.C100 campo VL_DOC · Ato COTEPE-44 Reg.C170.',
  });

  return { numDoc, vlDoc: c100.vlDoc, vlEsperado, diferenca, breakdown, finding };
}

// ─────────────────────────────────────────────────────────────────────────────
// Validar todas as NFs do arquivo
// ─────────────────────────────────────────────────────────────────────────────

export interface C100ValidatorOutput {
  findings:    Finding[];
  totalNfs:    number;
  totalErros:  number;
  totalDivBrl: number;
}

export function validarTodasC100(c100s: C100[], period: string, uf: string): C100ValidatorOutput {
  const findings: Finding[] = [];
  let totalErros = 0, totalDivBrl = 0;

  for (const c100 of c100s) {
    const result = validarC100VsC170(c100, period, uf);
    if (result.finding) {
      findings.push(result.finding);
      totalErros++;
      totalDivBrl = halfEven(totalDivBrl + (result.diferenca ?? 0));
    }
  }

  return { findings, totalNfs: c100s.length, totalErros, totalDivBrl: halfEven(totalDivBrl) };
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers de mensagem
// ─────────────────────────────────────────────────────────────────────────────

function buildC100Description(
  numDoc: string, vlDoc: number, esperado: number, diff: number, bd: C170Breakdown,
): string {
  return [
    `NF ${numDoc}:`,
    `VL_DOC declarado = R$ ${vlDoc.toFixed(2)}`,
    `VL_DOC esperado (C170) = R$ ${esperado.toFixed(2)}`,
    `  Prod R$ ${bd.vlProd.toFixed(2)} | Desc -R$ ${bd.vlDesc.toFixed(2)}`,
    `  Frt +R$ ${bd.vlFrt.toFixed(2)} | Seg +R$ ${bd.vlSeg.toFixed(2)}`,
    `  Out +R$ ${bd.vlOutro.toFixed(2)} | IPI +R$ ${bd.vlIpi.toFixed(2)}`,
    `  ST +R$ ${bd.vlIcmsSt.toFixed(2)}`,
    `Diferença: R$ ${diff.toFixed(2)}`,
  ].join(' | ');
}

function buildC100Hint(c100: C100, esperado: number, bd: C170Breakdown): string {
  // Ponto 5: usar os campos do próprio C100 como referência nos hints,
  // não vlDoc. Isso torna a mensagem semanticamente precisa.
  const diff = c100.vlDoc - esperado;

  if (diff > 0) {
    // VL_DOC maior que esperado — algum componente do cabeçalho não está nos itens
    if (c100.vlFrt > 0 && bd.vlFrt === 0) {
      return `VL_DOC > Σ C170 em R$ ${diff.toFixed(2)}. C100.VL_FRT = R$ ${c100.vlFrt.toFixed(2)} mas nenhum item C170 tem VL_FRT. Frete pode estar no cabeçalho sem ser espelhado nos itens.`;
    }
    if (c100.vlIcmsSt > 0 && bd.vlIcmsSt === 0) {
      return `VL_DOC > Σ C170 em R$ ${diff.toFixed(2)}. C100.VL_ICMS_ST = R$ ${c100.vlIcmsSt.toFixed(2)} mas nenhum item C170 tem VL_ICMS_ST. ST no cabeçalho sem rateio nos itens.`;
    }
    if (c100.vlSeg > 0 && bd.vlSeg === 0) {
      return `VL_DOC > Σ C170 em R$ ${diff.toFixed(2)}. C100.VL_SEG = R$ ${c100.vlSeg.toFixed(2)} sem correspondência nos itens C170.`;
    }
    return `VL_DOC > Σ C170 em R$ ${diff.toFixed(2)}. Verifique se frete, seguro, IPI ou ICMS-ST do cabeçalho estão refletidos nos itens C170.`;
  }

  // VL_DOC menor que esperado — componente faltando no cabeçalho
  if (bd.vlIpi > 0 && c100.vlIpi === 0) {
    return `VL_DOC < Σ C170 em R$ ${Math.abs(diff).toFixed(2)}. C100.VL_IPI = 0 mas itens somam IPI de R$ ${bd.vlIpi.toFixed(2)}. VL_DOC pode não estar incluindo o IPI total.`;
  }
  if (bd.vlIcmsSt > 0 && c100.vlIcmsSt === 0) {
    return `VL_DOC < Σ C170 em R$ ${Math.abs(diff).toFixed(2)}. C100.VL_ICMS_ST = 0 mas itens somam ST de R$ ${bd.vlIcmsSt.toFixed(2)}. VL_DOC pode não estar incluindo o ICMS-ST.`;
  }

  return `VL_DOC difere da soma dos componentes C170 em R$ ${Math.abs(diff).toFixed(2)}. Verificar configuração de geração do SPED no ERP.`;
}
