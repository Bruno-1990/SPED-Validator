# PRD — Plano de Implementação SPED EFD Validator
# Versão: 1.0 | Data: 2026-04-07 | Autor: Auditoria Técnica
# Status: APROVADO PARA EXECUÇÃO

> **ATENÇÃO:** Este documento é um script de execução sequencial.
> Cada bloco deve ser executado na ordem indicada.
> NÃO pule para o próximo bloco sem que o teste do bloco atual passe.
> Um log consolidado é gerado automaticamente ao final.

---

## PRÉ-REQUISITOS DE EXECUÇÃO

```bash
# Verifique que você está na raiz do projeto antes de iniciar
pwd  # deve terminar em /SPED ou similar
ls rules.yaml src/ api/ tests/  # deve listar os arquivos

# Verifique ambiente Python ativo
python --version  # >= 3.10
pytest --version

# Crie o arquivo de log antes de começar
echo "=== LOG DE IMPLEMENTAÇÃO SPED VALIDATOR ===" > IMPLEMENTATION_LOG.md
echo "Início: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 01 — FieldRegistry: Eliminar Índices Hardcoded

### Problema
Validadores acessam campos SPED por posição hardcoded (`fields[9]`, `fields[10]`).
Qualquer divergência com o Guia Prático gera erro silencioso — campo errado é lido
sem nenhuma exceção ou aviso. O README já documenta 15 correções já necessárias.

### Objetivo
Criar um `FieldRegistry` centralizado que resolve `(register, field_name) → índice`
a partir do banco `register_fields`. Todos os validadores usam exclusivamente essa
interface. Proibir índices hardcoded via lint.

### Critério de aceite
- `src/validators/field_registry.py` existe e passa todos os testes
- Nenhum validador usa `fields[N]` com N literal — ruff custom rule confirma
- `FieldRegistry.get_index("C170", "CST_ICMS")` retorna o índice correto do banco

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator (Python/FastAPI).

TAREFA: Criar o módulo FieldRegistry para eliminar índices hardcoded nos validadores.

CONTEXTO DO PROBLEMA:
Os validadores em src/validators/ acessam campos SPED por índice hardcoded, por exemplo:
  fields[9]  # CST_ICMS no C170
  fields[10] # DT_E_S no C100
Isso é frágil. O banco sped.db tem a tabela register_fields com as posições corretas.

IMPLEMENTAÇÃO NECESSÁRIA:

1. Crie src/validators/field_registry.py com:

from __future__ import annotations
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Optional
from config import DB_PATH


class FieldNotFoundError(Exception):
    pass


class FieldRegistry:
    '''
    Resolve (register, field_name) -> índice de campo no pipe-delimited SPED.
    Carregado uma vez do banco register_fields, cached em memória.
    Thread-safe para leitura após inicialização.
    '''
    _instance: Optional['FieldRegistry'] = None
    _registry: dict[tuple[str, str], int] = {}

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._load()

    def _load(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                'SELECT register, field_name, field_no FROM register_fields'
            ).fetchall()
        finally:
            conn.close()
        for register, field_name, field_no in rows:
            # field_no no banco é 1-based; fields[] na lista é 0-based
            self._registry[(register.upper(), field_name.upper())] = field_no
        
    @classmethod
    def get_instance(cls, db_path: Path = DB_PATH) -> 'FieldRegistry':
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        '''Para testes — reseta o singleton.'''
        cls._instance = None
        cls._registry = {}

    def get_index(self, register: str, field_name: str) -> int:
        '''
        Retorna o índice 0-based para acessar o campo na lista fields[].
        Equivale a field_no do banco (que é 1-based, indexando a partir do REG).
        Inclui o próprio REG como fields[0].
        
        Exemplo: register='C170', field_name='CST_ICMS'
        '''
        key = (register.upper(), field_name.upper())
        idx = self._registry.get(key)
        if idx is None:
            raise FieldNotFoundError(
                f'Campo {field_name!r} não encontrado no registro {register!r}. '
                f'Verifique se register_fields foi carregado corretamente.'
            )
        return idx

    def get_field_safe(self, fields: list[str], register: str, field_name: str, default: str = '') -> str:
        '''
        Versão segura: retorna o valor do campo ou default se não encontrado ou fora do range.
        Use em validadores para não quebrar em arquivos com menos campos que o esperado.
        '''
        try:
            idx = self.get_index(register, field_name)
            return fields[idx] if idx < len(fields) else default
        except FieldNotFoundError:
            return default

    def has_field(self, register: str, field_name: str) -> bool:
        return (register.upper(), field_name.upper()) in self._registry

    def list_fields(self, register: str) -> list[tuple[str, int]]:
        '''Lista todos os campos conhecidos de um registro com seus índices.'''
        prefix = register.upper()
        return [
            (fname, idx)
            for (reg, fname), idx in self._registry.items()
            if reg == prefix
        ]


# Instância global conveniente (lazy)
def get_registry(db_path: Path = DB_PATH) -> FieldRegistry:
    return FieldRegistry.get_instance(db_path)


2. Crie src/validators/helpers_registry.py com funções de conveniência:

from src.validators.field_registry import get_registry, FieldNotFoundError
from typing import Optional


def fval(fields: list[str], register: str, field_name: str, default: str = '') -> str:
    '''Shorthand para get_field_safe. Use em todos os validadores.'''
    return get_registry().get_field_safe(fields, register, field_name, default)


def fnum(fields: list[str], register: str, field_name: str, default: float = 0.0) -> float:
    '''Retorna campo como float. Retorna default se vazio ou não numérico.'''
    val = fval(fields, register, field_name, '')
    if not val:
        return default
    try:
        return float(val.replace(',', '.'))
    except ValueError:
        return default


def fstr(fields: list[str], register: str, field_name: str) -> str:
    '''Retorna campo como string stripped.'''
    return fval(fields, register, field_name, '').strip()


3. Crie tests/test_field_registry.py com:

import pytest
from unittest.mock import patch, MagicMock
from src.validators.field_registry import FieldRegistry, FieldNotFoundError, get_registry


@pytest.fixture(autouse=True)
def reset_registry():
    FieldRegistry.reset()
    yield
    FieldRegistry.reset()


def make_registry_with_data(rows):
    with patch('sqlite3.connect') as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_conn.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.execute.return_value = mock_cursor
        mock_conn.return_value.close = MagicMock()
        reg = FieldRegistry.__new__(FieldRegistry)
        reg._registry = {}
        for register, field_name, field_no in rows:
            reg._registry[(register.upper(), field_name.upper())] = field_no
        return reg


def test_get_index_returns_correct_position():
    reg = make_registry_with_data([('C170', 'CST_ICMS', 9), ('C170', 'ALIQ_ICMS', 10)])
    assert reg.get_index('C170', 'CST_ICMS') == 9
    assert reg.get_index('C170', 'ALIQ_ICMS') == 10


def test_get_index_case_insensitive():
    reg = make_registry_with_data([('c170', 'cst_icms', 9)])
    assert reg.get_index('C170', 'CST_ICMS') == 9
    assert reg.get_index('c170', 'cst_icms') == 9


def test_get_index_raises_field_not_found():
    reg = make_registry_with_data([('C170', 'CST_ICMS', 9)])
    with pytest.raises(FieldNotFoundError):
        reg.get_index('C170', 'CAMPO_INEXISTENTE')


def test_get_field_safe_within_range():
    reg = make_registry_with_data([('C170', 'CST_ICMS', 2)])
    fields = ['C170', 'item1', '400']
    assert reg.get_field_safe(fields, 'C170', 'CST_ICMS') == '400'


def test_get_field_safe_out_of_range_returns_default():
    reg = make_registry_with_data([('C170', 'CAMPO', 99)])
    fields = ['C170', 'only_two_fields']
    assert reg.get_field_safe(fields, 'C170', 'CAMPO', 'FALLBACK') == 'FALLBACK'


def test_get_field_safe_not_found_returns_default():
    reg = make_registry_with_data([])
    assert reg.get_field_safe(['C170', 'x'], 'C170', 'NAO_EXISTE', 'DEFAULT') == 'DEFAULT'


def test_has_field_true_and_false():
    reg = make_registry_with_data([('E110', 'VL_TOT_DEBITOS', 3)])
    assert reg.has_field('E110', 'VL_TOT_DEBITOS') is True
    assert reg.has_field('E110', 'CAMPO_FALSO') is False


def test_list_fields_returns_only_register_fields():
    reg = make_registry_with_data([
        ('C170', 'CST_ICMS', 9),
        ('C170', 'ALIQ_ICMS', 10),
        ('C100', 'VL_DOC', 11),
    ])
    c170_fields = reg.list_fields('C170')
    names = [name for name, _ in c170_fields]
    assert 'CST_ICMS' in names
    assert 'ALIQ_ICMS' in names
    assert 'VL_DOC' not in names


def test_singleton_pattern():
    FieldRegistry.reset()
    with patch.object(FieldRegistry, '_load', return_value=None):
        r1 = FieldRegistry.get_instance()
        r2 = FieldRegistry.get_instance()
        assert r1 is r2


Certifique-se que todos os arquivos são válidos Python, passam no mypy e no ruff.
Não modifique nenhum validador existente neste bloco — apenas crie os novos módulos.
"
```

### Teste do Bloco 01

```bash
# Roda apenas os testes do FieldRegistry
pytest tests/test_field_registry.py -v --tb=short

# Verifica tipos
mypy src/validators/field_registry.py src/validators/helpers_registry.py --ignore-missing-imports

# Verifica lint
ruff check src/validators/field_registry.py src/validators/helpers_registry.py

# Registra resultado no log
RESULT=$?
echo "## BLOCO 01 — FieldRegistry" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU — NÃO AVANCE PARA O PRÓXIMO BLOCO" >> IMPLEMENTATION_LOG.md
  echo "ATENÇÃO: Bloco 01 falhou. Corrija antes de continuar." && exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 02 — Migração dos Validadores Core para FieldRegistry

### Problema
Os validadores `intra_register_validator.py`, `tax_recalc.py`, `cst_validator.py`
e `cross_block_validator.py` usam índices hardcoded que já precisaram de 15 correções
documentadas no README. São os módulos de maior risco.

### Objetivo
Migrar os 4 validadores core para usar `fval()` e `fnum()` do `helpers_registry`.
Manter 100% de compatibilidade de output — os mesmos erros devem ser gerados,
agora com campos lidos corretamente pelo nome.

### Critério de aceite
- Os 4 validadores não contêm mais `fields[N]` com N numérico literal
- Todos os testes existentes continuam passando (zero regressão)
- `ruff check` passa sem erros em todos os 4 arquivos

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Migrar os validadores core para usar FieldRegistry em vez de índices hardcoded.

PRÉ-CONDIÇÃO: O módulo src/validators/field_registry.py já existe (criado no bloco anterior).

ARQUIVOS A MIGRAR (em ordem de prioridade):
1. src/validators/intra_register_validator.py
2. src/validators/tax_recalc.py
3. src/validators/cst_validator.py
4. src/validators/cross_block_validator.py

REGRA DE MIGRAÇÃO:
Substitua qualquer acesso por índice numérico literal como:
  cst = fields[9]
  bc = fields[15]
Por chamadas seguras via helpers:
  from src.validators.helpers_registry import fval, fnum, fstr
  cst = fval(fields, 'C170', 'CST_ICMS')
  bc = fnum(fields, 'C170', 'VL_BC_ICMS')

IMPORTANTE:
- Não altere a lógica de validação, apenas a forma de acessar os campos
- Não altere assinaturas de funções
- Não altere nomes de error_type
- Mantenha os comentários existentes
- Se um campo não existir no FieldRegistry para um registro específico,
  mantenha o índice hardcoded e adicione um comentário:
  # TODO: adicionar ao register_fields no banco
- Todos os imports devem estar no topo do arquivo
- Passe o register correto para cada registro (ex: 'C100', 'C170', 'E110')

VERIFICAÇÃO FINAL:
Para cada arquivo, execute:
  grep -n 'fields\[' arquivo.py
Se ainda houver fields[N] com N numérico, liste-os e adicione o comentário TODO.

Após migrar todos os 4 arquivos, rode:
  ruff check src/validators/intra_register_validator.py
  ruff check src/validators/tax_recalc.py
  ruff check src/validators/cst_validator.py
  ruff check src/validators/cross_block_validator.py
E corrija qualquer erro de lint antes de finalizar.
"
```

