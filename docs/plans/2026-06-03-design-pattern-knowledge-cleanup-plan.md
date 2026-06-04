# design-pattern-knowledge: Knowledge Base Cleanup & Cross-Reference Refactor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform 127 scraped markdown files into a clean, internally-navigable, schema-consistent
knowledge base by stripping promotional noise, removing broken images, converting external links to
relative paths, and standardizing frontmatter.

**Architecture:** Five composable Python scripts in `scripts/` operate on files in-place.
`cleanup.py` is the main runner that chains all transforms. `validate.py` is the CI gate.
Each transform is tested in isolation via a fixture file.

**Tech Stack:** Python 3.11+ · `python-frontmatter` (YAML parsing) · `re` (regex) · `pathlib` · `pytest`

**Spec:** `docs/plans/2026-06-03-design-pattern-knowledge-cleanup-spec.md`

---

### Task 1: Bootstrap — clone repo, install deps, confirm audit baseline

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/audit.py`
- Create: `requirements.txt`
- Create: `tests/__init__.py`

**Step 1: Clone the repo and set up a venv**

```bash
git clone https://github.com/pedro-mello30/design-pattern-knowledge.git
cd design-pattern-knowledge
python3 -m venv .venv && source .venv/bin/activate
echo "python-frontmatter\npytest" > requirements.txt
pip install -r requirements.txt
touch scripts/__init__.py tests/__init__.py
```

**Step 2: Write the audit script**

```python
# scripts/audit.py
"""Scans all .md files and reports issue counts — run before and after cleanup to diff."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKIP = {"README.md", "CLAUDE.md"}

PROMO = [r"Spring SALE", r"Tired of reading\?", r"Support our free website",
         r"browser does not support HTML video", r"own the eBook"]
EXT_IMG = re.compile(r"!\[.*?\]\(https://refactoring\.guru/images/")
EXT_LINK = re.compile(r"\[(?!!)[^\]]*\]\(https://refactoring\.guru/(?!images)")
BREADCRUMB = re.compile(r"^/ \[.*?\]\(https://refactoring\.guru", re.MULTILINE)

totals = dict(promo=0, images=0, ext_links=0, breadcrumbs=0)

for md in sorted(ROOT.glob("**/*.md")):
    if md.name in SKIP:
        continue
    text = md.read_text()
    for p in PROMO:
        if re.search(p, text):
            totals["promo"] += 1; break
    if EXT_IMG.search(text): totals["images"] += 1
    if EXT_LINK.search(text): totals["ext_links"] += 1
    if BREADCRUMB.search(text): totals["breadcrumbs"] += 1

print("Audit baseline:")
for k, v in totals.items():
    print(f"  {k}: {v} files")
```

**Step 3: Run the audit**

```bash
python scripts/audit.py
```

Expected output (approximate):
```
Audit baseline:
  promo: 125 files
  images: 125 files
  ext_links: 120 files
  breadcrumbs: 125 files
```

**Step 4: Commit**

```bash
git add scripts/__init__.py scripts/audit.py requirements.txt tests/__init__.py
git commit -m "chore: bootstrap — audit script + requirements"
```

---

### Task 2: Build the URL map (external URL → local relative path)

**Files:**
- Create: `scripts/url_map.py`
- Create: `tests/test_url_map.py`

**Step 1: Write the failing tests**

```python
# tests/test_url_map.py
from scripts.url_map import resolve_url

def test_creational_pattern():
    assert resolve_url("https://refactoring.guru/design-patterns/factory-method") == \
        "design-patterns/creational/factory-method.md"

def test_behavioral_pattern():
    assert resolve_url("https://refactoring.guru/design-patterns/observer") == \
        "design-patterns/behavioral/observer.md"

def test_technique_composing():
    assert resolve_url("https://refactoring.guru/extract-method") == \
        "refactoring/techniques/composing-methods/extract-method.md"

def test_technique_method_calls():
    assert resolve_url("https://refactoring.guru/introduce-parameter-object") == \
        "refactoring/techniques/simplifying-method-calls/introduce-parameter-object.md"

def test_technique_generalization():
    assert resolve_url("https://refactoring.guru/pull-up-method") == \
        "refactoring/techniques/dealing-with-generalization/pull-up-method.md"

def test_unknown_url_returns_none():
    assert resolve_url("https://refactoring.guru/store") is None
    assert resolve_url("https://refactoring.guru/refactoring/course") is None
```

**Step 2: Run tests to confirm failure**

```bash
pytest tests/test_url_map.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.url_map'`

**Step 3: Write `scripts/url_map.py`**

```python
# scripts/url_map.py
"""Maps every known refactoring.guru URL to its local relative path from repo root."""

_MAP: dict[str, str] = {
    # ── Design Patterns: Creational ────────────────────────────────────────────
    "https://refactoring.guru/design-patterns/factory-method":   "design-patterns/creational/factory-method.md",
    "https://refactoring.guru/design-patterns/abstract-factory": "design-patterns/creational/abstract-factory.md",
    "https://refactoring.guru/design-patterns/builder":          "design-patterns/creational/builder.md",
    "https://refactoring.guru/design-patterns/prototype":        "design-patterns/creational/prototype.md",
    "https://refactoring.guru/design-patterns/singleton":        "design-patterns/creational/singleton.md",
    # ── Design Patterns: Structural ────────────────────────────────────────────
    "https://refactoring.guru/design-patterns/adapter":          "design-patterns/structural/adapter.md",
    "https://refactoring.guru/design-patterns/bridge":           "design-patterns/structural/bridge.md",
    "https://refactoring.guru/design-patterns/composite":        "design-patterns/structural/composite.md",
    "https://refactoring.guru/design-patterns/decorator":        "design-patterns/structural/decorator.md",
    "https://refactoring.guru/design-patterns/facade":           "design-patterns/structural/facade.md",
    "https://refactoring.guru/design-patterns/flyweight":        "design-patterns/structural/flyweight.md",
    "https://refactoring.guru/design-patterns/proxy":            "design-patterns/structural/proxy.md",
    # ── Design Patterns: Behavioral ────────────────────────────────────────────
    "https://refactoring.guru/design-patterns/chain-of-responsibility": "design-patterns/behavioral/chain-of-responsibility.md",
    "https://refactoring.guru/design-patterns/command":          "design-patterns/behavioral/command.md",
    "https://refactoring.guru/design-patterns/iterator":         "design-patterns/behavioral/iterator.md",
    "https://refactoring.guru/design-patterns/mediator":         "design-patterns/behavioral/mediator.md",
    "https://refactoring.guru/design-patterns/memento":          "design-patterns/behavioral/memento.md",
    "https://refactoring.guru/design-patterns/observer":         "design-patterns/behavioral/observer.md",
    "https://refactoring.guru/design-patterns/state":            "design-patterns/behavioral/state.md",
    "https://refactoring.guru/design-patterns/strategy":         "design-patterns/behavioral/strategy.md",
    "https://refactoring.guru/design-patterns/template-method":  "design-patterns/behavioral/template-method.md",
    "https://refactoring.guru/design-patterns/visitor":          "design-patterns/behavioral/visitor.md",
    # ── Techniques: Composing Methods ──────────────────────────────────────────
    "https://refactoring.guru/extract-method":                   "refactoring/techniques/composing-methods/extract-method.md",
    "https://refactoring.guru/inline-method":                    "refactoring/techniques/composing-methods/inline-method.md",
    "https://refactoring.guru/extract-variable":                 "refactoring/techniques/composing-methods/extract-variable.md",
    "https://refactoring.guru/inline-temp":                      "refactoring/techniques/composing-methods/inline-temp.md",
    "https://refactoring.guru/replace-temp-with-query":          "refactoring/techniques/composing-methods/replace-temp-with-query.md",
    "https://refactoring.guru/split-temporary-variable":         "refactoring/techniques/composing-methods/split-temporary-variable.md",
    "https://refactoring.guru/remove-assignments-to-parameters": "refactoring/techniques/composing-methods/remove-assignments-to-parameters.md",
    "https://refactoring.guru/replace-method-with-method-object":"refactoring/techniques/composing-methods/replace-method-with-method-object.md",
    "https://refactoring.guru/substitute-algorithm":             "refactoring/techniques/composing-methods/substitute-algorithm.md",
    # ── Techniques: Moving Features Between Objects ────────────────────────────
    "https://refactoring.guru/move-method":                      "refactoring/techniques/moving-features-between-objects/move-method.md",
    "https://refactoring.guru/move-field":                       "refactoring/techniques/moving-features-between-objects/move-field.md",
    "https://refactoring.guru/extract-class":                    "refactoring/techniques/moving-features-between-objects/extract-class.md",
    "https://refactoring.guru/inline-class":                     "refactoring/techniques/moving-features-between-objects/inline-class.md",
    "https://refactoring.guru/hide-delegate":                    "refactoring/techniques/moving-features-between-objects/hide-delegate.md",
    "https://refactoring.guru/remove-middle-man":                "refactoring/techniques/moving-features-between-objects/remove-middle-man.md",
    "https://refactoring.guru/introduce-foreign-method":         "refactoring/techniques/moving-features-between-objects/introduce-foreign-method.md",
    "https://refactoring.guru/introduce-local-extension":        "refactoring/techniques/moving-features-between-objects/introduce-local-extension.md",
    # ── Techniques: Organizing Data ────────────────────────────────────────────
    "https://refactoring.guru/self-encapsulate-field":           "refactoring/techniques/organizing-data/self-encapsulate-field.md",
    "https://refactoring.guru/replace-data-value-with-object":   "refactoring/techniques/organizing-data/replace-data-value-with-object.md",
    "https://refactoring.guru/change-value-to-reference":        "refactoring/techniques/organizing-data/change-value-to-reference.md",
    "https://refactoring.guru/change-reference-to-value":        "refactoring/techniques/organizing-data/change-reference-to-value.md",
    "https://refactoring.guru/replace-array-with-object":        "refactoring/techniques/organizing-data/replace-array-with-object.md",
    "https://refactoring.guru/duplicate-observed-data":          "refactoring/techniques/organizing-data/duplicate-observed-data.md",
    "https://refactoring.guru/change-unidirectional-association-to-bidirectional": "refactoring/techniques/organizing-data/change-unidirectional-association-to-bidirectional.md",
    "https://refactoring.guru/change-bidirectional-association-to-unidirectional": "refactoring/techniques/organizing-data/change-bidirectional-association-to-unidirectional.md",
    "https://refactoring.guru/encapsulate-field":                "refactoring/techniques/organizing-data/encapsulate-field.md",
    "https://refactoring.guru/encapsulate-collection":           "refactoring/techniques/organizing-data/encapsulate-collection.md",
    "https://refactoring.guru/replace-magic-number-with-symbolic-constant": "refactoring/techniques/organizing-data/replace-magic-number-with-symbolic-constant.md",
    "https://refactoring.guru/replace-type-code-with-class":     "refactoring/techniques/organizing-data/replace-type-code-with-class.md",
    "https://refactoring.guru/replace-type-code-with-subclasses":"refactoring/techniques/organizing-data/replace-type-code-with-subclasses.md",
    "https://refactoring.guru/replace-type-code-with-state-strategy": "refactoring/techniques/organizing-data/replace-type-code-with-state-strategy.md",
    "https://refactoring.guru/replace-subclass-with-fields":     "refactoring/techniques/organizing-data/replace-subclass-with-fields.md",
    # ── Techniques: Simplifying Conditional Expressions ───────────────────────
    "https://refactoring.guru/decompose-conditional":            "refactoring/techniques/simplifying-conditional-expressions/decompose-conditional.md",
    "https://refactoring.guru/consolidate-conditional-expression": "refactoring/techniques/simplifying-conditional-expressions/consolidate-conditional-expression.md",
    "https://refactoring.guru/consolidate-duplicate-conditional-fragments": "refactoring/techniques/simplifying-conditional-expressions/consolidate-duplicate-conditional-fragments.md",
    "https://refactoring.guru/remove-control-flag":              "refactoring/techniques/simplifying-conditional-expressions/remove-control-flag.md",
    "https://refactoring.guru/replace-nested-conditional-with-guard-clauses": "refactoring/techniques/simplifying-conditional-expressions/replace-nested-conditional-with-guard-clauses.md",
    "https://refactoring.guru/replace-conditional-with-polymorphism": "refactoring/techniques/simplifying-conditional-expressions/replace-conditional-with-polymorphism.md",
    "https://refactoring.guru/introduce-null-object":            "refactoring/techniques/simplifying-conditional-expressions/introduce-null-object.md",
    "https://refactoring.guru/introduce-assertion":              "refactoring/techniques/simplifying-conditional-expressions/introduce-assertion.md",
    # ── Techniques: Simplifying Method Calls ───────────────────────────────────
    "https://refactoring.guru/rename-method":                    "refactoring/techniques/simplifying-method-calls/rename-method.md",
    "https://refactoring.guru/add-parameter":                    "refactoring/techniques/simplifying-method-calls/add-parameter.md",
    "https://refactoring.guru/remove-parameter":                 "refactoring/techniques/simplifying-method-calls/remove-parameter.md",
    "https://refactoring.guru/separate-query-from-modifier":     "refactoring/techniques/simplifying-method-calls/separate-query-from-modifier.md",
    "https://refactoring.guru/parameterize-method":              "refactoring/techniques/simplifying-method-calls/parameterize-method.md",
    "https://refactoring.guru/replace-parameter-with-explicit-methods": "refactoring/techniques/simplifying-method-calls/replace-parameter-with-explicit-methods.md",
    "https://refactoring.guru/preserve-whole-object":            "refactoring/techniques/simplifying-method-calls/preserve-whole-object.md",
    "https://refactoring.guru/replace-parameter-with-method-call": "refactoring/techniques/simplifying-method-calls/replace-parameter-with-method-call.md",
    "https://refactoring.guru/introduce-parameter-object":       "refactoring/techniques/simplifying-method-calls/introduce-parameter-object.md",
    "https://refactoring.guru/remove-setting-method":            "refactoring/techniques/simplifying-method-calls/remove-setting-method.md",
    "https://refactoring.guru/hide-method":                      "refactoring/techniques/simplifying-method-calls/hide-method.md",
    "https://refactoring.guru/replace-constructor-with-factory-method": "refactoring/techniques/simplifying-method-calls/replace-constructor-with-factory-method.md",
    "https://refactoring.guru/replace-error-code-with-exception":"refactoring/techniques/simplifying-method-calls/replace-error-code-with-exception.md",
    "https://refactoring.guru/replace-exception-with-test":      "refactoring/techniques/simplifying-method-calls/replace-exception-with-test.md",
    # ── Techniques: Dealing with Generalization ────────────────────────────────
    "https://refactoring.guru/pull-up-field":                    "refactoring/techniques/dealing-with-generalization/pull-up-field.md",
    "https://refactoring.guru/pull-up-method":                   "refactoring/techniques/dealing-with-generalization/pull-up-method.md",
    "https://refactoring.guru/pull-up-constructor-body":         "refactoring/techniques/dealing-with-generalization/pull-up-constructor-body.md",
    "https://refactoring.guru/push-down-method":                 "refactoring/techniques/dealing-with-generalization/push-down-method.md",
    "https://refactoring.guru/push-down-field":                  "refactoring/techniques/dealing-with-generalization/push-down-field.md",
    "https://refactoring.guru/extract-subclass":                 "refactoring/techniques/dealing-with-generalization/extract-subclass.md",
    "https://refactoring.guru/extract-superclass":               "refactoring/techniques/dealing-with-generalization/extract-superclass.md",
    "https://refactoring.guru/extract-interface":                "refactoring/techniques/dealing-with-generalization/extract-interface.md",
    "https://refactoring.guru/collapse-hierarchy":               "refactoring/techniques/dealing-with-generalization/collapse-hierarchy.md",
    "https://refactoring.guru/form-template-method":             "refactoring/techniques/dealing-with-generalization/form-template-method.md",
    "https://refactoring.guru/replace-inheritance-with-delegation": "refactoring/techniques/dealing-with-generalization/replace-inheritance-with-delegation.md",
    "https://refactoring.guru/replace-delegation-with-inheritance": "refactoring/techniques/dealing-with-generalization/replace-delegation-with-inheritance.md",
}


def resolve_url(url: str) -> str | None:
    """Returns the local relative path for a refactoring.guru URL, or None if unknown."""
    return _MAP.get(url.rstrip("/"))
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_url_map.py -v
```

Expected: 6 tests PASS.

**Step 5: Commit**

```bash
git add scripts/url_map.py tests/test_url_map.py
git commit -m "feat: URL map — all 95 refactoring.guru paths → local relative paths"
```

---

### Task 3: Build the content cleaner (promo noise + images + breadcrumbs)

**Files:**
- Create: `scripts/cleaner.py`
- Create: `tests/test_cleaner.py`
- Create: `tests/fixtures/dirty_pattern.md`

**Step 1: Create the test fixture**

Create `tests/fixtures/dirty_pattern.md`:

```markdown
---
url: https://refactoring.guru/design-patterns/factory-method
title: Factory Method
category: creational
---

[![](https://refactoring.guru/images/content-public/ann/spring/reading-book.svg?id=abc)Spring SALE![](https://refactoring.guru/images/pollen.svg?id=def)](https://refactoring.guru/store)

/ [Design Patterns](https://refactoring.guru/design-patterns)
/ [Creational Patterns](https://refactoring.guru/design-patterns/creational-patterns)

# Factory Method

## Intent

**Factory Method** is a creational design pattern.

![Structure](https://refactoring.guru/images/patterns/diagrams/factory-method/structure.png?id=xyz)

## Code Examples

[Java](https://refactoring.guru/design-patterns/factory-method#java) [C#](https://refactoring.guru/design-patterns/factory-method#csharp) [Python](https://refactoring.guru/design-patterns/factory-method#python)

```java
class Creator { }
```

[![Factory Method in Java](https://refactoring.guru/images/patterns/icons/java.svg?id=abc)](https://refactoring.guru/design-patterns/factory-method/java/example "Factory Method in Java")

[![](https://refactoring.guru/images/patterns/banners/patterns-book-banner-3.png?id=xyz)](https://refactoring.guru/design-patterns/book)

### Support our free website and own the eBook!

- 22 design patterns and 8 principles explained in depth.

[Learn more…](https://refactoring.guru/design-patterns/book)

### Tired of reading?

No wonder, it takes 7 hours to read all of the text we have here.

[Let's see…](https://refactoring.guru/refactoring/course)

[Your browser does not support HTML video.](https://refactoring.guru/refactoring/course)
```

**Step 2: Write the failing tests**

```python
# tests/test_cleaner.py
import pytest
from pathlib import Path
from scripts.cleaner import clean_body

FIXTURE = Path(__file__).parent / "fixtures" / "dirty_pattern.md"


def test_removes_sale_banner():
    assert "Spring SALE" not in clean_body(FIXTURE.read_text())


def test_removes_breadcrumb_navigation():
    assert "/ [Design Patterns]" not in clean_body(FIXTURE.read_text())


def test_removes_external_images():
    assert "refactoring.guru/images" not in clean_body(FIXTURE.read_text())


def test_removes_ebook_promotion():
    result = clean_body(FIXTURE.read_text())
    assert "own the eBook" not in result
    assert "Support our free website" not in result


def test_removes_tired_of_reading():
    assert "Tired of reading" not in clean_body(FIXTURE.read_text())


def test_removes_video_line():
    assert "browser does not support HTML video" not in clean_body(FIXTURE.read_text())


def test_removes_language_tab_row():
    result = clean_body(FIXTURE.read_text())
    assert "refactoring.guru/design-patterns/factory-method#java" not in result


def test_preserves_title_and_intent():
    result = clean_body(FIXTURE.read_text())
    assert "# Factory Method" in result
    assert "**Factory Method** is a creational design pattern." in result


def test_preserves_frontmatter():
    result = clean_body(FIXTURE.read_text())
    assert "url: https://refactoring.guru/design-patterns/factory-method" in result
    assert "title: Factory Method" in result


def test_preserves_code_blocks():
    result = clean_body(FIXTURE.read_text())
    assert "class Creator" in result
```

**Step 3: Run tests to confirm failure**

```bash
pytest tests/test_cleaner.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cleaner'`

**Step 4: Write `scripts/cleaner.py`**

```python
# scripts/cleaner.py
"""Strips promotional noise, broken images, and navigation breadcrumbs from scraped .md files."""
import re

# Spring SALE / promotional store banner (full [![...](...)](store) line)
_SALE_BANNER = re.compile(
    r'^\[?!\[.*?(?:Spring SALE|reading-book\.svg|pollen\.svg).*?\]\([^\)]*refactoring\.guru(?:/store)?[^\)]*\)\]?\(?[^\)]*\)?\s*$',
    re.MULTILINE,
)

# Breadcrumb navigation: / [Text](https://refactoring.guru/...)  (one or more on adjacent lines)
_BREADCRUMB = re.compile(
    r'^(?:/ \[[^\]]+\]\(https://refactoring\.guru[^\)]*\)\s*\n?)+',
    re.MULTILINE,
)

# External images: ![alt](https://refactoring.guru/images/...)
_EXT_IMAGE = re.compile(r'!\[[^\]]*\]\(https://refactoring\.guru/images/[^\)]+\)')

# Icon badge links: [![Pattern in Lang](icon-url)](example-url "tooltip")
_BADGE_LINK = re.compile(
    r'\[!\[[^\]]*\]\(https://refactoring\.guru/images/patterns/icons/[^\)]+\)\]\([^\)]+\)',
)

# Book banner section: from the book-banner image through "Learn more…" link
_BOOK_SECTION = re.compile(
    r'\[!\[.*?patterns-book-banner.*?\]\([^\)]+\)\].*?\[Learn more[^\]]*\]\([^\)]+\)',
    re.DOTALL,
)

# eBook promotional block: ### Support our free website ... through next heading or EOF
_EBOOK_BLOCK = re.compile(
    r'###\s+Support our free website.*?(?=\n##|\n###|\Z)',
    re.DOTALL,
)

# "Tired of reading?" block through next heading or EOF
_TIRED_BLOCK = re.compile(
    r'###\s+Tired of reading\?.*?(?=\n##|\n###|\Z)',
    re.DOTALL,
)

# "Your browser does not support HTML video." lines
_VIDEO_LINE = re.compile(r'^[^\n]*browser does not support HTML video[^\n]*\n?', re.MULTILINE)

# Language-tab link rows: [Java](url#java) [C#](url#csharp) ... (whole line, 2+ langs)
_LANG_TABS = re.compile(
    r'^\[(?:Java|C#|PHP|Python|TypeScript|Ruby|Rust|Go|Swift|C\+\+)\]\([^\)]+\)'
    r'(?:\s*\[(?:Java|C#|PHP|Python|TypeScript|Ruby|Rust|Go|Swift|C\+\+)\]\([^\)]+\))+\s*$',
    re.MULTILINE,
)


def clean_body(text: str) -> str:
    """Apply all cleanup transforms to a full .md file text (including frontmatter). Idempotent."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = "---" + parts[1] + "---"
            body = parts[2]
        else:
            fm, body = "", text
    else:
        fm, body = "", text

    body = _SALE_BANNER.sub("", body)
    body = _BREADCRUMB.sub("", body)
    body = _BOOK_SECTION.sub("", body)
    body = _EBOOK_BLOCK.sub("", body)
    body = _TIRED_BLOCK.sub("", body)
    body = _VIDEO_LINE.sub("", body)
    body = _BADGE_LINK.sub("", body)
    body = _EXT_IMAGE.sub("", body)
    body = _LANG_TABS.sub("", body)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()

    return (fm + "\n\n" + body + "\n") if fm else (body + "\n")
