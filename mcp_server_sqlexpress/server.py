import pyodbc
import logging
from contextlib import closing
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
from pydantic import AnyUrl
from typing import Any
from argparse import Namespace
import re

logger = logging.getLogger('mcp_sqlexpress_server')
logger.info("Starting MCP SQL Server Express Server")

class SqlExpressDatabase:
    def __init__(self, args: Namespace):
        self.connection_string = self._build_connection_string(args)
        self.allowed_databases = args.allowed_databases
        if not self.allowed_databases:
            raise ValueError("No databases specified in --allowed-databases. Please specify which databases to allow access to.")
        self._test_connection()

    def _build_connection_string(self, args: Namespace) -> str:
        """Build connection string based on arguments"""
        # List available drivers
        drivers = pyodbc.drivers()
        sql_drivers = [d for d in drivers if 'SQL Server' in d]
        if not sql_drivers:
            raise ValueError("No SQL Server ODBC drivers found")
        
        # Use the most recent driver
        driver = sql_drivers[-1]
        logger.info(f"Using SQL Server driver: {driver}")
        
        conn_parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={args.server}"
        ]
        
        if args.auth == 'windows' or args.trusted_connection == 'yes':
            conn_parts.append("Trusted_Connection=yes")
        else:
            conn_parts.extend([
                f"UID={args.username}",
                f"PWD={args.password}"
            ])
            
        if args.trust_server_certificate == 'yes':
            conn_parts.append("TrustServerCertificate=yes")
            
        connection_string = ";".join(conn_parts)
        logger.info(f"Connection string (without credentials): {connection_string}")
        return connection_string

    def _test_connection(self):
        """Test connection and verify access to allowed databases"""
        with closing(pyodbc.connect(self.connection_string)) as conn:
            with closing(conn.cursor()) as cursor:
                # Test each allowed database
                for db in self.allowed_databases:
                    try:
                        cursor.execute(f"USE [{db}]")
                    except pyodbc.Error as e:
                        raise ValueError(f"Cannot access database '{db}'. Please verify the database exists and you have proper permissions.")

    def _validate_database(self, query: str) -> bool:
        """Validate that the query only accesses allowed databases"""
        query_upper = query.upper()
        
        # Normalize database references by handling both bracketed and unbracketed identifiers
        def extract_db_name(identifier: str) -> str:
            # Remove brackets and split on dots to get first part
            cleaned = identifier.replace('[', '').replace(']', '')
            return cleaned.split('.')[0].strip()
        
        # Check for explicit USE statements
        use_matches = re.findall(r'USE\s+\[?([^\]\s\.]+)(?:\]|\b)', query_upper)
        
        # Check for three-part names (database.schema.object)
        # Handle both [database].[schema].[object] and database.schema.object
        three_part_pattern = r'(?:\[?([^\]\s\.]+)\]?\.(?:\[?[^\]\s\.]+\]?)\.(?:\[?[^\]\s\.]+\]?))'
        three_part_matches = [extract_db_name(match) for match in re.findall(three_part_pattern, query_upper)]
        
        # Check for two-part names with database prefix in FROM and JOIN clauses
        two_part_pattern = r'(?:FROM|JOIN)\s+\[?([^\]\s\.]+)\]?\.(?:\[?[^\]\s\.]+\]?)'
        two_part_matches = [extract_db_name(match) for match in re.findall(two_part_pattern, query_upper)]
        
        # Combine all database references
        all_db_refs = use_matches + three_part_matches + two_part_matches
        
        # Convert allowed databases to uppercase for case-insensitive comparison
        allowed_dbs_upper = [db.upper() for db in self.allowed_databases]
        
        # Check each database reference
        for db in all_db_refs:
            db_upper = db.upper()
            if db_upper not in allowed_dbs_upper:
                raise ValueError(
                    f"Access to database '{db}' is not allowed. "
                    f"Query contains unauthorized database access. "
                    f"Allowed databases: {', '.join(self.allowed_databases)}"
                )
        
        # Additional checks for potential database access
        dangerous_patterns = [
            r'EXEC\s+\(?.*\.', # Cross-database stored procedure execution
            r'sp_execute.*\.', # Dynamic SQL that might access other databases
            r'OPENROWSET\s*\(', # OPENROWSET calls
            r'OPENDATASOURCE\s*\(', # OPENDATASOURCE calls
            r'OPENQUERY\s*\(', # OPENQUERY calls
            r'INTO\s+\[?[^\]\s\.]+\]?\.(?:\[?[^\]\s\.]+\]?)', # Cross-database INSERT INTO
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, query_upper):
                raise ValueError(
                    "Query contains potentially unsafe operations that could access unauthorized databases. "
                    "Please use only direct queries on allowed databases."
                )
        
        return True

    async def execute_query(self, query: str) -> list[dict]:
        """Execute a query with database access validation"""
        self._validate_database(query)
        
        with closing(pyodbc.connect(self.connection_string)) as conn:
            with closing(conn.cursor()) as cursor:
                # Force context to first allowed database if no USE statement
                cursor.execute(f"USE [{self.allowed_databases[0]}]")
                
                # Additional safety: set context options to prevent cross-db access
                cursor.execute("""
                    SET CONTEXT_INFO 0x0;  -- Reset context
                    SET XACT_ABORT ON;     -- Terminate on error
                    SET TEXTSIZE 0;        -- Prevent large text
                    SET ARITHABORT ON;     -- Terminate on arithmetic errors
                    SET ANSI_WARNINGS ON;  -- Error on data truncation
                """)
                
                cursor.execute(query)
                
                if cursor.description:  # If query returns rows
                    columns = [column[0] for column in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
                return []

    async def list_tables(self) -> list[dict]:
        """List tables from allowed databases only"""
        results = []
        with closing(pyodbc.connect(self.connection_string)) as conn:
            with closing(conn.cursor()) as cursor:
                for db in self.allowed_databases:
                    cursor.execute(f"""
                        USE [{db}]
                        SELECT TABLE_SCHEMA, TABLE_NAME 
                        FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_TYPE = 'BASE TABLE'
                    """)
                    for schema, table in cursor.fetchall():
                        results.append({
                            "database": db,
                            "schema": schema,
                            "name": table
                        })
        return results

    async def describe_table(self, database: str, schema: str, table: str) -> list[dict]:
        """Describe table structure with database validation"""
        if database not in self.allowed_databases:
            raise ValueError(f"Access to database '{database}' is not allowed. Allowed databases: {', '.join(self.allowed_databases)}")
            
        with closing(pyodbc.connect(self.connection_string)) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(f"""
                    USE [{database}]
                    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, 
                           IS_NULLABLE, COLUMN_DEFAULT
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                    ORDER BY ORDINAL_POSITION
                """, (schema, table))
                
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

async def main(args: Namespace):
    logger.info(f"Starting SQL Server Express MCP Server")

    db = SqlExpressDatabase(args)
    server = Server("sqlexpress-manager")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            types.Tool(
                name="get_allowed_databases",
                description="Get list of databases that are allowed to be accessed",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            types.Tool(
                name="read_query",
                description="Execute a SELECT query on SQL Server",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SELECT SQL query to execute"},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="write_query",
                description="Execute an INSERT, UPDATE, or DELETE query on SQL Server",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="create_table",
                description="Create a new table in SQL Server",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "CREATE TABLE SQL statement"},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="list_tables",
                description="List all tables in the current database",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            types.Tool(
                name="describe_table",
                description="Get the schema information for a specific table",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "table_name": {"type": "string", "description": "Name of the table to describe"},
                    },
                    "required": ["table_name"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent]:
        """Handle tool execution requests"""
        try:
            if name == "get_allowed_databases":
                return [types.TextContent(
                    type="text",
                    text=f"Allowed databases: {', '.join(db.allowed_databases)}\n\n"
                         f"Note: These are the only databases you can access. "
                         f"Please use these database names in your queries."
                )]
            
            if name == "list_tables":
                results = await db.list_tables()
                return [types.TextContent(type="text", text=str(results))]

            elif name == "describe_table":
                if not arguments or "table_name" not in arguments:
                    raise ValueError("Missing table_name argument")
                
                results = await db.describe_table(arguments["database"], arguments["schema"], arguments["table_name"])
                return [types.TextContent(type="text", text=str(results))]

            if not arguments:
                raise ValueError("Missing arguments")

            if name == "read_query":
                if not arguments["query"].strip().upper().startswith("SELECT"):
                    raise ValueError("Only SELECT queries are allowed for read_query")
                results = await db.execute_query(arguments["query"])
                return [types.TextContent(type="text", text=str(results))]

            elif name == "write_query":
                if arguments["query"].strip().upper().startswith("SELECT"):
                    raise ValueError("SELECT queries are not allowed for write_query")
                results = await db.execute_query(arguments["query"])
                return [types.TextContent(type="text", text=str(results))]

            elif name == "create_table":
                if not arguments["query"].strip().upper().startswith("CREATE TABLE"):
                    raise ValueError("Only CREATE TABLE statements are allowed")
                await db.execute_query(arguments["query"])
                return [types.TextContent(type="text", text="Table created successfully")]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except pyodbc.Error as e:
            return [types.TextContent(type="text", text=f"Database error: {str(e)}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="sqlexpress",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )