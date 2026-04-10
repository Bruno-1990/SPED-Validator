// ─────────────────────────────────────────────────────────────────────────────
// validators.spec.ts — Suite completa pós-revisão de 8 pontos
// ─────────────────────────────────────────────────────────────────────────────

import { reconciliarDebitos, reconciliarCreditos } from '../validators/apuration.reconciler';
import { validarTodasC100, validarC100VsC170, calcularVlDocEsperado } from '../validators/c100.validator';
import { halfEven, absDiff, dominantSubblock } from '../utils/reconciler.utils';
import type { SpedAST, C100, C170 } from '../types/sped.types';

// ─────────────────────────────────────────────────────────────────────────────
// Mini framework
// ─────────────────────────────────────────────────────────────────────────────
let passed = 0, failed = 0;

function test(name: string, fn: () => void) {
  try   { fn(); console.log(`  ✅  ${name}`); passed++; }
  catch (e: any) { console.error(`  ❌  ${name}\n       ${e.message}`); failed++; }
}

function expect(v: any) {
  return {
    toBe:          (e: any)    => { if (v !== e)         throw new Error(`Expected ${JSON.stringify(e)}, got ${JSON.stringify(v)}`) },
    toBeTruthy:    ()          => { if (!v)               throw new Error(`Expected truthy, got ${JSON.stringify(v)}`) },
    toBeFalsy:     ()          => { if (v)                throw new Error(`Expected falsy, got ${JSON.stringify(v)}`) },
    toHaveLength:  (n: number) => { if (v.length !== n)   throw new Error(`Expected length ${n}, got ${v.length}`) },
    toBeCloseTo:   (e: number, d = 2) => {
      const diff = Math.abs(v - e);
      if (diff >= Math.pow(10, -d) / 2) throw new Error(`Expected ~${e}, got ${v}`);
    },
    toBeGreaterThan: (n: number) => { if (!(v > n)) throw new Error(`Expected > ${n}, got ${v}`) },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────────────────────

const makeC190 = (cst: string, vl: number, emit: '0'|'1' = '0') =>
  ({ cstIcms: cst, cfop:'5102', aliqIcms:17, vlOpr:vl/0.17, vlBcIcms:vl/0.17,
     vlIcms: vl, indEmit: emit, period:'202403', uf:'ES' });

const makeD190 = (cst: string, vl: number, emit: '0'|'1' = '0', codSit='00', cfop='5353') =>
  ({ cstIcms: cst, cfop, aliqIcms:12, vlOpr:vl/0.12, vlBcIcms:vl/0.12,
     vlIcms: vl, indEmit: emit, codSit, period:'202403', uf:'ES' });

const makeD590 = (cst: string, vl: number) =>
  ({ cstIcms: cst, cfop:'5300', aliqIcms:25, vlOpr:vl/0.25, vlBcIcms:vl/0.25,
     vlIcms: vl, period:'202403', uf:'ES' });

const makeE110 = (vlTotDeb: number, vlTotCred: number) => ({
  period:'202403', uf:'ES',
  vlTotDebitos: vlTotDeb, vlAjDebitos:0, vlTotAjDebitos: vlTotDeb,
  vlEstornosCred:0, vlTotCreditos: vlTotCred, vlAjCreditos:0, vlTotAjCreditos: vlTotCred,
  vlEstornosDeb:0, vlSldCredorAnt:0,
  vlSldApurado: halfEven(vlTotDeb - vlTotCred),
  vlTotDed:0, vlIcmsRecolher: halfEven(Math.max(0, vlTotDeb - vlTotCred)),
  vlSldCredorTransp: halfEven(Math.max(0, vlTotCred - vlTotDeb)), debEsp:0,
  children: { e111:[], e116:[] },
});

const makeSped = (o: { c190?:any[]; d190?:any[]; d590?:any[]; e110?:any }): SpedAST => ({
  bloco0: { r0000: { dtIni:'01042024',dtFin:'30042024',nome:'Empresa',
                     cnpj:'00000000000191',uf:'ES',ie:'000',indPerfil:'A',indAtiv:'0' } },
  blocoC: { c100:[], c190: o.c190 ?? [] },
  blocoD: { d100:[], d190: o.d190 ?? [], d590: o.d590 ?? [] },
  blocoE: { e110: o.e110 ? [o.e110] : [] },
});

const makeC100 = (vlDoc: number, itens: Partial<C170>[], codSit='00'): C100 => ({
  indOper:'0', indEmit:'0', dtDoc:'01042024', codSit,
  vlDoc, vlDesc:0, vlMerc:vlDoc, vlFrt:0, vlSeg:0, vlOutro:0, vlIpi:0, vlIcmsSt:0,
  numDoc:`NF-${Math.random().toFixed(4)}`,
  children: {
    c170: itens.map((item,i) => ({
      numItem:i+1, codItem:`I${i}`, vlItem:0, vlDesc:0, vlFrt:0, vlSeg:0,
      vlOutro:0, vlIpi:0, vlIcmsSt:0, vlBcIcms:0, aliqIcms:17, vlIcms:0,
      cstIcms:'00', cfop:'5102', aliqIpi:0, vlBcIpi:0, ...item,
    } as C170)),
    c190:[],
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// SUITE 1 — RF001-DEB
// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== RF001-DEB: Reconciliação de Débitos ===\n');

test('TC-001 — fechado sem Bloco D', () => {
  const s = makeSped({ c190:[makeC190('00',5000)], e110:makeE110(5000,0) });
  expect(reconciliarDebitos(s,'202403','ES').findings).toHaveLength(0);
});

test('TC-002 — fechado com D190 (CT-e)', () => {
  const s = makeSped({ c190:[makeC190('00',5000)], d190:[makeD190('00',1000)], e110:makeE110(6000,0) });
  const { findings, breakdown } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(0);
  expect(breakdown.c190).toBeCloseTo(5000);
  expect(breakdown.d190).toBeCloseTo(1000);
  expect(breakdown.total).toBeCloseTo(6000);
});

test('TC-003 — fechado com D590 (comunicação)', () => {
  const s = makeSped({ c190:[makeC190('00',3000)], d590:[makeD590('00',500)], e110:makeE110(3500,0) });
  const { findings, breakdown } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(0);
  expect(breakdown.d590).toBeCloseTo(500);
});

test('TC-004 — diff R$0,005 dentro da tolerância', () => {
  const s = makeSped({ c190:[makeC190('00',10000.005)], e110:makeE110(10000.01,0) });
  expect(reconciliarDebitos(s,'202403','ES').findings).toHaveLength(0);
});

test('TC-005 — diff R$150 → ALTO', () => {
  const s = makeSped({ c190:[makeC190('00',50150)], e110:makeE110(50000,0) });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.severity).toBe('ALTO');
  expect(findings[0]!.errorCode).toBe('E110-DEB-002');
});

test('TC-006 — diff R$50.000 → CRÍTICO', () => {
  const s = makeSped({ c190:[makeC190('00',100000)], e110:makeE110(50000,0) });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.severity).toBe('CRÍTICO');
  expect(findings[0]!.errorCode).toBe('E110-DEB-003');
});

// Ponto 6: nome do teste alinhado com o comportamento real
test('TC-007 — E110.VL_TOT_DEBITOS=0 com C190 tributadas → CRÍTICO E110-DEB-003', () => {
  const s = makeSped({ c190:[makeC190('00',5000)], e110:makeE110(0,0) });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.severity).toBe('CRÍTICO');
  expect(findings[0]!.errorCode).toBe('E110-DEB-003');
});

test('TC-008 — E110 ausente com débitos calculados → CRÍTICO E110-DEB-004', () => {
  const s = makeSped({ c190:[makeC190('00',5000)] });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.errorCode).toBe('E110-DEB-004');
});

test('TC-009 — EX-D-004: CT-e cancelado excluído', () => {
  const s = makeSped({
    c190:[makeC190('00',5000)], d190:[makeD190('00',1000,'0','02')], e110:makeE110(5000,0),
  });
  const { findings, breakdown } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(0);
  expect(breakdown.d190).toBeCloseTo(0);
});

test('TC-010 — EX-D-002: subcontratação CFOP 5932 excluída', () => {
  const s = makeSped({
    c190:[makeC190('00',5000)], d190:[makeD190('00',800,'0','00','5932')], e110:makeE110(5000,0),
  });
  const { findings, breakdown } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(0);
  expect(breakdown.d190).toBeCloseTo(0);
});

test('TC-011 — D190 tomador não entra em débitos', () => {
  const s = makeSped({
    c190:[makeC190('00',5000)], d190:[makeD190('00',500,'1')], e110:makeE110(5000,0),
  });
  expect(reconciliarDebitos(s,'202403','ES').findings).toHaveLength(0);
});

// Ponto 1: sourceSubblock dominante
test('TC-012 — sourceSubblock=D190 quando D190 > C190', () => {
  const s = makeSped({
    c190:[makeC190('00',1000)],  // C190 menor
    d190:[makeD190('00',8000)],  // D190 maior
    e110:makeE110(8500,0),       // divergência de 500
  });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.sourceSubblock).toBe('D190');
});

