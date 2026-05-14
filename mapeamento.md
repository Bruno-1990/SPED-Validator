# Mapeamento de Campos — XML NF-e ↔ SPED EFD ICMS/IPI

> Documento operacional: descreve **como o sistema atual** extrai cada campo do XML
> da NF-e (mod. 55/65), em qual registro/campo do SPED ele é confrontado, qual
> normalização é aplicada e qual regra de cruzamento dispara a divergência.
>
> Fonte: implementação real em `src/services/xml_service.py`,
> `src/services/cross_engine.py`, `src/services/cross_engine_models.py`,
> `src/services/field_comparator.py`, `src/validators/tolerance.py` e
> `data/reference/mapeamento_cbenef_xml_sped.yaml`.
>
> Versão: 1.0 — 2026-05-07

---

## 1. Princípios aplicados pelo motor

1. **Ausente ≠ zero.** O parser (`xml_service.parse_nfe_xml`) preserva o valor
   bruto e marca `status` (`ok` | `missing` | `explicit_zero` | `parse_error`)
   em `_tracked` para cada campo monetário crítico. Comparações monetárias
   (`FieldComparator._monetary`) tratam `None`/`""` como ausente e divergem
   contra valor presente do outro lado.
2. **Rastreabilidade.** Cada campo monetário relevante carrega
   `raw_value`, `source_xpath` e `status` em `parsed["_tracked"]` /
   `item["_tracked"]`. Esses campos alimentam a UI de cards de divergência.
3. **Comparação tipada.** O `FieldComparator` usa um dos seis tipos
   (`EXACT`, `MONETARY`, `PERCENTAGE`, `DATE`, `CST_AWARE`, `DERIVED`)
   conforme a natureza do campo.
4. **Tolerância proporcional** (BUG-005, `validators/tolerance.py`). Para
   `MONETARY` a tolerância é o menor entre absoluto e relativo da faixa:

   | Faixa do valor      | Tolerância absoluta | Tolerância relativa |
   |---------------------|---------------------|---------------------|
   | até R$ 100          | 0,02                | 0,02 %              |
   | R$ 100 – 10.000     | 0,05                | 0,01 %              |
   | R$ 10.000 – 500.000 | 0,10                | 0,005 %             |
   | acima de R$ 500.000 | 0,50                | 0,001 %             |

   Para C190/consolidação usa-se `max(0,10; tol_proporcional(maior))`.
5. **Período do SPED.** XMLs fora do `0000.DT_INI..DT_FIN` são marcados como
   `fora_periodo`. Até **1 mês antes** de `DT_INI` é aceito automaticamente;
   2+ meses antes ou qualquer mês após exige confirmação do usuário
   (`xml_service._classificar_periodo`).
6. **Modelos elegíveis para cruzamento:** apenas COD_MOD `55` e `65`
   (`XML_ELIGIBLE_MODELS`).

---

## 2. Normalizações padrão

| Função                   | Regra aplicada                                            |
|--------------------------|------------------------------------------------------------|
| `_norm_chave(s)`         | mantém só dígitos                                          |
| `_norm_cnpj(s)`          | só dígitos, `zfill(14)`                                    |
| `_norm_cfop(s)`          | só dígitos, primeiros 4                                    |
| `_norm_cst(s)`           | se 2 dígitos → `zfill(3)` (junção `orig+CST/CSOSN`)        |
| `_norm_ncm(s)`           | só dígitos, primeiros 8                                    |
| `_norm_date_iso(s)`      | ISO `dhEmi` → `DDMMAAAA` (formato SPED)                    |
| `_to_float(v)`           | troca `,` por `.`, `round(2)`, fallback `0.0`              |
| `_track_status(raw)`     | `missing` / `explicit_zero` / `ok` / `parse_error`         |

CST de saída do XML é sempre `orig (1 dígito) + CST/CSOSN`. Para regime SN,
quando há `CSOSN`, é usado `orig+CSOSN`; para regime normal, `orig+CST`.

---

## 3. Cabeçalho — XML × Registro **C100**

