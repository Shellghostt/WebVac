"""Orchestrates active recon probes — isolated from passive pipeline."""

from __future__ import annotations

import logging
from typing import Any, Optional

import aiohttp

from webvac.active.graphql_probe import probe_graphql
from webvac.active.interesting_files import probe_interesting_files
from webvac.intelligence.store import IntelligenceStore
from webvac.models.findings import ProbeResult


class ProbeRunner:
    def __init__(
        self,
        config: dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("webvac.active")

    async def run(
        self,
        base_url: str,
        intelligence: Optional[IntelligenceStore] = None,
    ) -> list[ProbeResult]:
        if not self.config.get("active_recon", False):
            return []

        self.logger.warning(
            "Active recon enabled — making out-of-band requests to %s", base_url
        )
        results: list[ProbeResult] = []

        async with aiohttp.ClientSession() as session:
            file_results = await probe_interesting_files(
                base_url, self.config, session=session
            )
            results.extend(file_results)
            self.logger.info("interesting_files: %d hits", len(file_results))

        graphql_results = await probe_graphql(base_url, self.config, intelligence)
        results.extend(graphql_results)
        self.logger.info("graphql_probe: %d hits", len(graphql_results))

        return results
