from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ... import security
from ...deps import SESSION_COOKIE, current_user, get_db
from ...repo import restaurants as rrepo
from ...repo import users as urepo
from ...schemas import LoginIn, RegisterIn

router = APIRouter(tags=["auth"])


def _issue(response: Response, user: dict) -> str:
    token = security.create_token(user["id"], user["email"])
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        secure=False, max_age=60 * 60 * 24)  # set secure=True under HTTPS
    return token


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    if urepo.get_user_by_email(conn, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    try:
        user = urepo.create_user(conn, body.name, body.email, body.password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    token = _issue(response, user)
    return {"id": user["id"], "email": user["email"], "name": user["name"], "token": token}


@router.post("/auth/login")
def login(body: LoginIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    user = urepo.get_user_by_email(conn, body.email)
    if not user or not security.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user["status"] != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    token = _issue(response, user)
    return {"id": user["id"], "email": user["email"], "name": user["name"], "token": token}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/users/me")
def me(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rest = rrepo.list_restaurants_for_user(conn, user["id"])
    return {"id": user["id"], "name": user["name"], "email": user["email"], "restaurants": rest}
