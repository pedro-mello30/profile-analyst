from pipeline.enrichment.enrichers.youtube import YouTubeEnricher

_FIXTURE = {
    "items": [{"id": "UCxyz1234567890123456789",
               "statistics": {"subscriberCount": "100000"},
               "snippet": {"country": "BR"}}]
}

def test_extracts_channel_id():
    enricher = YouTubeEnricher()
    entities = enricher.extract(_FIXTURE)
    assert any(e.type == "youtube_channel_id" for e in entities)

def test_empty_items_returns_empty():
    enricher = YouTubeEnricher()
    assert enricher.extract({"items": []}) == []

def test_safe_extract_on_empty_dict():
    enricher = YouTubeEnricher()
    assert YouTubeEnricher().safe_extract({}) == []

def test_no_http_imports():
    import ast, pathlib
    src = pathlib.Path("pipeline/enrichment/enrichers/youtube.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, 'names', [])
            names = [getattr(a, 'name', '') for a in mod]
            module = getattr(node, 'module', '') or ''
            assert 'requests' not in names and 'requests' not in module
            assert 'urllib.request' not in module