```

**Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_cleaner.py -v
```

Expected: 10 tests PASS.

**Step 6: Commit**

```bash
git add scripts/cleaner.py tests/test_cleaner.py tests/fixtures/dirty_pattern.md
git commit -m "feat: content cleaner — strips promo, images, breadcrumbs (10 tests)"
```

---

### Task 4: Build the cross-reference link converter

**Files:**
- Create: `scripts/cross_ref.py`
- Create: `tests/test_cross_ref.py`

**Step 1: Write failing tests**

```python
# tests/test_cross_ref.py
from scripts.cross_ref import convert_links


def test_technique_link_from_smell():
    body = "Use [Extract Method](https://refactoring.guru/extract-method) to fix this."
    result = convert_links(body, "refactoring/smells/bloaters/long-method.md")
    assert "../../techniques/composing-methods/extract-method.md" in result
    assert "refactoring.guru/extract-method" not in result


def test_pattern_link_from_smell():
    body = "See [Factory Method](https://refactoring.guru/design-patterns/factory-method)."
    result = convert_links(body, "refactoring/smells/bloaters/long-method.md")
    assert "../../../design-patterns/creational/factory-method.md" in result


def test_pattern_link_from_same_folder():
    body = "See [Mediator](https://refactoring.guru/design-patterns/mediator)."
    result = convert_links(body, "design-patterns/behavioral/observer.md")
    assert result == "See [Mediator](mediator.md)."


def test_unknown_url_is_unchanged():
    body = "Visit [the store](https://refactoring.guru/store)."
    result = convert_links(body, "design-patterns/creational/factory-method.md")
    assert "https://refactoring.guru/store" in result


def test_does_not_touch_frontmatter_url():
    body = "url: https://refactoring.guru/extract-method\n\n# Extract Method\n"
    result = convert_links(body, "refactoring/techniques/composing-methods/extract-method.md")
    assert "url: https://refactoring.guru/extract-method" in result
```

