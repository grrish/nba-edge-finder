"""Router for the manual sportsbook-promo tracker."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from config import get_settings
from models.schemas import Promo, PromoCreate, PromoListResponse, PromoStatus, PromoUpdate
from services.promos_db import PromoStore

router = APIRouter(prefix="/promos", tags=["promos"])


def _get_store() -> PromoStore:
    settings = get_settings()
    return PromoStore(PromoStore.resolve_path(settings.promos_db_path))


@router.post(
    "",
    response_model=Promo,
    status_code=status.HTTP_201_CREATED,
    summary="Log a new promo",
)
async def create_promo(
    payload: PromoCreate,
    store: PromoStore = Depends(_get_store),
) -> Promo:
    return store.create(payload)


@router.get(
    "",
    response_model=PromoListResponse,
    status_code=status.HTTP_200_OK,
    summary="List promos, soonest expiry first",
)
async def list_promos(
    promo_status: Optional[PromoStatus] = Query(None, alias="status"),
    store: PromoStore = Depends(_get_store),
) -> PromoListResponse:
    promos = store.list(status=promo_status)
    return PromoListResponse(promos=promos, count=len(promos))


@router.patch(
    "/{promo_id}",
    response_model=Promo,
    status_code=status.HTTP_200_OK,
    summary="Update a promo's status",
)
async def update_promo_status(
    promo_id: int,
    payload: PromoUpdate,
    store: PromoStore = Depends(_get_store),
) -> Promo:
    updated = store.update_status(promo_id, payload.status)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo not found")
    return updated


@router.delete(
    "/{promo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a promo",
)
async def delete_promo(
    promo_id: int,
    store: PromoStore = Depends(_get_store),
) -> None:
    deleted = store.delete(promo_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo not found")
