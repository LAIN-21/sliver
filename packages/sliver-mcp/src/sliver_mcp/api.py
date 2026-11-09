"""Thin HTTP client for the public Sliver API. Responses are untrusted data."""

from typing import Any

import httpx


class ApiError(RuntimeError):
    pass


class SliverApi:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.http = client or httpx.Client(base_url=self.base_url, timeout=30.0)

    def get_json(self, path: str, **params: Any) -> Any:
        try:
            response = self.http.get(path, params={k: v for k, v in params.items() if v not in (None, "")})
        except httpx.HTTPError as error:
            raise ApiError(f"Sliver API at {self.base_url} is unreachable: {error}") from None
        if response.status_code == 404:
            raise ApiError(f"Not found: {path}")
        if response.status_code >= 400:
            raise ApiError(f"Sliver API answered {response.status_code} for {path}: {response.text[:300]}")
        return response.json()

    def search(self, **params: Any) -> dict[str, Any]:
        return self.get_json("/api/catalog", **params)

    def listing(self, resource_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/catalog/{resource_id}")

    def receipt(self, receipt_id: str) -> dict[str, Any] | None:
        try:
            return self.get_json(f"/api/receipts/{receipt_id}")
        except ApiError:
            return None

    def data_path(self, resource_id: str) -> str:
        return f"/api/resources/{resource_id}/data"

    def fetch_data(self, resource_id: str, payment_signature: str | None = None) -> httpx.Response:
        headers = {"PAYMENT-SIGNATURE": payment_signature} if payment_signature else {}
        return self.http.get(self.data_path(resource_id), headers=headers, timeout=180.0)
