"""Starts the MCP server that ships inside notebooklm-py and lists its tools
using the official `mcp` SDK. No Google login is needed for this."""
import pytest

pytest.importorskip("mcp")

from notebooklm_lab import selfcheck


def test_upstream_mcp_server_starts_and_lists_tools():
    name, ok, detail = selfcheck.check_mcp()
    assert ok, detail
