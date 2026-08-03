"""Browser storage collector — localStorage, sessionStorage, cookies, IndexedDB."""

from __future__ import annotations

from webvac.collectors.base import BaseCollector, CollectorContext
from webvac.models.artifacts import BaseArtifact, StorageArtifact

_STORAGE_JS = """
async () => {
  const ls = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      ls[k] = localStorage.getItem(k);
    }
  } catch (e) {}

  const ss = {};
  try {
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      ss[k] = sessionStorage.getItem(k);
    }
  } catch (e) {}

  let cookie = '';
  try { cookie = document.cookie; } catch (e) {}

  const idb = [];
  try {
    if (indexedDB.databases) {
      const dbs = await indexedDB.databases();
      for (const db of dbs) {
        if (db && db.name) idb.push(db.name);
      }
    }
  } catch (e) {}

  let caches = [];
  try {
    if (window.caches && caches.keys) {
      caches = await caches.keys();
    }
  } catch (e) {}

  return { local_storage: ls, session_storage: ss, document_cookie: cookie, indexeddb: idb, cache_buckets: caches };
}
"""


class StorageCollector(BaseCollector):
    name = "storage"

    def supports(self, ctx: CollectorContext) -> bool:
        return ctx.config.get("collectors", {}).get(self.name, False)

    async def collect(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
    ) -> list[BaseArtifact]:
        if page is None:
            return []

        page_url = page.url or ctx.base_url
        try:
            data = await page.evaluate(_STORAGE_JS)
        except Exception:
            data = {}

        artifact = StorageArtifact(
            page_url=page_url,
            local_storage=dict(data.get("local_storage") or {}),
            session_storage=dict(data.get("session_storage") or {}),
            document_cookie=str(data.get("document_cookie") or ""),
            indexeddb_databases=tuple(data.get("indexeddb") or []),
            cache_buckets=tuple(data.get("cache_buckets") or []),
        )
        return [artifact]
