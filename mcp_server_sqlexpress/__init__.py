from . import server
import asyncio
import argparse

def main():
    """Main entry point for the package."""
    parser = argparse.ArgumentParser(description='SQL Server Express MCP Server')
    parser.add_argument('--server', required=True,
                       help='SQL Server instance name')
    parser.add_argument('--auth', choices=['windows', 'sql'],
                       default='windows',
                       help='Authentication type')
    parser.add_argument('--username',
                       help='SQL Server authentication username')
    parser.add_argument('--password',
                       help='SQL Server authentication password')
    parser.add_argument('--trusted-connection',
                       choices=['yes', 'no'],
                       default='no',
                       help='Use trusted connection')
    parser.add_argument('--trust-server-certificate',
                       choices=['yes', 'no'],
                       default='no',
                       help='Trust server certificate')
    parser.add_argument('--allowed-databases',
                       help='Comma-separated list of allowed database names',
                       default='')
    
    args = parser.parse_args()
    
    # Convert allowed databases string to list
    args.allowed_databases = [db.strip() for db in args.allowed_databases.split(',') if db.strip()]
    
    asyncio.run(server.main(args))

__all__ = ["main", "server"]