**Step 2: Run tests to confirm failure**

```bash
pytest tests/test_cross_ref.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cross_ref'`

**Step 3: Write `scripts/cross_ref.py`**

```python
# scripts/cross_ref.py
"""Converts refactoring.guru URLs in markdown link bodies to relative internal paths."""
import os
import re
from pathlib import Path
from scripts.url_map import resolve_url

_LINK_RE = re.compile(r'\[([^\]]+)\]\((https://refactoring\.guru/[^\)]+)\)')


def convert_links(body: str, source_path: str) -> str:
    """
    Replace refactoring.guru cross-reference URLs with relative paths.

    source_path: repo-root-relative path of the file being processed
                 (e.g. "refactoring/smells/bloaters/long-method.md")
    Frontmatter lines (starting with "url:") are left untouched because
    the regex only matches markdown link syntax [text](url).
    """
    src_dir = str(Path(source_path).parent)

    def _replace(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2).rstrip("/")
        target = resolve_url(url)
        if target is None:
            return m.group(0)
        rel = os.path.relpath(target, src_dir)
        return f"[{label}]({rel})"

    return _LINK_RE.sub(_replace, body)
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_cross_ref.py -v
```

Expected: 5 tests PASS.

**Step 5: Commit**

```bash
git add scripts/cross_ref.py tests/test_cross_ref.py
git commit -m "feat: cross-reference converter — external URLs → relative internal paths"
```