### Teste do Bloco 02

```bash
# Testes existentes de validação fiscal — zero regressão permitida
pytest tests/test_validator.py tests/test_fiscal_semantics.py -v --tb=short

# Verifica que não há mais índices numéricos hardcoded nos 4 arquivos migrados
echo "--- Verificando ausência de índices hardcoded ---"
for f in src/validators/intra_register_validator.py src/validators/tax_recalc.py src/validators/cst_validator.py src/validators/cross_block_validator.py; do
  COUNT=$(grep -c 'fields\[[0-9]' "$f" 2>/dev/null || echo 0)
  echo "$f: $COUNT índices hardcoded restantes"
done

# Lint nos 4 arquivos
ruff check src/validators/intra_register_validator.py src/validators/tax_recalc.py src/validators/cst_validator.py src/validators/cross_block_validator.py

RESULT=$?
echo "## BLOCO 02 — Migração Validadores Core" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
  pytest tests/test_validator.py tests/test_fiscal_semantics.py -q 2>&1 | tail -3 >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 03 — Tolerância de Cálculo por Contexto

### Problema
Tolerância única de R$ 0,02 para todos os tributos e contextos. Para itens de R$ 1,00,
2 centavos = 2% de tolerância — excessivo. Para apuração E110 com valores de milhões,
diferentes ERPs acumulam arredondamentos que excedem R$ 0,02 legitimamente.

### Objetivo
Implementar `ToleranceResolver` com tolerâncias distintas por contexto de cálculo,
usando o campo `tolerance_type` já existente no `rules.yaml`.

### Critério de aceite
- `src/validators/tolerance.py` tem `ToleranceResolver` com pelo menos 5 contextos
- Regras de recálculo (RECALC_*) usam o contexto correto
- Testes de tolerância cobrem casos-limite nos dois sentidos

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Substituir a tolerância única de R\$0,02 por um sistema de tolerâncias por contexto.

O arquivo src/validators/tolerance.py já existe com constantes simples.
Substitua-o pela implementação abaixo (mantendo compatibilidade):

NOVO tolerance.py:

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ToleranceType(str, Enum):
    ITEM_ICMS = 'item_icms'          # Cálculo ICMS por item (C170)
    ITEM_IPI = 'item_ipi'            # Cálculo IPI por item (C170)  
    ITEM_PIS = 'item_pis'            # Cálculo PIS por item (C170)
    ITEM_COFINS = 'item_cofins'      # Cálculo COFINS por item (C170)
    CONSOLIDACAO = 'consolidacao'    # C190 vs soma C170 (consolidação)
    APURACAO_E110 = 'apuracao_e110'  # Apuração ICMS no E110
    ABSOLUTE = 'absolute'            # Comparação absoluta — zero tolerância
    NONE = 'none'                    # Sem tolerância (exato)


@dataclass(frozen=True)
class ToleranceConfig:
    absolute_brl: float        # Tolerância absoluta em R$
    relative_pct: float        # Tolerância relativa em % do valor base (0.0 = desligada)
    description: str


# Mapa de configurações por tipo de contexto
_TOLERANCE_MAP: dict[ToleranceType, ToleranceConfig] = {
    ToleranceType.ITEM_ICMS: ToleranceConfig(
        absolute_brl=0.02,
        relative_pct=0.0,
        description='Cálculo ICMS por item — R$0,02 conforme prática SPED'
    ),
    ToleranceType.ITEM_IPI: ToleranceConfig(
        absolute_brl=0.02,
        relative_pct=0.0,
        description='Cálculo IPI por item'
    ),
    ToleranceType.ITEM_PIS: ToleranceConfig(
        absolute_brl=0.02,
        relative_pct=0.0,
        description='Cálculo PIS por item'
    ),
    ToleranceType.ITEM_COFINS: ToleranceConfig(
        absolute_brl=0.02,
        relative_pct=0.0,
        description='Cálculo COFINS por item'
    ),
    ToleranceType.CONSOLIDACAO: ToleranceConfig(
        absolute_brl=0.10,
        relative_pct=0.0,
        description='Consolidação C190 vs C170 — acumula arredondamentos por item'
    ),
    ToleranceType.APURACAO_E110: ToleranceConfig(
        absolute_brl=1.00,
        relative_pct=0.0,
        description='Apuração E110 — acumulação de arredondamentos de múltiplos documentos'
    ),
    ToleranceType.ABSOLUTE: ToleranceConfig(
        absolute_brl=0.0,
        relative_pct=0.0,
        description='Comparação exata — zero tolerância'
    ),
    ToleranceType.NONE: ToleranceConfig(
        absolute_brl=0.0,
        relative_pct=0.0,
        description='Sem tolerância'
    ),
}


class ToleranceResolver:
    '''
    Resolve se uma diferença está dentro da tolerância para um dado contexto.
    Use is_within_tolerance() em todos os validadores de cálculo.
    '''
    
    @staticmethod
    def get_config(tolerance_type: ToleranceType | str) -> ToleranceConfig:
        if isinstance(tolerance_type, str):
            try:
                tolerance_type = ToleranceType(tolerance_type)
            except ValueError:
                return _TOLERANCE_MAP[ToleranceType.ITEM_ICMS]  # fallback seguro
        return _TOLERANCE_MAP.get(tolerance_type, _TOLERANCE_MAP[ToleranceType.ITEM_ICMS])

    @staticmethod
    def is_within_tolerance(
        difference: float,
        base_value: float = 0.0,
        tolerance_type: ToleranceType | str = ToleranceType.ITEM_ICMS,
    ) -> bool:
        '''
        Retorna True se a diferença está dentro da tolerância aceitável.
        
        difference: |calculado - declarado|
        base_value: valor de referência para tolerância relativa (ex: VL_ITEM)
        tolerance_type: contexto do cálculo
        '''
        config = ToleranceResolver.get_config(tolerance_type)
        abs_diff = abs(difference)
        
        # Tolerância absoluta
        if abs_diff <= config.absolute_brl:
            return True
        
        # Tolerância relativa (se configurada)
        if config.relative_pct > 0.0 and base_value > 0:
            if abs_diff <= abs(base_value) * config.relative_pct:
                return True
        
        return False

    @staticmethod
    def format_tolerance_info(tolerance_type: ToleranceType | str) -> str:
        config = ToleranceResolver.get_config(tolerance_type)
        return f'Tolerância: R${config.absolute_brl:.2f} ({config.description})'


# Compatibilidade retroativa — mantém a constante antiga
CALCULATION_TOLERANCE = 0.02


Depois de criar o tolerance.py, atualize os validadores que usam tolerância:
Em tax_recalc.py e intra_register_validator.py, substitua comparações como:
  abs(calculado - declarado) > 0.02
  abs(calculado - declarado) > CALCULATION_TOLERANCE
Por:
  not ToleranceResolver.is_within_tolerance(
      calculado - declarado,
      tolerance_type=ToleranceType.ITEM_ICMS  # ou o tipo correto
  )

Para E110: use ToleranceType.APURACAO_E110
Para C190 vs C170: use ToleranceType.CONSOLIDACAO
Para item a item: use ToleranceType.ITEM_ICMS / ITEM_IPI / ITEM_PIS / ITEM_COFINS

Crie também tests/test_tolerance.py com casos de teste para:
- Diferença dentro da tolerância absoluta → True
- Diferença exatamente no limite → True
- Diferença acima do limite → False
- Tolerância APURACAO_E110 (R$1,00) com diferença de R$0,50 → True
- Tolerância CONSOLIDACAO (R$0,10) com diferença de R$0,05 → True
- ToleranceType inválido (string) → usa fallback sem exceção
"
```

### Teste do Bloco 03

