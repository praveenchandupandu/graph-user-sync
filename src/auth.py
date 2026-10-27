"""
auth.py - Gets an access token for Microsoft Graph.

Uses MSAL (Microsoft Authentication Library) with the OAuth 2.0
"client credentials" flow: the app signs in as itself (no human user),
using its Client ID + Client Secret, and receives a token that is valid
for about one hour.

MSAL caches the token in memory and only asks Microsoft for a new one
when the old one is about to expire, so calling get_token() before every
request is cheap and means long runs never use an expired token.
"""
import logging

import msal
import requests

log = logging.getLogger("auth")

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class AuthError(Exception):
    """Raised when Microsoft refuses to give us a token."""


class GraphAuth:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        try:
            self._app = msal.ConfidentialClientApplication(
                client_id=client_id,
                client_credential=client_secret,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
            )
        except (ValueError, requests.RequestException) as exc:
            # ValueError: tenant not found / bad tenant id; RequestException: no network
            raise AuthError(f"could not reach Microsoft login for tenant '{tenant_id}': {exc}") from exc

    def get_token(self) -> str:
        try:
            result = self._app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        except requests.RequestException as exc:
            raise AuthError(f"network error while getting token: {exc}") from exc
        if "access_token" not in result:
            # Typical causes: wrong secret, expired secret, wrong tenant ID
            raise AuthError(f"{result.get('error')}: {result.get('error_description')}")
        if result.get("token_source") == "identity_provider":
            log.info("Obtained new Microsoft Graph access token")
        return result["access_token"]

    def auth_header(self) -> str:
        return f"Bearer {self.get_token()}"
