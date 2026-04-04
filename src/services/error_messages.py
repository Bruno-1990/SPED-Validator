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