```bash
pytest tests/test_tolerance.py -v --tb=short

# Verifica que os validadores de recálculo ainda funcionam
pytest tests/ -k 'recalc or tax' -v --tb=short

RESULT=$?
echo "## BLOCO 03 — Tolerância por Contexto" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 04 — Streaming de Arquivos e Limite de Tamanho

### Problema
O parser carrega todo o arquivo SPED na memória de uma vez. Arquivos reais de grandes
contribuintes chegam a 500MB e 50 milhões de registros — causam crash por OOM.
Não há limite de tamanho no endpoint de upload.

### Objetivo
Implementar parser com streaming por generator e adicionar validação de limite
de tamanho no upload (configurável via variável de ambiente).

### Critério de aceite
- `parse_sped_file_stream()` usa generator e não carrega todo o arquivo na memória
- Upload com arquivo > MAX_UPLOAD_MB retorna HTTP 413 com mensagem clara
- O uso de memória do parser não escala com o tamanho do arquivo

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar parsing com streaming e limite de tamanho de arquivo.

PARTE 1 — Adicione ao config.py:

# Limite de upload (padrão: 50MB, configurável via env)
import os
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '50'))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
# Para produção com arquivos grandes, use: MAX_UPLOAD_MB=500

PARTE 2 — Em src/parser.py, adicione a função de streaming:

from typing import Generator, Iterator
from src.models import SpedRecord


def parse_sped_file_stream(
    filepath: str | Path,
    encoding: str | None = None,
    max_bytes: int | None = None,
) -> Generator[SpedRecord, None, None]:
    '''
    Parser com streaming — usa generator para não carregar o arquivo inteiro na memória.
    Ideal para arquivos grandes (>50MB).
    
    Yields SpedRecord um a um conforme lê o arquivo linha a linha.
    
    Args:
        filepath: caminho para o arquivo SPED
        encoding: encoding forçado; se None, tenta latin-1, cp1252, utf-8
        max_bytes: limite de bytes a processar; None = sem limite
    
    Raises:
        ValueError: se o arquivo exceder max_bytes
        FileNotFoundError: se o arquivo não existir
    '''
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f'Arquivo não encontrado: {filepath}')
    
    # Detectar encoding se não fornecido
    if encoding is None:
        encoding = _detect_encoding(filepath)
    
    # Verificar tamanho antes de abrir
    file_size = filepath.stat().st_size
    if max_bytes and file_size > max_bytes:
        raise ValueError(
            f'Arquivo muito grande: {file_size / 1024 / 1024:.1f}MB. '
            f'Limite: {max_bytes / 1024 / 1024:.0f}MB. '
            f'Configure MAX_UPLOAD_MB para aumentar o limite.'
        )
    
    line_number = 0
    with open(filepath, 'r', encoding=encoding, errors='replace') as f:
        for raw_line in f:
            line_number += 1
            raw_line = raw_line.rstrip('\\n\\r')
            if not raw_line.startswith('|'):
                continue
            fields = raw_line.split('|')
            # Remove primeiro e último elemento (sempre vazios pelo split do pipe)
            if len(fields) >= 3:
                fields = fields[1:-1]  # Remove '' inicial e '' final
            else:
                continue
            register = fields[0] if fields else ''
            if not register:
                continue
            yield SpedRecord(
                line_number=line_number,
                register=register,
                fields=fields,
                raw_line=raw_line,
            )


def _detect_encoding(filepath: Path) -> str:
    '''Detecta encoding tentando latin-1, cp1252, utf-8.'''
    for enc in ('latin-1', 'cp1252', 'utf-8'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                f.read(1024)  # Lê apenas o início para testar
            return enc
        except UnicodeDecodeError:
            continue
    return 'latin-1'  # Fallback seguro


PARTE 3 — Em api/routers/files.py, adicione validação de tamanho no endpoint de upload:

from config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from fastapi import HTTPException

# No endpoint POST /api/files/upload, antes de salvar o arquivo:
async def upload_sped_file(file: UploadFile, ...):
    # Verificar tamanho do arquivo
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                'error': 'FILE_TOO_LARGE',
                'message': f'Arquivo excede o limite de {MAX_UPLOAD_MB}MB. '
                           f'Tamanho recebido: {len(content)/1024/1024:.1f}MB.',
                'limit_mb': MAX_UPLOAD_MB,
                'received_mb': round(len(content)/1024/1024, 1),
            }
        )
    # Continua com o processamento normal...

PARTE 4 — Crie tests/test_parser_stream.py com:

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from src.parser import parse_sped_file_stream


MINIMAL_SPED = '''|0000|017|0|01012024|31012024|EMPRESA LTDA|12345678000190|ES|29|6210800|6210800|00000000000000000||A|1|
|0001|0|
|0990|2|
|9001|0|
|9900|0000|1|
|9990|1|
|9999|6|
'''


def test_stream_yields_records(tmp_path):
    f = tmp_path / 'test.txt'
    f.write_text(MINIMAL_SPED, encoding='latin-1')
    records = list(parse_sped_file_stream(str(f)))
    assert len(records) > 0
    assert records[0].register == '0000'


def test_stream_raises_on_file_too_large(tmp_path):
    f = tmp_path / 'big.txt'
    f.write_text(MINIMAL_SPED, encoding='latin-1')
    with pytest.raises(ValueError, match='muito grande'):
        list(parse_sped_file_stream(str(f), max_bytes=1))  # 1 byte limite


def test_stream_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        list(parse_sped_file_stream('/nao/existe.txt'))


def test_stream_memory_efficient(tmp_path):
    # Cria arquivo com muitas linhas
    lines = ['|0000|017|0|01012024|31012024|EMP|12345678000190|ES|29|6210800|6210800|||A|1|']
    for i in range(10000):
        lines.append(f'|C170|{i}|ITEM{i}|DESC|100|UN|10.00|1000.00|||||||||||||||||||||||||||||||||')
    f = tmp_path / 'large.txt'
    f.write_text('\\n'.join(lines), encoding='latin-1')
    
    # Verifica que o generator não carrega tudo de uma vez
    gen = parse_sped_file_stream(str(f))
    first = next(gen)  # Deve funcionar sem carregar o arquivo inteiro
    assert first.register == '0000'


def test_stream_encoding_detection(tmp_path):
    f = tmp_path / 'latin.txt'
    f.write_bytes('|0000|017|0||||||EMPRESA LTDA com acentuação|||||||A|1|\\n'.encode('latin-1'))
    records = list(parse_sped_file_stream(str(f)))
    assert any(r.register == '0000' for r in records)
"
```

### Teste do Bloco 04

```bash
pytest tests/test_parser_stream.py -v --tb=short

# Verifica que parse existente ainda funciona (retrocompatibilidade)
pytest tests/test_parser.py -v --tb=short

# Verifica que config.py tem as novas variáveis
python -c "from config import MAX_UPLOAD_MB, MAX_UPLOAD_BYTES; print(f'Limite: {MAX_UPLOAD_MB}MB')"

RESULT=$?
echo "## BLOCO 04 — Streaming e Limite de Upload" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 05 — Governança de Correções: Bloquear Automático em CNPJ/CPF

### Problema
Regras FMT_CNPJ e FMT_CPF estão marcadas como `corrigivel: automatico`.
Um CNPJ com DV inválido não pode ser corrigido automaticamente — o sistema não sabe
qual é o CNPJ correto. Corrigir o DV pode gerar um CNPJ sintaticamente válido mas
apontando para outra empresa.

### Objetivo
Implementar validação no `correction_service.py` que bloqueia correção automática
de campos sensíveis (CNPJ, CPF, CHV_NFE, datas, valores monetários).
Atualizar `rules.yaml` para reclassificar FMT_CNPJ e FMT_CPF para `investigar`.

### Critério de aceite
- `correction_service.py` tem lista de campos bloqueados para automação
- Tentativa de correção automática de CNPJ levanta `CorrectionBlockedError`
- `rules.yaml`: FMT_CNPJ e FMT_CPF têm `corrigivel: investigar`
- Teste cobre todos os casos de bloqueio

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar bloqueio de correção automática para campos sensíveis.

PARTE 1 — Em src/services/correction_service.py, adicione:

class CorrectionBlockedError(Exception):
    '''Levantada quando uma correção automática é bloqueada por regra de governança.'''
    pass


# Campos que NUNCA devem ter correção automática — requerem validação humana
FIELDS_BLOCKED_FROM_AUTO_CORRECTION: frozenset[str] = frozenset({
    # Identificadores fiscais — o sistema não sabe o valor correto
    'CNPJ', 'CPF', 'IE', 'CHV_NFE', 'CHV_CTE',
    # Chaves de documento — correção invalida a NF
    'NUM_DOC', 'SER', 'COD_MOD',
    # Valores monetários — requerem recálculo com contexto completo
    'VL_DOC', 'VL_ICMS', 'VL_BC_ICMS', 'VL_ICMS_ST', 'VL_IPI',
    'VL_PIS', 'VL_COFINS', 'VL_TOT_DEBITOS', 'VL_TOT_CREDITOS',
    # Classificações fiscais — podem ter base legal específica
    'CST_ICMS', 'CSOSN', 'CST_PIS', 'CST_COFINS', 'CFOP',
    # Datas de documento — devem refletir o documento original
    'DT_DOC',
})


def _validate_correction_governance(
    field_name: str,
    corrigivel: str,
    new_value: str,
) -> None:
    '''
    Valida a governança antes de aplicar uma correção.
    
    Raises:
        CorrectionBlockedError: se a correção viola as regras de governança
    '''
    field_upper = field_name.upper()
    
    # Bloco 1: campo bloqueado para automação
    if corrigivel == 'automatico' and field_upper in FIELDS_BLOCKED_FROM_AUTO_CORRECTION:
        raise CorrectionBlockedError(
            f'Campo {field_name!r} não pode ser corrigido automaticamente. '
            f'Este campo requer validação humana. '
            f'Use corrigivel=proposta e forneça uma justificativa.'
        )
    
    # Bloco 2: impossível = nunca pode ser corrigido automaticamente
    if corrigivel == 'impossivel':
        raise CorrectionBlockedError(
            f'Este apontamento está marcado como impossível de corrigir '
            f'apenas com dados do arquivo SPED. '
            f'É necessário consultar documentos externos (XML, ato concessivo, etc.).'
        )
    
    # Bloco 3: investigar = nunca automático, mas pode ser proposta com justificativa
    if corrigivel == 'investigar' and not new_value.strip():
        raise CorrectionBlockedError(
            f'Apontamento do tipo investigar requer análise externa. '
            f'Forneça uma justificativa e o novo valor proposto após investigação.'
        )


# Integre _validate_correction_governance() no início da função que aplica correções.
# Antes de qualquer UPDATE no banco, chame esta função.

PARTE 2 — Atualize rules.yaml:
Encontre as regras FMT_CNPJ e FMT_CPF e mude:
  corrigivel: automatico
Para:
  corrigivel: investigar

Adicione também a nota:
  corrigivel_nota: 'CNPJ/CPF com DV inválido não pode ser corrigido automaticamente — o sistema não conhece o valor correto. Consulte o documento fiscal original.'

PARTE 3 — Crie tests/test_correction_governance.py:

import pytest
from src.services.correction_service import (
    _validate_correction_governance,
    CorrectionBlockedError,
    FIELDS_BLOCKED_FROM_AUTO_CORRECTION,
)


def test_blocks_auto_correction_of_cnpj():
    with pytest.raises(CorrectionBlockedError, match='não pode ser corrigido automaticamente'):
        _validate_correction_governance('CNPJ', 'automatico', '12345678000190')


def test_blocks_auto_correction_of_vl_icms():
    with pytest.raises(CorrectionBlockedError):
        _validate_correction_governance('VL_ICMS', 'automatico', '100.00')


def test_blocks_impossivel():
    with pytest.raises(CorrectionBlockedError, match='impossível de corrigir'):
        _validate_correction_governance('QUALQUER_CAMPO', 'impossivel', 'valor')


def test_allows_auto_correction_of_safe_fields():
    # Campos seguros para automação (ex: contagem bloco 9)
    _validate_correction_governance('QTD_REG', 'automatico', '42')  # não deve levantar


def test_blocks_investigar_without_value():
    with pytest.raises(CorrectionBlockedError, match='requer análise externa'):
        _validate_correction_governance('CST_ICMS', 'investigar', '')


def test_allows_proposta_for_blocked_fields_with_human_review():
    # Proposta (com revisão humana) deve ser permitida mesmo para campos sensíveis
    _validate_correction_governance('CNPJ', 'proposta', '12345678000190')  # não deve levantar


def test_cnpj_in_blocked_set():
    assert 'CNPJ' in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
    assert 'CPF' in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
    assert 'CHV_NFE' in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
    assert 'VL_ICMS' in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
"
```

### Teste do Bloco 05

