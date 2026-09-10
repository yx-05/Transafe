"""TranSafe MCP gateway — L6 (Exposure).

This is a *local* package, deliberately not the PyPI ``mcp`` SDK: the stdio
JSON-RPC loop in :mod:`mcp.server` is hand-rolled so the tool layer stays
importable and unit-testable with no transport and no third-party dependency.

.. warning::

   **This package shadows the PyPI ``mcp`` distribution on ``sys.path``.**

   ``backend/`` is ``sys.path[0]`` under both pytest and uvicorn, so
   ``import mcp`` resolves *here*, not to the official SDK. Running
   ``uv add mcp`` will therefore install a package that can never be imported,
   and the failure surfaces as a baffling ``ImportError`` or an
   ``AttributeError`` on ``mcp.server.Server`` rather than as a name clash.

   Adopting the official SDK requires **renaming this package first** — e.g.
   to ``mcp_gateway`` — and updating the imports in ``mcp/server.py``,
   ``src/enterprise/liaison_agent.py``, ``src/api/enterprise/router.py`` and
   ``mcp/codebuddy_config.json``'s ``-m`` target. Do that rename before adding
   the dependency, not after.

Modules
-------
redaction  Role-based, recursive, server-side field redaction (B6)
server     MCP tool surface, rate limiting, audit logging, stdio transport (B6)
"""
