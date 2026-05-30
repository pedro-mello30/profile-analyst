"""make validate — checks schemas and spec metadata."""
import json
import sys
from pathlib import Path
import jsonschema
import yaml

ROOT = Path(__file__).parent.parent
SCHEMAS = ROOT / "schemas"
SPECS = ROOT / "specs"


def _load_json(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def validate_schemas():
    """Each schema file must be valid JSON Schema (draft-7)."""
    meta = _load_json(SCHEMAS / "meta-schema.json") if (SCHEMAS / "meta-schema.json").exists() else None
    errors = []
    for schema_file in sorted(SCHEMAS.glob("*.schema.json")):
        try:
            schema = _load_json(schema_file)
            if meta:
                jsonschema.validate(schema, meta)
            print(f"  ✓ {schema_file.name}")
        except Exception as e:
            errors.append(f"  ✗ {schema_file.name}: {e}")
    return errors


def validate_metadata():
    """Each spec's metadata.yml must have required fields."""
    required = {"id", "title", "status", "owner", "decisions", "acceptance"}
    errors = []
    for meta_file in sorted(SPECS.rglob("metadata.yml")):
        try:
            with open(meta_file) as f:
                data = yaml.safe_load(f)
            missing = required - set(data.keys())
            if missing:
                errors.append(f"  ✗ {meta_file}: missing fields: {missing}")
            else:
                print(f"  ✓ {meta_file.relative_to(ROOT)}")
        except Exception as e:
            errors.append(f"  ✗ {meta_file}: {e}")
    return errors


if __name__ == "__main__":
    print("Schemas:")
    errs = validate_schemas()
    print("Metadata:")
    errs += validate_metadata()

    if errs:
        print("\nErrors:")
        for e in errs:
            print(e)
        sys.exit(1)
    print("\nAll checks passed.")
