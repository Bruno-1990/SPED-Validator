"""Testes do xml_service — parser XML e cruzamento NF-e x SPED."""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.services.xml_service import (
    _norm_chave, _norm_cnpj, _norm_cfop, _norm_cst, _norm_ncm,
    _norm_date_iso, _to_float, parse_nfe_xml,
)


# ── Normalização ──

class TestNormalizacao:
    def test_chave_strip(self):
        assert _norm_chave(" 1234 5678 ") == "12345678"

    def test_chave_44_digitos(self):
        assert len(_norm_chave("32260112345678000199550010000012341000012345")) == 44

    def test_cnpj_formatado(self):
        assert _norm_cnpj("12.345.678/0001-99") == "12345678000199"

    def test_cnpj_curto(self):
        assert _norm_cnpj("123") == "00000000000123"

    def test_cfop_com_ponto(self):
        assert _norm_cfop("6.102") == "6102"

    def test_cfop_4_digitos(self):
        assert _norm_cfop("61021") == "6102"

    def test_cst_2_digitos(self):
        assert _norm_cst("00") == "000"

    def test_cst_3_digitos(self):
        assert _norm_cst("010") == "010"

    def test_ncm_com_pontos(self):
        assert _norm_ncm("3901.10.20") == "39011020"

    def test_ncm_limita_8(self):
        assert len(_norm_ncm("390110201")) == 8

    def test_date_iso(self):
        assert _norm_date_iso("2026-04-10T10:30:00-03:00") == "10042026"

    def test_date_iso_simples(self):
        """Data sem horário — converte para DDMMAAAA (formato SPED)."""
        assert _norm_date_iso("2026-04-10") == "10042026"

    def test_to_float(self):
        assert _to_float("1000.50") == 1000.50
        assert _to_float(None) == 0.0
        assert _to_float("abc") == 0.0


# ── Parser XML ──

_SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe32260112345678000199550010000012341000012345" versao="4.00">
      <ide>
        <nNF>1234</nNF>
        <serie>1</serie>
        <dhEmi>2026-04-10T10:30:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>12345678000199</CNPJ>
        <CRT>3</CRT>
      </emit>
      <dest>
        <CNPJ>98765432000188</CNPJ>
      </dest>
      <det nItem="1">
        <prod>
          <cProd>ABC123</cProd>
          <NCM>22030000</NCM>
          <CFOP>6102</CFOP>
          <vProd>1000.00</vProd>
        </prod>
        <imposto>
          <ICMS>
            <ICMS00>
              <orig>0</orig>
              <CST>00</CST>
              <vBC>1000.00</vBC>
              <pICMS>12.00</pICMS>
              <vICMS>120.00</vICMS>
            </ICMS00>
          </ICMS>
        </imposto>
      </det>
      <total>
        <ICMSTot>
          <vBC>1000.00</vBC>
          <vICMS>120.00</vICMS>
          <vST>0.00</vST>
          <vIPI>0.00</vIPI>
          <vPIS>16.50</vPIS>
          <vCOFINS>76.00</vCOFINS>
          <vNF>1000.00</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
  <protNFe versao="4.00">
    <infProt>
      <chNFe>32260112345678000199550010000012341000012345</chNFe>
      <cStat>100</cStat>
    </infProt>
  </protNFe>
</nfeProc>"""


class TestParseNfeXml:
    def test_parse_basico(self):
        result = parse_nfe_xml(_SAMPLE_XML)
        assert result is not None
        assert result["chave_nfe"] == "32260112345678000199550010000012341000012345"
        assert result["numero_nfe"] == "1234"
        assert result["serie"] == "1"
        assert result["cnpj_emitente"] == "12345678000199"
        assert result["cnpj_destinatario"] == "98765432000188"
        assert result["prot_cstat"] == "100"

    def test_totais(self):
        result = parse_nfe_xml(_SAMPLE_XML)
        assert result["vl_doc"] == 1000.00
        assert result["vl_icms"] == 120.00
        assert result["vl_icms_st"] == 0.0
        assert result["vl_ipi"] == 0.0

    def test_itens(self):
        result = parse_nfe_xml(_SAMPLE_XML)
        assert result["qtd_itens"] == 1
        item = result["itens"][0]
        assert item["num_item"] == 1
        assert item["cod_produto"] == "ABC123"
        assert item["ncm"] == "22030000"
        assert item["cfop"] == "6102"
        assert item["vl_prod"] == 1000.0
        assert item["cst_icms"] == "000"
        assert item["aliq_icms"] == 12.0
        assert item["vl_icms"] == 120.0

    def test_xml_malformado(self):
        assert parse_nfe_xml(b"<nao-e-xml") is None

    def test_xml_sem_nfe(self):
        assert parse_nfe_xml(b"<root><algo/></root>") is None

    def test_xml_cancelada(self):
        xml = _SAMPLE_XML.replace(b"<cStat>100</cStat>", b"<cStat>101</cStat>")
        result = parse_nfe_xml(xml)
        assert result["prot_cstat"] == "101"


# ── AI Service cache ──

class TestAiCache:
    def test_cache_key_deterministic(self):
        from src.services.ai_service import _build_cache_key
        k1 = _build_cache_key("RF001", "RF001_DEB", "normal", "ES")
        k2 = _build_cache_key("RF001", "RF001_DEB", "normal", "ES")
        assert k1 == k2

    def test_cache_key_varies_by_uf(self):
        from src.services.ai_service import _build_cache_key
        k1 = _build_cache_key("RF001", "RF001_DEB", "normal", "ES")
        k2 = _build_cache_key("RF001", "RF001_DEB", "normal", "SP")
        assert k1 != k2
