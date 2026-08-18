"""YooKassa payment client (aiohttp, no SDK).

Scaffold: create a payment link and poll its status. No webhook — the bot runs
on long-polling and has no public URL. Set YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY
in .env to enable live payments; until then `is_configured()` is False and the
bot falls back to the free trial.
"""
import base64
import os
from uuid import uuid4

import aiohttp

API_URL = 'https://api.yookassa.ru/v3/payments'

PRICE_VALUE = '500.00'
PRICE_RUB = 500
PRICE_CURRENCY = 'RUB'
YEAR_SECONDS = 365 * 86400


class PaymentsNotConfigured(Exception):
    pass


def is_configured() -> bool:
    return bool(os.getenv('YOOKASSA_SHOP_ID') and os.getenv('YOOKASSA_SECRET_KEY'))


def _headers() -> dict:
    shop_id = os.getenv('YOOKASSA_SHOP_ID', '')
    secret = os.getenv('YOOKASSA_SECRET_KEY', '')
    token = base64.b64encode(f'{shop_id}:{secret}'.encode()).decode()
    return {'Authorization': f'Basic {token}'}


async def create_payment(user_id: int, return_url: str, description: str = 'Sevrax Premium — год') -> dict:
    if not is_configured():
        raise PaymentsNotConfigured('YooKassa is not configured')
    headers = _headers()
    headers['Content-Type'] = 'application/json'
    headers['Idempotence-Key'] = uuid4().hex
    body = {
        'amount': {'value': PRICE_VALUE, 'currency': PRICE_CURRENCY},
        'capture': True,
        'confirmation': {'type': 'redirect', 'return_url': return_url},
        'description': description,
        'metadata': {'user_id': str(user_id)},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=body, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f'YooKassa create_payment error {resp.status}: {data}')
            return data


async def get_payment(payment_id: str) -> dict:
    if not is_configured():
        raise PaymentsNotConfigured('YooKassa is not configured')
    headers = _headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(f'{API_URL}/{payment_id}', headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f'YooKassa get_payment error {resp.status}: {data}')
            return data