| Campo lógico        | XPath (XML NF-e)                          | SPED                | Normalização          | Tipo comparação | Regra (rule_id)                | Severidade |
|---------------------|-------------------------------------------|---------------------|-----------------------|-----------------|--------------------------------|-----------|
| `chave_nfe`         | `infNFe/@Id` (sem prefixo `NFe`) ou fallback `protNFe/infProt/chNFe` | `C100.CHV_NFE` | `digits_only`        | EXACT           | XML001 / XC001, XML002 / XC002 | crítica / erro |
| `numero_nfe`        | `infNFe/ide/nNF`                          | `C100.NUM_DOC`      | trim                  | EXACT           | (apenas para mensagens)        | —         |
| `serie`             | `infNFe/ide/serie`                        | `C100.SER`          | trim                  | EXACT           | —                              | —         |
| `dh_emissao`        | `infNFe/ide/dhEmi`                        | `C100.DT_DOC`       | ISO → `DDMMAAAA`      | DATE            | XML014 / XC016                 | erro      |
| `dh_saida_entrada`  | `infNFe/ide/dhSaiEnt`                     | `C100.DT_E_S`       | ISO → `DDMMAAAA`      | DATE            | XML015 / XC017                 | warning   |
| `cnpj_emitente`     | `infNFe/emit/CNPJ`                        | `0150.CNPJ` (via `C100.COD_PART` quando `IND_EMIT=1`) | `digits_only`+`zfill(14)` | EXACT | XML013 / XC012, XC013 (UF) | erro      |
| `cnpj_destinatario` | `infNFe/dest/CNPJ`                        | `0150.CNPJ` (via `C100.COD_PART` quando `IND_EMIT=0`) | mesmo que acima           | EXACT | XML013 / XC012             | erro      |
| `crt_emitente`      | `infNFe/emit/CRT`                         | (deriva regime)     | trim                  | DERIVED         | usado por `_cst_aware`         | —         |
| `uf_emitente`       | `infNFe/emit/enderEmit/UF`                | `0150.UF` (parte)   | trim                  | EXACT           | XC013                          | erro      |
| `prot_cstat`        | `protNFe/infProt/cStat`                   | `C100.COD_SIT`      | trim                  | DERIVED         | XC008/XC008b + variantes (ver §4) | crítica |

### 3.1 Totais — `infNFe/total/ICMSTot/*` × `C100.*`

Campos extraídos para `result["totais"]` e versões `vl_*` espelhadas em
`nfe_xmls`. Tolerância sempre **proporcional** (não fixa em 0,02).

