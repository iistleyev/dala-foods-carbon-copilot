"""The stress test (stress_test.py) under pytest: one test per group, every check must pass."""

import pytest

import stress_test


@pytest.mark.parametrize("group", list(stress_test.GROUPS))
def test_stress_group(group):
    results = stress_test.GROUPS[group]()
    failed = [f"{name}: {detail}" for name, ok, detail in results if not ok]
    assert not failed, "\n".join(failed)
