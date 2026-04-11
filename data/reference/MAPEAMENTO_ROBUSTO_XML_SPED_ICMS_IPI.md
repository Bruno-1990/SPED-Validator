# MAPEAMENTO ROBUSTO — XML ↔ SPED EFD ICMS/IPI
## Versão técnica para parser, normalização e cruzamento
### Foco: NF-e modelo 55 × Registros C100 / C170 / C190

**Versão:** 1.0  
**Data:** 11/04/2026  

---

## 1. Objetivo

Este documento define um mapeamento **operacional**, e não apenas descritivo, para sustentar:

- parsing do XML com namespace;
- normalização de campos;
- formação do payload interno;
- comparação com o SPED;
- rastreabilidade de origem;
- diferenciação entre valor ausente, valor nulo e valor zero legítimo.

---

## 2. Princípios obrigatórios

### 2.1 Cada campo deve informar
- `xpath`
- `type`
- `required`
- `normalization`
- `default_policy`
- `compare_to`
- `compare_type`
- `join_key`
- `notes`

### 2.2 Ausente não é igual a zero
O parser nunca deve converter automaticamente:
- campo ausente → `0`
- campo ausente → `""`
- campo inválido → `0`

### 2.3 O payload deve ter rastreabilidade
Cada campo crítico deve poder armazenar:
- `value`
- `raw_value`
- `source_xpath`
- `status`

### 2.4 Comparação e parsing são camadas diferentes
O campo pode ser corretamente extraído e ainda assim comparado de forma errada.

---

## 3. Estrutura sugerida do schema técnico

```json
{
  "field_name": {
    "xpath": ".//caminho/xml",
    "type": "decimal|string|int|date|datetime|enum",
    "required": true,
    "join_key": false,
    "normalization": ["trim", "digits_only", "decimal_2"],
    "default_policy": "missing|null|zero_allowed|optional",
    "compare_to": "C100.VL_DOC",
    "compare_type": "MONETARY",
    "notes": "Observações técnicas e fiscais"
  }
}
```

---

## 4. Normalizações padronizadas

- `trim`: remove espaços
- `upper`: converte para maiúsculo
- `digits_only`: mantém apenas dígitos
- `decimal_2`: decimal com 2 casas
- `decimal_4`: decimal com 4 casas
- `date_from_iso`: extrai só a data
- `datetime_iso`: mantém datetime ISO
- `none_if_missing`: retorna `null`
- `empty_string_if_missing`: retorna `""`

**Regra preferencial:** para campos fiscais numéricos, usar `none_if_missing`, não zero automático.

---

## 5. Políticas de ausência

- `missing`: ausente real, retorna `null`
- `null`: campo pode ser nulo lógico
- `zero_allowed`: zero é valor válido
- `optional`: campo opcional, sem erro estrutural

---

## 6. Tipos de comparação

- `EXACT`
- `MONETARY`
- `PERCENTAGE`
- `DATE`
- `DERIVED`
- `CST_AWARE`
- `AGGREGATED`

---

## 7. Cabeçalho da NF-e ↔ C100

### 7.1 Identificação do documento

```json
{
  "chave_nfe": {
    "xpath": ".//protNFe/infProt/chNFe",
    "type": "string",
    "required": true,
    "join_key": true,
    "normalization": ["trim", "digits_only"],
    "default_policy": "missing",
    "compare_to": "C100.CHV_NFE",
    "compare_type": "EXACT",
    "notes": "Se ausente, fallback em infNFe/@Id removendo prefixo NFe."
  },
  "numero_nfe": {
    "xpath": ".//infNFe/ide/nNF",
    "type": "int",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C100.NUM_DOC",
    "compare_type": "EXACT"
  },
  "serie": {
    "xpath": ".//infNFe/ide/serie",
    "type": "int",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C100.SER",
    "compare_type": "EXACT"
  },
  "modelo_doc": {
    "xpath": ".//infNFe/ide/mod",
    "type": "int",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C100.COD_MOD",
    "compare_type": "EXACT"
  }
}
```

### 7.2 Datas