| Tag XML              | XPath                                          | SPED `C100.*`     | Tipo       | Regra (rule_id)        | Severidade |
|----------------------|------------------------------------------------|-------------------|------------|------------------------|-----------|
| `vNF`                | `.//infNFe/total/ICMSTot/vNF`                  | `VL_DOC`          | MONETARY   | XML003 / XC003 / XC014 | crítica   |
| `vBC`                | `.//infNFe/total/ICMSTot/vBC`                  | `VL_BC_ICMS`      | MONETARY   | (cobertura indireta via C170/C190) | — |
| `vICMS`              | `.//infNFe/total/ICMSTot/vICMS`                | `VL_ICMS`         | MONETARY   | XML004 / XC004 / XC016 | crítica   |
| `vICMSDeson`         | `.//infNFe/total/ICMSTot/vICMSDeson`           | `C197.VL_ICMS` / `E111` (ajuste) | MONETARY | XC093 (indício)        | warning   |
| `vBCST`              | `.//infNFe/total/ICMSTot/vBCST`                | `VL_BC_ICMS_ST`   | MONETARY   | (via C190)             | —         |
| `vST`                | `.//infNFe/total/ICMSTot/vST`                  | `VL_ICMS_ST`      | MONETARY   | XML005 / XC005         | erro      |
| `vProd`              | `.//infNFe/total/ICMSTot/vProd`                | `VL_MERC`         | MONETARY   | XC015 / XML013-legacy  | erro      |
| `vFrete`             | `.//infNFe/total/ICMSTot/vFrete`               | `VL_FRT`          | MONETARY   | XC023d                 | erro      |
| `vSeg`               | `.//infNFe/total/ICMSTot/vSeg`                 | `VL_SEG`          | MONETARY   | XC023e                 | erro      |
| `vDesc`              | `.//infNFe/total/ICMSTot/vDesc`                | `VL_DESC`         | MONETARY   | (via C170)             | —         |
| `vOutro`             | `.//infNFe/total/ICMSTot/vOutro`               | `VL_OUT_DA`       | MONETARY   | XC023f                 | erro      |
| `vIPI`               | `.//infNFe/total/ICMSTot/vIPI`                 | `VL_IPI`          | MONETARY   | XML006 / XC006 / XC017 | erro      |
| `vIPIDevol`          | `.//infNFe/total/ICMSTot/vIPIDevol`            | (sem espelho direto; vai a ajustes) | MONETARY | —             | —         |
| `vPIS`               | `.//infNFe/total/ICMSTot/vPIS`                 | `VL_PIS`          | MONETARY   | (via C170 — XC029)     | erro      |
| `vCOFINS`            | `.//infNFe/total/ICMSTot/vCOFINS`              | `VL_COFINS`       | MONETARY   | (via C170 — XC030)     | erro      |
| `vFCP` / `vFCPST`    | `.//infNFe/total/ICMSTot/vFCP[ST]`             | (FCP em C197/E111 quando exigido) | MONETARY | —              | —         |
| `vICMSUFDest` / `vICMSUFRemet` | idem                                | DIFAL → C101/C197 conforme UF      | MONETARY | —              | —         |
| `vII`                | `.//infNFe/total/ICMSTot/vII`                  | importação → C120 | MONETARY   | XC080 (ausência de C120) | warning |
| `qtd_itens`          | `count(infNFe/det)`                            | `count(C170)` filhos do C100 | EXACT (com Exceção 2 do Guia EFD v3.2.2) | XML012 / XC014 | erro |

> **Guia Prático EFD v3.2.2, Exceção 2 do C100:** NF-e de emissão própria
> (`COD_MOD=55`, `IND_EMIT=0`) sem C176/C177/C180/C181 dispensa C170 — nesses
> casos a regra XML012 não dispara mesmo com `count(C170)=0`.

---

## 4. Situação documental — `cStat` (XML) → `COD_SIT` (SPED)

`xml_service._CSTAT_TO_COD_SIT` (mapa hard-coded) + variantes que disparam
findings críticos quando há incoerência entre status SEFAZ e escrituração.

| `cStat` (XML)   | `COD_SIT` esperado | Significado              |
|-----------------|--------------------|--------------------------|
| `100`           | `00`               | Autorizada → Normal      |
| `101`           | `02`               | Cancelada                |
| `135`           | `02`               | Cancelada fora prazo     |
| `110`           | `05`               | Denegada                 |
| `301`           | `05`               | Uso indevido / Denegada  |

Variantes de finding:

| Situação real | rule_id (legacy / motor XC) | Severidade |
|--------------|------------------------------|-----------|
| `cStat=101/135` mas `COD_SIT=00` | `NF_CANCELADA_ESCRITURADA` (legacy XML011) | crítica |
| `cStat=110/301` mas `COD_SIT=00` | `NF_DENEGADA_ESCRITURADA`                  | crítica |
| `cStat=100` mas `COD_SIT in (02,03)` | `NF_ATIVA_ESCRITURADA_CANCELADA` / `XC008` | crítica |
| `cStat=100` mas `COD_SIT in (04,05)` | `NF_ATIVA_ESCRITURADA_DENEGADA` / `XC008b` | crítica |
| Outras combinações inválidas        | `COD_SIT_DIVERGENTE_XML`                    | erro    |

> Para `COD_SIT in {02,03,04,05}` o motor **interrompe** comparações monetárias
> daquele C100 (a causa raiz é o status; valores zerados são esperados pelo
> Guia Prático). Evita falsos positivos em VL_DOC/VL_ICMS.

