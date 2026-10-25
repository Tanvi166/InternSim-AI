"""
Token Encryption Service for InternSim AI.
Uses AES-256-GCM authenticated symmetric encryption to secure third-party credentials (e.g. GitHub tokens) at rest.
Tokens are never stored or logged in plain text.
Fails closed if encryption key is missing or invalid.
"""

import os
import base64
import binascii
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def _get_encryption_key() -> bytes:
    """
    Retrieves and strictly validates the 256-bit (32-byte) AES-GCM encryption key.

    Accepts only a 64-character hexadecimal string or a canonical 44-character
    standard Base64 string, each representing exactly 32 bytes.

    Fails closed if the dedicated GITHUB_TOKEN_ENCRYPTION_KEY is unset.
    Tests must inject their own key explicitly.
    """
    raw_key = os.environ.get("GITHUB_TOKEN_ENCRYPTION_KEY")
    if not raw_key:
        raise RuntimeError(
            "GITHUB_TOKEN_ENCRYPTION_KEY environment variable is missing. "
            "A securely generated 32-byte key encoded as 64 hexadecimal characters or 44 Base64 characters is required."
        )

    clean_key = raw_key.strip()
    key_bytes: Optional[bytes] = None

    # Try 64-char Hexadecimal
    if len(clean_key) == 64:
        try:
            key_bytes = binascii.unhexlify(clean_key)
        except (binascii.Error, ValueError):
            pass

    # Try canonical padded Base64 encoding of exactly 32 bytes.
    if key_bytes is None and len(clean_key) == 44:
        try:
            decoded = base64.b64decode(clean_key.encode("utf-8"), validate=True)
            if len(decoded) == 32 and base64.b64encode(decoded).decode("ascii") == clean_key:
                key_bytes = decoded
        except (binascii.Error, ValueError):
            pass

    if not key_bytes or len(key_bytes) != 32:
        raise ValueError(
            "Invalid GITHUB_TOKEN_ENCRYPTION_KEY encoding or length. "
            "Provide a 32-byte key encoded as 64 hexadecimal characters or 44 canonical Base64 characters. "
            "Generate a secure key using the GitHub integration setup guide."
        )

    return key_bytes

def encrypt_token(plain_token: str) -> str:
    """
    Encrypts a plaintext token using AES-256-GCM.
    Returns:
        Base64-encoded string containing nonce (12 bytes) + ciphertext + tag (16 bytes).
    """
    if not plain_token:
        raise ValueError("Cannot encrypt empty token")

    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    # Standard 96-bit (12 bytes) nonce for AES-GCM
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_token.encode("utf-8"), None)

    combined = nonce + ciphertext
    return base64.b64encode(combined).decode("utf-8")

def decrypt_token(encrypted_token_b64: str) -> str:
    """
    Decrypts a base64-encoded AES-256-GCM ciphertext.
    Returns:
        Plaintext token.
    Raises:
        ValueError if the payload is malformed or decryption authentication fails.
    """
    if not encrypted_token_b64:
        raise ValueError("Cannot decrypt empty payload")

    try:
        combined = base64.b64decode(encrypted_token_b64.encode("utf-8"))
        if len(combined) < 28: # 12 bytes nonce + 16 bytes minimum GCM tag
            raise ValueError("Encrypted payload too short")

        nonce = combined[:12]
        ciphertext = combined[12:]

        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")
    except Exception:
        raise ValueError("Decryption failed: invalid ciphertext or encryption key") from None
