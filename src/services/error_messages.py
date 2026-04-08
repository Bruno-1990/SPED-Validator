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
        "guidance": f"Clique em Corrigir para ajustar. {_DETALHE}",
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