---

## 5. Itens — XML `det/*` × Registro **C170**

Pareamento por `nItem` ↔ `NUM_ITEM` (preferencial). Estados possíveis em
`ItemMatchState`: `MATCH_EXATO`, `MATCH_PROVAVEL`, `MATCH_HEURISTICO`,
`AMBIGUO`, `SEM_MATCH`. Quando ambíguo (`XC019b`) demais regras do par são
suprimidas para evitar cascata de falsos positivos.

### 5.1 Identificação do item

| Campo lógico | XPath / origem | SPED | Normalização | Tipo | rule_id | Severidade |
|--------------|----------------|------|---------------|------|---------|-----------|
| `num_item`   | `det/@nItem`   | `C170.NUM_ITEM` | int | EXACT (chave de pareamento) | XC018 (item XML sem C170), XC019 (C170 sem item XML) | erro |
| `cod_produto`| `det/prod/cProd` | `C170.COD_ITEM` ↔ `0200.COD_ITEM` | trim | EXACT | (via 0200) | — |
| `desc_produto` | `det/prod/xProd` | `0200.DESCR_ITEM` | trim | EXACT | (via 0200) | — |
| `ncm`        | `det/prod/NCM` | `0200.COD_NCM` (e/ou `C170` lógico) | `digits_only`, 8 dígitos | EXACT | XC022 / XML010-legacy | erro |
| `cfop`       | `det/prod/CFOP`| `C170.CFOP`     | `digits_only`, 4 dígitos | EXACT | XC021 / XML009-legacy | erro |

### 5.2 Quantidades / valores do item

| Campo XML       | XPath                       | SPED              | Tipo     | rule_id  | Severidade |
|-----------------|-----------------------------|-------------------|----------|----------|-----------|
| `qCom`          | `det/prod/qCom`             | `C170.QTD`        | MONETARY | XC023b   | erro      |
| `vProd`         | `det/prod/vProd`            | `C170.VL_ITEM`    | MONETARY | XC023 / XML011-legacy | erro |
| `vDesc`         | `det/prod/vDesc`            | `C170.VL_DESC`    | MONETARY | XC023c   | erro      |
| `vFrete` (item) | `det/prod/vFrete`           | (rateado em VL_OUT_DA conforme parametrização ERP) | MONETARY | — | — |

### 5.3 ICMS do item — `det/imposto/ICMS/*`

O grupo é dinâmico (`ICMS00`, `ICMS10`, …, `ICMSSN101`, …). O parser pega o
**primeiro filho** de `<ICMS>` e extrai os campos abaixo. O grupo (ex.
`ICMSSN102`) é mapeado para o CST equivalente em `CST_FROM_XML_GROUP`.

