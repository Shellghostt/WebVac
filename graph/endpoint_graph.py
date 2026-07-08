"""
Endpoint graph — models parent/child relationships between discovered URLs.

Enables attack-surface visualization, path analysis, and prioritization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse


@dataclass
class EndpointNode:
    url: str
    method: str = "GET"
    source: str = ""
    depth: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)


class EndpointGraph:
    def __init__(self, root_url: str) -> None:
        self.root_url = root_url
        self._nodes: dict[str, EndpointNode] = {}
        self.add_node(root_url, source="seed", depth=0)

    def _normalize(self, url: str, parent_url: Optional[str] = None) -> str:
        if url.startswith(("http://", "https://")):
            return url
        base = parent_url or self.root_url
        return urljoin(base, url)

    def add_node(
        self,
        url: str,
        *,
        method: str = "GET",
        source: str = "",
        depth: int = 0,
        parent_url: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> EndpointNode:
        normalized = self._normalize(url, parent_url)
        if normalized not in self._nodes:
            self._nodes[normalized] = EndpointNode(
                url=normalized,
                method=method,
                source=source,
                depth=depth,
                metadata=metadata or {},
            )
        elif metadata:
            self._nodes[normalized].metadata.update(metadata)
        return self._nodes[normalized]

    def add_edge(
        self,
        parent_url: str,
        child_url: str,
        *,
        method: str = "GET",
        source: str = "",
        child_depth: Optional[int] = None,
    ) -> None:
        parent = self._normalize(parent_url)
        child = self._normalize(child_url, parent)
        parent_node = self.add_node(parent)
        depth = child_depth if child_depth is not None else parent_node.depth + 1
        child_node = self.add_node(
            child, method=method, source=source, depth=depth, parent_url=parent
        )
        if child not in parent_node.children:
            parent_node.children.append(child)

    def get_node(self, url: str) -> Optional[EndpointNode]:
        return self._nodes.get(self._normalize(url))

    def all_endpoints(self) -> list[EndpointNode]:
        return list(self._nodes.values())

    def paths_from_root(self) -> list[list[str]]:
        """Return URL paths from root to each leaf (for visualization)."""
        paths: list[list[str]] = []

        def walk(node_url: str, path: list[str]) -> None:
            node = self._nodes.get(node_url)
            if not node or not node.children:
                paths.append(path + [node_url])
                return
            for child in node.children:
                walk(child, path + [node_url])

        walk(self.root_url, [])
        return paths

    def to_dict(self) -> dict:
        return {
            "root": self.root_url,
            "nodes": {
                url: {
                    "url": n.url,
                    "method": n.method,
                    "source": n.source,
                    "depth": n.depth,
                    "metadata": n.metadata,
                    "children": n.children,
                }
                for url, n in self._nodes.items()
            },
        }

    def to_tree_lines(self) -> list[str]:
        """ASCII tree for logging / reports."""
        lines: list[str] = []
        root_path = urlparse(self.root_url).path or "/"
        lines.append(root_path)

        def render(node_url: str, prefix: str, is_last: bool) -> None:
            node = self._nodes.get(node_url)
            if not node:
                return
            for i, child_url in enumerate(node.children):
                child = self._nodes[child_url]
                branch = "└── " if i == len(node.children) - 1 else "├── "
                label = urlparse(child.url).path or child.url
                if child.method and child.method != "GET":
                    label = f"{child.method} {label}"
                lines.append(prefix + branch + label)
                extension = "    " if i == len(node.children) - 1 else "│   "
                render(child_url, prefix + extension, i == len(node.children) - 1)

        root_node = self._nodes.get(self.root_url)
        if root_node:
            for i, child_url in enumerate(root_node.children):
                child = self._nodes[child_url]
                branch = "└── " if i == len(root_node.children) - 1 else "├── "
                label = urlparse(child.url).path or child.url
                if child.method and child.method != "GET":
                    label = f"{child.method} {label}"
                lines.append(branch + label)
                extension = "    " if i == len(root_node.children) - 1 else "│   "
                render(child_url, extension, False)
        return lines
