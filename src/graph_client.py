"""
graph_client.py - Reads users from Microsoft Graph, page by page.

REST GET:  https://graph.microsoft.com/v1.0/users?$select=...&$top=100

Pagination: Graph returns at most $top users per response plus an
"@odata.nextLink" URL when more pages exist. We keep following that link
until it is absent. The nextLink already contains all query parameters,
so we must not add them again.
"""
import logging
from typing import Iterator

import requests

from .auth import GraphAuth
from .http_client import request_with_retry

log = logging.getLogger("graph")

GRAPH_USERS_URL = "https://graph.microsoft.com/v1.0/users"

# Only request the fields we actually use (smaller, faster responses; least data exposure)
SELECT_FIELDS = [
    "id",
    "displayName",
    "givenName",
    "surname",
    "mail",
    "userPrincipalName",
    "jobTitle",
    "department",
    "officeLocation",
    "accountEnabled",
]


def iter_user_pages(
    session: requests.Session,
    auth: GraphAuth,
    page_size: int,
    max_attempts: int,
    timeout: int,
) -> Iterator[list[dict]]:
    url = GRAPH_USERS_URL
    params = {"$select": ",".join(SELECT_FIELDS), "$top": str(page_size)}
    page = 0

    while url:
        response = request_with_retry(
            session, "GET", url,
            params=params,
            auth_header=auth.auth_header,
            max_attempts=max_attempts,
            timeout=timeout,
        )
        data = response.json()
        users = data.get("value", [])
        page += 1
        next_link = data.get("@odata.nextLink")
        log.info("Graph page %d: received %d users%s", page, len(users),
                 " (more pages available)" if next_link else " (last page)")
        yield users

        url = next_link
        params = None  # nextLink already includes $select/$top/$skiptoken