| Campo XML       | XPath                                           | SPED                  | Tipo            | rule_id (motor) | Severidade |
|-----------------|--------------------------------------------------|-----------------------|-----------------|------------------|-----------|
| `orig + CST`    | `.../ICMS/*/orig` + `.../ICMS/*/CST`             | `C170.CST_ICMS` (3 dígitos) | CST_AWARE | XC020 / XML007-legacy | erro |
| `orig + CSOSN`  | `.../ICMS/*/orig` + `.../ICMS/*/CSOSN`           | `C170.CST_ICMS` (via `CSOSN_TO_CST`) | CST_AWARE | XC020, XC031 (CSOSN em regime normal), XC032 (CST normal em regime SN) | erro/crítica |
| `vBC`           | `.../ICMS/*/vBC`                                 | `C170.VL_BC_ICMS`     | MONETARY        | XC024 (divergência) / XC024b (BC indevida em CST sem tributação) | erro |
| `pICMS`         | `.../ICMS/*/pICMS`                               | `C170.ALIQ_ICMS`      | PERCENTAGE      | XC025 / XC025b   | erro      |
| `vICMS`         | `.../ICMS/*/vICMS`                               | `C170.VL_ICMS`        | MONETARY        | XC026 / XC026b (ICMS indevido em CST sem tributação) | erro |
| `vBCST`         | `.../ICMS/*/vBCST`                               | `C170.VL_BC_ICMS_ST`  | MONETARY        | (via C190)       | —         |
| `pICMSST`/`pST` | `.../ICMS/*/pICMSST` ou `.../ICMS/*/pST`         | `C170.ALIQ_ST`        | PERCENTAGE      | (via C190)       | —         |
| `vICMSST` / `vICMSSTRet` | `.../ICMS/*/vICMSST` ou `.../ICMS/*/vICMSSTRet` | `C170.VL_ICMS_ST` | MONETARY      | (via C190)       | —         |
| `cBenef`        | `.../ICMS/*/cBenef`                              | `C197.COD_AJ` / `E111.COD_AJ_APUR` / `E115.COD_INF_ADIC` | EXACT (cadeia) | BENEF_XML_SEM_E115, BENEF_XML_SEM_C197, BENEF_E115_SEM_XML, BENEF_TRILHA_INCOMPLETA | warning/crítica |
| `vICMSDeson`    | `.../ICMS/*/vICMSDeson`                          | `C197.VL_ICMS` (ou `VL_OUTROS`) e/ou `E111.VL_AJ_APUR` | MONETARY | XC093 (vICMSDeson sem ajuste apuração) | warning |
| `motDesICMS`    | `.../ICMS/*/motDesICMS`                          | `E115.DESCR_COMPL_AJ` (descritivo) | EXACT | (informacional) | —      |

#### Grupos sem campo de cálculo ICMS (`GRUPOS_SEM_BC_ICMS`)

`ICMS40`, `ICMS41`, `ICMS50`, `ICMSST`, `ICMSSN102`, `ICMSSN103`,
`ICMSSN300`, `ICMSSN400`. Para esses, ter `VL_BC_ICMS`, `ALIQ_ICMS` ou
`VL_ICMS` no C170 dispara a **variante "indevida"** (`XC024b`/`XC025b`/`XC026b`).

#### Mapa CSOSN → CST aplicado pelo `_cst_aware` (Res. CGSN 140/2018)

| CSOSN | CST equivalente | Observação |
|-------|------------------|-----------|
| 101   | 00 | Tributada com permissão de crédito |
| 102   | 20 | Tributada com redução de BC |
| 103   | 40 | Isenta — sem tributação |
| 201   | 10 | Com ST + débito próprio |
| 202   | 10 | Com ST sem tributação própria |
| 203   | 30 | ST sem débito próprio |
| 300   | 41 | Imune |
| 400   | 40 | Não tributada pelo SN |
| 500   | 60 | ST já retida anteriormente |
| 900   | 90 | Outros |

A detecção de regime SN segue `crt_emitente in (1,2)` **ou** XML traz CSOSN
literal — o que vier primeiro.

### 5.4 IPI do item — `det/imposto/IPI/*`

| Campo XML | XPath                                       | SPED              | Tipo     | rule_id | Severidade |
|-----------|----------------------------------------------|-------------------|----------|---------|-----------|
| `CST` IPI | `det/imposto/IPI/IPITrib/CST` ou `IPINT/CST` | `C170.CST_IPI`    | EXACT    | (parte de XC028)                | erro |
| `vBC` IPI | `det/imposto/IPI/IPITrib/vBC`                | `C170.VL_BC_IPI`  | MONETARY | XC028 / XC028b (IPI sem respaldo no XML) | erro |
| `pIPI`    | `det/imposto/IPI/IPITrib/pIPI`               | `C170.ALIQ_IPI`   | PERCENTAGE | XC028                         | erro |
| `vIPI`    | `det/imposto/IPI/IPITrib/vIPI`               | `C170.VL_IPI`     | MONETARY | XC028 / XC028c (IPI indevido em item isento) | erro |

### 5.5 PIS / COFINS do item

Modalidades em `PIS_GRUPO_MAP` / `COFINS_GRUPO_MAP`: `PISAliq` (ad valorem),
`PISQtde` (por quantidade), `PISNT` (não tributado), `PISOutr` (outros) — e
seus análogos para COFINS.

