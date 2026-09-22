"""Expected Core interaction management failures."""


class InteractionError(Exception):
    pass


class InteractionNotFound(InteractionError):
    pass


class InteractionConflict(InteractionError):
    pass


class InteractionStateError(InteractionError):
    pass
