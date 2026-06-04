# Feature Specification: design-pattern-knowledge — Knowledge Base Cleanup & Cross-Reference Refactor

**Feature Branch**: `refactor/knowledge-base-cleanup`

**Created**: 2026-06-03

**Status**: Draft

**Repository**: https://github.com/pedro-mello30/design-pattern-knowledge

---

## Overview

The repository is a 127-file markdown knowledge base scraped from refactoring.guru covering the
full GoF Design Pattern catalog (26 patterns) and Refactoring catalog (28 code smells + 66 techniques
+ 7 catalog/index pages). The scrape introduced five structural defect classes that make files noisy,
un-navigable offline, and fragile as a standalone reference:

1. **Promotional noise** — every file contains a Spring SALE banner, an eBook upsell block, and a
   "Tired of reading?" CTA that have nothing to do with the content.
2. **Broken image references** — all `![...](https://refactoring.guru/images/...)` URLs point to an
   external CDN with hash-versioned paths that will eventually 404.
3. **External cross-references** — "Relations with Other Patterns" and "Treatment" sections link to
   `refactoring.guru` instead of to local sibling files.
4. **Inconsistent frontmatter** — `category` values have no consistent convention (`category: creational`
   vs `category: smells/bloaters`); `type`, `tags`, and relationship fields are absent.
5. **Broken navigation breadcrumbs** — every file opens with `/ [Design Patterns](https://refactoring.guru/...)` 
   breadcrumb lines that are meaningless in a local repo.

This spec defines the cleanup and structural refactoring needed to make this a clean, self-contained,
offline-navigable reference suitable for tooling and AI agent consumption.

---

## User Scenarios & Testing

### User Story 1 — Clean Readable Content (Priority: P1)

As a developer reading a design pattern or refactoring technique in this repo, I want files to contain
only the technical content without promotional banners, e-book upsells, breadcrumb navigation, image
badge links, and "Tired of reading?" CTAs, so I can focus on the knowledge.

**Why this priority**: Every single file is affected. It is the highest signal-to-noise problem and
blocks all other use cases including AI embedding and search.

**Independent Test**: Clone the repo, open any `.md` file, and run the grep checks below.

**Acceptance Scenarios**:

1. **Given** any `.md` content file in the repo, **When** I run
   `grep -n "Spring SALE\|eBook\|Tired of reading\|browser does not support HTML video" <file>`,
   **Then** zero matches are found.
2. **Given** any `.md` content file, **When** I search for lines matching `^/ \[.*\]\(https://refactoring`,
   **Then** zero breadcrumb navigation lines are found.
3. **Given** `design-patterns/behavioral/observer.md`, **When** I read it, **Then** the "Support our
   free website and own the eBook!" block is absent and all image badge links are gone.

---

### User Story 2 — Internal Cross-Reference Navigation (Priority: P2)

As a developer consulting this knowledge base offline, I want cross-references between patterns,
smells, and techniques to use relative file paths (e.g., `../../techniques/composing-methods/extract-method.md`)
rather than external URLs, so I can navigate without internet access in any markdown viewer.

**Why this priority**: Currently all "Relations with Other Patterns" and "Treatment" sections link back
to refactoring.guru, making local navigation entirely broken.

**Independent Test**: Run `grep -rn "refactoring.guru" --include="*.md" . | grep -v "url:"` from the
repo root and confirm zero results.

**Acceptance Scenarios**:

1. **Given** any cross-reference link in a `.md` file body, **When** I resolve it relative to that
   file's directory, **Then** it resolves to an existing local `.md` file.
2. **Given** `refactoring/smells/bloaters/long-method.md`, **When** I follow the `[Extract Method]` link,
   **Then** it navigates to `../../techniques/composing-methods/extract-method.md`.
3. **Given** `design-patterns/behavioral/observer.md`, **When** I follow the `[Mediator]` link,
   **Then** it navigates to `mediator.md` (same directory).

---

### User Story 3 — Consistent Frontmatter Schema (Priority: P3)

As a tool or AI agent parsing this knowledge base, I want all 127 files to share a documented, consistent
frontmatter schema with required fields (`url`, `title`, `type`, `category`, `tags`), so I can reliably
build indexes without per-file special cases.

**Why this priority**: Current `category` values are inconsistent; missing `type` forces parsers to infer
content type from the filesystem path, coupling tooling to the folder structure.

**Independent Test**: Run `python scripts/validate.py` — all 127 files pass with required fields present.

**Acceptance Scenarios**:

1. **Given** any `.md` file in `design-patterns/creational/`, **When** I read its frontmatter,
   **Then** `type: pattern`, `category: design-patterns/creational`, and `tags` contains `creational`.
2. **Given** any `.md` file in `refactoring/smells/bloaters/`, **When** I read its frontmatter,
   **Then** `type: smell`, `category: refactoring/smells/bloaters`, and `tags` contains `bloater`.
3. **Given** `design-patterns/creational/factory-method.md`, **When** I read its frontmatter,
   **Then** `aliases: [Virtual Constructor]` is present.

