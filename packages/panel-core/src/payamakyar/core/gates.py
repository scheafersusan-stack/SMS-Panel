"""Account gates and the capabilities they unlock."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Gates:
    registered: bool
    profile_complete: bool
    identity_matched: bool
    documents_approved: bool


@dataclass(frozen=True)
class Capabilities:
    can_send: bool
    can_buy_line: bool
    can_use_service_line_and_links: bool


def capabilities(g: Gates) -> Capabilities:
    return Capabilities(
        can_send=g.identity_matched,
        can_buy_line=g.profile_complete and g.identity_matched,
        can_use_service_line_and_links=g.documents_approved,
    )
