import dataclasses

import pytest

from payamakyar.core.gates import Capabilities, Gates, capabilities


def test_capabilities_ladder() -> None:
    assert capabilities(Gates(False, False, False, False)) == Capabilities(False, False, False)
    assert capabilities(Gates(True, False, False, False)) == Capabilities(False, False, False)
    assert capabilities(Gates(True, True, False, False)) == Capabilities(False, False, False)
    assert capabilities(Gates(True, True, True, False)) == Capabilities(True, True, False)
    assert capabilities(Gates(True, True, True, True)) == Capabilities(True, True, True)


def test_each_gate_unlocks_its_capability() -> None:
    assert capabilities(Gates(False, False, True, False)).can_send
    assert not capabilities(Gates(False, True, False, False)).can_buy_line
    assert capabilities(Gates(False, True, True, False)).can_buy_line
    assert capabilities(Gates(False, False, False, True)).can_use_service_line_and_links


def test_frozen() -> None:
    g = Gates(True, True, True, True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.registered = False  # type: ignore[misc]
