from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ...deps import current_user, enforce_role, get_db
from ...repo import restaurants as rrepo
from ...repo import users as urepo
from ...schemas import MembershipIn, RestaurantIn

router = APIRouter(tags=["restaurants"])


@router.get("/restaurants")
def list_restaurants(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return rrepo.list_restaurants_for_user(conn, user["id"])


@router.post("/restaurants", status_code=status.HTTP_201_CREATED)
def create_restaurant(body: RestaurantIn, user: dict = Depends(current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    return rrepo.create_restaurant(conn, body.name, user["id"], body.description,
                                   body.location, body.timezone)


@router.get("/restaurants/{restaurant_id}")
def get_restaurant(restaurant_id: int, user: dict = Depends(current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    rest = rrepo.get_restaurant(conn, restaurant_id)
    if not rest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
    return rest


@router.patch("/restaurants/{restaurant_id}")
def update_restaurant(restaurant_id: int, body: RestaurantIn, user: dict = Depends(current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "manager")
    return rrepo.update_restaurant(conn, restaurant_id, name=body.name, description=body.description,
                                   location=body.location, timezone=body.timezone)


@router.get("/restaurants/{restaurant_id}/members")
def list_members(restaurant_id: int, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "manager")
    return rrepo.list_members(conn, restaurant_id)


@router.post("/restaurants/{restaurant_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(restaurant_id: int, body: MembershipIn, user: dict = Depends(current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "owner")
    target = urepo.get_user_by_email(conn, body.email)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that email")
    rrepo.add_membership(conn, target["id"], restaurant_id, body.role)
    return {"ok": True, "user_id": target["id"], "role": body.role}
