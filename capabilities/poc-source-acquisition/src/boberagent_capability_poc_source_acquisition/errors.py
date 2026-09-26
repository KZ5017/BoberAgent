"""Stable, safe failure categories for fixture acquisition."""


class AcquisitionRejected(Exception):
    """A bounded source cannot become a completion-ready acquisition."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
