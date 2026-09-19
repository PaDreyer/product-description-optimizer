---
description: Maintain CSV import/export, AI optimization, and bulk recovery
---

# /core-pipeline — Core Pipeline Maintenance

Read the current modules in `src/pdo/core/` and the GUI/CLI contracts in `docs/getting_started.md` and `docs/cli_reference.md`.

1. Import requires mapped description column(s), not fixed column names. Empty descriptions can use mapped context. Preserve source headers, format, and unmapped columns.
2. Desktop replacement uses a staging database; CLI import appends without ID deduplication. Correction import uses unchanged headers/order and unique failed-product IDs.
3. Optimization processes pending rows and persists every result. Error-group retries target only selected failures; missing source data requires correction first. Pause takes effect between products.
4. AI adapters inherit `BaseLLMOptimizer`; provider defaults live in `provider_defaults.py`, and registration belongs in `registry.py`. Include the generated text and product ID when documenting validation data flow.
5. Export uses `CsvFormat` and the same serializer for previews and files, bounded paging, collision-safe added columns, and temporary-file replacement. Keep the original source path protected and successful destination replacement explicit.
6. Run importer, optimizer, exporter, and batch-workflow tests plus affected provider/desktop tests. Include encodings, failed writes, correction rollback, and preservation of successful products.

Follow [AGENTS.md](../../AGENTS.md), the [Development guide](../../docs/development.md), and the [Git workflow](../rules/rules.md#git--workflow). Work on the current branch, request confirmation before committing, and merge only on explicit request.
