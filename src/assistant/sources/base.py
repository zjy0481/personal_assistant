"""Shared errors for external data sources."""


class DataSourceError(RuntimeError):
    """Raised when an external source cannot return usable data."""