```json
{
  "dh_emissao": {
    "xpath": ".//infNFe/ide/dhEmi",
    "type": "datetime",
    "required": true,
    "normalization": ["datetime_iso"],
    "default_policy": "missing",
    "compare_to": "C100.DT_DOC",
    "compare_type": "DATE",
    "notes": "Truncar para data ao comparar."
  },
  "dh_saida_entrada": {
    "xpath": ".//infNFe/ide/dhSaiEnt",
    "type": "datetime",
    "required": false,
    "normalization": ["datetime_iso"],
    "default_policy": "optional",
    "compare_to": "C100.DT_E_S",
    "compare_type": "DATE"
  }
}
```

### 7.3 Emitente e destinatário

```json
{
  "cnpj_emitente": {
    "xpath": ".//infNFe/emit/CNPJ",
    "type": "string",
    "required": true,
    "normalization": ["digits_only"],
    "default_policy": "missing",
    "compare_to": "emitente lógico / 0000.CNPJ",
    "compare_type": "EXACT"
  },
  "crt_emitente": {
    "xpath": ".//infNFe/emit/CRT",
    "type": "int",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "context.emitente_crt",
    "compare_type": "DERIVED",
    "notes": "Fundamental para CST_AWARE."
  },
  "cnpj_destinatario": {
    "xpath": ".//infNFe/dest/CNPJ",
    "type": "string",
    "required": false,
    "normalization": ["digits_only"],
    "default_policy": "optional",
    "compare_to": "0150.CNPJ via C100.COD_PART",
    "compare_type": "EXACT"
  },
  "cpf_destinatario": {
    "xpath": ".//infNFe/dest/CPF",
    "type": "string",
    "required": false,
    "normalization": ["digits_only"],
    "default_policy": "optional",
    "compare_to": "0150.CNPJ/CPF via C100.COD_PART",
    "compare_type": "EXACT"
  },
  "ie_destinatario": {
    "xpath": ".//infNFe/dest/IE",
    "type": "string",
    "required": false,
    "normalization": ["trim", "digits_only"],
    "default_policy": "optional",
    "compare_to": "0150.IE",
    "compare_type": "EXACT"
  },
  "uf_destinatario": {
    "xpath": ".//infNFe/dest/enderDest/UF",
    "type": "string",
    "required": false,
    "normalization": ["trim", "upper"],
    "default_policy": "optional",
    "compare_to": "0150.UF",
    "compare_type": "EXACT"
  }
}
```

### 7.4 Totais da NF-e ↔ C100

```json
{
  "total_vnf": {
    "xpath": ".//infNFe/total/ICMSTot/vNF",
    "type": "decimal",
    "required": true,
    "normalization": ["decimal_2"],
    "default_policy": "missing",
    "compare_to": "C100.VL_DOC",
    "compare_type": "MONETARY",
    "notes": "Se ausente ou inválido, nunca converter automaticamente para 0.00."
  },
  "total_vbc": {
    "xpath": ".//infNFe/total/ICMSTot/vBC",
    "type": "decimal",
    "required": true,
    "normalization": ["decimal_2"],
    "default_policy": "missing",
    "compare_to": "C100.VL_BC_ICMS",
    "compare_type": "MONETARY"
  },
  "total_vicms": {
    "xpath": ".//infNFe/total/ICMSTot/vICMS",
    "type": "decimal",
    "required": true,
    "normalization": ["decimal_2"],
    "default_policy": "missing",
    "compare_to": "C100.VL_ICMS",
    "compare_type": "MONETARY"
  },
  "total_vst": {
    "xpath": ".//infNFe/total/ICMSTot/vST",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "zero_allowed",
    "compare_to": "C100.VL_ICMS_ST",
    "compare_type": "MONETARY"
  },
  "total_vipi": {
    "xpath": ".//infNFe/total/ICMSTot/vIPI",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "zero_allowed",
    "compare_to": "C100.VL_IPI",
    "compare_type": "MONETARY"
  },
  "total_vfrete": {
    "xpath": ".//infNFe/total/ICMSTot/vFrete",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "zero_allowed",
    "compare_to": "C100.VL_FRT",
    "compare_type": "MONETARY"
  },
  "total_vdesc": {
    "xpath": ".//infNFe/total/ICMSTot/vDesc",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "zero_allowed",
    "compare_to": "C100.VL_DESC",
    "compare_type": "MONETARY"
  }
}
```

