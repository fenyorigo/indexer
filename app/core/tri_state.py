from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriStateResult:
    root_state: int
    any_checked: bool
    all_checked: bool


UNCHECKED = 0
PARTIAL = 1
CHECKED = 2


def compute_root_state(child_states: list[int]) -> TriStateResult:
    any_checked = any(state == CHECKED for state in child_states)
    all_checked = all(state == CHECKED for state in child_states) if child_states else False

    if all_checked and child_states:
        return TriStateResult(root_state=CHECKED, any_checked=True, all_checked=True)
    if any_checked:
        return TriStateResult(root_state=PARTIAL, any_checked=True, all_checked=False)
    return TriStateResult(root_state=UNCHECKED, any_checked=False, all_checked=False)