test('TC-013 — sourceSubblock=C190 quando C190 > D190', () => {
  const s = makeSped({
    c190:[makeC190('00',8000)],  // C190 maior
    d190:[makeD190('00',1000)],  // D190 menor
    e110:makeE110(8500,0),       // divergência de 500
  });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.sourceSubblock).toBe('C190');
});

test('TC-014 — ALERTA FALTA_PARAMETRIZACAO com UF vazia', () => {
  const s = makeSped({ c190:[makeC190('00',5000)] });
  const { findings } = reconciliarDebitos(s,'','');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.situationType).toBe('FALTA_PARAMETRIZACAO');
  // Ponto 2: sourceSubblock deve ser E110, não C190
  expect(findings[0]!.sourceSubblock).toBe('E110');
});

test('TC-015 — breakdown presente com composição mista', () => {
  const s = makeSped({
    c190:[makeC190('00',5000)], d190:[makeD190('00',1000)], e110:makeE110(5500,0),
  });
  const { findings } = reconciliarDebitos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  const bd = findings[0]!.breakdown!;
  expect(bd['C190 mercadorias']).toBeCloseTo(5000);
  expect(bd['D190 transporte']).toBeCloseTo(1000);
});

// ─────────────────────────────────────────────────────────────────────────────
// SUITE 2 — RF002-CRE
// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== RF002-CRE: Reconciliação de Créditos ===\n');

