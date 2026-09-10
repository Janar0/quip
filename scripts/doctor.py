"""Read-only OpenRouter connectivity check. Run from the backend's environment."""

import ipaddress
import socket
import sys
import urllib.error
import urllib.request

HOST = "openrouter.ai"


def main() -> int:
    print("Checking DNS and HTTPS from this process (no API key is sent).")
    try:
        addresses = sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
            }
        )
        print("DNS:", ", ".join(addresses))
        if any(
            ipaddress.ip_address(address) in ipaddress.ip_network("198.18.0.0/15")
            for address in addresses
            if ":" not in address
        ):
            print(
                "VPN fake-IP DNS detected. The backend/container must use the matching VPN route or HTTP proxy."
            )
    except OSError as exc:
        print(f"DNS FAILED: {exc}")
        print(
            "Check the OS/container resolver and VPN. Retrying an API key cannot repair DNS."
        )
        return 1
    proxies = urllib.request.getproxies()
    print(
        "HTTPS proxy:",
        "configured"
        if proxies.get("https") or proxies.get("all")
        else "not configured",
    )
    try:
        request = urllib.request.Request(
            f"https://{HOST}/api/v1/models", headers={"User-Agent": "QUIP-doctor"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            print("HTTPS:", response.status)
    except (urllib.error.URLError, OSError) as exc:
        # Do not dump proxy URLs, which can contain credentials.
        print(
            f"HTTPS FAILED ({type(exc).__name__}). Check VPN/proxy reachability and system CA certificates."
        )
        return 1
    print(
        "OpenRouter is reachable. This checks connectivity, not API-key validity or generation."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
