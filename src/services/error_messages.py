"""Mapeamento de mensagens amigáveis para erros de validação SPED."""

from __future__ import annotations

# Template de mensagens por error_type.
# Variáveis disponíveis: {field_name}, {register}, {line}, {value},
# {expected}, {valid_values}, {difference}
#
# REGRA: guidance deve ser breve e direto (1-2 frases curtas).
_DETALHE = ""

ERROR_MESSAGES: dict[str, dict[str, str]] = {
    "MISSING_REQUIRED": {
        "friendly": (
            "O campo '{field_name}' é obrigatório mas está vazio "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Preencha este campo conforme o layout do registro. {_DETALHE}",
        "icon": "alert-circle",
    },
    "WRONG_TYPE": {
        "friendly": (
            "O campo '{field_name}' deveria ser numérico, "
            "mas contém o valor '{value}' no registro {register} (linha {line})."
        ),
        "guidance": f"Corrija o valor para um numero valido. {_DETALHE}",
        "icon": "type",
    },
    "WRONG_SIZE": {
        "friendly": (
            "O campo '{field_name}' excede o tamanho máximo permitido "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Reduza o valor para o tamanho maximo do campo. {_DETALHE}",
        "icon": "maximize",
    },
    "INVALID_VALUE": {
        "friendly": (
            "O valor '{value}' não é aceito para '{field_name}'. "
            "Valores permitidos: {valid_values}."
        ),
        "guidance": f"Corrija para uma das opcoes listadas. {_DETALHE}",
        "icon": "x-circle",
    },
    "INVALID_DATE": {
        "friendly": (
            "A data '{value}' no campo '{field_name}' não é válida "
            "(formato esperado: DDMMAAAA)."
        ),
        "guidance": f"Informe uma data valida no formato DDMMAAAA. {_DETALHE}",
        "icon": "calendar-x",
    },
    "DATE_OUT_OF_PERIOD": {
        "friendly": (
            "A data '{value}' no campo '{field_name}' está fora do período "
            "de apuração informado no registro 0000."
        ),
        "guidance": f"Verifique se a data esta dentro do periodo DT_INI/DT_FIN. {_DETALHE}",
        "icon": "calendar-range",
    },
    "DATE_ORDER": {
        "friendly": (
            "A data do documento (DT_DOC) é posterior à data de entrada/saída "
            "(DT_E_S) no registro {register} (linha {line})."
        ),
        "guidance": f"DT_DOC deve ser anterior ou igual a DT_E_S. {_DETALHE}",
        "icon": "calendar-arrow",
    },
    "MISSING_CONDITIONAL": {
        "friendly": (
            "O campo '{field_name}' é obrigatório nesta situação "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Preencha conforme o tipo de operacao. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "INCONSISTENCY": {
        "friendly": (
            "Inconsistência detectada no campo '{field_name}' "
            "do registro {register} (linha {line}): {value}."
        ),
        "guidance": f"Revise o status do documento e os valores declarados. {_DETALHE}",
        "icon": "alert-octagon",
    },
    "CALCULO_DIVERGENTE": {
        "friendly": (
            "O cálculo de '{field_name}' não confere: "
            "esperado R$ {expected}, encontrado R$ {value}."
        ),
        "guidance": f"Clique em Corrigir para aplicar o valor recalculado. {_DETALHE}",
        "icon": "calculator",
    },
    "CALCULO_ARREDONDAMENTO": {
        "friendly": (
            "Divergencia de arredondamento no campo '{field_name}' "
            "do registro {register} (linha {line}). "
            "Valor declarado: R$ {value}."
        ),
        "guidance": (
            "ERP calculou com aliquota de precisao maior que 2 decimais. "
            f"Clique em Corrigir para padronizar, se desejado. {_DETALHE}"
        ),
        "icon": "info",
    },
    "CRUZAMENTO_DIVERGENTE": {
        "friendly": (
            "Os totais do registro {register} não conferem "
            "com os documentos fiscais de origem."
        ),
        "guidance": f"Clique em Corrigir para ajustar o totalizador. {_DETALHE}",
        "icon": "git-branch",
    },
    "SOMA_DIVERGENTE": {
        "friendly": (
            "A soma dos itens não confere com o total declarado "
            "em {register} (linha {line}). Esperado: R$ {expected}, "
            "encontrado: R$ {value}."
        ),
        "guidance": f"Clique em Corrigir para ajustar. {_DETALHE}",
        "icon": "sigma",
    },
    "CONTAGEM_DIVERGENTE": {
        "friendly": (
            "A quantidade de registros declarada no Bloco 9 "
            "não confere com o arquivo."
        ),
        "guidance": f"Clique em Corrigir para atualizar a contagem. {_DETALHE}",
        "icon": "hash",
    },
    "REF_INEXISTENTE": {
        "friendly": (
            "O código '{value}' usado em {register} não foi encontrado "
            "no cadastro (Bloco 0)."
        ),
        "guidance": f"Verifique o cadastro 0150 ou 0200. {_DETALHE}",
        "icon": "link-broken",
    },
    "CFOP_MISMATCH": {
        "friendly": (
            "O CFOP '{value}' é incompatível com o tipo de operação "
            "declarado no registro {register} (linha {line})."
        ),
        "guidance": f"1/2/3=entrada, 5/6/7=saida. Verifique o IND_OPER. {_DETALHE}",
        "icon": "arrows-cross",
    },
    "CST_INVALIDO": {
        "friendly": (
            "O código de situação tributária '{value}' não é válido "
            "para o campo '{field_name}'."
        ),
        "guidance": f"Consulte a Tabela A (origem) e Tabela B (tributacao). {_DETALHE}",
        "icon": "file-warning",
    },
    "ISENCAO_INCONSISTENTE": {
        "friendly": (
            "O CST indica isenção/não-tributação, mas há valores de "
            "imposto preenchidos no registro {register} (linha {line})."
        ),
        "guidance": f"CST 40/41/50 exige BC e ICMS zerados. {_DETALHE}",
        "icon": "shield-alert",
    },
    "TRIBUTACAO_INCONSISTENTE": {
        "friendly": (
            "O CST indica tributação, mas o valor do imposto está "
            "zerado no registro {register} (linha {line})."
        ),
        "guidance": f"CST tributado com BC>0 exige ICMS preenchido. {_DETALHE}",
        "icon": "shield-x",
    },
    "VALOR_NEGATIVO": {
        "friendly": (
            "O campo '{field_name}' contém valor negativo "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Valores negativos nao sao permitidos. {_DETALHE}",
        "icon": "minus-circle",
    },
    "FORMATO_INVALIDO": {
        "friendly": (
            "O formato do campo '{field_name}' está inválido: '{value}'."
        ),
        "guidance": f"Verifique o formato esperado no Guia Pratico EFD. {_DETALHE}",
        "icon": "file-x",
    },
    "CST_ALIQ_ZERO_FORTE": {
        "friendly": (
            "O CST indica tributação, mas a alíquota está zerada com base "
            "de cálculo preenchida no registro {register} (linha {line})."
        ),
        "guidance": f"Verifique se o CST deveria ser 40/41/50/51. {_DETALHE}",
        "icon": "shield-alert",
    },
    "CST_ALIQ_ZERO_MODERADO": {
        "friendly": (
            "O CST indica tributação integral, mas base, alíquota e imposto "
            "estão todos zerados no registro {register} (linha {line})."
        ),
        "guidance": f"Possivel classificacao incorreta. Revise o CST. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "CST_ALIQ_ZERO_INFO": {
        "friendly": (
            "Operação com alíquota zero aceita no contexto fiscal "
            "do registro {register} (linha {line})."
        ),
        "guidance": f"Nenhuma acao necessaria. {_DETALHE}",
        "icon": "info",
    },
    "IPI_CST_ALIQ_ZERO": {
        "friendly": (
            "O CST_IPI indica tributação, mas base, alíquota e valor "
            "de IPI estão zerados no registro {register} (linha {line})."
        ),
        "guidance": f"Verifique se o CST_IPI deveria ser 02/03/04/05. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "PIS_CST_ALIQ_ZERO": {
        "friendly": (
            "O CST_PIS indica operação tributável, mas base, alíquota "
            "e valor estão zerados no registro {register} (linha {line})."
        ),
        "guidance": f"Verifique se o CST_PIS deveria ser 04/06/07/08. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "COFINS_CST_ALIQ_ZERO": {
        "friendly": (
            "O CST_COFINS indica operação tributável, mas base, alíquota "
            "e valor estão zerados no registro {register} (linha {line})."
        ),
        "guidance": f"Verifique se o CST_COFINS deveria ser 04/06/07/08. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "CST_CFOP_INCOMPATIVEL": {
        "friendly": (
            "Incompatibilidade entre CST e CFOP detectada "
            "no registro {register} (linha {line}): {value}."
        ),
        "guidance": f"CST deve ser coerente com a natureza do CFOP. {_DETALHE}",
        "icon": "arrows-cross",
    },
    "MONOFASICO_ALIQ_INVALIDA": {
        "friendly": (
            "CST indica operação monofásica, mas a alíquota é maior que zero "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"CST 04 (monofasico) exige aliquota zero. {_DETALHE}",
        "icon": "shield-x",
    },
    "MONOFASICO_VALOR_INDEVIDO": {
        "friendly": (
            "CST indica operação monofásica, mas há valor de tributo "
            "preenchido no registro {register} (linha {line})."
        ),
        "guidance": f"Monofasico: valor de PIS/COFINS deve ser zero. {_DETALHE}",
        "icon": "shield-x",
    },
    "MONOFASICO_NCM_INCOMPATIVEL": {
        "friendly": (
            "CST monofásico informado, mas o NCM do produto não consta na "
            "lista de incidência monofásica ({register}, linha {line})."
        ),
        "guidance": f"Verifique se o NCM e realmente monofasico. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "MONOFASICO_CST_INCORRETO": {
        "friendly": (
            "Produto com NCM sujeito a incidência monofásica está com CST "
            "de tributação normal no registro {register} (linha {line})."
        ),
        "guidance": f"Revenda monofasica deveria usar CST 04. {_DETALHE}",
        "icon": "alert-octagon",
    },
    "MONOFASICO_ENTRADA_CST04": {
        "friendly": (
            "CST monofásico (04) informado em operação de entrada "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Verifique se ha direito a credito (CST 50-56). {_DETALHE}",
        "icon": "info",
    },
    # ── Regras de auditoria (audit_rules.py) ──
    "CFOP_INTERESTADUAL_DESTINO_INTERNO": {
        "friendly": (
            "CFOP interestadual com destinatário da mesma UF no "
            "registro {register} (linha {line})."
        ),
        "guidance": f"CFOP 6xxx mas destinatario e da mesma UF. Deveria ser 5xxx? {_DETALHE}",
        "icon": "alert-octagon",
    },
    "DIFERIMENTO_COM_DEBITO": {
        "friendly": (
            "CST de diferimento gerando débito de ICMS no "
            "registro {register} (linha {line})."
        ),
        "guidance": f"CST 051: ICMS adiado, nao deve gerar debito. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "IPI_REFLEXO_INCORRETO": {
        "friendly": (
            "IPI não recuperável parece não estar incluído na base do "
            "ICMS no registro {register} (linha {line})."
        ),
        "guidance": f"IPI nao recuperavel deve integrar a BC do ICMS. {_DETALHE}",
        "icon": "calculator",
    },
    "BENEFICIO_CARGA_REDUZIDA_DOCUMENTO": {
        "friendly": (
            "Operação interestadual com alíquota que não corresponde às "
            "alíquotas padrão (4%/7%/12%) no registro {register} (linha {line})."
        ),
        "guidance": f"Beneficio deve ser na apuracao (E111), nao no documento. {_DETALHE}",
        "icon": "shield-alert",
    },
    "VOLUME_ISENTO_ATIPICO": {
        "friendly": (
            "Percentual de operações isentas/NT acima de 50% do total."
        ),
        "guidance": f"Volume elevado de isencao e atipico. Revise as classificacoes. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "REMESSA_SEM_RETORNO": {
        "friendly": (
            "Remessa sem retorno correspondente no período no "
            "registro {register} (linha {line})."
        ),
        "guidance": f"Remessa sem retorno pode indicar venda disfarçada. {_DETALHE}",
        "icon": "arrows-cross",
    },
    "INVENTARIO_ITEM_PARADO": {
        "friendly": (
            "Item no inventário sem movimentação no período."
        ),
        "guidance": f"Possivel estoque obsoleto ou erro de inventario. {_DETALHE}",
        "icon": "info",
    },
    "PARAMETRIZACAO_SISTEMICA_INCORRETA": {
        "friendly": (
            "Padrão repetitivo de CST incompatível com CFOP detectado "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Erro sistêmico no cadastro fiscal do ERP. {_DETALHE}",
        "icon": "alert-octagon",
    },
    "CREDITO_USO_CONSUMO_INDEVIDO": {
        "friendly": (
            "Item com entrada para comercialização mas sem saída e sem "
            "estoque no registro {register} (linha {line})."
        ),
        "guidance": f"Possivel credito indevido de uso/consumo. {_DETALHE}",
        "icon": "shield-x",
    },
    "REGISTROS_ESSENCIAIS_AUSENTES": {
        "friendly": (
            "O arquivo SPED não contém registros essenciais para auditoria."
        ),
        "guidance": f"Registros 0150, 0200, C100, C170, C190, E110 necessarios. {_DETALHE}",
        "icon": "info",
    },
    # ── Fase 1 — Alíquotas ──
    "ALIQ_INTERESTADUAL_INVALIDA": {
        "friendly": (
            "Operação interestadual com alíquota fora do padrão esperado "
            "(4%/7%/12%) no registro {register} (linha {line})."
        ),
        "guidance": f"Revise UF origem/destino e regra de tributacao. {_DETALHE}",
        "icon": "alert-octagon",
    },
    "ALIQ_INTERNA_EM_INTERESTADUAL": {
        "friendly": (
            "Alíquota interna usada em operação interestadual "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Interestadual usa 4/7/12%. Aliq >=17% e interna. {_DETALHE}",
        "icon": "alert-octagon",
    },
    "ALIQ_INTERESTADUAL_EM_INTERNA": {
        "friendly": (
            "Alíquota interestadual usada em operação interna "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Operacao interna nao deve usar 4/7/12%. Revise o cadastro. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "ALIQ_MEDIA_INDEVIDA": {
        "friendly": (
            "C190 com alíquota intermediária não suportada pelos itens "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"C190 nao deve usar aliquota media. Agrupe item a item. {_DETALHE}",
        "icon": "calculator",
    },
    # ── Fase 1 — C190 ──
    "C190_DIVERGE_C170": {
        "friendly": (
            "C190 não fecha com a soma dos itens C170 "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Compare os valores de C190 com a soma dos C170 agrupados por CST+CFOP+Aliquota. "
            "Quando XMLs estao disponiveis, o valor do XML serve como referencia cruzada "
            "para identificar se o erro esta nos itens (C170) ou no totalizador (C190). "
            f"Verifique tambem o rateio de despesas (frete, seguro, outras) do C100. {_DETALHE}"
        ),
        "icon": "sigma",
    },
    "C190_COMBINACAO_INCOMPATIVEL": {
        "friendly": (
            "Combinação atípica de CST/CFOP/ALIQ no C190 "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"CST deve ser coerente com aliquota e CFOP. {_DETALHE}",
        "icon": "alert-triangle",
    },
    # ── Fase 1 — CST/IPI expandidos ──
    "CST_020_SEM_REDUCAO": {
        "friendly": (
            "CST 020 informado sem redução real de base "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Base praticamente integral — deveria ser CST 00? {_DETALHE}",
        "icon": "alert-triangle",
    },
    "IPI_CST_INCOMPATIVEL": {
        "friendly": (
            "CST IPI incompatível com campos monetários "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"CST tributado exige base/valor; isento exige zeros. {_DETALHE}",
        "icon": "shield-alert",
    },
    "ALIQ_ICMS_AUSENTE": {
        "friendly": (
            "Aliquota ICMS ausente (0%) com valor de imposto destacado "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Aliquota identificada pela relacao BC/ICMS. "
            f"Clique em Corrigir para aplicar. {_DETALHE}"
        ),
        "icon": "calculator",
    },
    # ── DIFAL ──────────────────────────────────
    "DIFAL_FALTANTE_CONSUMO_FINAL": {
        "friendly": (
            "DIFAL faltante: operacao interestadual para consumidor final "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"Verifique apuracao E300 ou recolhimento por GNRE. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "DIFAL_INDEVIDO_REVENDA": {
        "friendly": (
            "DIFAL indevido em operacao de revenda/industrializacao "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"DIFAL so se aplica a consumidor final. {_DETALHE}",
        "icon": "alert-circle",
    },
    "DIFAL_UF_DESTINO_INCONSISTENTE": {
        "friendly": (
            "UF do destinatario inconsistente com CFOP interestadual "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"CFOP interestadual mas destinatario e da mesma UF. {_DETALHE}",
        "icon": "map-pin",
    },
    "DIFAL_ALIQ_INTERNA_INCORRETA": {
        "friendly": (
            "Aliquota interna do destino incorreta para DIFAL "
            "no registro {register} (linha {line}). Usado: {value}, "
            "esperado: {expected}."
        ),
        "guidance": f"Consulte tabela de aliquotas internas da UF destino. {_DETALHE}",
        "icon": "percent",
    },
    "DIFAL_BASE_INCONSISTENTE": {
        "friendly": (
            "Base de calculo do DIFAL inconsistente "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"Revise BC e aliquota da operacao interestadual. {_DETALHE}",
        "icon": "calculator",
    },
    "DIFAL_FCP_AUSENTE": {
        "friendly": (
            "FCP (Fundo de Combate a Pobreza) possivelmente ausente "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"UF destino cobra FCP adicional. Verifique o calculo. {_DETALHE}",
        "icon": "dollar-sign",
    },
    "DIFAL_PERFIL_INCOMPATIVEL": {
        "friendly": (
            "Perfil do destinatario incompativel com a operacao "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"Indicador IE impacta responsabilidade do DIFAL. {_DETALHE}",
        "icon": "user-x",
    },
    "DIFAL_CONSUMO_FINAL_SEM_MARCADOR": {
        "friendly": (
            "Operacao para consumidor final sem CFOP adequado "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": f"Use CFOP de consumo final (6107, 6108, etc.). {_DETALHE}",
        "icon": "tag",
    },
    "CST_HIPOTESE": {
        "friendly": (
            "Possivel inconsistencia no CST ICMS do registro {register} "
            "(linha {line}). O enquadramento fiscal informado ({value}) "
            "nao e compativel com os demais campos do item."
        ),
        "guidance": (
            "CST incompativel com os campos do item. "
            f"Clique em Corrigir para aplicar a sugestao. {_DETALHE}"
        ),
        "icon": "search",
    },
    # ── Auditoria de beneficios e ajustes ──
    "AJUSTE_SEM_LASTRO_DOCUMENTAL": {
        "friendly": (
            "Ajuste de apuracao (E111) sem detalhamento E112/E113 "
            "no registro {register} (linha {line}). {value}"
        ),
        "guidance": (
            "Verifique se o codigo de ajuste exige detalhamento via "
            "E112/E113. Nem todo ajuste requer esses registros — depende "
            "da legislacao e da tabela 5.1.1 aplicavel. "
            f"{_DETALHE}"
        ),
        "icon": "shield-alert",
    },
    "BENEFICIO_NAO_VINCULADO": {
        "friendly": (
            "Operacao com possivel beneficio fiscal sem vinculacao "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Verifique se ha beneficio fiscal aplicavel. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "DIVERGENCIA_DOCUMENTO_ESCRITURACAO": {
        "friendly": (
            "Divergencia entre documento fiscal e escrituracao "
            "detectada no arquivo SPED."
        ),
        "guidance": f"Compare os documentos originais com o SPED. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "CLASSIFICACAO_TIPO_ERRO": {
        "friendly": (
            "Classificacao do tipo de erro identificada pelo motor de auditoria."
        ),
        "guidance": f"Informativo sobre a natureza do achado. {_DETALHE}",
        "icon": "info",
    },
    "ACHADO_LIMITADO_AO_SPED": {
        "friendly": (
            "Achado identificado com base apenas nos dados do SPED. "
            "Pode requerer verificacao em documentos externos."
        ),
        "guidance": f"Valide com documentos fiscais originais. {_DETALHE}",
        "icon": "info",
    },
    "ANOMALIA_HISTORICA": {
        "friendly": (
            "Operacao com padrao atipico em relacao ao historico "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Padrao fora do habitual. Verifique a operacao. {_DETALHE}",
        "icon": "alert-triangle",
    },
    "TRILHA_BENEFICIO_AUSENTE": {
        "friendly": (
            "Trilha de auditoria de beneficio fiscal ausente "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Beneficio sem rastreabilidade completa. {_DETALHE}",
        "icon": "shield-alert",
    },
    "AJUSTE_SOMA_DIVERGENTE": {
        "friendly": (
            "Soma dos ajustes E111 diverge do valor no E110 "
            "no registro {register} (linha {line})."
        ),
        "guidance": f"Revise os registros E111 e o totalizador E110. {_DETALHE}",
        "icon": "sigma",
    },
    # ── Novos error types Fases 1-6 ──

    "NF_CANCELADA_ESCRITURADA": {
        "friendly": "NF-e cancelada (cStat={value}) escriturada como ativa (COD_SIT=00) na linha {line}. Credito de ICMS indevido.",
        "guidance": "Corrija COD_SIT para 02 (cancelada). Credito tomado sobre NF cancelada deve ser estornado.",
        "icon": "alert-octagon",
    },
    "NF_DENEGADA_ESCRITURADA": {
        "friendly": "NF-e denegada (cStat={value}) escriturada como ativa (COD_SIT=00) na linha {line}.",
        "guidance": "Corrija COD_SIT para 05 (denegada). NF com autorizacao denegada nao deve gerar credito.",
        "icon": "alert-octagon",
    },
    "COD_SIT_DIVERGENTE_XML": {
        "friendly": "COD_SIT={value} incompativel com cStat do XML na linha {line}.",
        "guidance": "Verifique a situacao da NF-e na SEFAZ e corrija o COD_SIT no SPED.",
        "icon": "alert-triangle",
    },
    "ST_MVA_AUSENTE": {
        "friendly": "Produto sujeito a ST (NCM com MVA) mas BC_ICMS_ST esta zerada na linha {line}.",
        "guidance": "Calcule a BC_ST usando a formula: (valor operacao) x (1 + MVA/100). Consulte tabela MVA por NCM/UF.",
        "icon": "calculator",
    },
    "ST_MVA_DIVERGENTE": {
        "friendly": "BC_ICMS_ST={value} diverge do esperado R${expected} com MVA tabelado na linha {line}.",
        "guidance": "Recalcule a BC_ST com MVA correto para o NCM/UF. Diferenca: R${difference}.",
        "icon": "calculator",
    },
    "ST_MVA_NAO_MAPEADO": {
        "friendly": "NCM sem MVA na tabela de referencia na linha {line}. Recalculo de ST nao executado.",
        "guidance": "Atualize a tabela mva_por_ncm_uf.yaml com o MVA vigente para este NCM/UF.",
        "icon": "database",
    },
    "ST_ALIQ_INCORRETA": {
        "friendly": "Aliquota ST={value}% diverge da esperada {expected}% para NCM/UF na linha {line}.",
        "guidance": "Verifique a aliquota de ST vigente para este NCM na UF de destino.",
        "icon": "percent",
    },
    "SPED_CST_BENEFICIO": {
        "friendly": "CST {value} incompativel com beneficio fiscal ativo para CFOP na linha {line}.",
        "guidance": "CSTs validos para este beneficio: {expected}. Verifique a parametrizacao do beneficio.",
        "icon": "shield-alert",
    },
    "SPED_ALIQ_BENEFICIO": {
        "friendly": "Aliquota {value}% em saida com beneficio que exige debito integral na linha {line}.",
        "guidance": "COMPETE exige aliquota cheia (17% ES). Credito presumido deve ser via E111, nao por reducao de aliquota.",
        "icon": "shield-alert",
    },
    "BENEFICIO_SEM_AJUSTE_E111": {
        "friendly": "Beneficio fiscal ativo no periodo sem ajuste E111 correspondente.",
        "guidance": "Verifique se o credito presumido/diferimento esta sendo declarado via E111 com codigo de ajuste correto.",
        "icon": "file-warning",
    },
    "C100_SEM_ITENS": {
        "friendly": "C100 (VL_DOC=R${value}) sem nenhum C170 vinculado na linha {line}.",
        "guidance": "Documento fiscal ativo deve ter itens detalhados (C170). Verifique se os itens foram escriturados.",
        "icon": "file-x",
    },
    "C100_ICMS_INCONSISTENTE": {
        "friendly": "VL_ICMS do C100 (R${value}) diverge da soma dos C170 (R${expected}) na linha {line}.",
        "guidance": "Corrija VL_ICMS do C100 ou os valores de ICMS dos C170 vinculados.",
        "icon": "calculator",
    },
    "C100_IPI_INCONSISTENTE": {
        "friendly": "VL_IPI do C100 (R${value}) diverge da soma dos C170 (R${expected}) na linha {line}.",
        "guidance": "Corrija VL_IPI do C100 ou os valores de IPI dos C170 vinculados.",
        "icon": "calculator",
    },
    "C100_ICMS_ST_INCONSISTENTE": {
        "friendly": "VL_ICMS_ST do C100 (R${value}) diverge da soma dos C170 (R${expected}) na linha {line}.",
        "guidance": "Corrija VL_ICMS_ST do C100 ou os valores de ST dos C170 vinculados.",
        "icon": "calculator",
    },
    "C170_ORFAO": {
        "friendly": "Registro C170 na linha {line} sem C100 pai.",
        "guidance": "Item fiscal deve estar vinculado a um documento (C100). Verifique a estrutura do arquivo.",
        "icon": "unlink",
    },
    "ST_APURACAO_DIVERGENTE": {
        "friendly": "E210.VL_ICMS_RECOL_ST (R${value}) diverge da soma de ST dos C170 saidas (R${expected}).",
        "guidance": "Reconcilie os valores de ICMS-ST na apuracao (E210) com os itens escriturados.",
        "icon": "sigma",
    },
    "IPI_REFLEXO_BC_AUSENTE": {
        "friendly": "BC_ICMS (R${value}) nao inclui VL_IPI em operacao de entrada para empresa industrial na linha {line}.",
        "guidance": "Para empresas industriais, o IPI integra a base de calculo do ICMS nas entradas (RIPI Art. 153).",
        "icon": "calculator",
    },
    "IPI_CST_MONETARIO_ZERADO": {
        "friendly": "CST IPI {value} indica tributacao mas VL_IPI esta zerado na linha {line}.",
        "guidance": "Se o IPI e tributado, o valor deve ser > 0. Verifique CST IPI e base de calculo.",
        "icon": "alert-triangle",
    },
    "CST_REGIME_INCOMPATIVEL": {
        "friendly": "CST {value} incompativel com regime tributario detectado na linha {line}.",
        "guidance": "Empresa SN deve usar CSOSN (101-900). Empresa Normal deve usar CST Tabela A (00-90).",
        "icon": "alert-circle",
    },
    "XML_C190_DIVERGE": {
        "friendly": (
            "C190 diverge dos itens XML no grupo CST/CFOP/ALIQ "
            "do registro {register} (linha {line})."
        ),
        "guidance": (
            "Compare os itens do XML com C170/C190 do SPED. "
            "Verifique agrupamento CST+CFOP+Aliquota e recalcule."
        ),
        "icon": "sigma",
    },
}

# Mensagem padrão para tipos não mapeados
_DEFAULT = {
    "friendly": "Erro de validação no campo '{field_name}' do registro {register} (linha {line}).",
    "guidance": f"Consulte o Guia Pratico EFD. {_DETALHE}",
    "icon": "info",
}


def format_friendly_message(
    error_type: str,
    *,
    field_name: str = "",
    register: str = "",
    line: int = 0,
    value: str = "",
    expected: str = "",
    valid_values: str = "",
    difference: str = "",
) -> str:
    """Formata mensagem amigável para um tipo de erro."""
    template = ERROR_MESSAGES.get(error_type, _DEFAULT)["friendly"]
    return template.format(
        field_name=field_name,
        register=register,
        line=line,
        value=value,
        expected=expected,
        valid_values=valid_values,
        difference=difference,
    )


def get_guidance(error_type: str) -> str:
    """Retorna orientação de correção para o tipo de erro."""
    return ERROR_MESSAGES.get(error_type, _DEFAULT)["guidance"]


def get_icon(error_type: str) -> str:
    """Retorna ícone sugerido para o tipo de erro."""
    return ERROR_MESSAGES.get(error_type, _DEFAULT).get("icon", "info")
