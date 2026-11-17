#!/usr/bin/env python3
"""
Gateway MCP endpoint verification

What it checks:
    1. Does Gateway inbound authentication accept a Cognito ID token?
    2. Does the Gateway expose the Lambda as an MCP tool (tools/list)?
    3. Does tools/call actually invoke the Lambda?
    4. Is a call without authentication rejected?

The Lambda does not implement the MCP protocol. The point of this check is that the
Gateway translates JSON-RPC into a Lambda invocation.

Run:
    python3 tools/verify_gateway_mcp.py <GATEWAY_URL> <ID_TOKEN_FILE>
"""

import json
import ssl
import sys
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2025-03-26"


def make_ssl_context():
    """
    The python.org build of macOS Python does not use the system keychain, which causes
    CERTIFICATE_VERIFY_FAILED. Use the CA bundle of certifi (installed alongside botocore) explicitly.
    (Verification is not turned off — turning it off would make this test meaningless.)
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = make_ssl_context()


def post(url, payload, token=None, session_id=None):
    """MCP JSON-RPC request. streamable-http answers with JSON or SSE."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if session_id:
        req.add_header("Mcp-Session-Id", session_id)

    try:
        with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as r:
            body = r.read().decode()
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def parse_body(body):
    """Extract the JSON-RPC object from a JSON or SSE (data: ...) response."""
    body = body.strip()
    if not body:
        return None
    if body.startswith("{"):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    return None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    url, token_file = sys.argv[1], sys.argv[2]
    token = open(token_file).read().strip()

    print("=" * 68)
    print("  Gateway MCP verification")
    print(f"  {url}")
    print("=" * 68)

    # ── 0) Call without authentication -> must be rejected ──
    print("\n[0] initialize without authentication (should be rejected)")
    status, _, body = post(
        url,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "dryrun", "version": "1"},
            },
        },
    )
    print(f"    HTTP {status}")
    if status in (401, 403):
        print("    O Unauthenticated call was blocked")
    else:
        print(f"    X Not blocked — response: {body[:200]}")

    # ── 1) initialize ──
    print("\n[1] initialize (Bearer token)")
    status, headers, body = post(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "dryrun", "version": "1"},
            },
        },
        token=token,
    )
    print(f"    HTTP {status}")
    session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    print(f"    Mcp-Session-Id: {session_id}")
    obj = parse_body(body)
    if status != 200 or obj is None:
        print(f"    X Failed — {body[:400]}")
        return 1
    info = obj.get("result", {}).get("serverInfo", {})
    print(f"    O Server {info.get('name')} / protocol {obj.get('result',{}).get('protocolVersion')}")

    post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"},
         token=token, session_id=session_id)

    # ── 2) tools/list ──
    print("\n[2] tools/list")
    status, _, body = post(
        url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        token=token, session_id=session_id,
    )
    obj = parse_body(body)
    if status != 200 or obj is None:
        print(f"    X Failed HTTP {status} — {body[:400]}")
        return 1
    tools = obj.get("result", {}).get("tools", [])
    print(f"    O {len(tools)} tool(s)")
    tool_name = None
    for t in tools:
        print(f"      - {t['name']}")
        print(f"        description: {t.get('description','')[:70]}...")
        print(f"        input: {list(t.get('inputSchema',{}).get('properties',{}))}")
        if "extract_body_composition" in t["name"]:
            tool_name = t["name"]
    if not tool_name:
        print("    X extract_body_composition tool not found")
        return 1

    # ── 3) tools/call ──
    print(f"\n[3] tools/call -> {tool_name}")
    status, _, body = post(
        url,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"s3_key": "measurements/user-a-session-03.pdf"},
            },
        },
        token=token, session_id=session_id,
    )
    obj = parse_body(body)
    print(f"    HTTP {status}")
    if obj is None:
        print(f"    X Failed to parse response — {body[:400]}")
        return 1
    if "error" in obj:
        print(f"    X JSON-RPC error: {obj['error']}")
        return 1
    result = obj.get("result", {})
    print(f"    isError: {result.get('isError')}")
    for c in result.get("content", []):
        if "text" in c:
            txt = c["text"]
            print(f"    Lambda response: {txt[:300]}")
            if "NOT_IMPLEMENTED" in txt:
                print("    O Gateway invoked the Lambda (placeholder response confirmed)")
            if "extract_body_composition" in txt or "received_tool" in txt:
                print("    O The tool name reached the Lambda context")

    print("\n" + "=" * 68)
    print("  Verification complete")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
