"""Core-owned World State materialization primitives."""

from .network_service import NetworkServiceReducer, NetworkServiceValue, service_ref_for_endpoint
from .reducers import ReducerRegistry

__all__ = [
    "NetworkServiceReducer",
    "NetworkServiceValue",
    "ReducerRegistry",
    "service_ref_for_endpoint",
]
