#!/usr/bin/env python3
"""
Artemis CLI - Programmatic key management for Artemis AI Management Platform.

Usage:
    artemis-cli.py create-key [--name NAME] [--artemis-url URL]
    artemis-cli.py list-keys [--artemis-url URL]
    artemis-cli.py revoke-key KEY_ID [--artemis-url URL]

Environment Variables:
    ARTEMIS_API_KEY - Your Artemis API key (art_xxx)
    ARTEMIS_URL - Artemis server URL (default: https://artemis.jettaintelligence.com)

Examples:
    # Create a key for a new app
    export ARTEMIS_API_KEY=art_your_key_here
    ./artemis-cli.py create-key --name "Robin Email Bot"

    # List all keys
    ./artemis-cli.py list-keys

    # Revoke a key
    ./artemis-cli.py revoke-key abc123-uuid-here
"""

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_ARTEMIS_URL = "https://artemis.jettaintelligence.com"


def get_api_key():
    """Get API key from environment."""
    key = os.environ.get("ARTEMIS_API_KEY")
    if not key:
        print("Error: ARTEMIS_API_KEY environment variable not set", file=sys.stderr)
        print("Set it with: export ARTEMIS_API_KEY=art_your_key_here", file=sys.stderr)
        sys.exit(1)
    return key


def api_request(method: str, endpoint: str, artemis_url: str, data: dict = None):
    """Make an API request to Artemis."""
    url = f"{artemis_url.rstrip('/')}{endpoint}"
    api_key = get_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode() if data else None

    req = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req) as response:
            return json.loads(response.read().decode())
    except HTTPError as e:
        error_body = e.read().decode()
        try:
            error_json = json.loads(error_body)
            detail = error_json.get("detail", error_body)
        except json.JSONDecodeError:
            detail = error_body
        print(f"Error {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def cmd_create_key(args):
    """Create a new API key."""
    data = {"name": args.name}
    result = api_request("POST", "/api/v1/keys", args.artemis_url, data)

    print(f"Created key: {result['name']}")
    print(f"  ID: {result['id']}")
    print(f"  Key: {result['key']}")
    print(f"  Prefix: {result['key_prefix']}")
    print(f"  Created: {result['created_at']}")
    print()
    print("Save this key securely - it won't be shown again!")

    # Also output just the key for piping
    if args.quiet:
        print(result['key'])


def cmd_list_keys(args):
    """List all API keys."""
    result = api_request("GET", "/api/v1/keys", args.artemis_url)

    keys = result.get("keys", [])
    if not keys:
        print("No API keys found.")
        return

    print(f"{'Name':<30} {'Prefix':<15} {'Status':<10} {'Last Used':<20}")
    print("-" * 75)

    for key in keys:
        status = "Revoked" if key.get("revoked_at") else "Active"
        if key.get("is_system"):
            status = "System"
        last_used = key.get("last_used_at", "Never")[:19] if key.get("last_used_at") else "Never"

        print(f"{key['name']:<30} {key['key_prefix']:<15} {status:<10} {last_used:<20}")


def cmd_revoke_key(args):
    """Revoke an API key."""
    result = api_request("DELETE", f"/api/v1/keys/{args.key_id}", args.artemis_url)

    print(f"Key revoked: {result.get('id', args.key_id)}")


def main():
    parser = argparse.ArgumentParser(
        description="Artemis CLI - Programmatic key management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--artemis-url",
        default=os.environ.get("ARTEMIS_URL", DEFAULT_ARTEMIS_URL),
        help=f"Artemis server URL (default: {DEFAULT_ARTEMIS_URL})"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-key
    create_parser = subparsers.add_parser("create-key", help="Create a new API key")
    create_parser.add_argument("--name", default="Default", help="Key name/description")
    create_parser.add_argument("--quiet", "-q", action="store_true", help="Only output the key (for scripting)")
    create_parser.set_defaults(func=cmd_create_key)

    # list-keys
    list_parser = subparsers.add_parser("list-keys", help="List all API keys")
    list_parser.set_defaults(func=cmd_list_keys)

    # revoke-key
    revoke_parser = subparsers.add_parser("revoke-key", help="Revoke an API key")
    revoke_parser.add_argument("key_id", help="The key ID to revoke")
    revoke_parser.set_defaults(func=cmd_revoke_key)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
