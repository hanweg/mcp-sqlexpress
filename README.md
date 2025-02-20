# SQL Server Express MCP Server

An MCP server for interacting with Microsoft SQL Server Express. Supports Windows and SQL Server authentication.

## Prerequisites

- Python 3.10 or higher
- Microsoft ODBC Driver 18 for SQL Server
- SQL Server instance with appropriate permissions

## Installation

Clone this repo

```powershell
cd mcp-sqlexpress

# Create and activate virtual environment
uv venv
.venv\Scripts\activate

# Install dependencies
uv pip install --editable .
```

## Usage with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "sqlexpress": {
            "command": "uv",
            "args": [
                "--directory",
                "PATH\\TO\\PROJECT\\mcp-sqlexpress",
                "run",
                "mcp-server-sqlexpress",
                "--server",
                "server\\instance",
                "--auth",
                "windows",
                "--trusted-connection",
                "yes",
                "--trust-server-certificate",
                "yes",
                "--allowed-databases",
                "database1,database2"
            ]
        }
    }
}
```

### Authentication Options

For Windows Authentication:
- Set `--auth windows`
- Set `--trusted-connection yes`

For SQL Server Authentication:
- Set `--auth sql`
- Add `--username` and `--password`

## Features

### Tools
- `get_allowed_databases`: Get list of databases that are allowed to be accessed
- `read_query`: Execute SELECT queries
- `write_query`: Execute INSERT/UPDATE/DELETE queries
- `create_table`: Create new tables
- `list_tables`: List all tables in database
- `describe_table`: Show table schema