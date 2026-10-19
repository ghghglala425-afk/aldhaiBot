# -*- coding: utf-8 -*-
"""مسارات أدوات اختبار الويب: Repeater + Intruder-lite + Decoder."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import current_user
from core import proxy as svc
from core.db import get_session
from core.models import User
from core.proxy import ProxyError

router = APIRouter(prefix="/api/proxy", tags=["proxy"])


class RequestIn(BaseModel):
    method: str = "GET"
    url: str
    headers: dict = {}
    body: str | None = None


class FuzzIn(BaseModel):
    url: str
    method: str = "GET"
    payloads: list[str]
    marker: str = "FUZZ"
    headers: dict = {}
    body: str | None = None


class DecodeIn(BaseModel):
    op: str
    value: str


@router.post("/request")
async def send_request(
    body: RequestIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await svc.send(session, user, method=body.method, url=body.url,
                              headers=body.headers, body=body.body)
    except ProxyError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/fuzz")
async def fuzz_request(
    body: FuzzIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        return {"results": await svc.fuzz(session, user, url=body.url, method=body.method,
                                          payloads=body.payloads, marker=body.marker,
                                          headers=body.headers, body=body.body)}
    except ProxyError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/decode")
async def decode_value(body: DecodeIn, user: User = Depends(current_user)):
    return svc.decode(body.op, body.value)
