from app.core.tri_state import CHECKED, PARTIAL, UNCHECKED, compute_root_state


def test_root_state_all_checked() -> None:
    result = compute_root_state([CHECKED, CHECKED])
    assert result.root_state == CHECKED


def test_root_state_partial() -> None:
    result = compute_root_state([CHECKED, UNCHECKED])
    assert result.root_state == PARTIAL


def test_root_state_unchecked() -> None:
    result = compute_root_state([UNCHECKED, UNCHECKED])
    assert result.root_state == UNCHECKED