| Campo XML | XPath (variável conforme grupo)                                     | SPED              | Tipo     | rule_id | Severidade |
|-----------|----------------------------------------------------------------------|-------------------|----------|---------|-----------|
| `CST` PIS | `det/imposto/PIS/<grupo>/CST`                                        | `C170.CST_PIS`    | EXACT    | XC029   | erro |
| `vBC` PIS | `det/imposto/PIS/PISAliq/vBC` ou `PIS/PISOutr/vBC`                   | `C170.VL_BC_PIS`  | MONETARY | XC029   | erro |
| `pPIS`    | `det/imposto/PIS/<grupo>/pPIS`                                       | `C170.ALIQ_PIS`   | PERCENTAGE | XC029 | erro |
| `vPIS`    | `det/imposto/PIS/<grupo>/vPIS`                                       | `C170.VL_PIS`     | MONETARY | XC029 / XC029b (sem respaldo / item não tributado) | erro |
| `qBCProd` PIS | `det/imposto/PIS/PISQtde/qBCProd`                                | `C170.QUANT_BC_PIS` | MONETARY | XC029 | erro |
| `vAliqProd` PIS | `det/imposto/PIS/PISQtde/vAliqProd`                            | `C170.ALIQ_PIS` (R$/un.) | MONETARY | XC029 | erro |
| `CST` COFINS / `vBC` / `pCOFINS` / `vCOFINS` / `qBCProd` / `vAliqProd` | espelho dos campos PIS dentro de `det/imposto/COFINS/*` | `C170.CST_COFINS`, `VL_BC_COFINS`, `ALIQ_COFINS`, `VL_COFINS`, `QUANT_BC_COFINS`, `ALIQ_COFINS` | mesmos tipos do PIS | XC030 / XC030 (variantes) | erro |

---

## 6. Consolidação — `count(det)` agrupado × Registro **C190**

`xml_service._check_c190_vs_xml` e `cross_engine` (`XC051`) agrupam os itens
do XML pela tripla **(CST_norm, CFOP, ALIQ arredondada para 2 casas)** e
comparam com o C190 do mesmo C100.

| Soma agregada do XML | Campo C190     | Tipo     | rule_id          | Tolerância              |
|----------------------|----------------|----------|------------------|-------------------------|
| Σ `vBC`              | `VL_BC_ICMS`   | MONETARY | `XML_C190_DIVERGE` (legacy) / `XC051` (triangular) | `max(0,10; tol_proporcional)` |
| Σ `vICMS`            | `VL_ICMS`      | MONETARY | mesma            | mesma                   |
| Σ `vProd`            | `VL_OPR`       | MONETARY | `XC051`          | mesma                   |
| Σ `vBCST`            | `VL_BC_ICMS_ST`| MONETARY | (cobertura indireta) | mesma               |
| Σ `vICMSST`          | `VL_ICMS_ST`   | MONETARY | (cobertura indireta) | mesma               |

Chave de agrupamento gerada com `_norm_cst` no SPED e no XML para evitar
divergência por padding (`040` vs `40`).

---

## 7. Cadeia de **benefício fiscal** (`cBenef`)

Trilha completa documentada em `data/reference/mapeamento_cbenef_xml_sped.yaml`:

```
cBenef (XML, ICMS/*/cBenef)
  → C179  (info complementar ST do C170, quando aplicável)
  → C197  (COD_AJ, VL_ICMS / VL_OUTROS, DESCR_COMPL_AJ)
  → E111  (COD_AJ_APUR, VL_AJ_APUR — efeito na apuração)
  → E115  (COD_INF_ADIC, VL_INF_ADIC, DESCR_COMPL_AJ — declaração)
```

### Regras de validação cruzada