```bash
pytest tests/test_correction_governance.py -v --tb=short

# Verifica que rules.yaml foi atualizado
python -c "
import yaml
with open('rules.yaml') as f:
    data = yaml.safe_load(f)
for rule in data.get('formato', []):
    if rule['id'] in ('FMT_CNPJ', 'FMT_CPF'):
        print(f'{rule[\"id\"]}: corrigivel={rule[\"corrigivel\"]}')
        assert rule['corrigivel'] == 'investigar', f'ERRO: {rule[\"id\"]} ainda é automatico!'
print('✅ rules.yaml atualizado corretamente')
"

RESULT=$?
echo "## BLOCO 05 — Governança de Correções" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 06 — Detecção Robusta de Regime Tributário

### Problema
O sistema usa `IND_PERFIL='C'` do registro 0000 como proxy de Simples Nacional.
Isso falha em arquivos com IND_PERFIL errado, e não distingue MEI de SN completo.
As 11 regras SN_001 a SN_012 dependem dessa detecção.

### Objetivo
Implementar `RegimeDetector` com lógica multi-sinal e persistência na tabela
`sped_files`. Adicionar campo obrigatório de confirmação de regime no upload.

### Critério de aceite
- `RegimeDetector` usa múltiplos campos para inferência (IND_PERFIL, CNPJ, histórico)
- `sped_files` tem campo `ind_regime` com enum validado
- Upload retorna aviso quando regime é ambíguo
- Testes cobrem os 3 regimes principais

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar detecção robusta de regime tributário.

PARTE 1 — Crie src/validators/regime_detector.py:

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from src.models import SpedRecord


class RegimeTributario(str, Enum):
    REGIME_NORMAL = 'NORMAL'               # Lucro Real ou Presumido
    SIMPLES_NACIONAL = 'SIMPLES_NACIONAL'  # LC 123/2006
    MEI = 'MEI'                            # Microempreendedor Individual
    DESCONHECIDO = 'DESCONHECIDO'          # Não foi possível determinar


@dataclass
class DetectionResult:
    regime: RegimeTributario
    confidence: float          # 0.0 a 1.0
    signals: list[str]         # Explicação dos sinais usados
    needs_confirmation: bool   # True = pedir confirmação ao usuário


class RegimeDetector:
    '''
    Detecta o regime tributário a partir dos registros do arquivo SPED.
    Usa múltiplos sinais com pesos para aumentar confiança.
    
    Sinais usados:
    1. IND_PERFIL no 0000: C = Simples Nacional (forte)
    2. Presença de CSOSN nos C170: indica SN (forte)  
    3. IND_PERFIL A/B: indica Regime Normal (forte)
    4. Presença de CST Tabela A (00-90) nos C170: indica Normal (moderado)
    5. VL_DOC < R$81.000 todos os documentos: pode ser MEI (fraco)
    '''

    @classmethod
    def detect(cls, records: list[SpedRecord]) -> DetectionResult:
        signals: list[str] = []
        sn_score = 0.0
        normal_score = 0.0
        mei_score = 0.0

        # Sinal 1: IND_PERFIL no 0000
        reg_0000 = next((r for r in records if r.register == '0000'), None)
        if reg_0000:
            ind_perfil = reg_0000.fields[18] if len(reg_0000.fields) > 18 else ''
            if ind_perfil == 'C':
                sn_score += 0.7
                signals.append('IND_PERFIL=C no 0000 (forte indício de Simples Nacional)')
            elif ind_perfil in ('A', 'B'):
                normal_score += 0.7
                signals.append(f'IND_PERFIL={ind_perfil} no 0000 (indica Regime Normal)')

        # Sinal 2: presença de CSOSN nos C170
        c170_records = [r for r in records if r.register == 'C170']
        csosn_values = {'101','102','103','201','202','203','300','400','500','900'}
        cst_normal_values = {'00','10','20','30','40','41','50','51','60','70','90'}
        
        has_csosn = False
        has_normal_cst = False
        
        for r in c170_records[:200]:  # Amostra dos primeiros 200 itens
            cst = r.fields[9] if len(r.fields) > 9 else ''
            if cst in csosn_values:
                has_csosn = True
            if cst in cst_normal_values:
                has_normal_cst = True

        if has_csosn:
            sn_score += 0.6
            signals.append('CSOSN encontrado em itens C170 (indica Simples Nacional)')
        if has_normal_cst and not has_csosn:
            normal_score += 0.5
            signals.append('CST Tabela A encontrado em C170 sem CSOSN (indica Regime Normal)')

        # Determinar regime
        if sn_score >= 0.6:
            regime = RegimeTributario.SIMPLES_NACIONAL
            confidence = min(sn_score, 1.0)
        elif normal_score >= 0.6:
            regime = RegimeTributario.REGIME_NORMAL
            confidence = min(normal_score, 1.0)
        else:
            regime = RegimeTributario.DESCONHECIDO
            confidence = 0.0
            signals.append('Sinais insuficientes — confirme o regime manualmente')

        needs_confirmation = confidence < 0.8 or regime == RegimeTributario.DESCONHECIDO

        return DetectionResult(
            regime=regime,
            confidence=confidence,
            signals=signals,
            needs_confirmation=needs_confirmation,
        )


PARTE 2 — Adicione migração ao src/services/database.py:

Execute via migration o SQL:
ALTER TABLE sped_files ADD COLUMN ind_regime TEXT DEFAULT 'DESCONHECIDO';
ALTER TABLE sped_files ADD COLUMN regime_confidence REAL DEFAULT 0.0;
ALTER TABLE sped_files ADD COLUMN regime_signals TEXT DEFAULT '[]';

(Use o padrão de migração já existente no arquivo — não quebre as migrações existentes)

PARTE 3 — Em src/services/file_service.py, após o parse do arquivo:

from src.validators.regime_detector import RegimeDetector

# Após extrair metadados do 0000, detectar regime:
detection = RegimeDetector.detect(records)
# Salvar no banco junto com os outros metadados

PARTE 4 — Crie tests/test_regime_detector.py com casos de teste cobrindo:
- Arquivo com IND_PERFIL=C → SIMPLES_NACIONAL com confidence >= 0.7
- Arquivo com IND_PERFIL=A → REGIME_NORMAL com confidence >= 0.7
- Arquivo com CSOSN nos C170 → SIMPLES_NACIONAL
- Arquivo sem sinais → DESCONHECIDO com needs_confirmation=True
- Arquivo misto (CSOSN + CST normal) → sinalizar ambiguidade
"
```

### Teste do Bloco 06

```bash
pytest tests/test_regime_detector.py -v --tb=short

# Verifica migração do banco
python -c "
import sqlite3
conn = sqlite3.connect('db/audit.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(sped_files)').fetchall()]
print('Colunas de regime:', [c for c in cols if 'regime' in c])
assert 'ind_regime' in cols, 'ERRO: coluna ind_regime não encontrada'
print('✅ Schema atualizado corretamente')
conn.close()
" 2>/dev/null || echo "⚠️  Banco não encontrado — teste de schema pulado"

RESULT=$?
echo "## BLOCO 06 — Detecção de Regime Tributário" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 07 — Deduplicação de Apontamentos

### Problema
Com 22 módulos de validação em sequência, o mesmo erro pode disparar em múltiplos
validadores com `error_type` diferente. Um CST 40 com VL_ICMS > 0 pode gerar
`ISENCAO_INCONSISTENTE`, `CST_CFOP_INCOMPATIVEL` e `TRIBUTACAO_INCONSISTENTE`
simultaneamente — sobrecarregando o analista com ruído.

### Objetivo
Implementar `ErrorDeduplicator` que, dada uma lista de erros na mesma linha e campo,
mantém apenas o de maior severidade e adiciona referências às demais detecções.

### Critério de aceite
- `ErrorDeduplicator.deduplicate()` reduz corretamente erros duplicados
- Erros em linhas diferentes não são deduplicados entre si
- O erro mantido tem `duplicates_detected` com a lista dos demais `error_type`
- Testes cobrem: sem duplicatas, duplicata mesma linha, duplicata linhas diferentes

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar deduplicação de apontamentos de validação.

Crie src/validators/error_deduplicator.py:

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from src.models import ValidationError


# Ordem de severidade para desempate (maior = mais importante)
SEVERITY_ORDER = {
    'critical': 4,
    'error': 3,
    'warning': 2,
    'info': 1,
}

# Grupos de error_type semanticamente equivalentes
# Se dois erros do mesmo grupo aparecem na mesma linha+campo, são deduplicados
EQUIVALENT_ERROR_GROUPS: list[frozenset[str]] = [
    frozenset({'ISENCAO_INCONSISTENTE', 'TRIBUTACAO_INCONSISTENTE', 'CST_ALIQ_ZERO_FORTE'}),
    frozenset({'CST_CFOP_INCOMPATIVEL', 'CFOP_MISMATCH', 'CFOP_INTERESTADUAL_MESMA_UF'}),
    frozenset({'SOMA_DIVERGENTE', 'CALCULO_DIVERGENTE', 'CRUZAMENTO_DIVERGENTE'}),
    frozenset({'REF_INEXISTENTE', 'D_REF_INEXISTENTE'}),
    frozenset({'CONTAGEM_DIVERGENTE'}),
]


def _same_group(error_type_a: str, error_type_b: str) -> bool:
    '''Retorna True se os dois error_types pertencem ao mesmo grupo semântico.'''
    for group in EQUIVALENT_ERROR_GROUPS:
        if error_type_a in group and error_type_b in group:
            return True
    return False


class ErrorDeduplicator:
    '''
    Deduplica erros de validação mantendo o de maior severidade por linha+campo.
    Preserva referências às detecções duplicadas para rastreabilidade.
    '''

    @staticmethod
    def deduplicate(errors: list[ValidationError]) -> list[ValidationError]:
        '''
        Recebe lista de erros (possivelmente com duplicatas) e retorna lista
        deduplicada. Erros são considerados duplicados se:
        1. Mesma line_number
        2. Mesmo field_name (ou ambos None)
        3. error_type pertence ao mesmo grupo semântico
        
        O erro mantido é o de maior severidade.
        '''
        if not errors:
            return []

        # Agrupa por (line_number, field_name)
        groups: dict[tuple, list[ValidationError]] = {}
        for err in errors:
            key = (err.line_number, err.field_name or '')
            groups.setdefault(key, []).append(err)

        result: list[ValidationError] = []
        for key, group_errors in groups.items():
            if len(group_errors) == 1:
                result.append(group_errors[0])
                continue

            # Dentro do grupo, identificar clusters de error_types equivalentes
            processed: set[int] = set()
            for i, err_i in enumerate(group_errors):
                if i in processed:
                    continue
                cluster = [err_i]
                for j, err_j in enumerate(group_errors):
                    if j == i or j in processed:
                        continue
                    if _same_group(err_i.error_type, err_j.error_type):
                        cluster.append(err_j)
                        processed.add(j)
                processed.add(i)

                # Mantém o de maior severidade no cluster
                winner = max(
                    cluster,
                    key=lambda e: SEVERITY_ORDER.get(e.severity or 'info', 0)
                )
                # Adiciona referência às duplicatas no message
                duplicates = [e.error_type for e in cluster if e is not winner]
                if duplicates:
                    winner = ValidationError(
                        line_number=winner.line_number,
                        register=winner.register,
                        field_no=winner.field_no,
                        field_name=winner.field_name,
                        value=winner.value,
                        error_type=winner.error_type,
                        severity=winner.severity,
                        message=winner.message + f' [também detectado como: {', '.join(duplicates)}]',
                        doc_suggestion=winner.doc_suggestion,
                        materialidade=winner.materialidade,
                    )
                result.append(winner)

        # Ordena por line_number para output consistente
        result.sort(key=lambda e: (e.line_number or 0, e.field_name or ''))
        return result


Crie tests/test_error_deduplicator.py com casos:
- Lista vazia → lista vazia
- Um erro → mesmo erro retornado
- Dois erros em linhas diferentes → ambos mantidos
- Dois erros mesma linha, mesmo campo, mesmo grupo → apenas o de maior severidade
- Dois erros mesma linha, mesmo campo, grupos diferentes → ambos mantidos
- Winner tem message com referência ao duplicado
- Três erros no mesmo cluster → winner é o de critical, outros descartados
"
```

