"""Ephemeral recipient routing for Official Bot outbound messages."""

from collections import OrderedDict


class OfficialBotRecipientRegistry:
    """Bounded in-memory mapping; raw chat identifiers never cross this adapter boundary."""

    def __init__(self, maximum: int = 10_000) -> None:
        self._maximum = maximum
        self._recipients: OrderedDict[str, str | int] = OrderedDict()
        self._bound: OfficialBotRecipientRegistry | None = None

    def bind(self, target: "OfficialBotRecipientRegistry") -> None:
        """Forward a route-installed registry to its lifecycle-owned runtime registry."""
        self._bound = target

    def unbind(self) -> None:
        self._bound = None

    def remember(self, identity_hmac: str, chat_id: str | int) -> None:
        if self._bound is not None:
            self._bound.remember(identity_hmac, chat_id)
            return
        self._recipients.pop(identity_hmac, None)
        self._recipients[identity_hmac] = chat_id
        while len(self._recipients) > self._maximum:
            self._recipients.popitem(last=False)

    def resolve(self, identity_hmac: str) -> str | int | None:
        if self._bound is not None:
            return self._bound.resolve(identity_hmac)
        return self._recipients.get(identity_hmac)

    def clear(self, identity_hmac: str | None = None) -> None:
        if self._bound is not None:
            self._bound.clear(identity_hmac)
            return
        if identity_hmac is None:
            self._recipients.clear()
        else:
            self._recipients.pop(identity_hmac, None)