---

## 8. Situação documental ↔ C100.COD_SIT

```json
{
  "prot_cstat": {
    "xpath": ".//protNFe/infProt/cStat",
    "type": "int",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C100.COD_SIT",
    "compare_type": "DERIVED",
    "notes": "Mapear 100→00, 101/135→02, 110/301→05."
  }
}
```

### Regra derivada
- `100` → `00`
- `101` ou `135` → `02`
- `110` ou `301` → `05`

---

## 9. Itens ↔ C170

### 9.1 Chave do item

```json
{
  "num_item": {
    "xpath": ".//infNFe/det/@nItem",
    "type": "int",
    "required": true,
    "join_key": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C170.NUM_ITEM",
    "compare_type": "EXACT"
  }
}
```

### 9.2 Produto

```json
{
  "cod_produto": {
    "xpath": ".//infNFe/det/prod/cProd",
    "type": "string",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C170.COD_ITEM / 0200.COD_ITEM",
    "compare_type": "EXACT"
  },
  "desc_produto": {
    "xpath": ".//infNFe/det/prod/xProd",
    "type": "string",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "0200.DESCR_ITEM",
    "compare_type": "EXACT"
  },
  "ncm": {
    "xpath": ".//infNFe/det/prod/NCM",
    "type": "string",
    "required": true,
    "normalization": ["digits_only"],
    "default_policy": "missing",
    "compare_to": "0200.COD_NCM / C170.NCM lógico",
    "compare_type": "EXACT"
  },
  "cfop": {
    "xpath": ".//infNFe/det/prod/CFOP",
    "type": "string",
    "required": true,
    "normalization": ["digits_only"],
    "default_policy": "missing",
    "compare_to": "C170.CFOP",
    "compare_type": "EXACT"
  },
  "qtd_com": {
    "xpath": ".//infNFe/det/prod/qCom",
    "type": "decimal",
    "required": true,
    "normalization": ["decimal_4"],
    "default_policy": "missing",
    "compare_to": "C170.QTD",
    "compare_type": "MONETARY"
  },
  "vl_prod": {
    "xpath": ".//infNFe/det/prod/vProd",
    "type": "decimal",
    "required": true,
    "normalization": ["decimal_2"],
    "default_policy": "missing",
    "compare_to": "C170.VL_ITEM",
    "compare_type": "MONETARY"
  }
}
```

### 9.3 ICMS

```json
{
  "cst_icms": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/CST | .//infNFe/det/imposto/ICMS/*/CSOSN",
    "type": "string",
    "required": true,
    "normalization": ["trim"],
    "default_policy": "missing",
    "compare_to": "C170.CST_ICMS",
    "compare_type": "CST_AWARE",
    "notes": "Se CRT=1/2, usar CSOSN-aware."
  },
  "vbc_icms": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/vBC",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "optional",
    "compare_to": "C170.VL_BC_ICMS",
    "compare_type": "MONETARY"
  },
  "paliq_icms": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/pICMS",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_4"],
    "default_policy": "optional",
    "compare_to": "C170.ALIQ_ICMS",
    "compare_type": "PERCENTAGE"
  },
  "vl_icms": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/vICMS",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "optional",
    "compare_to": "C170.VL_ICMS",
    "compare_type": "MONETARY"
  },
  "vbc_st": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/vBCST",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "optional",
    "compare_to": "C170.VL_BC_ICMS_ST",
    "compare_type": "MONETARY"
  },
  "paliq_st": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/pICMSST | .//infNFe/det/imposto/ICMS/*/pST",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_4"],
    "default_policy": "optional",
    "compare_to": "C170.ALIQ_ST",
    "compare_type": "PERCENTAGE"
  },
  "vl_icms_st": {
    "xpath": ".//infNFe/det/imposto/ICMS/*/vICMSST | .//infNFe/det/imposto/ICMS/*/vICMSSTRet",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "optional",
    "compare_to": "C170.VL_ICMS_ST",
    "compare_type": "MONETARY"
  }
}
```

