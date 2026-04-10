// ─────────────────────────────────────────────────────────────────────────────
// apuration.reconciler.ts
//
// RF001-DEB  Reconciliação (C190 + D190 + D590) → E110.VL_TOT_DEBITOS
// RF002-CRE  Reconciliação (C190 + D190)        → E110.VL_TOT_CREDITOS
//
// Base legal: GP-317 Reg.E110 · LC-87 art.12/20 · Ato COTEPE-44 Reg.D190
// ─────────────────────────────────────────────────────────────────────────────

import type { SpedAST, Finding } from '../types/sped.types';
import {
  halfEven, absDiff, tolerance, classifyDiffSeverity,
  makeFinding, makeParamAlert, dominantSubblock,
  isCstDebitoC190, isCstCreditoC190,
  isCstDebitoD190, isCstCreditoD190,
  isCstDebitoD590,
} from '../utils/reconciler.utils';

// ─────────────────────────────────────────────────────────────────────────────
// Tipos internos
// ─────────────────────────────────────────────────────────────────────────────

export interface DebitsBreakdown  { c190: number; d190: number; d590: number; total: number }
export interface CreditsBreakdown { c190: number; d190: number; total: number }

export interface ReconcileDebitsResult  { findings: Finding[]; breakdown: DebitsBreakdown }
export interface ReconcileCreditsResult { findings: Finding[]; breakdown: CreditsBreakdown }

// ─────────────────────────────────────────────────────────────────────────────
// Exceções do Bloco D — PRD v3 §2.6
// ─────────────────────────────────────────────────────────────────────────────

/** EX-D-004: CT-e cancelado não entra na apuração */
function isDocumentoCancelado(codSit: string): boolean {
  return codSit === '02';
}

/**
 * EX-D-002: CT-e de subcontratação (CFOP 5932/6932).
 * O ICMS já foi recolhido pelo transportador contratante; o subcontratado
 * não gera débito próprio. Aplicado APENAS em débitos (IND_EMIT = '0').
 *
 * Por que não existe equivalente em créditos?
 * O tomador que recebe um CT-e de subcontratação (entrada, IND_EMIT = '1')
 * pode ou não ter direito a crédito dependendo do seu regime e do CFOP.
 * Para não gerar falso positivo, mantemos a exceção somente no lado do
 * prestador (débito). O lado do tomador será tratado quando RF002 for
 * revisado com tabela de CFOP × crédito admissível.
 */
function isSubcontratacao(cfop: string): boolean {
  return cfop === '5932' || cfop === '6932';
}

// ─────────────────────────────────────────────────────────────────────────────
// RF001-DEB
// ─────────────────────────────────────────────────────────────────────────────

