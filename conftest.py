"""Repo-wide pytest configuration.

Key guarantee: tests never write to the developer's real ``results/`` dir.

The agent runtime and auth/session stores all default to relative paths
(``results/apex.db``, ``results/artifacts``). Without this fixture, any
test that constructs a runtime or archive without explicitly overriding
the path would pollute the dev database on every ``pytest`` run — which
is what bit us earlier (13 orphan sessions showing up in litecli).

We make every test run inside its own ``tmp_path`` by ``chdir``-ing into
it before the test body executes. Any relative paths then resolve under
the tmp dir and are cleaned up when pytest tears down the fixture.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
