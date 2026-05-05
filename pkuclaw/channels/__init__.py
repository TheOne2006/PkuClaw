"""Chat channel adapter contracts and implementations."""

from pkuclaw.channels.base import (
    ChannelAdapter,
    ChannelEnvelope,
    ChannelEventSinkFactory,
    ChannelInboundMessage,
    ChannelOutboundBackend,
    ChannelOutboundResult,
    ChannelOutbox,
    ChannelTarget,
)

__all__ = [
    "ChannelAdapter",
    "ChannelEnvelope",
    "ChannelEventSinkFactory",
    "ChannelInboundMessage",
    "ChannelOutboundBackend",
    "ChannelOutboundResult",
    "ChannelOutbox",
    "ChannelTarget",
]
