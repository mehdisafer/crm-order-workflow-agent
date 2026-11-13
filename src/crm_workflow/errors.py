"""Safe error codes; remote bodies and credentials never enter user-facing errors."""


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


class TransientError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(message)


class UnknownOutcome(TransientError):
    """A write may have committed; reconcile its remote key before sending it again."""
