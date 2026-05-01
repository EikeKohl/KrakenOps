"""GitHub Projects v2 client used by the poller.

Defines an abstract `GitHubClient` and two implementations:

- `GitHubGraphQLClient` — real httpx-based client targeting api.github.com/graphql.
- `FakeGitHubClient` — in-memory; lets tests + no-PAT demos exercise the
  full poller/orchestrator pipeline without network or credentials.

The interface is deliberately tiny: list items, set status. Field/option ID
discovery is cached on first list_items() call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

_log = logging.getLogger("krakenops.poller.github")

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Standard statuses we expect on the project's "Status" single-select field.
KNOWN_STATUSES = ("Todo", "In Progress", "Needs Human Review", "Done")


@dataclass
class TicketItem:
    """A single GitHub ProjectV2 item, normalized."""

    id: str               # ProjectV2Item node ID
    title: str
    status: str           # one of KNOWN_STATUSES, or whatever the user has
    url: str | None
    labels: list[str]     # for matching against agent_mappings.match_label


class GitHubClient(Protocol):
    async def list_items(self) -> list[TicketItem]: ...
    async def set_status(self, item_id: str, status: str) -> None: ...
    async def aclose(self) -> None: ...


# --- Real GraphQL implementation -----------------------------------------

_LIST_QUERY = """
query($project: ID!) {
  node(id: $project) {
    ... on ProjectV2 {
      fields(first: 50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
      items(first: 100) {
        nodes {
          id
          content {
            __typename
            ... on Issue {
              title
              url
              labels(first: 20) { nodes { name } }
            }
            ... on PullRequest {
              title
              url
              labels(first: 20) { nodes { name } }
            }
            ... on DraftIssue { title }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2SingleSelectField { name } }
                name
              }
            }
          }
        }
      }
    }
  }
}
"""

_UPDATE_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field,
    value: { singleSelectOptionId: $option }
  }) { projectV2Item { id } }
}
"""


class GitHubGraphQLClient:
    def __init__(self, pat: str, project_id: str, http: httpx.AsyncClient | None = None) -> None:
        self._project_id = project_id
        self._http = http or httpx.AsyncClient(
            timeout=10.0,
            headers={
                "Authorization": f"bearer {pat}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "krakenops-backend",
            },
        )
        # Discovered on first list_items() call.
        self._status_field_id: str | None = None
        self._status_option_ids: dict[str, str] = {}

    async def list_items(self) -> list[TicketItem]:
        data = await self._gql(_LIST_QUERY, {"project": self._project_id})
        node = data.get("node") or {}
        self._cache_status_field(node.get("fields", {}).get("nodes") or [])

        items_out: list[TicketItem] = []
        for raw in (node.get("items", {}).get("nodes") or []):
            content = raw.get("content") or {}
            title = content.get("title") or "(untitled)"
            url = content.get("url")
            labels = [
                lab["name"]
                for lab in (content.get("labels") or {}).get("nodes", [])
            ]
            status = "Todo"
            for fv in (raw.get("fieldValues") or {}).get("nodes") or []:
                if (fv.get("field") or {}).get("name") == "Status" and fv.get("name"):
                    status = fv["name"]
                    break
            items_out.append(
                TicketItem(id=raw["id"], title=title, status=status, url=url, labels=labels)
            )
        return items_out

    async def set_status(self, item_id: str, status: str) -> None:
        if self._status_field_id is None or status not in self._status_option_ids:
            # Force a refresh; we may not have hit list_items yet.
            await self.list_items()
        if self._status_field_id is None:
            raise RuntimeError("Status field not found on project")
        option_id = self._status_option_ids.get(status)
        if option_id is None:
            raise RuntimeError(f"Status option {status!r} not found on project")
        await self._gql(
            _UPDATE_MUTATION,
            {
                "project": self._project_id,
                "item": item_id,
                "field": self._status_field_id,
                "option": option_id,
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _cache_status_field(self, fields: list[dict]) -> None:
        for field in fields:
            if field.get("name") == "Status":
                self._status_field_id = field["id"]
                self._status_option_ids = {
                    opt["name"]: opt["id"] for opt in (field.get("options") or [])
                }
                return

    async def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        r = await self._http.post(
            GITHUB_GRAPHQL_URL, json={"query": query, "variables": variables}
        )
        r.raise_for_status()
        body = r.json()
        if "errors" in body:
            raise RuntimeError(f"GitHub GraphQL error: {body['errors']}")
        return body.get("data") or {}


# --- Fake implementation for tests + demo mode ---------------------------


class FakeGitHubClient:
    """In-memory project board. Mutations land instantly."""

    def __init__(self, items: list[TicketItem] | None = None) -> None:
        self._items: dict[str, TicketItem] = {it.id: it for it in (items or [])}
        self.status_calls: list[tuple[str, str]] = []   # for assertions in tests

    async def list_items(self) -> list[TicketItem]:
        return list(self._items.values())

    async def set_status(self, item_id: str, status: str) -> None:
        self.status_calls.append((item_id, status))
        if item_id in self._items:
            self._items[item_id] = TicketItem(
                id=item_id,
                title=self._items[item_id].title,
                status=status,
                url=self._items[item_id].url,
                labels=self._items[item_id].labels,
            )

    async def aclose(self) -> None:
        return None

    # Test helpers ---------------------------------------------------------

    def add(self, item: TicketItem) -> None:
        self._items[item.id] = item

    def remove(self, item_id: str) -> None:
        self._items.pop(item_id, None)