| rule_id                | Disparo                                            | Severidade |
|------------------------|-----------------------------------------------------|-----------|
| `BENEF_XML_SEM_E115`   | `cBenef` no XML mas sem `E115.COD_INF_ADIC` correspondente | warning |
| `BENEF_XML_SEM_C197`   | `cBenef` com `vICMSDeson > 0` mas sem `C197`        | warning   |
| `BENEF_E115_SEM_XML`   | `E115` com COD_INF_ADIC de benefício mas sem `cBenef` em nenhum XML | warning |
| `BENEF_TRILHA_INCOMPLETA` | Benefício com elo da cadeia faltando (C197 ou E111 ou E115) | crítica |
| `XC093` (`VICMSDESON_SEM_AJUSTE_APURACAO`) | XML traz `vICMSDeson > 0` mas E111 não tem ajuste correspondente | warning |

---

## 8. Famílias avançadas do motor de cruzamento (XC06x – XC09x)

| Família | rule_id   | Descrição                                                                 | SPED principal | Severidade |
|---------|-----------|---------------------------------------------------------------------------|---------------|-----------|
| Devolução | `XC070` | CFOP de devolução (1201/1202/2201/2202/5201/5202/6201/6202/1410/2410/5410/6410…) sem nota origem referenciada (`refNFe`/`refNF`) ↔ `C113`/`C100.CHV_NFE_REF` | `C100.CFOP` | erro |
| Complemento | `XC074` | `COD_SIT=06` ou `IND_NAT_FRT` indicando complementar com delta de valores incorreto | `C100.COD_SIT` | warning |
| Importação | `XC080` | `IDest=3` ou CFOP 3xxx + `vII>0` mas sem `C120` filho do C100 | `C100` | warning |
| Desoneração | `XC093` | `vICMSDeson > 0` no XML sem `E111.COD_AJ_APUR` | `E111` | warning |

---

## 9. Tipos de comparação (`FieldComparator`)

| Tipo         | Como funciona (resumido)                                                                                  |
|--------------|------------------------------------------------------------------------------------------------------------|
| `EXACT`      | Strings normalizadas (`upper`, sem `.-/`). Igualdade exata. Diverge caso contrário.                        |
| `MONETARY`   | Decimal com tolerância proporcional. **Ambos ausentes → OK**; **um ausente + outro ≠ 0 → diverge** com nota "Campo ausente no SPED/XML…". Diferenças `≤ tol` retornam `ok` (ou `ok_arredondamento` se houver delta). |
| `PERCENTAGE` | Float com tolerância fixa de **0,001 p.p.**                                                                |
| `DATE`       | Normaliza SPED (`DDMMAAAA`) e XML (truncando a 10 chars do ISO) para `AAAA-MM-DD` e compara igualdade.     |
| `CST_AWARE`  | Detecta SN (`crt_emitente ∈ {1,2}` ou XML com CSOSN). Se SN, converte CSOSN→CST (`CSOSN_TO_CST`) antes de comparar com `CST_ICMS` do SPED (zfill/strip 2 dígitos). |
| `DERIVED`    | Usa um mapa fornecido pelo contexto (ex. `cStat → COD_SIT`). Sem mapa → `skip`.                            |

Estados possíveis de `CompareResult.status`: `ok`, `ok_arredondamento`,
`diverge`, `skip` (quando o tipo retorna `None`).

---

## 10. Estrutura `_tracked` e estados (rastreabilidade)

Para cada campo monetário crítico (totais e itens), o parser preserva:

```python
"_tracked": {
    "totais.vNF": {
        "raw_value": "1931.49",
        "source_xpath": ".//infNFe/total/ICMSTot/vNF",
        "status": "ok",
    },
    "vbc_icms": { "raw_value": None, "source_xpath": ".../ICMS/*/vBC", "status": "missing" },
    ...
}
```

| `status` em `_tracked` | Quando aparece                                            |
|------------------------|-----------------------------------------------------------|
| `ok`                   | valor numérico válido                                     |
| `missing`              | tag ausente ou string vazia                               |
| `explicit_zero`        | XML traz `0`, `0.0`, `0.00` (zero legítimo)               |
| `parse_error`          | texto presente mas não conversível (não vira `0` silencioso) |

