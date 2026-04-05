"""Mapeamento de mensagens amigáveis para erros de validação SPED."""

from __future__ import annotations

# Template de mensagens por error_type.
# Variáveis disponíveis: {field_name}, {register}, {line}, {value},
# {expected}, {valid_values}, {difference}
ERROR_MESSAGES: dict[str, dict[str, str]] = {
    "MISSING_REQUIRED": {
        "friendly": (
            "O campo '{field_name}' é obrigatório mas está vazio "
            "no registro {register} (linha {line})."
        ),
        "guidance": "Preencha este campo conforme o layout do registro.",
        "icon": "alert-circle",
    },
    "WRONG_TYPE": {
        "friendly": (
            "O campo '{field_name}' deveria ser numérico, "
            "mas contém o valor '{value}' no registro {register} (linha {line})."
        ),
        "guidance": "Corrija o valor para um número válido.",
        "icon": "type",
    },
    "WRONG_SIZE": {
        "friendly": (
            "O campo '{field_name}' excede o tamanho máximo permitido "
            "no registro {register} (linha {line})."
        ),
        "guidance": "Reduza o valor para o tamanho máximo do campo.",
        "icon": "maximize",
    },
    "INVALID_VALUE": {
        "friendly": (
            "O valor '{value}' não é aceito para '{field_name}'. "
            "Valores permitidos: {valid_values}."
        ),
        "guidance": "Corrija para uma das opções listadas.",
        "icon": "x-circle",
    },
    "INVALID_DATE": {
        "friendly": (
            "A data '{value}' no campo '{field_name}' não é válida "
            "(formato esperado: DDMMAAAA)."
        ),
        "guidance": "Informe uma data válida no formato dia/mês/ano (DDMMAAAA).",
        "icon": "calendar-x",
    },
    "DATE_OUT_OF_PERIOD": {
        "friendly": (
            "A data '{value}' no campo '{field_name}' está fora do período "
            "de apuração informado no registro 0000."
        ),
        "guidance": (
            "Verifique se a data do documento está dentro do período "
            "DT_INI e DT_FIN declarado."
        ),
        "icon": "calendar-range",
    },
    "DATE_ORDER": {
        "friendly": (
            "A data do documento (DT_DOC) é posterior à data de entrada/saída "
            "(DT_E_S) no registro {register} (linha {line})."
        ),
        "guidance": "A data do documento deve ser anterior ou igual à data de entrada/saída.",
        "icon": "calendar-arrow",
    },
    "MISSING_CONDITIONAL": {
        "friendly": (
            "O campo '{field_name}' é obrigatório nesta situação "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Este campo é condicional e deve ser preenchido conforme "
            "o tipo de operação."
        ),
        "icon": "alert-triangle",
    },
    "INCONSISTENCY": {
        "friendly": (
            "Inconsistência detectada no campo '{field_name}' "
            "do registro {register} (linha {line}): {value}."
        ),
        "guidance": "Revise o status do documento e os valores declarados.",
        "icon": "alert-octagon",
    },
    "CALCULO_DIVERGENTE": {
        "friendly": (
            "O cálculo de '{field_name}' não confere: "
            "esperado R$ {expected}, encontrado R$ {value}."
        ),
        "guidance": (
            "Verifique a base de cálculo e a alíquota aplicada. "
            "O sistema pode corrigir automaticamente."
        ),
        "icon": "calculator",
    },
    "CRUZAMENTO_DIVERGENTE": {
        "friendly": (
            "Os totais do registro {register} não conferem "
            "com os documentos fiscais de origem."
        ),
        "guidance": "Revise os valores dos documentos e da apuração.",
        "icon": "git-branch",
    },
    "SOMA_DIVERGENTE": {
        "friendly": (
            "A soma dos itens não confere com o total declarado "
            "em {register} (linha {line}). Esperado: R$ {expected}, "
            "encontrado: R$ {value}."
        ),
        "guidance": "Revise os valores individuais e o totalizador.",
        "icon": "sigma",
    },
    "CONTAGEM_DIVERGENTE": {
        "friendly": (
            "A quantidade de registros declarada no Bloco 9 "
            "não confere com o arquivo."
        ),
        "guidance": "O Bloco 9 será recalculado automaticamente.",
        "icon": "hash",
    },
    "REF_INEXISTENTE": {
        "friendly": (
            "O código '{value}' usado em {register} não foi encontrado "
            "no cadastro (Bloco 0)."
        ),
        "guidance": (
            "Verifique se o cadastro 0150 (participantes) ou "
            "0200 (itens) contém este código."
        ),
        "icon": "link-broken",
    },
    "CFOP_MISMATCH": {
        "friendly": (
            "O CFOP '{value}' é incompatível com o tipo de operação "
            "declarado no registro {register} (linha {line})."
        ),
        "guidance": (
            "CFOPs iniciados em 1/2/3 são de entrada; "
            "5/6/7 são de saída. Verifique o IND_OPER do C100 pai."
        ),
        "icon": "arrows-cross",
    },
    "CST_INVALIDO": {
        "friendly": (
            "O código de situação tributária '{value}' não é válido "
            "para o campo '{field_name}'."
        ),
        "guidance": "Consulte a Tabela A (origem) e Tabela B (tributação) do ICMS.",
        "icon": "file-warning",
    },
    "ISENCAO_INCONSISTENTE": {
        "friendly": (
            "O CST indica isenção/não-tributação, mas há valores de "
            "imposto preenchidos no registro {register} (linha {line})."
        ),
        "guidance": (
            "Se o CST for 40, 41 ou 50, a base de cálculo "
            "e o ICMS devem ser zero."
        ),
        "icon": "shield-alert",
    },
    "TRIBUTACAO_INCONSISTENTE": {
        "friendly": (
            "O CST indica tributação, mas o valor do imposto está "
            "zerado no registro {register} (linha {line})."
        ),
        "guidance": (
            "Se o CST for 00, 10, 20, 70 ou 90 e a base de cálculo "
            "for maior que zero, o ICMS deve ser informado."
        ),
        "icon": "shield-x",
    },
    "VALOR_NEGATIVO": {
        "friendly": (
            "O campo '{field_name}' contém valor negativo "
            "no registro {register} (linha {line})."
        ),
        "guidance": "Valores negativos não são permitidos neste campo.",
        "icon": "minus-circle",
    },
    "FORMATO_INVALIDO": {
        "friendly": (
            "O formato do campo '{field_name}' está inválido: '{value}'."
        ),
        "guidance": "Verifique o formato esperado conforme o Guia Prático EFD.",
        "icon": "file-x",
    },
    "CST_ALIQ_ZERO_FORTE": {
        "friendly": (
            "O CST indica tributação, mas a alíquota está zerada com base "
            "de cálculo preenchida no registro {register} (linha {line})."
        ),
        "guidance": (
            "Verifique se o item deveria usar CST de isenção (40), "
            "não-tributação (41), suspensão (50) ou diferimento (51). "
            "Se houver benefício fiscal, parametrize-o no sistema."
        ),
        "icon": "shield-alert",
    },
    "CST_ALIQ_ZERO_MODERADO": {
        "friendly": (
            "O CST indica tributação integral, mas base, alíquota e imposto "
            "estão todos zerados no registro {register} (linha {line})."
        ),
        "guidance": (
            "Verifique se há classificação fiscal incorreta ou lançamento "
            "incompleto. Se a operação for isenta, use CST 40; se não "
            "tributada, CST 41; se suspensa, CST 50."
        ),
        "icon": "alert-triangle",
    },
    "CST_ALIQ_ZERO_INFO": {
        "friendly": (
            "Operação com alíquota zero aceita no contexto fiscal "
            "do registro {register} (linha {line})."
        ),
        "guidance": (
            "Nenhuma ação necessária. A alíquota zero é compatível "
            "com o contexto da operação (exportação, remessa, etc.)."
        ),
        "icon": "info",
    },
    "IPI_CST_ALIQ_ZERO": {
        "friendly": (
            "O CST_IPI indica tributação, mas base, alíquota e valor "
            "de IPI estão zerados no registro {register} (linha {line})."
        ),
        "guidance": (
            "Verifique se o CST_IPI deveria ser 02 (isento), "
            "03 (não tributado), 04 (imune) ou 05 (suspenso)."
        ),
        "icon": "alert-triangle",
    },
    "PIS_CST_ALIQ_ZERO": {
        "friendly": (
            "O CST_PIS indica operação tributável, mas base, alíquota "
            "e valor estão zerados no registro {register} (linha {line})."
        ),
        "guidance": (
            "Verifique se o CST_PIS deveria ser 04 (não tributado), "
            "06 (alíquota zero), 07 (isento) ou 08 (sem incidência)."
        ),
        "icon": "alert-triangle",
    },
    "COFINS_CST_ALIQ_ZERO": {
        "friendly": (
            "O CST_COFINS indica operação tributável, mas base, alíquota "
            "e valor estão zerados no registro {register} (linha {line})."
        ),
        "guidance": (
            "Verifique se o CST_COFINS deveria ser 04 (não tributado), "
            "06 (alíquota zero), 07 (isento) ou 08 (sem incidência)."
        ),
        "icon": "alert-triangle",
    },
    "CST_CFOP_INCOMPATIVEL": {
        "friendly": (
            "Incompatibilidade entre CST e CFOP detectada "
            "no registro {register} (linha {line}): {value}."
        ),
        "guidance": (
            "Verifique se o CST está coerente com a natureza da operação "
            "indicada pelo CFOP. Vendas tributadas normalmente usam CST de "
            "tributação; exportações normalmente têm imunidade."
        ),
        "icon": "arrows-cross",
    },
    "MONOFASICO_ALIQ_INVALIDA": {
        "friendly": (
            "CST indica operação monofásica, mas a alíquota é maior que zero "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Na revenda de produto monofásico (CST 04), a alíquota de "
            "PIS/COFINS deve ser zero. O tributo já foi recolhido pelo "
            "fabricante ou importador (Lei 10.147/00, Lei 10.485/02, "
            "Lei 10.833/03)."
        ),
        "icon": "shield-x",
    },
    "MONOFASICO_VALOR_INDEVIDO": {
        "friendly": (
            "CST indica operação monofásica, mas há valor de tributo "
            "preenchido no registro {register} (linha {line})."
        ),
        "guidance": (
            "Na revenda de produto monofásico, o valor de PIS/COFINS deve "
            "ser zero. O recolhimento ocorre na etapa de industrialização "
            "ou importação."
        ),
        "icon": "shield-x",
    },
    "MONOFASICO_NCM_INCOMPATIVEL": {
        "friendly": (
            "CST monofásico informado, mas o NCM do produto não consta na "
            "lista de incidência monofásica ({register}, linha {line})."
        ),
        "guidance": (
            "Verifique se o produto realmente está sujeito à tributação "
            "monofásica conforme Lei 10.147/00 (farmacêuticos/higiene), "
            "Lei 10.485/02 (veículos/autopeças), Lei 10.833/03 (bebidas) "
            "ou Lei 10.865/04 (combustíveis). Se não for monofásico, "
            "corrija o CST para 01 (tributação normal) ou outro adequado."
        ),
        "icon": "alert-triangle",
    },
    "MONOFASICO_CST_INCORRETO": {
        "friendly": (
            "Produto com NCM sujeito a incidência monofásica está com CST "
            "de tributação normal no registro {register} (linha {line})."
        ),
        "guidance": (
            "Na revenda de produto monofásico, o CST de PIS/COFINS deveria "
            "ser 04 (monofásico - revenda a alíquota zero). Tributar "
            "normalmente um produto monofásico pode gerar recolhimento "
            "indevido em duplicidade."
        ),
        "icon": "alert-octagon",
    },
    "MONOFASICO_ENTRADA_CST04": {
        "friendly": (
            "CST monofásico (04) informado em operação de entrada "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Na entrada, o CST 04 se aplica à aquisição para revenda sem "
            "direito a crédito. Se a empresa for industrializadora com "
            "direito a crédito de PIS/COFINS, o CST deveria ser 50-56. "
            "Verifique a natureza da operação e o regime tributário."
        ),
        "icon": "info",
    },
    # ── Regras de auditoria (audit_rules.py) ──
    "CFOP_INTERESTADUAL_DESTINO_INTERNO": {
        "friendly": (
            "CFOP interestadual com destinatário da mesma UF no "
            "registro {register} (linha {line})."
        ),
        "guidance": (
            "CFOP da série 6xxx indica operação interestadual, mas o "
            "participante é da mesma UF do declarante. Verifique se o "
            "CFOP deveria ser da série 5xxx (interna)."
        ),
        "icon": "alert-octagon",
    },
    "DIFERIMENTO_COM_DEBITO": {
        "friendly": (
            "CST de diferimento gerando débito de ICMS no "
            "registro {register} (linha {line})."
        ),
        "guidance": (
            "No diferimento (CST 051), o ICMS é adiado e não deve gerar "
            "débito no período corrente, salvo diferimento parcial."
        ),
        "icon": "alert-triangle",
    },
    "IPI_REFLEXO_INCORRETO": {
        "friendly": (
            "IPI não recuperável parece não estar incluído na base do "
            "ICMS no registro {register} (linha {line})."
        ),
        "guidance": (
            "Para contribuintes que não recuperam IPI (CST IPI 02-05), "
            "o valor do IPI deve integrar a base de cálculo do ICMS."
        ),
        "icon": "calculator",
    },
    "BENEFICIO_CARGA_REDUZIDA_DOCUMENTO": {
        "friendly": (
            "Operação interestadual com alíquota que não corresponde às "
            "alíquotas padrão (4%/7%/12%) no registro {register} (linha {line})."
        ),
        "guidance": (
            "Benefícios por crédito presumido devem ser tratados na "
            "apuração (E111), não como redução direta no documento. "
            "O destaque na NF-e deve ser integral."
        ),
        "icon": "shield-alert",
    },
    "VOLUME_ISENTO_ATIPICO": {
        "friendly": (
            "Percentual de operações isentas/NT acima de 50% do total."
        ),
        "guidance": (
            "Um volume elevado de operações com CST isento, não tributado "
            "ou suspenso é atípico para a maioria dos contribuintes. "
            "Revise se as classificações estão corretas."
        ),
        "icon": "alert-triangle",
    },
    "REMESSA_SEM_RETORNO": {
        "friendly": (
            "Remessa sem retorno correspondente no período no "
            "registro {register} (linha {line})."
        ),
        "guidance": (
            "Operações de remessa devem ter retorno dentro do prazo "
            "legal. Remessa sem retorno pode indicar venda disfarçada."
        ),
        "icon": "arrows-cross",
    },
    "INVENTARIO_ITEM_PARADO": {
        "friendly": (
            "Item no inventário sem movimentação no período."
        ),
        "guidance": (
            "Itens no H010 sem nenhum C170 no período podem indicar "
            "estoque obsoleto ou erro de inventário."
        ),
        "icon": "info",
    },
    "PARAMETRIZACAO_SISTEMICA_INCORRETA": {
        "friendly": (
            "Padrão repetitivo de CST incompatível com CFOP detectado "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "O mesmo item apresenta CST incompatível com o CFOP na "
            "maioria das ocorrências, indicando erro sistêmico no "
            "cadastro fiscal do ERP."
        ),
        "icon": "alert-octagon",
    },
    "CREDITO_USO_CONSUMO_INDEVIDO": {
        "friendly": (
            "Item com entrada para comercialização mas sem saída e sem "
            "estoque no registro {register} (linha {line})."
        ),
        "guidance": (
            "O item foi creditado como compra para revenda mas nunca "
            "aparece em saídas nem no inventário. Pode ser material "
            "de uso/consumo com crédito indevido de ICMS."
        ),
        "icon": "shield-x",
    },
    "REGISTROS_ESSENCIAIS_AUSENTES": {
        "friendly": (
            "O arquivo SPED não contém registros essenciais para auditoria."
        ),
        "guidance": (
            "Registros como 0150, 0200, C100, C170, C190, E110 e H010 "
            "são necessários para uma auditoria fiscal completa."
        ),
        "icon": "info",
    },
    # ── Fase 1 — Alíquotas ──
    "ALIQ_INTERESTADUAL_INVALIDA": {
        "friendly": (
            "Operação interestadual com alíquota fora do padrão esperado "
            "(4%/7%/12%) no registro {register} (linha {line})."
        ),
        "guidance": (
            "Revise UF de origem, UF de destino, origem da mercadoria "
            "e regra de tributação. Resolução Senado 22/1989 e 13/2012."
        ),
        "icon": "alert-octagon",
    },
    "ALIQ_INTERNA_EM_INTERESTADUAL": {
        "friendly": (
            "Alíquota interna usada em operação interestadual "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Operações interestaduais usam 4%, 7% ou 12%. Alíquota >= 17% "
            "é típica de operação interna. Confirme UF do destinatário "
            "e parametrização do ERP."
        ),
        "icon": "alert-octagon",
    },
    "ALIQ_INTERESTADUAL_EM_INTERNA": {
        "friendly": (
            "Alíquota interestadual usada em operação interna "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Operações internas não devem usar alíquotas interestaduais "
            "(4%/7%/12%). Revise cadastro do cliente e UF do participante."
        ),
        "icon": "alert-triangle",
    },
    "ALIQ_MEDIA_INDEVIDA": {
        "friendly": (
            "C190 com alíquota intermediária não suportada pelos itens "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Cada item deve ser tratado com sua própria alíquota. "
            "O C190 não deve conter alíquota média. Reprocesse o "
            "agrupamento item a item."
        ),
        "icon": "calculator",
    },
    # ── Fase 1 — C190 ──
    "C190_DIVERGE_C170": {
        "friendly": (
            "C190 não fecha com a soma dos itens C170 "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "O C190 deve refletir exatamente os agrupamentos dos C170 "
            "por CST+CFOP+ALIQ. Reprocesse o analítico da nota."
        ),
        "icon": "sigma",
    },
    "C190_COMBINACAO_INCOMPATIVEL": {
        "friendly": (
            "Combinação atípica de CST/CFOP/ALIQ no C190 "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "Verifique se o CST é coerente com a alíquota e o CFOP. "
            "CST isento não deveria ter alíquota; CST tributado deveria "
            "ter alíquota positiva."
        ),
        "icon": "alert-triangle",
    },
    # ── Fase 1 — CST/IPI expandidos ──
    "CST_020_SEM_REDUCAO": {
        "friendly": (
            "CST 020 informado sem redução real de base "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "CST 020 indica redução de base de cálculo. Se a base é "
            "praticamente integral, verifique se deveria ser CST 00 "
            "ou se a redução não foi aplicada corretamente."
        ),
        "icon": "alert-triangle",
    },
    "IPI_CST_INCOMPATIVEL": {
        "friendly": (
            "CST IPI incompatível com campos monetários "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "CST de IPI tributado deve ter base/valor; CST isento/NT "
            "deve ter base/valor zerados. Revise a tributação do IPI."
        ),
        "icon": "shield-alert",
    },
    "ALIQ_ICMS_AUSENTE": {
        "friendly": (
            "Aliquota ICMS ausente (0%) com valor de imposto destacado "
            "no registro {register} (linha {line})."
        ),
        "guidance": (
            "O campo ALIQ_ICMS esta zerado mas existe VL_ICMS calculado. "
            "A aliquota foi identificada pela relacao entre base de calculo "
            "e valor do imposto. Clique em Corrigir para aplicar."
        ),
        "icon": "calculator",
    },
    "CST_HIPOTESE": {
        "friendly": (
            "Possivel inconsistencia no CST ICMS do registro {register} "
            "(linha {line}). O enquadramento fiscal informado ({value}) "
            "nao e compativel com os demais campos do item."
        ),
        "guidance": (
            "O motor identificou incompatibilidade entre o CST informado e "
            "os campos de base de calculo, aliquota e valor do ICMS. "
            "Verifique o enquadramento fiscal da operacao e clique em "
            "Corrigir para aplicar a sugestao, se pertinente."
        ),
        "icon": "search",
    },
}

# Mensagem padrão para tipos não mapeados
_DEFAULT = {
    "friendly": "Erro de validação no campo '{field_name}' do registro {register} (linha {line}).",
    "guidance": "Consulte o Guia Prático EFD para detalhes sobre este campo.",
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
    """Gera mensagem amigável interpolando o template do error_type."""
    template = ERROR_MESSAGES.get(error_type, _DEFAULT)
    try:
        return template["friendly"].format(
            field_name=field_name,
            register=register,
            line=line,
            value=value,
            expected=expected,
            valid_values=valid_values,
            difference=difference,
        )
    except (KeyError, IndexError):
        return template["friendly"]


def get_guidance(error_type: str) -> str:
    """Retorna a orientação de correção para um tipo de erro."""
    template = ERROR_MESSAGES.get(error_type, _DEFAULT)
    return template["guidance"]


def get_icon(error_type: str) -> str:
    """Retorna o ícone sugerido para um tipo de erro."""
    template = ERROR_MESSAGES.get(error_type, _DEFAULT)
    return template["icon"]
