"""Process-wide HTTP clients with connection pooling."""

import httpx


_sync_client: httpx.Client | None = None
_async_client: httpx.AsyncClient | None = None


def get_sync_http_client() -> httpx.Client:
	global _sync_client
	if _sync_client is None or _sync_client.is_closed:
		_sync_client = httpx.Client()
	return _sync_client


def get_async_http_client() -> httpx.AsyncClient:
	global _async_client
	if _async_client is None or _async_client.is_closed:
		_async_client = httpx.AsyncClient()
	return _async_client


async def close_http_clients() -> None:
	global _sync_client, _async_client
	async_client, _async_client = _async_client, None
	sync_client, _sync_client = _sync_client, None
	try:
		if async_client is not None and not async_client.is_closed:
			await async_client.aclose()
	finally:
		if sync_client is not None and not sync_client.is_closed:
			sync_client.close()
