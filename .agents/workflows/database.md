---
description: Maintain SQLite schema, bounded queries, and atomic batch recovery
---

# /database — Database Maintenance

Read `src/pdo/core/db.py` and `docs/development.md` for the current schema.

1. Keep one SQLite database per data directory, owned by the daemon. Use in-memory databases or temporary directories for unit tests.
2. Preserve original CSV columns in `products.raw_data` JSON; `pipeline_state`, `column_mappings`, and `metadata` have distinct roles. Do not create a second pipeline-state representation in metadata.
3. Use parameterized SQL and transactions for mutations. Serialize access to the shared connection and preserve migration of older schemas (including error categories).
4. Keep product previews, search, and export paging bounded. Recovery must preserve successful products; correction import validates unique failed IDs and applies the entire file atomically.
5. Check reset semantics: full reset clears the batch; `keep=True` retains source data and mappings but clears all optimized results and errors.
6. Run `tests/test_db.py`, `tests/test_batch_workflow.py`, and `tests/test_instance_lock.py`; include importer/exporter and desktop tests when changing their data contract.

Follow [AGENTS.md](../../AGENTS.md), the [Development guide](../../docs/development.md), and the [Git workflow](../rules/rules.md#git--workflow). Work on the current branch, request confirmation before committing, and merge only on explicit request.