test('TC-CRE-001 — fechado só com C190', () => {
  const s = makeSped({ c190:[makeC190('00',3000,'1')], e110:makeE110(0,3000) });
  expect(reconciliarCreditos(s,'202403','ES').findings).toHaveLength(0);
});

test('TC-CRE-002 — fechado com D190 tomador', () => {
  const s = makeSped({
    c190:[makeC190('00',3000,'1')], d190:[makeD190('00',500,'1')], e110:makeE110(0,3500),
  });
  const { findings, breakdown } = reconciliarCreditos(s,'202403','ES');
  expect(findings).toHaveLength(0);
  expect(breakdown.d190).toBeCloseTo(500);
});

test('TC-CRE-003 — D190 emitente não entra em créditos', () => {
  const s = makeSped({
    c190:[makeC190('00',3000,'1')], d190:[makeD190('00',500,'0')], e110:makeE110(0,3000),
  });
  expect(reconciliarCreditos(s,'202403','ES').findings).toHaveLength(0);
});

test('TC-CRE-004 — diff R$300 → ALTO', () => {
  const s = makeSped({ c190:[makeC190('00',3300,'1')], e110:makeE110(0,3000) });
  const { findings } = reconciliarCreditos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.severity).toBe('ALTO');
});

test('TC-CRE-005 — D190 cancelado excluído dos créditos (EX-D-004)', () => {
  const s = makeSped({
    c190:[makeC190('00',3000,'1')], d190:[makeD190('00',500,'1','02')], e110:makeE110(0,3000),
  });
  const { breakdown } = reconciliarCreditos(s,'202403','ES');
  expect(breakdown.d190).toBeCloseTo(0);
});

