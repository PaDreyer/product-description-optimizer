"""PDO — Product Description Optimizer.

A CLI application that optimizes product descriptions via a daemon/client
architecture.  The ``pdo`` CLI connects to a background daemon (started
with ``pdo daemon start``) that handles CSV import, AI-powered
description optimization, and export.
"""

__version__ = "0.1.0"