---

### Task 5: Build the frontmatter standardizer

**Files:**
- Create: `scripts/frontmatter_std.py`
- Create: `tests/test_frontmatter_std.py`

**Step 1: Write failing tests**

```python
# tests/test_frontmatter_std.py
from scripts.frontmatter_std import standardize_frontmatter


def test_pattern_gets_type_tags_category():
    raw = "---\nurl: https://refactoring.guru/design-patterns/factory-method\ntitle: Factory Method\ncategory: creational\n---\n\n# Body"
    result = standardize_frontmatter(raw, "design-patterns/creational/factory-method.md")
    assert "type: pattern" in result
    assert "category: design-patterns/creational" in result
    assert "creational" in result


def test_smell_gets_type_and_category():
    raw = "---\nurl: https://refactoring.guru/smells/long-method\ntitle: Long Method\ncategory: smells/bloaters\n---\n\n# Body"
    result = standardize_frontmatter(raw, "refactoring/smells/bloaters/long-method.md")
    assert "type: smell" in result
    assert "category: refactoring/smells/bloaters" in result


def test_technique_gets_type():
    raw = "---\nurl: https://refactoring.guru/extract-method\ntitle: Extract Method\ncategory: techniques/composing-methods\n---\n\n# Body"
    result = standardize_frontmatter(raw, "refactoring/techniques/composing-methods/extract-method.md")
    assert "type: technique" in result
    assert "category: refactoring/techniques/composing-methods" in result


def test_catalog_gets_type():
    raw = "---\nurl: https://refactoring.guru/design-patterns/catalog\ntitle: Catalog\ncategory: catalog\n---\n\n# Body"
    result = standardize_frontmatter(raw, "design-patterns/catalog/catalog.md")
    assert "type: catalog" in result


def test_tags_are_list():
    raw = "---\nurl: x\ntitle: T\ncategory: c\n---\n\n# B"
    result = standardize_frontmatter(raw, "design-patterns/behavioral/observer.md")
    assert "tags:" in result
    assert "behavioral" in result
```

