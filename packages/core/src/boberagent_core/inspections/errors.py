"""Bounded source-text-free errors shared by evidence and classification services."""


class InspectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