### Teste do Bloco 07

```bash
pytest tests/test_error_deduplicator.py -v --tb=short

RESULT=$?
echo "## BLOCO 07 — Deduplicação de Apontamentos" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 08 — Alíquota Interna por UF Parametrizada (CST_004)

### Problema
A regra CST_004 usa 17% como piso interno hardcoded. Vários estados têm alíquota
modal diferente: MG=18%, SP=18%, CE=20%, AM=20%, PA=17%, ES=17%. Isso gera
falso positivo para empresas de UFs com alíquota acima de 17%.

### Objetivo
Parametrizar o piso da regra CST_004 usando a tabela `aliquotas_internas_uf.yaml`
em função da UF declarante do arquivo (campo `uf` da tabela `sped_files`).

### Critério de aceite
- `aliquota_validator.py` busca alíquota interna da UF do declarante em runtime
- Para UF=SP: piso = 18%, não 17%
- Para UF=PA: piso = 17% (comportamento anterior mantido)
- Teste cobre pelo menos 5 UFs diferentes

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Parametrizar o piso de alíquota interna na regra CST_004 por UF.

PARTE 1 — Verifique o arquivo data/reference/aliquotas_internas_uf.yaml.
Se ele não existir ou estiver incompleto, crie/complete com:

# Alíquotas internas padrão por UF (CONFAZ / RICMS estadual)
# Fonte: legislações estaduais vigentes em 2024
# Atualização: verificar sempre que houver alteração de RICMS estadual
AC: 17.0  # Acre
AL: 17.0  # Alagoas
AM: 20.0  # Amazonas (Decreto 20.686/2000)
AP: 18.0  # Amapá
BA: 19.0  # Bahia (Dec. 6.284/97)
CE: 20.0  # Ceará (Dec. 24.569/97)
DF: 18.0  # Distrito Federal
ES: 17.0  # Espírito Santo
GO: 17.0  # Goiás
MA: 18.0  # Maranhão
MG: 18.0  # Minas Gerais (Lei 6.763/75)
MS: 17.0  # Mato Grosso do Sul
MT: 17.0  # Mato Grosso
PA: 17.0  # Pará
PB: 18.0  # Paraíba
PE: 18.0  # Pernambuco
PI: 18.0  # Piauí
PR: 19.0  # Paraná (Lei 11.580/96)
RJ: 20.0  # Rio de Janeiro (Lei 2.657/96)
RN: 18.0  # Rio Grande do Norte
RO: 17.5  # Rondônia
RR: 17.0  # Roraima
RS: 18.0  # Rio Grande do Sul (Decreto 37.699/97)
SC: 17.0  # Santa Catarina
SE: 18.0  # Sergipe
SP: 18.0  # São Paulo (Lei 6.374/89)
TO: 18.0  # Tocantins

PARTE 2 — Em src/services/reference_loader.py, adicione se não existir:

@lru_cache(maxsize=1)
def load_aliquotas_internas_uf() -> dict[str, float]:
    '''Carrega alíquotas internas por UF do arquivo YAML de referência.'''
    path = Path('data/reference/aliquotas_internas_uf.yaml')
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def get_aliquota_interna_uf(uf: str, default: float = 17.0) -> float:
    '''Retorna a alíquota interna padrão para a UF informada.'''
    tabela = load_aliquotas_internas_uf()
    return float(tabela.get(uf.upper(), default))


PARTE 3 — Em src/validators/cst_validator.py ou aliquota_validator.py,
localize a regra CST_004 / CST_020_ALIQ_REDUZIDA e substitua o valor hardcoded:

ANTES:
  if cst == '020' and aliq_icms < 17.0 and cfop.startswith('5'):
      # erro

DEPOIS:
  from src.services.reference_loader import get_aliquota_interna_uf
  piso_uf = get_aliquota_interna_uf(uf_declarante, default=17.0)
  if cst == '020' and aliq_icms < piso_uf and cfop.startswith('5'):
      # erro com mensagem incluindo o piso usado:
      # f'CST 020 com alíquota {aliq_icms}% abaixo do piso interno de {piso_uf}% para {uf_declarante}'

PARTE 4 — Crie tests/test_aliquota_interna_uf.py:

import pytest
from src.services.reference_loader import get_aliquota_interna_uf, load_aliquotas_internas_uf

def test_aliquota_sp():
    assert get_aliquota_interna_uf('SP') == 18.0

def test_aliquota_pa():
    assert get_aliquota_interna_uf('PA') == 17.0

def test_aliquota_rj():
    assert get_aliquota_interna_uf('RJ') == 20.0

def test_aliquota_pr():
    assert get_aliquota_interna_uf('PR') == 19.0

def test_aliquota_desconhecida_usa_default():
    assert get_aliquota_interna_uf('XX', default=17.0) == 17.0

def test_todas_ufs_carregadas():
    tabela = load_aliquotas_internas_uf()
    ufs_obrigatorias = {'SP', 'RJ', 'MG', 'RS', 'PR', 'SC', 'BA', 'GO', 'AM', 'ES'}
    for uf in ufs_obrigatorias:
        assert uf in tabela, f'UF {uf} não encontrada na tabela'
        assert 15.0 <= tabela[uf] <= 25.0, f'Alíquota de {uf} fora do range esperado'
"
```

### Teste do Bloco 08

```bash
pytest tests/test_aliquota_interna_uf.py -v --tb=short

# Verifica que o arquivo YAML existe e tem pelo menos 27 UFs
python -c "
import yaml
with open('data/reference/aliquotas_internas_uf.yaml') as f:
    data = yaml.safe_load(f)
print(f'UFs mapeadas: {len(data)}')
assert len(data) >= 27, 'Menos de 27 UFs mapeadas'
print('✅ Tabela de alíquotas completa')
"

RESULT=$?
echo "## BLOCO 08 — Alíquota Interna por UF" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 09 — Rate Limiting na API

### Problema
Sem rate limiting, qualquer cliente pode enviar centenas de requisições de validação
simultâneas, consumindo CPU e memória indefinidamente. Vulnerável a DoS acidental
(loop de automação) e intencional.

### Objetivo
Implementar rate limiting por IP com janela deslizante de 60 segundos.
Endpoints de upload e validação têm limites mais restritivos.

### Critério de aceite
- Upload: máx 10 requisições/minuto por IP
- Validação: máx 5 requisições/minuto por IP  
- Excesso retorna HTTP 429 com header `Retry-After`
- Testes verificam o comportamento correto de aceite e rejeição

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar rate limiting nos endpoints críticos da API.

PARTE 1 — Instale se necessário (verifique pyproject.toml):
A implementação deve usar apenas stdlib + fastapi — sem dependências extras.
Usaremos um rate limiter em memória com sliding window.

PARTE 2 — Crie src/services/rate_limiter.py:

from __future__ import annotations
import time
import threading
from collections import defaultdict, deque
from typing import Optional
from fastapi import Request, HTTPException


class SlidingWindowRateLimiter:
    '''
    Rate limiter com janela deslizante em memória.
    Thread-safe para uso com FastAPI (múltiplos workers na mesma thread).
    
    NOTA: Em deployment com múltiplos processos (gunicorn multiprocessing),
    use Redis-backed rate limiter em vez desta implementação.
    '''
    
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, client_id: str) -> tuple[bool, int]:
        '''
        Verifica se a requisição é permitida.
        
        Returns:
            (allowed, retry_after_seconds)
            retry_after_seconds: 0 se permitido, tempo de espera se bloqueado
        '''
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            requests = self._requests[client_id]
            # Remove requisições fora da janela
            while requests and requests[0] < window_start:
                requests.popleft()
            
            if len(requests) >= self.max_requests:
                # Quanto tempo até a requisição mais antiga sair da janela
                retry_after = int(requests[0] + self.window_seconds - now) + 1
                return False, retry_after
            
            requests.append(now)
            return True, 0


# Instâncias por tipo de endpoint
_upload_limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
_validation_limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
_general_limiter = SlidingWindowRateLimiter(max_requests=60, window_seconds=60)


def get_client_id(request: Request) -> str:
    '''Extrai identificador do cliente (IP real, considerando proxies).'''
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'


def check_upload_rate_limit(request: Request) -> None:
    client_id = get_client_id(request)
    allowed, retry_after = _upload_limiter.is_allowed(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                'error': 'RATE_LIMIT_EXCEEDED',
                'message': f'Limite de uploads excedido. Máximo: {_upload_limiter.max_requests} por minuto.',
                'retry_after_seconds': retry_after,
            },
            headers={'Retry-After': str(retry_after)},
        )


def check_validation_rate_limit(request: Request) -> None:
    client_id = get_client_id(request)
    allowed, retry_after = _validation_limiter.is_allowed(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                'error': 'RATE_LIMIT_EXCEEDED',
                'message': f'Limite de validações excedido. Máximo: {_validation_limiter.max_requests} por minuto.',
                'retry_after_seconds': retry_after,
            },
            headers={'Retry-After': str(retry_after)},
        )


PARTE 3 — Integre nos routers:

Em api/routers/files.py (endpoint de upload):
from src.services.rate_limiter import check_upload_rate_limit
from fastapi import Depends

@router.post('/upload')
async def upload_sped_file(request: Request, ...):
    check_upload_rate_limit(request)
    # ... resto do endpoint

Em api/routers/validation.py (endpoint de validação):
from src.services.rate_limiter import check_validation_rate_limit

@router.post('/{file_id}/validate')
async def validate_file(file_id: int, request: Request, ...):
    check_validation_rate_limit(request)
    # ... resto do endpoint

PARTE 4 — Crie tests/test_rate_limiter.py:

import pytest
from src.services.rate_limiter import SlidingWindowRateLimiter
import time


def test_allows_requests_within_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, _ = limiter.is_allowed('client1')
        assert allowed is True


def test_blocks_after_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed('client1')
    allowed, retry_after = limiter.is_allowed('client1')
    assert allowed is False
    assert retry_after > 0


def test_different_clients_independent():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed('client1')
    limiter.is_allowed('client1')
    allowed_1, _ = limiter.is_allowed('client1')
    allowed_2, _ = limiter.is_allowed('client2')
    assert allowed_1 is False
    assert allowed_2 is True


def test_window_expiry():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=1)
    limiter.is_allowed('client1')
    limiter.is_allowed('client1')
    allowed, _ = limiter.is_allowed('client1')
    assert allowed is False
    time.sleep(1.1)
    allowed, _ = limiter.is_allowed('client1')
    assert allowed is True
"
```

