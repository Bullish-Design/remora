
stario.dev
Testing
~2 minutes
Testing Reference ¶

Stario makes it easy to unit test handlers without starting a real server.
Core Utilities ¶
Tool 	Purpose
TestRequest 	Mock an incoming HTTP request.
ResponseRecorder 	Capture and inspect the handler's output.
Example: Testing a Handler ¶

from stario import TestRequest, ResponseRecorder, Context

async def test_my_handler():
    # 1. Setup mock request
    req = TestRequest(
        method="POST",
        query={"debug": "true"},
        body={"name": "Alice"}
    )

    # 2. Setup recorder
    rec = ResponseRecorder()

    # 3. Call handler
    await my_handler(Context(req), rec)

    # 4. Assert
    assert rec.status == 200
    assert "Hello Alice" in rec.body

TestRequest Options ¶

req = TestRequest(
    method="GET",
    query={"q": "search"},
    headers={"X-Test": "1"},
    cookies={"sid": "123"},
    body={"foo": "bar"},     # Dicts are converted to JSON
    tail="path/after/star"   # For /* routes
)

ResponseRecorder API ¶
Property 	Description
.status 	HTTP status code (int)
.body 	Response body (str)
.headers 	Response headers (dict)
.cookies 	Set-Cookie data (dict)
.patches 	List of w.patch calls
.signals 	List of w.sync calls
Integration with pytest ¶

import pytest

@pytest.mark.asyncio
async def test_handler():
    rec = ResponseRecorder()
    await my_handler(Context(TestRequest()), rec)
    assert rec.status == 200

Changing the world, one byte at a time
