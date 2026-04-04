from fastapi import Request


def get_base_url(request: Request) -> str:
    """Derive the public-facing base URL from the incoming request.

    Behind a reverse proxy (e.g. Cloudflare Tunnel) the actual scheme and host
    seen by the client differ from what uvicorn receives.  We prefer the
    forwarded headers when present.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"