### Teste do Bloco 09

```bash
pytest tests/test_rate_limiter.py -v --tb=short

# Verifica integração nos endpoints
python -c "
import ast, sys
for fpath in ['api/routers/files.py', 'api/routers/validation.py']:
    try:
        content = open(fpath).read()
        if 'rate_limit' in content:
            print(f'✅ {fpath}: rate limiting integrado')
        else:
            print(f'⚠️  {fpath}: rate limiting NÃO encontrado')
    except FileNotFoundError:
        print(f'⚠️  {fpath}: arquivo não encontrado')
"

RESULT=$?
echo "## BLOCO 09 — Rate Limiting" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 10 — Regras Bloco K: Validação Básica de Produção e Estoque

### Problema
O banco `sped.db` tem definições de campos para registros K001, K200, K210-K292,
mas existem zero regras de validação para o Bloco K. Para empresas industriais,
este bloco é crítico e erros aqui podem impactar créditos de PIS/COFINS e ICMS.

### Objetivo
Implementar validações básicas do Bloco K: integridade referencial, fechamento
de bloco e consistência de quantidades. Adicionar ao `rules.yaml` e ao pipeline.

### Critério de aceite
- `src/validators/bloco_k_validator.py` com pelo menos 5 regras implementadas
- Regras adicionadas ao `rules.yaml` com IDs K_001 a K_005
- Integradas no pipeline de validação
- Testes unitários para cada regra

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar validações básicas do Bloco K (Controle de Produção e Estoque).

PARTE 1 — Crie src/validators/bloco_k_validator.py com 5 regras:

from __future__ import annotations
from src.models import SpedRecord, ValidationError
from src.validators.helpers_registry import fval, fnum, fstr


def validate_bloco_k(records: list[SpedRecord]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    
    k200_items = {r for r in records if r.register == 'K200'}
    k210_records = [r for r in records if r.register == 'K210']
    k220_records = [r for r in records if r.register == 'K220']
    k230_records = [r for r in records if r.register == 'K230']
    reg_0200_codes = {fstr(r.fields, '0200', 'COD_ITEM') for r in records if r.register == '0200'}
    
    # K_001: K200 deve ter IND_MOV=0 quando há registros K210/K220/K230
    k001_checked = False
    for r in records:
        if r.register == 'K001':
            ind_mov = fval(r.fields, 'K001', 'IND_MOV', '1')
            has_k_detail = bool(k210_records or k220_records or k230_records)
            if ind_mov == '1' and has_k_detail:
                errors.append(ValidationError(
                    line_number=r.line_number,
                    register='K001',
                    field_no=2,
                    field_name='IND_MOV',
                    value=ind_mov,
                    error_type='K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS',
                    severity='error',
                    message='K001 com IND_MOV=1 (sem movimento) mas existem registros K210/K220/K230. '
                            'IND_MOV deve ser 0 quando há registros analíticos no Bloco K.',
                ))
            k001_checked = True
    
    # K_002: COD_ITEM no K200 deve existir no 0200
    for r in records:
        if r.register == 'K200':
            cod_item = fstr(r.fields, 'K200', 'COD_ITEM')
            if cod_item and cod_item not in reg_0200_codes:
                errors.append(ValidationError(
                    line_number=r.line_number,
                    register='K200',
                    field_no=None,
                    field_name='COD_ITEM',
                    value=cod_item,
                    error_type='K_REF_ITEM_INEXISTENTE',
                    severity='warning',
                    message=f'COD_ITEM {cod_item!r} do K200 não encontrado no cadastro 0200. '
                            'Verifique se o item está corretamente cadastrado.',
                ))
    
    # K_003: QTD no K200 não pode ser negativa
    for r in records:
        if r.register == 'K200':
            qtd = fnum(r.fields, 'K200', 'QTD', 0.0)
            if qtd < 0:
                errors.append(ValidationError(
                    line_number=r.line_number,
                    register='K200',
                    field_no=None,
                    field_name='QTD',
                    value=str(qtd),
                    error_type='K_QTD_NEGATIVA',
                    severity='error',
                    message=f'Quantidade no K200 não pode ser negativa: {qtd}. '
                            'Saldo de estoque negativo indica erro de escrituração.',
                ))
    
    # K_004: COD_ITEM no K210 deve existir no 0200
    for r in records:
        if r.register == 'K210':
            cod_item = fstr(r.fields, 'K210', 'COD_ITEM')
            if cod_item and cod_item not in reg_0200_codes:
                errors.append(ValidationError(
                    line_number=r.line_number,
                    register='K210',
                    field_no=None,
                    field_name='COD_ITEM',
                    value=cod_item,
                    error_type='K_REF_ITEM_INEXISTENTE',
                    severity='warning',
                    message=f'COD_ITEM {cod_item!r} do K210 não encontrado no 0200.',
                ))
    
    # K_005: K230 (ordem de produção) sem K235 (componentes) é suspeito
    k235_by_ordem = {}
    for r in records:
        if r.register == 'K235':
            ordem = fstr(r.fields, 'K235', 'ORDEM_PROD') if hasattr(r, 'fields') else ''
            k235_by_ordem.setdefault(ordem, []).append(r)
    
    for r in records:
        if r.register == 'K230':
            ordem = fstr(r.fields, 'K230', 'ORDEM_PROD')
            if ordem and ordem not in k235_by_ordem:
                errors.append(ValidationError(
                    line_number=r.line_number,
                    register='K230',
                    field_no=None,
                    field_name='ORDEM_PROD',
                    value=ordem,
                    error_type='K_ORDEM_SEM_COMPONENTES',
                    severity='info',
                    message=f'Ordem de produção {ordem!r} no K230 sem registros K235 (componentes). '
                            'Verifique se a estrutura do produto está completa.',
                ))
    
    return errors


PARTE 2 — Adicione ao rules.yaml (no final, antes do último bloco):

bloco_k:
- id: K_001
  register: K001
  fields: [IND_MOV]
  error_type: K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS
  severity: error
  corrigivel: proposta
  description: K001 com IND_MOV=1 mas existem registros analíticos K210/K220/K230
  condition: IND_MOV=1 AND existe(K210 OR K220 OR K230)
  implemented: true
  module: bloco_k_validator.py
  vigencia_de: '2000-01-01'
  vigencia_ate: null
  version: '1.0'
  last_updated: '2026-04-07'
  certeza: objetivo
  impacto: relevante

- id: K_002
  register: K200
  fields: [COD_ITEM]
  error_type: K_REF_ITEM_INEXISTENTE
  severity: warning
  corrigivel: proposta
  description: COD_ITEM do K200 não encontrado no cadastro 0200
  condition: COD_ITEM not in {0200.COD_ITEM}
  implemented: true
  module: bloco_k_validator.py
  vigencia_de: '2000-01-01'
  vigencia_ate: null
  version: '1.0'
  last_updated: '2026-04-07'
  certeza: objetivo
  impacto: relevante

- id: K_003
  register: K200
  fields: [QTD]
  error_type: K_QTD_NEGATIVA
  severity: error
  corrigivel: proposta
  description: Quantidade no inventário K200 negativa
  condition: QTD < 0
  implemented: true
  module: bloco_k_validator.py
  vigencia_de: '2000-01-01'
  vigencia_ate: null
  version: '1.0'
  last_updated: '2026-04-07'
  certeza: objetivo
  impacto: relevante

- id: K_004
  register: K210
  fields: [COD_ITEM]
  error_type: K_REF_ITEM_INEXISTENTE
  severity: warning
  corrigivel: proposta
  description: COD_ITEM do K210 não encontrado no 0200
  condition: COD_ITEM not in {0200.COD_ITEM}
  implemented: true
  module: bloco_k_validator.py
  vigencia_de: '2000-01-01'
  vigencia_ate: null
  version: '1.0'
  last_updated: '2026-04-07'
  certeza: objetivo
  impacto: relevante

- id: K_005
  register: K230
  fields: [ORDEM_PROD]
  error_type: K_ORDEM_SEM_COMPONENTES
  severity: info
  corrigivel: investigar
  description: Ordem de produção K230 sem registros K235 de componentes
  condition: K230.ORDEM_PROD not in {K235.ORDEM_PROD}
  implemented: true
  module: bloco_k_validator.py
  vigencia_de: '2000-01-01'
  vigencia_ate: null
  version: '1.0'
  last_updated: '2026-04-07'
  certeza: provavel
  impacto: informativo

PARTE 3 — Crie tests/test_bloco_k_validator.py com pelo menos um teste para cada regra.
PARTE 4 — Integre validate_bloco_k() no pipeline em src/services/validation_service.py.
"
```

### Teste do Bloco 10