export function reconciliarDebitos(
  sped:   SpedAST,
  period: string,
  uf:     string,
): ReconcileDebitsResult {

  // Pré-condição: sem uf/period, parametrização ausente
  // sourceSubblock = 'E110' porque é a regra de apuração do E110 que está bloqueada
  if (!uf || !period) {
    return {
      findings: [makeParamAlert(
        'RF001-DEB', period, uf, 'E110-DEB-000',
        `Tabela CST não carregada para UF=${uf} / período=${period}. Validação de débitos desabilitada.`,
        'E110',
      )],
      breakdown: { c190: 0, d190: 0, d590: 0, total: 0 },
    };
  }

  // ── Etapa 1a: débitos C190 (mercadorias) ─────────────────────────────────
  let deb_c190 = 0;
  for (const c190 of sped.blocoC.c190) {
    if (c190.period === period && c190.uf === uf &&
        c190.indEmit === '0' && isCstDebitoC190(c190.cstIcms)) {
      deb_c190 = halfEven(deb_c190 + c190.vlIcms);
    }
  }

  // ── Etapa 1b: débitos D190 (transporte — CT-e) ───────────────────────────
  let deb_d190 = 0;
  for (const d190 of sped.blocoD.d190) {
    if (d190.period === period && d190.uf === uf &&
        d190.indEmit === '0' &&
        !isDocumentoCancelado(d190.codSit) &&
        !isSubcontratacao(d190.cfop) &&
        isCstDebitoD190(d190.cstIcms)) {
      deb_d190 = halfEven(deb_d190 + d190.vlIcms);
    }
  }

  // ── Etapa 1c: débitos D590 (comunicação — NFSC) ──────────────────────────
  let deb_d590 = 0;
  for (const d590 of sped.blocoD.d590) {
    if (d590.period === period && d590.uf === uf &&
        isCstDebitoD590(d590.cstIcms)) {
      deb_d590 = halfEven(deb_d590 + d590.vlIcms);
    }
  }

  const debitos_total = halfEven(deb_c190 + deb_d190 + deb_d590);
  const breakdown: DebitsBreakdown = {
    c190:  halfEven(deb_c190),
    d190:  halfEven(deb_d190),
    d590:  halfEven(deb_d590),
    total: debitos_total,
  };

  // ── Etapa 2: obter E110 ──────────────────────────────────────────────────
  const e110 = sped.blocoE.e110.find(e => e.period === period && e.uf === uf);

  if (!e110) {
    if (debitos_total > 0) {
      return {
        findings: [{
          ruleId:        'RF001-DEB',
          severity:      'CRÍTICO',
          situationType: 'ERRO_ESTRUTURAL',
          errorCode:     'E110-DEB-004',
          // Ponto 1: subbloco dominante reflete de onde veio o valor calculado
          sourceSubblock: dominantSubblock(breakdown),
          period, uf,
          found:         debitos_total,
          expected:      0,
          difference:    debitos_total,
          breakdown:     breakdown as unknown as Record<string, number>,
          description:   `E110 ausente para período ${period} / UF ${uf}, mas há débitos calculados (R$ ${debitos_total.toFixed(2)}).`,
          correctionHint:'Verificar se o Bloco E foi gerado pelo ERP. Possível arquivo incompleto.',
          legalBasis:    'GP-317 Reg.E110 — registro obrigatório quando há operações tributadas.',
        }],
        breakdown,
      };
    }
    return { findings: [], breakdown };
  }

  // ── Etapa 3: comparar com tolerância ────────────────────────────────────
  const declarado = e110.vlTotDebitos;
  const diferenca = absDiff(debitos_total, declarado);
  const tol       = tolerance(declarado);

  if (diferenca <= tol) return { findings: [], breakdown };

  // Caso especial: declarado = 0 com débitos calculados → sempre CRÍTICO
  const severity = (declarado === 0 && debitos_total > 0)
    ? 'CRÍTICO'
    : classifyDiffSeverity(diferenca);

  const codeMap: Record<string, string> = {
    MÉDIO:   'E110-DEB-001',
    ALTO:    'E110-DEB-002',
    CRÍTICO: 'E110-DEB-003',
  };

  return {
    findings: [makeFinding({
      ruleId:        'RF001-DEB',
      severity,
      situationType: 'INCONSISTENCIA_NUMERICA',
      errorCode:     codeMap[severity]!,
      // Ponto 1: sourceSubblock = componente que mais pesou no total calculado
      sourceSubblock: dominantSubblock(breakdown),
      period, uf,
      found:    debitos_total,
      expected: declarado,
      breakdown: {
        'C190 mercadorias': deb_c190,
        'D190 transporte':  deb_d190,
        'D590 comunicacao': deb_d590,
        'Total calculado':  debitos_total,
        'E110 declarado':   declarado,
        'Diferenca':        diferenca,
      },
      description:    buildDebitDescription(breakdown, declarado, diferenca, severity),
      correctionHint: buildDebitHint(breakdown, declarado),
      legalBasis:     'GP-317 Reg.E110 campo VL_TOT_DEBITOS · LC-87 art.12 · COTEPE-44 Reg.D190.',
    })],
    breakdown,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// RF002-CRE
// ─────────────────────────────────────────────────────────────────────────────

export function reconciliarCreditos(
  sped:   SpedAST,
  period: string,
  uf:     string,
): ReconcileCreditsResult {

  if (!uf || !period) {
    return {
      findings: [makeParamAlert(
        'RF002-CRE', period, uf, 'E110-CRE-000',
        `Tabela CST não carregada para UF=${uf} / período=${period}. Validação de créditos desabilitada.`,
        'E110',
      )],
      breakdown: { c190: 0, d190: 0, total: 0 },
    };
  }

  // ── Etapa 1a: créditos C190 (entradas de mercadorias) ───────────────────
  let cre_c190 = 0;
  for (const c190 of sped.blocoC.c190) {
    if (c190.period === period && c190.uf === uf &&
        c190.indEmit === '1' && isCstCreditoC190(c190.cstIcms)) {
      cre_c190 = halfEven(cre_c190 + c190.vlIcms);
    }
  }

  // ── Etapa 1b: créditos D190 (tomador de transporte) ─────────────────────
  // IND_EMIT = '1': contribuinte é o tomador; recebe CT-e de terceiro.
  //
  // Nota sobre subcontratação em créditos (EX-D-002 parcial):
  // A exceção de subcontratação (CFOP 5932/6932) NÃO está sendo aplicada aqui
  // porque no lado do tomador (entrada) o direito ao crédito depende do regime
  // tributário e do CFOP — não é uma exclusão automática. Isso será tratado
  // quando RF002 for refinado com tabela de CFOP × crédito admissível no SQLite.
  let cre_d190 = 0;
  for (const d190 of sped.blocoD.d190) {
    if (d190.period === period && d190.uf === uf &&
        d190.indEmit === '1' &&
        !isDocumentoCancelado(d190.codSit) &&
        isCstCreditoD190(d190.cstIcms)) {
      cre_d190 = halfEven(cre_d190 + d190.vlIcms);
    }
  }

  const creditos_total = halfEven(cre_c190 + cre_d190);
  const breakdown: CreditsBreakdown = {
    c190:  halfEven(cre_c190),
    d190:  halfEven(cre_d190),
    total: creditos_total,
  };

  // ── Etapa 2: obter E110 ──────────────────────────────────────────────────
  const e110 = sped.blocoE.e110.find(e => e.period === period && e.uf === uf);

  // Ponto 3: ausência de E110 com créditos calculados = mesmo tratamento que RF001-DEB
  if (!e110) {
    if (creditos_total > 0) {
      return {
        findings: [{
          ruleId:        'RF002-CRE',
          severity:      'CRÍTICO',
          situationType: 'ERRO_ESTRUTURAL',
          errorCode:     'E110-CRE-004',
          sourceSubblock: cre_d190 > cre_c190 ? 'D190' : 'C190',
          period, uf,
          found:         creditos_total,
          expected:      0,
          difference:    creditos_total,
          breakdown:     breakdown as unknown as Record<string, number>,
          description:   `E110 ausente para período ${period} / UF ${uf}, mas há créditos calculados (R$ ${creditos_total.toFixed(2)}).`,
          correctionHint:'Verificar se o Bloco E foi gerado pelo ERP. Créditos escriturados sem registro de apuração.',
          legalBasis:    'GP-317 Reg.E110 — registro obrigatório quando há operações com crédito.',
        }],
        breakdown,
      };
    }
    return { findings: [], breakdown };
  }

  // ── Etapa 3: comparar ────────────────────────────────────────────────────
  const declarado = e110.vlTotCreditos;
  const diferenca = absDiff(creditos_total, declarado);
  const tol       = tolerance(declarado);

  if (diferenca <= tol) return { findings: [], breakdown };

  const severity = classifyDiffSeverity(diferenca);
  const codeMap: Record<string, string> = {
    MÉDIO:   'E110-CRE-001',
    ALTO:    'E110-CRE-002',
    CRÍTICO: 'E110-CRE-003',
  };

  return {
    findings: [makeFinding({
      ruleId:        'RF002-CRE',
      severity,
      situationType: 'INCONSISTENCIA_NUMERICA',
      errorCode:     codeMap[severity]!,
      // Ponto 1: sourceSubblock = maior componente dos créditos
      sourceSubblock: cre_d190 > cre_c190 ? 'D190' : 'C190',
      period, uf,
      found:    creditos_total,
      expected: declarado,
      breakdown: {
        'C190 mercadorias': cre_c190,
        'D190 transporte':  cre_d190,
        'Total calculado':  creditos_total,
        'E110 declarado':   declarado,
        'Diferenca':        diferenca,
      },
      description:    `Créditos ICMS (C190+D190): R$ ${creditos_total.toFixed(2)} | E110.VL_TOT_CREDITOS: R$ ${declarado.toFixed(2)} | Diferença: R$ ${diferenca.toFixed(2)} [${severity}].`,
      correctionHint: cre_d190 > 0
        ? `D190 (CT-e tomador) contribuiu com R$ ${cre_d190.toFixed(2)} dos créditos. Verifique se todos os CT-e do período estão escriturados no Bloco D.`
        : 'Verifique notas de entrada com CST 00/20/90 no período.',
      legalBasis:     'GP-317 Reg.E110 campo VL_TOT_CREDITOS · LC-87 art.20 · COTEPE-44 Reg.D190.',
    })],
    breakdown,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers de mensagem
// ─────────────────────────────────────────────────────────────────────────────

function buildDebitDescription(
  bd:       DebitsBreakdown,
  declared: number,
  diff:     number,
  severity: string,
): string {
  const parts = [`Débitos ICMS calculados: R$ ${bd.total.toFixed(2)}`,
                 `  C190 mercadorias: R$ ${bd.c190.toFixed(2)}`];
  if (bd.d190 > 0) parts.push(`  D190 transporte:   R$ ${bd.d190.toFixed(2)}`);
  if (bd.d590 > 0) parts.push(`  D590 comunicação:  R$ ${bd.d590.toFixed(2)}`);
  parts.push(
    `E110.VL_TOT_DEBITOS declarado: R$ ${declared.toFixed(2)}`,
    `Diferença: R$ ${diff.toFixed(2)} [${severity}]`,
  );
  return parts.join(' | ');
}

function buildDebitHint(bd: DebitsBreakdown, declared: number): string {
  if (bd.d190 === 0 && bd.d590 === 0) {
    return bd.total > declared
      ? 'Total calculado > declarado: verifique NFs de saída com CST 00/10/20 não consolidadas no E110.'
      : 'Total calculado < declarado: verifique débitos em E110 sem correspondência em C190.';
  }
  return `CT-e/D190 contribuiu com R$ ${bd.d190.toFixed(2)} nos débitos. Se a divergência é nova, verifique: CT-e cancelado incluído; subcontratação CFOP 5932/6932 não excluída; IE divergente.`;
}
