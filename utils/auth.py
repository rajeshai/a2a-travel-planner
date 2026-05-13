"""
Shared JWT authentication utilities for A2A agents.
Handles token validation, JWKS fetching, rate limiting,
and webhook signature verification.
"""

import time
import hashlib
import hmac
import httpx
import jwt as pyjwt
from collections import defaultdict


class A2AAuthenticator:
    """
    Validates incoming A2A requests using JWT tokens
    verified against the remote agent's JWKS endpoint.
    Supports automatic key rotation with cached key sets.
    """

    def __init__(self, jwks_cache_ttl: int = 3600):
        self.jwks_cache_ttl = jwks_cache_ttl
        self._jwks_cache: dict[str, dict] = {}
        self._cache_timestamps: dict[str, float] = {}

    async def fetch_jwks(self, jwks_url: str) -> dict:
        """Fetch and cache JWKS from the issuing agent's endpoint."""
        now = time.time()

        if (
            jwks_url in self._jwks_cache
            and now - self._cache_timestamps.get(jwks_url, 0)
                < self.jwks_cache_ttl
        ):
            return self._jwks_cache[jwks_url]

        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks = response.json()

        self._jwks_cache[jwks_url] = jwks
        self._cache_timestamps[jwks_url] = now
        return jwks

    async def validate_token(
        self,
        token: str,
        jwks_url: str,
        expected_audience: str,
        expected_scopes: list[str] | None = None
    ) -> dict:
        """
        Validate a JWT token against the JWKS endpoint.
        Checks signature, expiration, audience, and optional scopes.
        """
        jwks = await self.fetch_jwks(jwks_url)

        # Extract the key ID from the token header
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find the matching key in the JWKS
        signing_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                signing_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if signing_key is None:
            # Key not found — try refreshing JWKS (key may have rotated)
            self._jwks_cache.pop(jwks_url, None)
            jwks = await self.fetch_jwks(jwks_url)

            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    signing_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break

        if signing_key is None:
            raise ValueError(f"No matching key found for kid: {kid}")

        # Decode and validate the token
        payload = pyjwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=expected_audience,
            options={"require": ["exp", "iss", "aud"]}
        )

        # Validate scopes if required
        if expected_scopes:
            token_scopes = payload.get("scope", "").split()
            if not all(s in token_scopes for s in expected_scopes):
                raise PermissionError(
                    f"Token missing required scopes: {expected_scopes}"
                )

        return payload


class RateLimiter:
    """
    Token-bucket rate limiter for A2A agent endpoints.
    Limits requests per agent based on their authenticated identity.
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._request_log: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, agent_id: str) -> bool:
        """Check if the requesting agent is within rate limits."""
        now = time.time()
        cutoff = now - self.window_seconds

        # Remove expired entries
        self._request_log[agent_id] = [
            t for t in self._request_log[agent_id] if t > cutoff
        ]

        if len(self._request_log[agent_id]) >= self.max_requests:
            return False

        self._request_log[agent_id].append(now)
        return True


class WebhookValidator:
    """
    Validates incoming webhook payloads using HMAC signatures.
    Ensures that task update callbacks originate from
    the expected A2A agent.
    """

    def __init__(self, shared_secrets: dict[str, str]):
        # Map of agent_id -> shared secret for HMAC validation
        self.shared_secrets = shared_secrets

    def validate(
        self,
        agent_id: str,
        payload: bytes,
        signature: str
    ) -> bool:
        """
        Validate a webhook payload against its HMAC-SHA256 signature.
        The signature should be provided in the X-A2A-Signature header.
        """
        secret = self.shared_secrets.get(agent_id)
        if not secret:
            return False

        expected = hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