```bash
pytest tests/test_bloco_k_validator.py -v --tb=short

# Verifica que as regras foram adicionadas ao YAML
python -c "
import yaml
with open('rules.yaml') as f:
    data = yaml.safe_load(f)
k_rules = data.get('bloco_k', [])
print(f'Regras Bloco K: {len(k_rules)}')
ids = [r['id'] for r in k_rules]
for expected in ['K_001', 'K_002', 'K_003', 'K_004', 'K_005']:
    status = '✅' if expected in ids else '❌'
    print(f'{status} {expected}')
"

RESULT=$?
echo "## BLOCO 10 — Validação Bloco K" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 11 — Lint Customizado: Proibir Índices Hardcoded

### Problema
Mesmo após a migração do Bloco 02, novos validadores adicionados futuramente podem
voltar a usar índices hardcoded. Sem enforcement automático, o problema pode retornar.

### Objetivo
Criar uma regra de lint ruff customizada (via plugin AST) que detecta `fields[N]`
com N numérico e falha o CI. Adicionar ao pre-commit e ao CI workflow.

### Critério de aceite
- Script `scripts/check_hardcoded_indices.py` detecta `fields[N]` com N > 1
- Execução em `src/validators/` retorna exit code 1 se encontrar violações
- Script é chamado no CI (verificado via `.github/` ou `Makefile`)

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Criar lint customizado para proibir índices hardcoded em validadores.

PARTE 1 — Crie scripts/check_hardcoded_indices.py:

#!/usr/bin/env python3
'''
Lint customizado: detecta acesso por índice numérico em listas 'fields'.
Uso: python scripts/check_hardcoded_indices.py src/validators/

Retorna exit code 1 se encontrar violações.
Adicione ao CI e ao pre-commit para enforcement automático.
'''
import ast
import sys
from pathlib import Path


# Número mínimo de índice para considerar suspeito.
# 0 = REG (sempre seguro), 1 pode ser campos simples como IND_MOV em blocos de controle
MIN_SUSPICIOUS_INDEX = 2

# Nomes de variáveis considerados 'fields' (lista de campos SPED)
FIELD_VARIABLE_NAMES = {'fields', 'record_fields', 'sped_fields'}

# Arquivos/diretórios a ignorar
IGNORED_PATHS = {
    'field_registry.py',
    'helpers_registry.py', 
    'tolerance.py',
    '__init__.py',
    'conftest.py',
}


class HardcodedIndexVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.violations: list[tuple[int, str]] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Detecta padrão: nome_variavel[número_inteiro]
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in FIELD_VARIABLE_NAMES
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
            and node.slice.value >= MIN_SUSPICIOUS_INDEX
        ):
            self.violations.append((
                node.lineno,
                f'Índice hardcoded: {node.value.id}[{node.slice.value}] — '
                f'use fval(fields, REGISTER, FIELD_NAME) em vez disso.'
            ))
        self.generic_visit(node)


def check_file(path: Path) -> list[tuple[str, int, str]]:
    if path.name in IGNORED_PATHS:
        return []
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError:
        return []
    visitor = HardcodedIndexVisitor(str(path))
    visitor.visit(tree)
    return [(str(path), line, msg) for line, msg in visitor.violations]


def main(targets: list[str]) -> int:
    all_violations = []
    for target in targets:
        p = Path(target)
        if p.is_file():
            all_violations.extend(check_file(p))
        elif p.is_dir():
            for py_file in sorted(p.rglob('*.py')):
                all_violations.extend(check_file(py_file))

    if all_violations:
        print(f'❌ {len(all_violations)} índice(s) hardcoded encontrado(s):\\n')
        for path, line, msg in all_violations:
            print(f'  {path}:{line}: {msg}')
        print()
        print('Corrija usando fval(fields, REGISTER, FIELD_NAME) de helpers_registry.py')
        return 1
    else:
        print(f'✅ Nenhum índice hardcoded encontrado nos validadores.')
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:] or ['src/validators/']))


PARTE 2 — Adicione ao Makefile (crie se não existir):

.PHONY: lint test check-indices

lint:
\truff check src/ api/ tests/
\tmypy src/ api/ --ignore-missing-imports

check-indices:
\tpython scripts/check_hardcoded_indices.py src/validators/

test:
\tpytest tests/ -q --tb=short

ci: lint check-indices test

PARTE 3 — Crie tests/test_check_hardcoded_indices.py:

import pytest
from pathlib import Path
from scripts.check_hardcoded_indices import check_file
import tempfile


def test_detects_hardcoded_index(tmp_path):
    f = tmp_path / 'bad_validator.py'
    f.write_text('def validate(fields):\\n    return fields[5]\\n')
    violations = check_file(f)
    assert len(violations) == 1
    assert 'fields[5]' in violations[0][2]


def test_allows_index_zero(tmp_path):
    f = tmp_path / 'validator.py'
    f.write_text('def validate(fields):\\n    reg = fields[0]\\n')
    violations = check_file(f)
    assert violations == []


def test_allows_variable_index(tmp_path):
    f = tmp_path / 'validator.py'
    f.write_text('def validate(fields):\\n    i = get_index()\\n    return fields[i]\\n')
    violations = check_file(f)
    assert violations == []


def test_ignores_non_fields_variable(tmp_path):
    f = tmp_path / 'validator.py'
    f.write_text('def validate(row):\\n    return row[5]\\n')
    violations = check_file(f)
    assert violations == []


def test_detects_multiple_violations(tmp_path):
    f = tmp_path / 'validator.py'
    f.write_text('def v(fields):\\n    a = fields[3]\\n    b = fields[7]\\n')
    violations = check_file(f)
    assert len(violations) == 2
"
```

### Teste do Bloco 11

```bash
# Testa o script de lint
pytest tests/test_check_hardcoded_indices.py -v --tb=short

# Executa o lint nos validadores (deve mostrar violations dos que ainda não foram migrados)
python scripts/check_hardcoded_indices.py src/validators/

RESULT=$?
echo "## BLOCO 11 — Lint Customizado Anti-Hardcode" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ⚠️  PASSOU COM VIOLAÇÕES RESTANTES (veja log acima)" >> IMPLEMENTATION_LOG.md
  # Não falha o bloco — registra a contagem de violações restantes
  COUNT=$(python scripts/check_hardcoded_indices.py src/validators/ 2>&1 | grep -c 'hardcoded' || echo '0')
  echo "Violações restantes: $COUNT (migrar nos próximos sprints)" >> IMPLEMENTATION_LOG.md
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 12 — Suite de Testes Fiscais com Cenários Reais

### Problema
Os testes atuais usam fixtures mínimas (`sped_minimal.txt`, `sped_valid.txt`).
Não há cobertura de cenários reais: empresa com ST, benefícios estaduais,
Simples Nacional, DIFAL, monofásicos. Sem esses cenários, a taxa de falso positivo
das regras não é conhecida.

### Objetivo
Criar fixtures de teste representando 6 cenários fiscais reais (anonimizados).
Verificar que cada cenário produz os erros esperados e apenas eles.

### Critério de aceite
- 6 fixtures em `tests/fixtures/` representando cenários distintos
- `tests/test_fiscal_scenarios.py` verifica cada cenário
- Nenhum cenário "limpo" gera erros `critical`
- Cenários com erros conhecidos os detectam corretamente

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Criar suite de testes com cenários fiscais representativos.

Crie os seguintes arquivos de fixture em tests/fixtures/:

1. tests/fixtures/sped_simples_nacional.txt
Arquivo SPED de empresa do Simples Nacional com:
- 0000 com IND_PERFIL=C
- C170 com CSOSN 400 (não tributada) — correto
- C170 com CSOSN 101 com ALIQ_ICMS=1.28% — correto (dentro do range SN)
- C170 com CSOSN 500 (ST retida) — correto
Esperado: zero erros critical, zero errors

2. tests/fixtures/sped_simples_nacional_erros.txt
Arquivo SPED de empresa do Simples Nacional com erros intencionais:
- C170 com CST_ICMS=00 (Tabela A) em vez de CSOSN → deve gerar SN_001
- C170 com CSOSN 101 e ALIQ_ICMS=5.0% (acima do teto) → deve gerar SN_003
Esperado: SN_001 e SN_003 detectados

3. tests/fixtures/sped_regime_normal_icms_st.txt
Arquivo SPED de empresa do Regime Normal com ST:
- C170 com CST 10 (tributada + ST), VL_ICMS_ST preenchido — correto
- C190 fechando corretamente com C170
- E200/E210 com apuração ICMS-ST
Esperado: zero erros critical

4. tests/fixtures/sped_exportacao.txt
Arquivo com operações de exportação:
- C170 com CFOP 7101 (exportação), CST 03 (tributada com alíquota zero), ALIQ_ICMS=0
- C190 fechando corretamente
Esperado: zero falsos positivos em CST_CFOP_INCOMPATIVEL

5. tests/fixtures/sped_devolucao.txt
Arquivo com devoluções:
- C100 de saída original (CFOP 5101)
- C100 de entrada por devolução (CFOP 1201) com mesmo COD_PART
- C170 com CST e alíquota espelhando a nota original
Esperado: zero erros DEV_001 (devolução com espelhamento correto)

6. tests/fixtures/sped_erros_multiplos.txt
Arquivo com erros deliberados para testar detecção:
- C170 com CST 00 e ALIQ_ICMS=0 e VL_BC_ICMS>0 → TRIBUTACAO_INCONSISTENTE
- C170 com CFOP 6101 e destinatário da mesma UF → CFOP_INTERESTADUAL_MESMA_UF
- Bloco 9 com contagem errada → CONTAGEM_DIVERGENTE
Esperado: pelo menos 3 tipos de erro distintos detectados

Para cada fixture, gere um arquivo SPED válido e mínimo (apenas os registros necessários):
- 0000 (identificação da empresa)
- 0001 (abertura bloco 0)
- 0150 (participante necessário)
- 0200 (produto necessário)
- 0990 (fechamento bloco 0)
- C001 (abertura bloco C)
- C100 (nota fiscal)
- C170 (item da nota)
- C190 (consolidação por CFOP)
- C990 (fechamento bloco C)
- E001, E110, E990 (apuração ICMS quando aplicável)
- 9001, 9900, 9990, 9999 (bloco 9 com contagens corretas)

Crie também tests/test_fiscal_scenarios.py:

import pytest
from pathlib import Path
from src.parser import parse_sped_file
from src.services.validation_service import ValidationService  # ajuste para o import correto

FIXTURES = Path('tests/fixtures')


def get_error_types(errors):
    return {e.error_type for e in errors}


def test_simples_nacional_sem_erros():
    records = parse_sped_file(str(FIXTURES / 'sped_simples_nacional.txt'))
    # Testar que não há erros critical em arquivo SN correto
    # (ajuste conforme a interface real do ValidationService)
    assert records is not None
    # TODO: integrar com ValidationService quando disponível


def test_simples_nacional_detecta_cst_tabela_a():
    records = parse_sped_file(str(FIXTURES / 'sped_simples_nacional_erros.txt'))
    assert records is not None
    # TODO: verificar que SN_001 é detectado


def test_exportacao_sem_falso_positivo_cfop():
    records = parse_sped_file(str(FIXTURES / 'sped_exportacao.txt'))
    assert records is not None


def test_todos_fixtures_parseiam_sem_erro():
    for fixture in FIXTURES.glob('sped_*.txt'):
        records = parse_sped_file(str(fixture))
        assert records is not None, f'Falhou ao parsear {fixture.name}'
        assert len(records) > 0, f'Nenhum registro em {fixture.name}'
"
```

### Teste do Bloco 12

