"""Standalone fake provider HTTP server — DEV/TEST ONLY.

Serves the same simulated Microsoft Graph / Zoom / Google Meet endpoints as the
in-process ``FakeProviders`` mock so a browser E2E test can run the real OAuth
redirect flow. It is never a real provider and the backend marks every
connection made through it as SANDBOX (endpoint overrides are refused in
production).

    python -m tests.fakes.server --port 9100
    INTEGRATION_ENDPOINT_OVERRIDES='{"teams":"http://127.0.0.1:9100/teams",...}'
"""

from __future__ import annotations

import argparse

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from tests.fakes.fake_providers import FakeProviders, overrides_json


def create_app(base_url: str) -> Starlette:
    providers = FakeProviders(base_url=base_url)

    async def handle(request: Request) -> Response:
        body = await request.body()
        req = httpx.Request(
            request.method,
            f"{base_url}{request.url.path}" + (f"?{request.url.query}" if request.url.query else ""),
            headers=[(k, v) for k, v in request.headers.items() if k.lower() != "host"],
            content=body,
        )
        res = providers.handle(req)
        res.read()
        headers = {k: v for k, v in res.headers.items() if k.lower() not in ("content-length", "content-encoding")}
        return Response(res.content, status_code=res.status_code, headers=headers)

    async def scenario(request: Request) -> Response:
        # Test hook: POST /__scenario?provider=teams&name=transcripts_disabled (empty name clears)
        provider, name = request.query_params.get("provider", ""), request.query_params.get("name", "")
        if name:
            providers.scenario[provider] = name
        else:
            providers.scenario.pop(provider, None)
        return Response("ok")

    methods = ["GET", "POST", "DELETE", "PUT", "PATCH"]
    return Starlette(
        routes=[Route("/__scenario", scenario, methods=["POST"]), Route("/{path:path}", handle, methods=methods)]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--public-base", default="", help="URL other services use to reach this server")
    args = parser.parse_args()
    base = args.public_base.rstrip("/") or f"http://{args.host}:{args.port}"
    print(f"Fake providers (DEV/TEST ONLY) on {base}\nINTEGRATION_ENDPOINT_OVERRIDES='{overrides_json(base)}'")  # noqa: T201
    uvicorn.run(create_app(base), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
