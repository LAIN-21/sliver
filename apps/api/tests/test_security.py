import asyncio

from sliver_api.security import BodyLimit


def call(app, chunks: list[bytes], headers: list[tuple[bytes, bytes]]):
    sent = []
    queue = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]

    async def receive():
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/upload", "headers": headers}
    asyncio.run(app(scope, receive, send))
    return sent


async def echo(scope, receive, send):
    total = 0
    while True:
        message = await receive()
        total += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(total).encode()})


async def swallowing(scope, receive, send):
    # Like a framework that turns parse errors into its own 400.
    try:
        await echo(scope, receive, send)
    except Exception:
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"parse error"})


def test_streamed_bodies_over_the_limit_get_413_even_without_content_length():
    for inner in (echo, swallowing):
        sent = call(BodyLimit(inner, default_limit=10, limits={}), [b"12345", b"67890", b"X"], [])
        assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413]


def test_declared_oversized_bodies_are_refused_without_reading():
    sent = call(BodyLimit(echo, default_limit=10, limits={}), [b"x" * 50], [(b"content-length", b"50")])
    assert sent[0]["status"] == 413


def test_per_path_limits_and_bodies_within_the_limit():
    app = BodyLimit(echo, default_limit=1, limits={"/upload": 100})
    sent = call(app, [b"x" * 60], [(b"content-length", b"60")])
    assert sent[0]["status"] == 200 and sent[1]["body"] == b"60"
