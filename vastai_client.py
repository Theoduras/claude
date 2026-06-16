"""Minimal client and CLI for the Vast.ai REST API.

The API key is read from the VAST_API_KEY environment variable. It is never
hardcoded and never logged. Get/rotate your key at:
    https://console.vast.ai/account/

Usage examples:
    export VAST_API_KEY="..."        # your own key, not pasted into chat
    python vastai_client.py whoami
    python vastai_client.py offers --max-price 0.5 --gpu-name RTX_4090
    python vastai_client.py instances
    python vastai_client.py create 1234567 --image pytorch/pytorch --disk 20
    python vastai_client.py destroy 9876543

API reference: https://docs.vast.ai/api/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

import requests

DEFAULT_BASE_URL = "https://console.vast.ai/api/v0"


class VastAPIError(RuntimeError):
    """Raised when the Vast.ai API returns an error response."""


class VastClient:
    """Thin wrapper around the Vast.ai v0 REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        api_key = api_key or os.environ.get("VAST_API_KEY")
        if not api_key:
            raise VastAPIError(
                "No API key found. Set the VAST_API_KEY environment variable."
            )
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise VastAPIError(f"Request to {url} failed: {exc}") from exc

        if not resp.ok:
            # Avoid echoing the Authorization header; only surface the body.
            raise VastAPIError(
                f"{method} {path} -> HTTP {resp.status_code}: {resp.text}"
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # --- API methods -----------------------------------------------------

    def whoami(self) -> Any:
        """Return the current user / account details."""
        return self._request("GET", "/users/current/")

    def search_offers(
        self,
        max_price: Optional[float] = None,
        gpu_name: Optional[str] = None,
        num_gpus: Optional[int] = None,
        order: str = "score-",
        limit: int = 20,
    ) -> Any:
        """Search available machine offers (bundles)."""
        query: dict[str, Any] = {"rentable": {"eq": True}}
        if max_price is not None:
            query["dph_total"] = {"lte": max_price}
        if gpu_name is not None:
            query["gpu_name"] = {"eq": gpu_name}
        if num_gpus is not None:
            query["num_gpus"] = {"eq": num_gpus}
        params = {
            "q": json.dumps(query),
            "order": order,
            "limit": limit,
        }
        return self._request("GET", "/bundles/", params=params)

    def list_instances(self) -> Any:
        """List the caller's current instances."""
        return self._request("GET", "/instances/")

    def create_instance(
        self,
        offer_id: int,
        image: str,
        disk: float = 10.0,
        label: Optional[str] = None,
        onstart_cmd: Optional[str] = None,
    ) -> Any:
        """Rent an offer, creating a new instance."""
        body: dict[str, Any] = {
            "client_id": "me",
            "image": image,
            "disk": disk,
        }
        if label is not None:
            body["label"] = label
        if onstart_cmd is not None:
            body["onstart"] = onstart_cmd
        return self._request("PUT", f"/asks/{offer_id}/", json_body=body)

    def destroy_instance(self, instance_id: int) -> Any:
        """Destroy (terminate) an instance the caller owns."""
        return self._request("DELETE", f"/instances/{instance_id}/")


# --- CLI ----------------------------------------------------------------


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal CLI for the Vast.ai API (key via VAST_API_KEY)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", help="Show the authenticated account.")

    p_offers = sub.add_parser("offers", help="Search rentable GPU offers.")
    p_offers.add_argument("--max-price", type=float, help="Max $/hour total.")
    p_offers.add_argument("--gpu-name", help="Exact GPU name, e.g. RTX_4090.")
    p_offers.add_argument("--num-gpus", type=int, help="Number of GPUs.")
    p_offers.add_argument("--limit", type=int, default=20)

    sub.add_parser("instances", help="List your instances.")

    p_create = sub.add_parser("create", help="Rent an offer as a new instance.")
    p_create.add_argument("offer_id", type=int, help="Offer/ask id from 'offers'.")
    p_create.add_argument("--image", required=True, help="Docker image to run.")
    p_create.add_argument("--disk", type=float, default=10.0, help="Disk GB.")
    p_create.add_argument("--label", help="Optional label for the instance.")
    p_create.add_argument("--onstart", help="Command to run on start.")

    p_destroy = sub.add_parser("destroy", help="Destroy an instance.")
    p_destroy.add_argument("instance_id", type=int)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = VastClient()
        if args.command == "whoami":
            _print(client.whoami())
        elif args.command == "offers":
            _print(
                client.search_offers(
                    max_price=args.max_price,
                    gpu_name=args.gpu_name,
                    num_gpus=args.num_gpus,
                    limit=args.limit,
                )
            )
        elif args.command == "instances":
            _print(client.list_instances())
        elif args.command == "create":
            _print(
                client.create_instance(
                    offer_id=args.offer_id,
                    image=args.image,
                    disk=args.disk,
                    label=args.label,
                    onstart_cmd=args.onstart,
                )
            )
        elif args.command == "destroy":
            _print(client.destroy_instance(args.instance_id))
    except VastAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