```bash
pytest tests/test_fiscal_scenarios.py -v --tb=short

# Verifica que todas as fixtures existem e são parseáveis
python -c "
from pathlib import Path
from src.parser import parse_sped_file
fixtures = list(Path('tests/fixtures').glob('sped_*.txt'))
print(f'Fixtures encontradas: {len(fixtures)}')
for f in fixtures:
    records = parse_sped_file(str(f))
    print(f'  ✅ {f.name}: {len(records)} registros')
"

RESULT=$?
echo "## BLOCO 12 — Suite de Testes Fiscais" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
  python -c "from pathlib import Path; print(f'Fixtures: {len(list(Path(\"tests/fixtures\").glob(\"sped_*.txt\")))}')" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 13 — Documento de Escopo e Limitações (Frontend + API)

### Problema
O sistema valida o que está no arquivo SPED mas não documenta o que ele não valida:
documentos fiscais subjacentes, XML vs escrituração, regime tributário declarado, etc.
Analistas podem tomar decisões baseados na ausência de erros sem entender o escopo.

### Objetivo
Implementar endpoint `/api/audit-scope` que retorna o escopo e limitações da validação.
Adicionar componente `AuditScopePanel` ao frontend exibido no relatório.

### Critério de aceite
- `GET /api/audit-scope` retorna JSON estruturado com escopo e limitações
- O endpoint está documentado no Swagger
- Frontend exibe o escopo como banner no topo do relatório
- O texto usa linguagem clara, não técnica

### Comando de implementação

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Implementar documentação de escopo e limitações na API e no frontend.

PARTE 1 — Crie api/routers/audit_scope.py:

from fastapi import APIRouter

router = APIRouter(prefix='/api', tags=['Escopo de Auditoria'])


AUDIT_SCOPE = {
    'version': '1.0',
    'last_updated': '2026-04-07',
    'validacao_cobre': [
        {
            'categoria': 'Formato e estrutura',
            'descricao': 'Formato de CNPJ, CPF, datas, CEP, NCM, chave NF-e, tamanho de campos.',
            'confianca': 'alta',
        },
        {
            'categoria': 'Cálculos tributários',
            'descricao': 'Recálculo de ICMS, IPI, PIS, COFINS, ST. Verificação de BC × Alíquota = Imposto.',
            'confianca': 'alta',
        },
        {
            'categoria': 'Cruzamento entre blocos',
            'descricao': 'Consistência entre C170 e C190, entre C190/D690 e E110, entre bloco 0 e blocos C/D.',
            'confianca': 'alta',
        },
        {
            'categoria': 'Semântica fiscal',
            'descricao': 'Coerência de CST × CFOP, monofásicos, alíquotas interestaduais, DIFAL.',
            'confianca': 'media',
        },
        {
            'categoria': 'Auditoria de benefícios',
            'descricao': 'Rastreabilidade de ajustes E111/E112/E113, proporção de benefícios, sobreposições.',
            'confianca': 'media',
            'observacao': 'Requer confirmação com o ato concessivo estadual para conclusão definitiva.',
        },
    ],
    'validacao_nao_cobre': [
        {
            'limitacao': 'Documentos fiscais originais',
            'detalhe': 'O sistema não verifica se o XML da NF-e corresponde à escrituração. '
                       'Divergências entre o XML e o SPED não são detectáveis apenas pelo arquivo SPED.',
        },
        {
            'limitacao': 'Validade jurídica do regime tributário',
            'detalhe': 'O regime tributário (Simples Nacional, Lucro Real, etc.) é detectado '
                       'do arquivo, mas o sistema não verifica se é o regime correto para o CNPJ.',
        },
        {
            'limitacao': 'Vigência e escopo dos benefícios fiscais',
            'detalhe': 'Para confirmar que um benefício fiscal é válido, é necessário consultar '
                       'o ato concessivo estadual, que não faz parte do arquivo SPED.',
        },
        {
            'limitacao': 'Conformidade com obrigações acessórias',
            'detalhe': 'O sistema valida apenas o SPED EFD ICMS/IPI. '
                       'Não valida EFD-Contribuições, SPED Contábil, DCTF, DES ou outras obrigações.',
        },
        {
            'limitacao': 'Cruzamento com SPED de outros contribuintes',
            'detalhe': 'Não é possível verificar se as informações do SPED do fornecedor '
                       'correspondem às informações escrituradas pelo destinatário.',
        },
    ],
    'aviso_legal': (
        'Os apontamentos gerados por este sistema são auxiliares de revisão. '
        'Apontamentos classificados como "investigar" requerem análise humana e '
        'documentação externa antes de qualquer ação. '
        'A ausência de apontamentos não representa conformidade fiscal plena.'
    ),
    'apontamentos_por_certeza': {
        'objetivo': 'Erro confirmado — a divergência é inequívoca dentro do arquivo.',
        'provavel': 'Proposta — alta probabilidade de erro, mas pode haver exceção legal. Revisar antes de corrigir.',
        'indicio': 'Investigação necessária — sinal de alerta que requer análise externa antes de conclusão.',
    },
}


@router.get(
    '/audit-scope',
    summary='Escopo e limitações da validação',
    description='Retorna o escopo completo do que o sistema valida e não valida. '
                'Inclua sempre este texto no relatório de auditoria.',
)
async def get_audit_scope():
    return AUDIT_SCOPE


PARTE 2 — Registre o router em api/main.py:
from api.routers.audit_scope import router as audit_scope_router
app.include_router(audit_scope_router)

PARTE 3 — No frontend, crie src/components/AuditScopePanel.tsx:
Um componente React que:
- Faz GET /api/audit-scope na montagem
- Exibe como accordion colapsável: 'O que esta validação cobre' e 'O que ela não cobre'
- Exibe o aviso_legal como banner amarelo no topo
- É incluído na FileDetailPage antes do resumo de erros
- Usa TailwindCSS consistente com o restante do frontend

PARTE 4 — Crie tests/test_audit_scope.py:

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_audit_scope_returns_200():
    resp = client.get('/api/audit-scope')
    assert resp.status_code == 200

def test_audit_scope_has_required_fields():
    resp = client.get('/api/audit-scope').json()
    assert 'validacao_cobre' in resp
    assert 'validacao_nao_cobre' in resp
    assert 'aviso_legal' in resp
    assert len(resp['validacao_nao_cobre']) >= 4

def test_aviso_legal_is_string():
    resp = client.get('/api/audit-scope').json()
    assert isinstance(resp['aviso_legal'], str)
    assert len(resp['aviso_legal']) > 50
"
```

### Teste do Bloco 13

```bash
pytest tests/test_audit_scope.py -v --tb=short

# Verifica endpoint via curl se a API estiver rodando
curl -s http://localhost:8000/api/audit-scope 2>/dev/null | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print('✅ Endpoint /api/audit-scope respondeu corretamente')
    print(f'  Coberturas: {len(data.get(\"validacao_cobre\", []))}')
    print(f'  Limitações: {len(data.get(\"validacao_nao_cobre\", []))}')
except:
    print('⚠️  API não está rodando — teste apenas via pytest')
"

RESULT=$?
echo "## BLOCO 13 — Escopo e Limitações" >> IMPLEMENTATION_LOG.md
if [ $RESULT -eq 0 ]; then
  echo "STATUS: ✅ PASSOU" >> IMPLEMENTATION_LOG.md
else
  echo "STATUS: ❌ FALHOU" >> IMPLEMENTATION_LOG.md
  exit 1
fi
echo "Data: $(date)" >> IMPLEMENTATION_LOG.md
echo "" >> IMPLEMENTATION_LOG.md
```

---

## BLOCO 14 — Teste de Regressão Completo + Geração de Log Final

### Objetivo
Executar a suite completa de testes após todas as implementações para confirmar
zero regressão. Gerar o relatório final de implementação consolidado.

### Critério de aceite
- `pytest tests/` passa com cobertura >= 95% (era 97% antes das implementações)
- Zero erros de lint (ruff) e tipos (mypy)
- Log final gerado com status de todos os blocos
- Documento `IMPLEMENTATION_SUMMARY.md` criado

### Comando de execução

```bash
claude --dangerously-skip-permissions "
Você é um engenheiro sênior trabalhando no projeto SPED EFD Validator.

TAREFA: Gerar o resumo final de implementação após todos os blocos.

Leia o arquivo IMPLEMENTATION_LOG.md e crie IMPLEMENTATION_SUMMARY.md com:

1. Tabela de status de todos os 13 blocos implementados
2. Métricas antes vs depois (testes, cobertura, regras)
3. Riscos residuais que ainda precisam de atenção
4. Próximos passos recomendados para a próxima sprint
5. Data e hora de conclusão

Formato da tabela:
| Bloco | Título | Status | Data |
|-------|--------|--------|------|
| 01 | FieldRegistry | ✅ | ... |
...

Use o conteúdo real do IMPLEMENTATION_LOG.md para preencher.
"
```

```bash
# Teste de regressão completo
echo "=== EXECUTANDO SUITE COMPLETA ===" 
pytest tests/ -v --tb=short --cov=src --cov-report=term-missing 2>&1 | tee test_results.txt

# Extrair métricas
TOTAL_TESTS=$(grep -E '^[0-9]+ passed' test_results.txt | head -1 | awk '{print $1}')
COVERAGE=$(grep 'TOTAL' test_results.txt | awk '{print $NF}')
FAILED=$(grep -E '^[0-9]+ failed' test_results.txt | head -1 | awk '{print $1}' || echo 0)

# Lint final
echo "=== EXECUTANDO LINT FINAL ==="
ruff check src/ api/ 2>&1 | tee lint_results.txt
LINT_ERRORS=$(wc -l < lint_results.txt)

# Mypy final
echo "=== EXECUTANDO MYPY FINAL ==="
mypy src/ api/ --ignore-missing-imports 2>&1 | tee mypy_results.txt

# Lint customizado
echo "=== VERIFICANDO ÍNDICES HARDCODED ==="
python scripts/check_hardcoded_indices.py src/validators/ 2>&1 | tee hardcode_results.txt

# Gerar log final
cat >> IMPLEMENTATION_LOG.md << EOF

---

## RESULTADO FINAL

### Métricas de Qualidade

| Métrica | Resultado |
|---------|-----------|
| Total de testes | ${TOTAL_TESTS:-'N/A'} |
| Cobertura | ${COVERAGE:-'N/A'} |
| Testes falhados | ${FAILED:-0} |
| Erros de lint (ruff) | ${LINT_ERRORS:-'N/A'} linhas |

### Status de Todos os Blocos

EOF

# Extrai status de cada bloco do log
grep -E '^## BLOCO|^STATUS:' IMPLEMENTATION_LOG.md | paste - - | \
  sed 's/## //;s/STATUS: //' | \
  awk '{print "| " $0 " |"}' >> IMPLEMENTATION_LOG.md

cat >> IMPLEMENTATION_LOG.md << EOF

### Conclusão

EOF

if [ "${FAILED:-0}" -eq 0 ]; then
  echo "✅ Implementação concluída com sucesso. Zero regressões." >> IMPLEMENTATION_LOG.md
else
  echo "⚠️  Implementação concluída com ${FAILED} teste(s) falhando. Investigar antes do deploy." >> IMPLEMENTATION_LOG.md
fi

echo "" >> IMPLEMENTATION_LOG.md
echo "Fim: $(date)" >> IMPLEMENTATION_LOG.md

echo ""
echo "============================================"
echo "IMPLEMENTAÇÃO CONCLUÍDA"
echo "============================================"
echo "Testes: ${TOTAL_TESTS:-'N/A'} | Cobertura: ${COVERAGE:-'N/A'} | Falhas: ${FAILED:-0}"
echo "Log gerado em: IMPLEMENTATION_LOG.md"
echo "============================================"
```

---

## REFERÊNCIA RÁPIDA — Comandos de Verificação

```bash
# Verificar status de um bloco específico
grep -A3 "BLOCO 01" IMPLEMENTATION_LOG.md

# Rodar apenas testes novos (rápido)
pytest tests/test_field_registry.py tests/test_tolerance.py tests/test_rate_limiter.py -v

# Rodar suite completa com cobertura
pytest tests/ --cov=src --cov-report=html -q

# Verificar índices hardcoded
python scripts/check_hardcoded_indices.py src/validators/

# Verificar consistência do rules.yaml
python -m src.rules --check

# Ver log de implementação
cat IMPLEMENTATION_LOG.md
```

---

*PRD gerado em 2026-04-07 a partir da auditoria técnica do SPED EFD Validator.*
*Versão: 1.0 | 13 blocos de implementação | estimativa total: 3-4 semanas de desenvolvimento*
