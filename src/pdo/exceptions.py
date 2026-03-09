"""Custom exception hierarchy for the PDO application.

All application-specific exceptions inherit from :class:`PdoError` so
callers can catch a single base type when appropriate.
"""


class PdoError(Exception):
    """Base exception for all PDO errors."""


class DaemonNotRunningError(PdoError):
    """Raised when the CLI cannot connect to the daemon."""


class DatabaseError(PdoError):
    """Raised on database access or integrity failures."""


class ImportDataError(PdoError):
    """Raised when CSV import fails."""


class OptimizationError(PdoError):
    """Raised when the description optimization step fails."""


class ExportError(PdoError):
    """Raised when exporting data from the database fails."""


class ProtocolError(PdoError):
    """Raised on IPC message serialization or protocol violations."""