Estados de `RuleOutcome` (motor XC) usados para decidir se a regra rodou:
`EXECUTED_OK`, `EXECUTED_ERROR`, `NOT_APPLICABLE`, `NOT_EXECUTED_MISSING_DATA`,
`SUPPRESSED_BY_ROOT_CAUSE`, `NEUTRALIZED_BY_BENEFIT`, `AMBIGUOUS_MATCH`.

---

## 11. Mapeamento legacy `XML###` → motor `XC###`

Tabela em `cross_engine_models.LEGACY_RULE_MAP`:

| Legacy | Motor XC | Sentido                                  |
|--------|----------|-------------------------------------------|
| XML001 | XC001    | XML sem C100                              |
| XML002 | XC002    | C100 sem XML                              |
| XML003 | XC003    | VL_DOC                                    |
| XML004 | XC004    | VL_ICMS                                   |
| XML005 | XC005    | VL_ICMS_ST                                |
| XML006 | XC006    | VL_IPI                                    |
| XML007 | XC018    | item XML sem C170                         |
| XML008 | XC019    | C170 sem item XML                         |
| XML009 | XC021    | CFOP                                      |
| XML010 | XC022    | NCM                                       |
| XML011 | XC023    | VL_ITEM                                   |
| XML012 | XC014    | quantidade de itens                       |
| XML013 | XC015    | VL_MERC                                   |
| XML014 | XC016    | DT_DOC                                    |
| XML015 | XC017    | DT_E_S                                    |
| XML016 | XC012    | CNPJ participante                         |
| XML017 | XC013    | UF participante                           |

---

## 12. Pontos de atenção operacionais

1. **Ausente vs zero**: o parser registra `status="missing"` em `_tracked` se a
   tag não existir; o `_monetary` do FieldComparator só diverge se o **outro lado**
   tiver valor ≠ 0. Comparação `vs 0,00` no SPED com tag ausente no XML → divergência.
2. **COD_SIT 02/03/04/05** interrompe comparações monetárias do C100
   (a causa raiz é o status; valores zerados são esperados).
3. **CSOSN em regime normal / CST normal em regime SN** geram `XC031/XC032`
   antes de `XC020`, indicando **erro de cadastro** (não divergência aritmética).
4. **Campos sem BC (`GRUPOS_SEM_BC_ICMS`)** disparam a variante `*b`
   (`XC024b`/`XC025b`/`XC026b`) quando o C170 traz BC/alíquota/valor.
5. **Pareamento ambíguo de itens** (`XC019b`) suprime as demais regras do par
   para não gerar cascata.
6. **Quantidade de itens (XML012/XC014)**: respeita Exceção 2 do Guia EFD v3.2.2
   (NF-e própria sem C176/C177/C180/C181 dispensa C170).
7. **Tolerância** sempre **proporcional**, exceto C190 onde se usa
   `max(0,10; tol_proporcional)` para acomodar arredondamento de consolidação.

---

## 13. Referências internas

- `src/services/xml_service.py` — parser, regras XML### legacy, mapa `_CSTAT_TO_COD_SIT`, `_FIELD_NO_C100`, `_check_c190_vs_xml`.
- `src/services/cross_engine.py` — motor XC (camadas A, D, E + famílias 06–09 + XC051).
- `src/services/cross_engine_models.py` — enums, `CSOSN→CST` indireto, `CST_FROM_XML_GROUP`, `GRUPOS_SEM_BC_ICMS`, `PIS_GRUPO_MAP`, `COFINS_GRUPO_MAP`, `LEGACY_RULE_MAP`.
- `src/services/field_comparator.py` — implementação dos 6 tipos de comparação.
- `src/services/beneficio_engine.py` — `CSOSN_TO_CST`, regras de benefício UF.
- `src/validators/tolerance.py` — `tolerancia_proporcional`, faixas.
- `data/reference/mapeamento_cbenef_xml_sped.yaml` — trilha cBenef → C179 → C197 → E111 → E115.
- `data/reference/MAPEAMENTO_ROBUSTO_XML_SPED_ICMS_IPI.md` — schema técnico de referência (princípios e contrato de payload).
