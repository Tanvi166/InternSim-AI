# GitHub integration setup

## Token encryption key

The backend requires `GITHUB_TOKEN_ENCRYPTION_KEY`. Supply exactly 32 cryptographically random bytes encoded as either 64 hexadecimal characters or canonical, padded Base64 (44 characters). Raw text keys and fallback keys are not accepted.

Generate a key locally with Python's cryptographic random generator. Choose one encoding:

```powershell
# Hexadecimal (64 characters)
python -c "import secrets; print(secrets.token_hex(32))"

# Base64 (44 characters)
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode('ascii'))"
```

Configure the generated value as the `GITHUB_TOKEN_ENCRYPTION_KEY` secret in the backend's deployment environment or secret manager. For a local environment file, use a placeholder such as:

```dotenv
GITHUB_TOKEN_ENCRYPTION_KEY=<generated-64-character-hex-or-44-character-base64-value>
```

Never commit the generated key or include it in logs. `TESTING` and pytest environment variables do not enable a key fallback. Tests must explicitly inject their test key. The OAuth scope explanation and GitHub App migration considerations are in [GITHUB_OAUTH_PERMISSIONS.md](GITHUB_OAUTH_PERMISSIONS.md).
