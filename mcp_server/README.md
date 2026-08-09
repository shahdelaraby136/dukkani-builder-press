# Dukani MCP Adapter

This adapter is the controlled bridge between ChatGPT and the Dukani custom app.
It does not connect directly to MariaDB. It calls the app's authenticated API.

## First-stage tools

- `get_store_context`: returns the configured tenant context.
- `list_content_drafts`: reads draft content for the authenticated tenant.
- `create_content_draft`: creates a draft only; it cannot publish anything.

The adapter must run behind HTTPS and receive a per-tenant API token through its
deployment secret store. Never put tokens in the repository or in tool arguments.

## ChatGPT connection model

1. Deploy this adapter at a stable HTTPS URL.
2. Configure its MCP authentication and allowed tools.
3. Add the MCP server as an app/connector in the ChatGPT workspace.
4. ChatGPT discovers the tools and calls them only within the authorized tenant.

This repository does not publish or register the server automatically. Workspace
approval, authentication, and production deployment are required before connection.

## Local smoke check

The server requires the `mcp` package and tenant API secrets. Do not use production
credentials for local tests. First validate syntax with:

```bash
python -c "from pathlib import Path; compile(Path('server.py').read_text(), 'server.py', 'exec')"
```
