import uuid
import aiohttp

BASE = "https://paystars.uz/api/v1"


class PayStarsError(Exception):
    def __init__(self, status: int, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class PayStars:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _headers(self, idem=None):
        h = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if idem:
            h["Idempotency-Key"] = idem
        return h

    async def account(self):
        return await self._get("/account")

    async def check_username(self, username, kind):
        username = username.lstrip("@")
        return await self._post("/check-username", {"username": username, "kind": kind})

    async def buy_stars(self, username, quantity, token):
        return await self._post(
            "/stars/buy",
            {"username": username.lstrip("@"), "quantity": quantity, "verification_token": token},
            idem="stars_" + str(uuid.uuid4()),
        )

    async def buy_premium(self, username, months, token):
        return await self._post(
            "/premium/buy",
            {"username": username.lstrip("@"), "months": months, "verification_token": token},
            idem="premium_" + str(uuid.uuid4()),
        )

    async def _get(self, path):
        async with aiohttp.ClientSession() as s:
            async with s.get(BASE + path, headers=self._headers(), timeout=30) as r:
                data = await r.json(content_type=None)
                if r.status >= 400:
                    raise PayStarsError(r.status, data)
                return data

    async def _post(self, path, payload, idem=None):
        async with aiohttp.ClientSession() as s:
            async with s.post(BASE + path, headers=self._headers(idem), json=payload, timeout=60) as r:
                data = await r.json(content_type=None)
                if r.status >= 400:
                    raise PayStarsError(r.status, data)
                return data
