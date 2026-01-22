import hashlib
import secrets


def generate_api_key(length: int = 64) -> str:
    """Generate a secure random API key."""
    return secrets.token_hex(length // 2)


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA-256.

    Returns the hex digest of the hash.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, api_key_hash: str) -> bool:
    """
    Verify an API key against its stored hash.

    Uses constant-time comparison to prevent timing attacks.
    """
    return secrets.compare_digest(hash_api_key(api_key), api_key_hash)
