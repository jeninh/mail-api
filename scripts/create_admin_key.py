#!/usr/bin/env python3
"""
CLI script to generate an admin API key.

Usage:
    python scripts/create_admin_key.py

This generates a secure random key that should be added to your .env file
as ADMIN_API_KEY.
"""

import secrets


def generate_admin_key(length: int = 64) -> str:
    """Generate a secure random admin API key."""
    return secrets.token_hex(length // 2)


def main():
    api_key = generate_admin_key()

    print("\n✅ Admin API Key Created")
    print(f"API Key: {api_key}")
    print("\n📝 Add this to your .env file as:")
    print(f"ADMIN_API_KEY={api_key}")
    print("\n⚠️  Keep this key secure!")


if __name__ == "__main__":
    main()
