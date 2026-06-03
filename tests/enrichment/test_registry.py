import json
import yaml
import jsonschema
import pytest
from pathlib import Path

CONFIG_DIR = Path("pipeline/enrichment/config")
SCHEMA_PATH = Path("pipeline/enrichment/schemas/adapter_config.schema.json")

EXPECTED_ADAPTERS = {
    "linktree", "whois", "crt", "knowledge_graph", "wikidata",
    "youtube", "itunes", "spotify", "github", "reddit", "twitch", "cnpj",
    "holehe", "ghunt", "hibp", "gdelt", "google_news", "substack", "maigret",
}


def test_schema_is_valid_json_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.Draft7Validator.check_schema(schema)


def test_all_19_adapters_configured():
    names = {f.stem for f in CONFIG_DIR.glob("*.yaml")}
    missing = EXPECTED_ADAPTERS - names
    assert not missing, f"Missing adapter configs: {missing}"


def test_all_yaml_files_valid_against_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = []
    for yaml_path in sorted(CONFIG_DIR.glob("*.yaml")):
        data = yaml.safe_load(yaml_path.read_text())
        if data.get("adapter_id") != yaml_path.stem:
            errors.append(f"{yaml_path.name}: adapter_id '{data.get('adapter_id')}' != filename '{yaml_path.stem}'")
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{yaml_path.name}: {e.message}")
    assert not errors, "\n".join(errors)


def test_osint_adapters_flagged():
    osint_adapters = {"holehe", "ghunt", "hibp", "maigret"}
    for name in osint_adapters:
        data = yaml.safe_load((CONFIG_DIR / f"{name}.yaml").read_text())
        assert data["osint_risk"] is True, f"{name} should have osint_risk=true"


def test_slow_tier_only_maigret():
    slow = [
        f.stem for f in CONFIG_DIR.glob("*.yaml")
        if yaml.safe_load(f.read_text()).get("tier") == "slow"
    ]
    assert slow == ["maigret"]


def test_hibp_requires_api_key():
    data = yaml.safe_load((CONFIG_DIR / "hibp.yaml").read_text())
    assert "HIBP_API_KEY" in data["secrets_required"]
