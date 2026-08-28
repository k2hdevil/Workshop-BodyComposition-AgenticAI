#!/usr/bin/env python3
"""
Gateway MCP 엔드포인트 검증

확인하려는 것:
    1. Cognito ID 토큰으로 Gateway 인바운드 인증이 통과하는가
    2. Gateway 가 Lambda 를 MCP 도구로 노출하는가 (tools/list)
    3. tools/call 이 Lambda 를 실제로 호출하는가
    4. 인증 없이 호출하면 거부되는가

Lambda 는 MCP 프로토콜을 구현하지 않습니다. Gateway 가 JSON-RPC 를 Lambda 호출로
번역하는지가 이 검증의 핵심입니다.

실행:
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
    python.org 빌드의 macOS Python 은 시스템 키체인을 쓰지 않아 CERTIFICATE_VERIFY_FAILED
    가 발생합니다. botocore 가 함께 설치하는 certifi 의 CA 번들을 명시적으로 사용합니다.
    (검증을 끄지 않습니다 — 끄면 이 테스트의 의미가 없어집니다)
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = make_ssl_context()


def post(url, payload, token=None, session_id=None):
    """MCP JSON-RPC 요청. streamable-http 는 JSON 또는 SSE 로 응답합니다."""
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
    """JSON 또는 SSE(data: ...) 응답에서 JSON-RPC 객체를 꺼냅니다."""
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
    print("  Gateway MCP 검증")
    print(f"  {url}")
    print("=" * 68)

    # ── 0) 인증 없이 호출 -> 거부되어야 합니다 ──
    print("\n[0] 인증 없이 initialize (거부되어야 정상)")
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
        print("    O 인증 없는 호출이 차단됨")
    else:
        print(f"    X 차단되지 않음 — 응답: {body[:200]}")

    # ── 1) initialize ──
    print("\n[1] initialize (Bearer 토큰)")
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
        print(f"    X 실패 — {body[:400]}")
        return 1
    info = obj.get("result", {}).get("serverInfo", {})
    print(f"    O 서버 {info.get('name')} / 프로토콜 {obj.get('result',{}).get('protocolVersion')}")

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
        print(f"    X 실패 HTTP {status} — {body[:400]}")
        return 1
    tools = obj.get("result", {}).get("tools", [])
    print(f"    O 도구 {len(tools)}개")
    tool_name = None
    for t in tools:
        print(f"      - {t['name']}")
        print(f"        설명: {t.get('description','')[:70]}...")
        print(f"        입력: {list(t.get('inputSchema',{}).get('properties',{}))}")
        if "extract_body_composition" in t["name"]:
            tool_name = t["name"]
    if not tool_name:
        print("    X extract_body_composition 도구를 찾지 못함")
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
        print(f"    X 응답 파싱 실패 — {body[:400]}")
        return 1
    if "error" in obj:
        print(f"    X JSON-RPC 오류: {obj['error']}")
        return 1
    result = obj.get("result", {})
    print(f"    isError: {result.get('isError')}")
    for c in result.get("content", []):
        if "text" in c:
            txt = c["text"]
            print(f"    Lambda 응답: {txt[:300]}")
            if "NOT_IMPLEMENTED" in txt:
                print("    O Gateway 가 Lambda 를 호출했습니다 (자리표시자 응답 확인)")
            if "extract_body_composition" in txt or "received_tool" in txt:
                print("    O 도구 이름이 Lambda 컨텍스트로 전달되었습니다")

    print("\n" + "=" * 68)
    print("  검증 완료")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
