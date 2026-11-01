"""Control Tower API Client for Airflow DAGs.

Provides decoupled HTTP integration between Apache Airflow tasks
and Control Tower ingestion/sync endpoints (Type B and Type C connectors).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("airflow.task")

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


class ControlTowerClient:
    """HTTP client for orchestrating Control Tower sync operations."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("CONTROL_TOWER_API_URL", "http://backend:8000")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("ADMIN_API_KEY", "")
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "Airflow-ControlTower-Orchestrator/1.0",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def trigger_type_a_sync(
        self,
        carrier_slug: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Trigger Type A simulator pull sync via Control Tower backend.

        Endpoint: POST /api/v1/sync/type-a
        """
        endpoint = f"{self.base_url}/api/v1/sync/type-a"
        params: dict[str, Any] = {"limit": limit}
        if carrier_slug:
            params["carrier_slug"] = carrier_slug

        logger.info(
            "Triggering Type A sync against %s (carrier: %s, limit: %d)",
            endpoint,
            carrier_slug or "ALL",
            limit,
        )

        if requests is not None:
            resp = requests.post(
                endpoint,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

        import urllib.parse
        import urllib.request

        url = endpoint
        if params:
            url += f"?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, data=b"", headers=self._get_headers(), method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)  # type: ignore[no-any-return]

    def trigger_type_b_sync(self, carrier_name: str | None = None) -> dict[str, Any]:
        """Trigger Type B pull polling sync via Control Tower backend.

        Endpoint: POST /api/v1/sync/type-b
        """
        endpoint = f"{self.base_url}/api/v1/sync/type-b"
        params = {"carrier_name": carrier_name} if carrier_name else {}

        logger.info(
            "Triggering Type B sync against %s (carrier: %s)",
            endpoint,
            carrier_name or "ALL",
        )

        if requests is not None:
            resp = requests.post(
                endpoint,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

        # Fallback using standard library urllib
        import urllib.parse
        import urllib.request

        url = endpoint
        if params:
            url += f"?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, data=b"", headers=self._get_headers(), method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)  # type: ignore[no-any-return]

    def upload_type_c_file(
        self,
        file_path: str | Path,
        carrier_name: str,
    ) -> dict[str, Any]:
        """Upload and ingest a Type C batch file (CSV / XLSX) via Control Tower backend.

        Endpoint: POST /api/v1/sync/type-c/upload
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found for Type C upload: {file_path}")

        endpoint = f"{self.base_url}/api/v1/sync/type-c/upload"
        logger.info(
            "Uploading Type C batch file '%s' for carrier '%s' to %s",
            path.name,
            carrier_name,
            endpoint,
        )

        if requests is not None:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, "application/octet-stream")}
                data = {"carrier_name": carrier_name}
                headers = {k: v for k, v in self._get_headers().items() if k != "Content-Type"}
                resp = requests.post(
                    endpoint,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]

        # Fallback using standard library urllib with multipart/form-data
        import urllib.request

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body = bytearray()

        # Add carrier_name field
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="carrier_name"\r\n\r\n')
        body.extend(carrier_name.encode() + b"\r\n")

        # Add file content
        with open(path, "rb") as f:
            file_bytes = f.read()

        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(file_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        headers = self._get_headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        req = urllib.request.Request(endpoint, data=bytes(body), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)  # type: ignore[no-any-return]

    def check_health(self) -> dict[str, Any]:
        """Perform a readiness health check against Control Tower backend."""
        endpoint = f"{self.base_url}/api/v1/health"
        if requests is not None:
            resp = requests.get(endpoint, headers=self._get_headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

        import urllib.request

        req = urllib.request.Request(endpoint, headers=self._get_headers(), method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))  # type: ignore[no-any-return]
