"""Endpoint de escopo e limitações da validação."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["Escopo de Auditoria"])


AUDIT_SCOPE = {
    "version": "1.0",
    "last_updated": "2026-04-07",
    "validacao_cobre": [
        {
            "categoria": "Formato e estrutura",
            "descricao": "Formato de CNPJ, CPF, datas, CEP, NCM, chave NF-e, tamanho de campos.",
            "confianca": "alta",
        },
        {
            "categoria": "Cálculos tributários",
            "descricao": "Recálculo de ICMS, IPI, PIS, COFINS, ST. Verificação de BC × Alíquota = Imposto.",
            "confianca": "alta",
        },
        {
            "categoria": "Cruzamento entre blocos",
            "descricao": "Consistência entre C170 e C190, entre C190/D690 e E110, entre bloco 0 e blocos C/D.",
            "confianca": "alta",
        },
        {
            "categoria": "Semântica fiscal",
            "descricao": "Coerência de CST × CFOP, monofásicos, alíquotas interestaduais, DIFAL.",
            "confianca": "media",
        },
        {
            "categoria": "Auditoria de benefícios",
            "descricao": "Rastreabilidade de ajustes E111/E112/E113, proporção de benefícios, sobreposições.",
            "confianca": "media",
            "observacao": "Requer confirmação com o ato concessivo estadual para conclusão definitiva.",
        },
    ],
    "validacao_nao_cobre": [
        {
            "limitacao": "Documentos fiscais originais",
            "detalhe": (
                "O sistema não verifica se o XML da NF-e corresponde à escrituração. "
                "Divergências entre o XML e o SPED não são detectáveis apenas pelo arquivo SPED."
            ),
        },
        {
            "limitacao": "Validade jurídica do regime tributário",
            "detalhe": (
                "O regime tributário (Simples Nacional, Lucro Real, etc.) é detectado "
                "do arquivo, mas o sistema não verifica se é o regime correto para o CNPJ."
            ),
        },
        {
            "limitacao": "Vigência e escopo dos benefícios fiscais",
            "detalhe": (
                "Para confirmar que um benefício fiscal é válido, é necessário consultar "
                "o ato concessivo estadual, que não faz parte do arquivo SPED."
            ),
        },
        {
            "limitacao": "Conformidade com obrigações acessórias",
            "detalhe": (
                "O sistema valida apenas o SPED EFD ICMS/IPI. "
                "Não valida EFD-Contribuições, SPED Contábil, DCTF, DES ou outras obrigações."
            ),
        },
        {
            "limitacao": "Cruzamento com SPED de outros contribuintes",
            "detalhe": (
                "Não é possível verificar se as informações do SPED do fornecedor "
                "correspondem às informações escrituradas pelo destinatário."
            ),
        },
    ],
    "aviso_legal": (
        "Os apontamentos gerados por este sistema são auxiliares de revisão. "
        "Apontamentos classificados como 'investigar' requerem análise humana e "
        "documentação externa antes de qualquer ação. "
        "A ausência de apontamentos não representa conformidade fiscal plena."
    ),
    "apontamentos_por_certeza": {
        "objetivo": "Erro confirmado — a divergência é inequívoca dentro do arquivo.",
        "provavel": "Proposta — alta probabilidade de erro, mas pode haver exceção legal. Revisar antes de corrigir.",
        "indicio": "Investigação necessária — sinal de alerta que requer análise externa antes de conclusão.",
    },
}


@router.get(
    "/audit-scope",
    summary="Escopo e limitações da validação",
    description=(
        "Retorna o escopo completo do que o sistema valida e não valida. "
        "Inclua sempre este texto no relatório de auditoria."
    ),
)
async def get_audit_scope():
    return AUDIT_SCOPE