**Step 2: Run tests to confirm failure**

```bash
pytest tests/test_frontmatter_std.py -v
```

Expected: FAIL.

**Step 3: Write `scripts/frontmatter_std.py`**

```python
# scripts/frontmatter_std.py
"""Normalizes YAML frontmatter to the canonical schema across all content files."""
import frontmatter
from pathlib import Path

_TYPE_MAP: dict[str, str] = {
    "design-patterns/creational":                        "pattern",
    "design-patterns/structural":                        "pattern",
    "design-patterns/behavioral":                        "pattern",
    "refactoring/smells/bloaters":                       "smell",
    "refactoring/smells/oo-abusers":                     "smell",
    "refactoring/smells/change-preventers":              "smell",
    "refactoring/smells/dispensables":                   "smell",
    "refactoring/smells/couplers":                       "smell",
    "refactoring/techniques/composing-methods":          "technique",
    "refactoring/techniques/moving-features-between-objects": "technique",
    "refactoring/techniques/organizing-data":            "technique",
    "refactoring/techniques/simplifying-conditional-expressions": "technique",
    "refactoring/techniques/simplifying-method-calls":   "technique",
    "refactoring/techniques/dealing-with-generalization":"technique",
}

_TAG_MAP: dict[str, list[str]] = {
    "design-patterns/creational":                        ["creational", "design-pattern"],
    "design-patterns/structural":                        ["structural", "design-pattern"],
    "design-patterns/behavioral":                        ["behavioral", "design-pattern"],
    "refactoring/smells/bloaters":                       ["smell", "bloater"],
    "refactoring/smells/oo-abusers":                     ["smell", "oo-abuser"],
    "refactoring/smells/change-preventers":              ["smell", "change-preventer"],
    "refactoring/smells/dispensables":                   ["smell", "dispensable"],
    "refactoring/smells/couplers":                       ["smell", "coupler"],
    "refactoring/techniques/composing-methods":          ["technique", "composing-methods"],
    "refactoring/techniques/moving-features-between-objects": ["technique", "moving-features"],
    "refactoring/techniques/organizing-data":            ["technique", "organizing-data"],
    "refactoring/techniques/simplifying-conditional-expressions": ["technique", "simplifying-conditionals"],
    "refactoring/techniques/simplifying-method-calls":   ["technique", "simplifying-method-calls"],
    "refactoring/techniques/dealing-with-generalization":["technique", "generalization"],
}


def standardize_frontmatter(text: str, file_path: str) -> str:
    """Set type, category, tags from the file's folder path. Idempotent."""
    post = frontmatter.loads(text)
    folder = str(Path(file_path).parent)

    post.metadata["type"] = _TYPE_MAP.get(folder, "catalog")
    post.metadata["category"] = folder
    if "tags" not in post.metadata:
        post.metadata["tags"] = _TAG_MAP.get(folder, ["catalog"])
    if "aliases" not in post.metadata:
        post.metadata["aliases"] = []

    return frontmatter.dumps(post)
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_frontmatter_std.py -v
```

