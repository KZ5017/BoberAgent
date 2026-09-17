"""Transport and protocol failures kept distinct from capability execution results."""

from boberagent_contracts import CapabilityRunRef


class TransportError(Exception):
    code = "TRANSPORT_ERROR"

    def __init__(
        self,
        message: str,
        *,
        node_id: str | None = None,
        message_id: str | None = None,
        correlation_id: CapabilityRunRef | None = None,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.message_id = message_id
        self.correlation_id = correlation_id


class TransportDisconnected(TransportError):
    code = "TRANSPORT_DISCONNECTED"


class UnknownNode(TransportError):
    code = "UNKNOWN_NODE"


class ProtocolError(TransportError):
    code = "PROTOCOL_ERROR"


class UnsupportedProtocolVersion(ProtocolError):
    code = "UNSUPPORTED_PROTOCOL_VERSION"


class MalformedMessage(ProtocolError):
    code = "MALFORMED_MESSAGE"


class ConflictingInvocation(ProtocolError):
    code = "CONFLICTING_INVOCATION"


class TransportBackpressure(TransportError):
    code = "TRANSPORT_BACKPRESSURE"