// Ponto 3: E110 ausente com créditos calculados → CRÍTICO
test('TC-CRE-006 — E110 ausente com créditos calculados → CRÍTICO E110-CRE-004', () => {
  const s = makeSped({ c190:[makeC190('00',3000,'1')] });
  const { findings } = reconciliarCreditos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.severity).toBe('CRÍTICO');
  expect(findings[0]!.errorCode).toBe('E110-CRE-004');
  expect(findings[0]!.situationType).toBe('ERRO_ESTRUTURAL');
});

// Ponto 3: E110 ausente sem créditos → silêncio (sem achado)
test('TC-CRE-007 — E110 ausente sem créditos → sem achado', () => {
  const s = makeSped({ c190:[] }); // nenhuma entrada com crédito
  const { findings } = reconciliarCreditos(s,'202403','ES');
  expect(findings).toHaveLength(0);
});

// Ponto 1: sourceSubblock dominante em créditos
test('TC-CRE-008 — sourceSubblock=D190 quando D190 > C190 nos créditos', () => {
  const s = makeSped({
    c190:[makeC190('00',500,'1')],
    d190:[makeD190('00',5000,'1')],
    e110:makeE110(0,4000),  // divergência
  });
  const { findings } = reconciliarCreditos(s,'202403','ES');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.sourceSubblock).toBe('D190');
});

// Ponto 2: ALERTA de parâmetro em crédito usa sourceSubblock E110
test('TC-CRE-009 — ALERTA FALTA_PARAMETRIZACAO com sourceSubblock=E110', () => {
  const s = makeSped({ c190:[makeC190('00',3000,'1')] });
  const { findings } = reconciliarCreditos(s,'','');
  expect(findings).toHaveLength(1);
  expect(findings[0]!.sourceSubblock).toBe('E110');
});

// ─────────────────────────────────────────────────────────────────────────────
// SUITE 3 — C100 vs C170
// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== C100-VL-DOC: Valor da NF vs Componentes C170 ===\n');

test('TC-C100-001 — NF fechada', () => {
  const c100 = makeC100(1170, [{ vlItem:1000, vlIcmsSt:170 }]);
  expect(validarC100VsC170(c100,'202403','ES').finding).toBeFalsy();
});

test('TC-C100-002 — IPI faltando no cabeçalho', () => {
  const c100 = makeC100(1000, [{ vlItem:1000, vlIpi:50 }]);
  const r = validarC100VsC170(c100,'202403','ES');
  expect(r.finding).toBeTruthy();
  expect(r.vlEsperado).toBeCloseTo(1050);
});

test('TC-C100-003 — ICMS-ST faltando → ALTO', () => {
  const c100 = makeC100(1000, [{ vlItem:1000, vlIcmsSt:200 }]);
  const r = validarC100VsC170(c100,'202403','ES');
  expect(r.finding).toBeTruthy();
  expect(r.finding!.severity).toBe('ALTO');
});

test('TC-C100-004 — desconto correto', () => {
  const c100 = makeC100(900, [{ vlItem:1000, vlDesc:100 }]);
  expect(validarC100VsC170(c100,'202403','ES').finding).toBeFalsy();
});

test('TC-C100-005 — NF cancelada sem erro', () => {
  const c100 = makeC100(1000, [{ vlItem:999 }], '02');
  expect(validarC100VsC170(c100,'202403','ES').finding).toBeFalsy();
});

test('TC-C100-006 — sem itens C170 → ERRO_ESTRUTURAL', () => {
  const r = validarC100VsC170(makeC100(1000,[]),'202403','ES');
  expect(r.finding!.situationType).toBe('ERRO_ESTRUTURAL');
  expect(r.finding!.errorCode).toBe('C100-001');
});