Expected: 5 tests PASS.

**Step 5: Commit**

```bash
git add scripts/frontmatter_std.py tests/test_frontmatter_std.py
git commit -m "feat: frontmatter standardizer — type/category/tags normalization"
```

---

### Task 6: Build the main cleanup runner and run it on all files

**Files:**
- Create: `scripts/cleanup.py`

**Step 1: Write `scripts/cleanup.py`**

```python
#!/usr/bin/env python3
# scripts/cleanup.py
"""Main idempotent runner — chains all transforms over every content .md file."""
import sys
from pathlib import Path
from scripts.cleaner import clean_body
from scripts.cross_ref import convert_links
from scripts.frontmatter_std import standardize_frontmatter

ROOT = Path(__file__).parent.parent
SKIP = {"README.md", "CLAUDE.md"}


def process_file(md: Path) -> None:
    rel = str(md.relative_to(ROOT))
    text = md.read_text(encoding="utf-8")
    text = clean_body(text)
    text = convert_links(text, rel)
    text = standardize_frontmatter(text, rel)
    md.write_text(text, encoding="utf-8")


def main() -> None:
    files = [f for f in sorted(ROOT.glob("**/*.md")) if f.name not in SKIP]
    for i, md in enumerate(files, 1):
        print(f"[{i:>3}/{len(files)}] {md.relative_to(ROOT)}")
        process_file(md)
    print(f"\nDone — {len(files)} files processed.")


if __name__ == "__main__":
    main()
```