---

### User Story 4 — Relationship Metadata in Frontmatter (Priority: P4)

As an AI agent building a context window from this knowledge base, I want each file to have
`related_patterns`, `applicable_smells`, and `applicable_techniques` frontmatter fields, so I can
discover connections without parsing full body text.

**Why this priority**: Enables semantic retrieval and graph construction from frontmatter alone,
without requiring full-document embedding.

**Independent Test**: Read `design-patterns/behavioral/observer.md` frontmatter — confirm
`related_patterns` is populated.

**Acceptance Scenarios**:

1. **Given** `design-patterns/behavioral/observer.md`, **When** I read its frontmatter, **Then**
   `related_patterns` includes `mediator`, `chain-of-responsibility`, `command`.
2. **Given** `refactoring/smells/bloaters/long-method.md`, **When** I read its frontmatter, **Then**
   `applicable_techniques` includes `extract-method`, `replace-temp-with-query`,
   `replace-method-with-method-object`.

---

### Edge Cases

- Catalog/index files (`catalog/` subdirectories): get `type: catalog`; image badge links stripped to
  plain text links.
- Pattern "Also known as" aliases (e.g., Factory Method = Virtual Constructor): captured in
  `aliases: []` frontmatter field.
- Technique files' language tab links (`[Java](url#java) [C#](url#csharp)` on a single line):
  stripped entirely — the code blocks that follow already carry language identifiers.
- The cleanup script must be **idempotent**: running it twice on already-cleaned files produces
  identical output.

---

## Requirements

### Functional Requirements

- **FR-001**: All 127 `.md` content files MUST have all promotional content stripped (Spring SALE
  banners, eBook upsells, "Tired of reading?" sections, HTML video references, breadcrumb navigation
  lines, language-tab link rows, book-banner image sections).
- **FR-002**: All external `![alt](https://refactoring.guru/images/...)` inline image references MUST
  be removed from file bodies. Structural diagram alt-text MAY be retained as a `> **Figure:** alt-text`
  blockquote.
- **FR-003**: All cross-reference URLs matching `https://refactoring.guru/design-patterns/*` and
  `https://refactoring.guru/<technique-slug>` in file bodies MUST be replaced with correct relative
  internal paths computed from each file's location.
- **FR-004**: All files MUST conform to the standardized frontmatter schema:
  ```yaml
  url: <original source URL>                    # required — kept for attribution
  title: <page title>                           # required
  type: pattern | smell | technique | catalog   # required, NEW
  category: <folder-path-from-repo-root>        # required, standardized
  tags: [<list>]                                # required, NEW
  aliases: [<list>]                             # optional, NEW
  related_patterns: [<slugs>]                   # optional, NEW — pattern files
  applicable_smells: [<slugs>]                  # optional, NEW — technique files
  applicable_techniques: [<slugs>]              # optional, NEW — smell files
  ```
- **FR-005**: A re-runnable, idempotent Python utility `scripts/cleanup.py` MUST exist that applies
  all transformations (FR-001 through FR-004) to every content file.
- **FR-006**: A validation script `scripts/validate.py` MUST exist that checks all success criteria
  and exits non-zero with a descriptive error list if any fail.

### Key Entities

- **Frontmatter Schema**: The standardized YAML block at the top of every `.md` file. Defined by
  FR-004 above.
- **URL Map** (`scripts/url_map.py`): A Python dict mapping every known `refactoring.guru` path to
  its local relative path. Used by the cross-reference converter. Must cover all 127 content files.
- **Promotional Patterns**: The set of regexes and string markers that identify noise content. Lives
  in `scripts/cleaner.py`.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: `grep -rn "refactoring.guru" --include="*.md" . | grep -v "url:"` returns **zero** lines.
- **SC-002**: `python scripts/validate.py` exits 0 — 127 files validated, all required frontmatter
  fields present, all `type` and `category` values correct.
- **SC-003**: `grep -rn "Spring SALE\|eBook\|Tired of reading\|browser does not support" --include="*.md" .`
  returns **zero** lines.
- **SC-004**: All internal cross-reference links in `.md` bodies resolve to existing local files (no
  dangling relative paths).
- **SC-005**: `pytest tests/ -v` exits 0 — unit tests for cleaner, URL map, cross-ref converter, and
  frontmatter standardizer all pass.

---

## Assumptions

- The repo is cleaned in-place via a local clone; a re-scrape is not part of this spec.
- Images are removed (not downloaded). No local image assets are introduced.
- The "eBook" and promotional sections at the bottom of files vary slightly in wording across pages —
  regex patterns in `cleaner.py` must be resilient to these variations.
- `scripts/cleanup.py` is idempotent: running it on already-cleaned files is safe and produces
  identical output.
- Code example language tabs (`[Java](url#java) [C#]...` on a single line) are stripped; the code
  blocks in the file already carry fenced-code language identifiers.
- `README.md` and `CLAUDE.md` are excluded from automated cleanup (they are manually maintained).