test('TC-C100-007 — diff R$0,01 dentro da tolerância', () => {
  const c100 = makeC100(1000.01, [{ vlItem:1000 }]);
  expect(validarC100VsC170(c100,'202403','ES').finding).toBeFalsy();
});

test('TC-C100-008 — múltiplos itens somados', () => {
  const c100 = makeC100(2500, [{ vlItem:1000,vlFrt:50 },{ vlItem:1200,vlSeg:50 },{ vlItem:200 }]);
  const r = validarC100VsC170(c100,'202403','ES');
  expect(r.finding).toBeFalsy();
  expect(r.vlEsperado).toBeCloseTo(2500);
});

test('TC-C100-009 — validarTodasC100 agrega erros', () => {
  const ok  = makeC100(1000, [{ vlItem:1000 }]);
  const err = makeC100(1000, [{ vlItem:1200 }]);
  const r = validarTodasC100([ok,err],'202403','ES');
  expect(r.totalNfs).toBe(2);
  expect(r.totalErros).toBe(1);
  expect(r.totalDivBrl).toBeCloseTo(200);
});

// Ponto 5: hint usa campos do C100, não vlDoc
test('TC-C100-010 — hint frete usa C100.VL_FRT, não VL_DOC', () => {
  // C100 com VL_FRT preenchido mas nenhum item tem VL_FRT → hint menciona C100.VL_FRT
  const c100: C100 = {
    ...makeC100(1050, [{ vlItem:1000 }]),
    vlFrt: 50,   // cabeçalho tem frete mas itens não
  };
  const r = validarC100VsC170(c100,'202403','ES');
  // VL_DOC esperado pelos itens = 1000; VL_DOC declarado = 1050
  // Hint deve mencionar C100.VL_FRT = 50
  expect(r.finding).toBeTruthy();
  const hint = r.finding!.correctionHint;
  expect(hint.includes('VL_FRT')).toBeTruthy();
  expect(hint.includes('50')).toBeTruthy();
  // Garantir que o hint NÃO usa vlDoc como valor de VL_FRT
  expect(hint.includes(`R$ ${c100.vlDoc.toFixed(2)}`)).toBeFalsy();
});

// ─────────────────────────────────────────────────────────────────────────────
// SUITE 4 — Utilitários
// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== Utilitários ===\n');

test('halfEven — 1.235 → 1.24', () => { expect(halfEven(1.235)).toBeCloseTo(1.24) });
test('halfEven — 1.5 → 2 (par)', () => { expect(halfEven(1.5,0)).toBe(2) });
test('halfEven — 2.5 → 2 (par, para baixo)', () => { expect(halfEven(2.5,0)).toBe(2) });
test('halfEven — 3.5 → 4 (par)', () => { expect(halfEven(3.5,0)).toBe(4) });
test('absDiff — iguais → zero', () => { expect(absDiff(100,100)).toBe(0) });
test('absDiff — diff 0.005 dentro de 0.01', () => { expect(absDiff(100.005,100) <= 0.01).toBeTruthy() });

// Ponto 1: dominantSubblock
test('dominantSubblock — retorna C190 quando maior', () => {
  expect(dominantSubblock({ c190:5000, d190:1000, d590:0 })).toBe('C190');
});
test('dominantSubblock — retorna D190 quando maior', () => {
  expect(dominantSubblock({ c190:1000, d190:5000, d590:0 })).toBe('D190');
});
test('dominantSubblock — retorna D590 quando maior', () => {
  expect(dominantSubblock({ c190:100, d190:200, d590:500 })).toBe('D590');
});
test('dominantSubblock — retorna C190 quando todos zero', () => {
  expect(dominantSubblock({ c190:0, d190:0, d590:0 })).toBe('C190');
});

// ─────────────────────────────────────────────────────────────────────────────
console.log(`\n${'─'.repeat(62)}`);
console.log(`Resultado: ${passed} passaram  |  ${failed} falharam`);
if (failed > 0) process.exit(1);