**Step 2: Do a dry-run on a single file to confirm output looks correct**

```bash
python -c "
from pathlib import Path
from scripts.cleanup import process_file
import shutil

src = Path('design-patterns/creational/factory-method.md')
shutil.copy(src, '/tmp/factory-method.md.bak')
process_file(src)
print(open(src).read()[:600])
"
```

Confirm: frontmatter has `type: pattern`, body has no `refactoring.guru` links except `url:`,
and no promotional content.

**Step 3: Run on the full repo**

```bash
python scripts/cleanup.py
```

Expected: `Done — 125 files processed.`

**Step 4: Spot-check two more files**

```bash
grep "refactoring.guru" refactoring/smells/bloaters/long-method.md | grep -v "^url:"
grep "Spring SALE" design-patterns/behavioral/observer.md
```

Expected: both return empty.

**Step 5: Commit the cleaned files**

```bash
git add -A
git commit -m "refactor: clean all 125 .md files — promo, images, cross-refs, frontmatter"
```

---

### Task 7: Validation suite

**Files:**
- Create: `scripts/validate.py`
- Create: `tests/test_validation.py`

**Step 1: Write `scripts/validate.py`**

```python
#!/usr/bin/env python3
# scripts/validate.py
"""CI gate — validates all success criteria. Exits 1 with a full error list on failure."""
import re
import sys
import frontmatter
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKIP = {"README.md", "CLAUDE.md"}
REQUIRED = {"url", "title", "type", "category", "tags"}
PROMO = ["Spring SALE", "Tired of reading", "own the eBook",
         "Support our free website", "browser does not support HTML video"]

errors: list[str] = []


def validate_file(md: Path) -> None:
    rel = str(md.relative_to(ROOT))
    text = md.read_text(encoding="utf-8")

    # SC-001: no external refactoring.guru links in body (frontmatter url: field is exempt)
    for i, line in enumerate(text.splitlines(), 1):
        if i <= 10 and line.startswith("url:"):
            continue
        if "refactoring.guru" in line and "url:" not in line:
            errors.append(f"SC-001  {rel}:{i} — external link in body")

    # SC-003: no promotional content
    for p in PROMO:
        if p in text:
            errors.append(f"SC-003  {rel} — promo content: '{p[:40]}'")

    # SC-005: required frontmatter fields
    try:
        post = frontmatter.loads(text)
        missing = REQUIRED - set(post.metadata)
        if missing:
            errors.append(f"SC-005  {rel} — missing fields: {sorted(missing)}")
    except Exception as exc:
        errors.append(f"SC-005  {rel} — frontmatter error: {exc}")


for md in sorted(ROOT.glob("**/*.md")):
    if md.name not in SKIP:
        validate_file(md)

if errors:
    print(f"VALIDATION FAILED — {len(errors)} error(s):\n")
    for e in errors[:30]:
        print(f"  {e}")
    if len(errors) > 30:
        print(f"  … and {len(errors) - 30} more")
    sys.exit(1)

print(f"VALIDATION PASSED — {len(list(ROOT.glob('**/*.md'))) - len(SKIP)} files clean.")
```

