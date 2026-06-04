from pipeline.enrichment.enrichers.cross_platform import CrossPlatformEnricher

def test_adapter_id_is_none():
    assert CrossPlatformEnricher.adapter_id is None

def test_extract_returns_list():
    enricher = CrossPlatformEnricher()
    result = enricher.extract([])
    assert isinstance(result, list)

def test_safe_extract_never_raises():
    enricher = CrossPlatformEnricher()
    assert enricher.safe_extract(None) == []