### 9.4 IPI

```json
{
  "cst_ipi": {
    "xpath": ".//infNFe/det/imposto/IPI/*/CST",
    "type": "string",
    "required": false,
    "normalization": ["trim"],
    "default_policy": "optional",
    "compare_to": "C170.CST_IPI",
    "compare_type": "EXACT"
  },
  "vbc_ipi": {
    "xpath": ".//infNFe/det/imposto/IPI/*/vBC",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "optional",
    "compare_to": "C170.VL_BC_IPI",
    "compare_type": "MONETARY"
  },
  "paliq_ipi": {
    "xpath": ".//infNFe/det/imposto/IPI/*/pIPI",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_4"],
    "default_policy": "optional",
    "compare_to": "C170.ALIQ_IPI",
    "compare_type": "PERCENTAGE"
  },
  "vl_ipi": {
    "xpath": ".//infNFe/det/imposto/IPI/*/vIPI",
    "type": "decimal",
    "required": false,
    "normalization": ["decimal_2"],
    "default_policy": "zero_allowed",
    "compare_to": "C170.VL_IPI",
    "compare_type": "MONETARY"
  }
}
```

---

## 10. C190 por agregação

O `C190` não é comparação 1:1.

### Regra
Agrupar os itens do XML por:
- CST/CSOSN convertido
- CFOP
- alíquota ICMS

E comparar as somas com o `C190`.

### Campos agregados
- soma `vBC`
- soma `vICMS`
- soma `vBCST`
- soma `vICMSST`

---

## 11. Regras para evitar falso positivo

### 11.1 Campo monetário ausente
Se `xpath` não existir:
- retornar `null`
- registrar `raw_value = null`
- registrar `status = missing`

Nunca retornar `0.00` automaticamente.

### 11.2 Campo monetário zero explícito
Se o XML tiver `0.00`:
- retornar `0.00`
- registrar `status = explicit_zero`

### 11.3 Campo monetário inválido
Se o texto não puder virar decimal:
- retornar `parse_error`
- nunca substituir por zero silenciosamente

### 11.4 Fallback de chave
Para `chave_nfe`:
1. tentar `protNFe/infProt/chNFe`
2. se ausente, usar `infNFe/@Id` removendo prefixo `NFe`

---

## 12. Estrutura recomendada do payload interno

```json
{
  "totais": {
    "total_vnf": {
      "value": 1931.49,
      "raw_value": "1931.49",
      "source_xpath": ".//infNFe/total/ICMSTot/vNF",
      "status": "ok"
    }
  }
}
```

### Status possíveis
- `ok`
- `missing`
- `explicit_zero`
- `parse_error`
- `fallback`

---

## 13. Caso do erro de VL_DOC

Para evitar o falso positivo visto no seu caso, o mapeamento correto é:

- XML: `.//infNFe/total/ICMSTot/vNF`
- Payload: `totais.total_vnf`
- SPED: `C100.VL_DOC`
- Compare type: `MONETARY`

Se a tela mostrou:
- SPED = `0.00`
- XML = `1931.49`

mas o `C100` do SPED tem `1931,49`, então o problema está em:
1. parser do SPED;
2. payload intermediário;
3. comparador;
4. UI;
5. fallback silencioso para zero.

---

## 14. Recomendação imediata

### Prioridade 1
Criar schema técnico novo para os campos críticos do `C100` e `C170`.

### Prioridade 2
Alterar o parser para armazenar:
- `value`
- `raw_value`
- `source_xpath`
- `status`

### Prioridade 3
No frontend, mostrar:
- XPath do XML usado
- campo do SPED usado
- valor bruto
- valor normalizado

### Prioridade 4
Bloquear a regra de cruzamento quando o valor comparado vier com status `parse_error`.

---

## 15. Conclusão

O schema atual de vocês é bom como **dicionário de negócio**, mas insuficiente como **schema técnico de parser e comparação**.

Para o motor ficar robusto de verdade, o mapeamento precisa dizer:
- de onde vem o valor;
- como ele é normalizado;
- com o que ele compara;
- como se comporta se estiver ausente.
