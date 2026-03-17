# CLI Reference

Complete reference for PDO (Product Description Optimizer) CLI commands.

For step-by-step setup and tutorials, see [Getting Started](docs/getting_started.md).

## General Usage Example

```bash
# 1. Start the daemon
pdo daemon start

# 2. Set up configuration
pdo config set zhipuai.api_key "your-key"
pdo config set optimizer zhipuai

# 3. Import products
pdo import products.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung \
  -m context:Titel

# 4. Optimize with progress tracking
pdo optimize --watch

# 5. Check status at any time
pdo status

# 6. Export results
pdo export optimized_output.csv

# 7. Stop daemon when done
pdo daemon stop
```

All commands support `--help` for detailed usage information and available options.

---

## Daemon Commands

### `pdo daemon start [--foreground]`
Start the background daemon process.

```bash
# Start in background
pdo daemon start

# Start in foreground (see logs in real-time)
pdo daemon start --foreground
```

### `pdo daemon stop`
Stop the running daemon.

```bash
pdo daemon stop
```

### `pdo daemon status`
Check if the daemon is running.

```bash
pdo daemon status
# → Daemon is running
```

### `pdo daemon repair`
Repair an unresponsive daemon by cleaning up PID file and socket.

```bash
pdo daemon repair
```

---

## Configuration Commands

### `pdo config set <key> <value>`
Set a configuration key to a given value.

```bash
# Set optimizer
pdo config set optimizer zhipuai

# Set API keys
pdo config set zhipuai.api_key "your-key"
pdo config set gemini.api_key "your-key"

# Set tuning parameters
pdo config set target_sentences 3
pdo config set optimize_temperature 0.4
```

### `pdo config get <key>`
Get the value of a configuration key.

```bash
pdo config get optimizer
# → zhipuai

pdo config get target_sentences
# → 3
```

### `pdo config list`
List all configuration keys and values.

```bash
pdo config list
# → optimizer = zhipuai
# → target_sentences = 3
# → optimize_temperature = 0.4
# → ...
```

---

## Pipeline Commands

### `pdo import <file> [-m ROLE:COLUMN] [-l N] [-d DELIMITER]`
Import products from CSV file.

```bash
# Basic import
pdo import products.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung

# Import with multiple context fields
pdo import catalogue.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung \
  -m context:Titel \
  -m context:Marke \
  -m context:Kategorie

# Import with limit (for testing)
pdo import products.csv -m product_id:ID -m description:Desc -l 10

# Use comma delimiter instead of semicolon
pdo import products.csv -m product_id:ID -m description:Desc -d ","
```

### `pdo optimize [--watch] [--optimizer BACKEND]`
Start optimization with optional progress watching.

```bash
# Start optimization and watch progress
pdo optimize --watch

# Use specific optimizer backend
pdo optimize --optimizer zhipuai --watch
pdo optimize --optimizer gemini --watch
pdo optimize --optimizer local_llm --watch
```

### `pdo pause`
Pause the current optimization.

```bash
pdo pause
```

### `pdo resume`
Resume a paused optimization.

```bash
pdo resume
```

### `pdo reset [--yes]`
Stop all operations and clear the database.

```bash
# Reset with confirmation prompt
pdo reset

# Reset without prompt
pdo reset --yes
```

---

## Output Commands

### `pdo export <file> [--include-errors]`
Export results to CSV file.

```bash
# Export only completed products
pdo export optimized_output.csv

# Export all products including errors
pdo export output.csv --include-errors
```

### `pdo logs [-f] [-n N]`
View daemon log output.

```bash
# View last 50 lines
pdo logs

# View last 200 lines
pdo logs -n 200

# Follow logs in real-time
pdo logs -f
```

### `pdo status`
Show pipeline progress.

```bash
pdo status
# → Import: 100 products
# → Optimize: 45 done, 55 pending
# → Export: 0 done
```

---

## Utility Commands

### `pdo optimizer list`
List available optimizer backends.

```bash
pdo optimizer list
# → Available optimizers: zhipuai, gemini, local_llm
```

### `pdo version`
Print version information.

```bash
pdo version
# → pdo 0.1.0
```

---

## Command Options Summary

| Option | Description | Used With |
|--------|-------------|-----------|
| `--foreground` | Run daemon in foreground | `daemon start` |
| `--watch` | Watch optimization progress in real-time | `optimize` |
| `--optimizer` | Specify optimizer backend | `optimize` |
| `--yes` | Skip confirmation prompts | `reset` |
| `-m ROLE:COLUMN` | Map CSV column to role | `import` |
| `-l N` | Limit number of products | `import` |
| `-d DELIMITER` | CSV delimiter (default `;`) | `import` |
| `--include-errors` | Export products with errors | `export` |
| `-f` | Follow logs in real-time | `logs` |
| `-n N` | Number of log lines to show | `logs` |

For more detailed help on any command:
```bash
pdo <command> --help
```