**Step 2: Run the validator**

```bash
python scripts/validate.py
```

Expected: `VALIDATION PASSED — 125 files clean.`

If any errors appear, fix the corresponding cleaner/converter regex and re-run `python scripts/cleanup.py`.

**Step 3: Write the pytest wrapper**

```python
# tests/test_validation.py
import subprocess, sys

def test_full_validation_suite_passes():
    result = subprocess.run(
        [sys.executable, "scripts/validate.py"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

**Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests pass (cleaner × 10 + url_map × 6 + cross_ref × 5 + frontmatter × 5 + validation × 1 = 27 tests).

**Step 5: Commit**

```bash
git add scripts/validate.py tests/test_validation.py
git commit -m "feat: validation suite — CI gate for all 5 success criteria"
```

---

### Task 8: Update README with internal navigation links

**Files:**
- Modify: `README.md`

**Step 1: Replace all external pattern links in the README tables with relative internal links**

In the "Contents" section, update each pattern/category link. Example:

```markdown
| **Creational** | [Factory Method](design-patterns/creational/factory-method.md), [Abstract Factory](design-patterns/creational/abstract-factory.md), [Builder](design-patterns/creational/builder.md), [Prototype](design-patterns/creational/prototype.md), [Singleton](design-patterns/creational/singleton.md) |
```

All 26 pattern links and all smell/technique cross-references in the README tables must point to local files.

**Step 2: Verify no external links remain in the tables**

```bash
grep "refactoring.guru" README.md | grep -v "Source\|scraped from\|Firecrawl"
```

Expected: zero output (only the "Source" attribution sentence keeps the external URL).

**Step 3: Run the full test suite one final time**

```bash
pytest tests/ -v && python scripts/validate.py
```

Expected: all 27 tests pass, validation passes.

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README — all navigation links converted to relative internal paths"
```

---

### Task 9: Final audit diff and PR

**Step 1: Run audit to confirm zero issues remain**

```bash
python scripts/audit.py
```

Expected:
```
Audit baseline:
  promo: 0 files
  images: 0 files
  ext_links: 0 files
  breadcrumbs: 0 files
```

**Step 2: Push and open PR**

```bash
git push -u origin refactor/knowledge-base-cleanup
gh pr create \
  --title "refactor: knowledge base cleanup — promo noise, broken images, cross-refs, frontmatter" \
  --body "Resolves all 5 defect classes identified in the spec. 125 files cleaned, 27 tests pass, validation suite CI-ready."
```

---

## Execution Options

**1. Subagent-Driven (this session)** — dispatch a fresh subagent per task, review between tasks.
Use `superpowers:subagent-driven-development`.

**2. Parallel Session** — open a new session in the cloned worktree.
Use `superpowers:executing-plans` with this file as input.
