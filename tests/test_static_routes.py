import asyncio

import httpx

from backend.main import app


def test_backend_serves_favicon_without_database_dependency():
  async def get_favicon():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
      return await client.get("/favicon.ico")

  response = asyncio.run(get_favicon())

  assert response.status_code == 200
  assert response.headers["content-type"].startswith("image/svg+xml")
  assert b"<svg" in response.content
