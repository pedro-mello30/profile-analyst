"""Tests for BioEntityExtractor (spec-0017 §4)."""
import pytest

from pipeline.enrichment.extractors.bio import BioEntityExtractor


def test_extracts_email():
    hits = BioEntityExtractor().extract("Contato: pedro@vidacomia.com.br para parcerias")
    types = {h[0] for h in hits}
    assert "email" in types
    emails = [h[1] for h in hits if h[0] == "email"]
    assert "pedro@vidacomia.com.br" in emails


def test_extracts_cnpj_formatted():
    hits = BioEntityExtractor().extract("Empresa: 12.345.678/0001-90 | NF disponível")
    types = {h[0] for h in hits}
    assert "cnpj" in types
    cnpjs = [h[1] for h in hits if h[0] == "cnpj"]
    assert "12345678000190" in cnpjs


def test_extracts_cnpj_raw_digits():
    hits = BioEntityExtractor().extract("CNPJ 12345678000190")
    cnpjs = [h[1] for h in hits if h[0] == "cnpj"]
    assert "12345678000190" in cnpjs


def test_extracts_br_phone():
    hits = BioEntityExtractor().extract("WhatsApp: +55 31 99999-1234")
    types = {h[0] for h in hits}
    assert "phone" in types


def test_extracts_url_as_website_url():
    hits = BioEntityExtractor().extract("Acesse: https://vidacomia.com.br/cursos")
    types = {h[0] for h in hits}
    assert "website_url" in types


def test_extracts_domain_from_url():
    hits = BioEntityExtractor().extract("Acesse: https://vidacomia.com.br/cursos")
    domains = [h[1] for h in hits if h[0] == "domain"]
    assert "vidacomia.com.br" in domains


def test_skips_linktr_ee_domain():
    hits = BioEntityExtractor().extract("", website="https://linktr.ee/vidacomia")
    domains = [h[1] for h in hits if h[0] == "domain"]
    assert "linktr.ee" not in domains


def test_website_from_website_field():
    hits = BioEntityExtractor().extract("", website="https://vidacomia.com.br")
    urls = [h[1] for h in hits if h[0] == "website_url"]
    assert any("vidacomia.com.br" in u for u in urls)


def test_empty_bio_returns_empty():
    assert BioEntityExtractor().extract("") == []


def test_none_bio_returns_empty():
    assert BioEntityExtractor().extract(None) == []


def test_returns_list_of_tuples():
    hits = BioEntityExtractor().extract("hello@world.com")
    assert isinstance(hits, list)
    assert all(len(h) == 3 for h in hits)


def test_url_trailing_comma_does_not_corrupt_domain():
    hits = BioEntityExtractor().extract("Acesse https://vidacomia.com.br, obrigado")
    domains = [h[1] for h in hits if h[0] == "domain"]
    assert "vidacomia.com.br" in domains
    assert "vidacomia.com.br," not in domains


def test_cnpj_in_url_path_not_extracted():
    hits = BioEntityExtractor().extract("Nota em https://nfe.io/12345678000190/notas")
    cnpjs = [h[1] for h in hits if h[0] == "cnpj"]
    assert "12345678000190" not in cnpjs


def test_confidence_values():
    ext = BioEntityExtractor()
    assert ext.extract("x@y.com")[0][2] == 0.7
    cnpj_fmt = [h for h in ext.extract("12.345.678/0001-90") if h[0] == "cnpj"]
    assert cnpj_fmt[0][2] == 0.85
