from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import client_meta, get_current_user
from app.db.database import get_db
from app.models.price_alert import PriceAlert
from app.models.user import User
from app.schemas.alert import PriceAlertCreate, PriceAlertOut, PriceAlertUpdate
from app.services.activity_service import log_activity
from app.services.alert_service import list_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _can_access(alert: PriceAlert, user: User) -> bool:
    if user.role == "admin":
        return True
    return alert.user_id == user.id


@router.get("", response_model=list[PriceAlertOut])
async def get_alerts(
    product_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PriceAlertOut]:
    alerts = await list_alerts(
        db,
        product_id,
        user_id=user.id,
        admin=user.role == "admin",
    )
    return [PriceAlertOut.model_validate(a) for a in alerts]


@router.post("", response_model=PriceAlertOut, status_code=201)
async def create_alert(
    payload: PriceAlertCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriceAlertOut:
    alert = PriceAlert(
        user_id=user.id,
        product_id=payload.product_id.upper(),
        target_price=payload.target_price,
        direction=payload.direction,
        message=payload.message,
        notify_telegram=payload.notify_telegram,
        channel_id=payload.channel_id,
    )
    db.add(alert)
    await db.flush()
    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=user,
        action="alert.create",
        resource_type="price_alert",
        resource_id=str(alert.id),
        detail=f"Alert on {alert.product_id} {alert.direction} ${alert.target_price}",
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    await db.refresh(alert)
    return PriceAlertOut.model_validate(alert)


@router.patch("/{alert_id}", response_model=PriceAlertOut)
async def update_alert(
    alert_id: int,
    payload: PriceAlertUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriceAlertOut:
    alert = await db.get(PriceAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _can_access(alert, user):
        raise HTTPException(status_code=403, detail="Not allowed to modify this alert")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(alert, field, value)
    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=user,
        action="alert.update",
        resource_type="price_alert",
        resource_id=str(alert.id),
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    await db.refresh(alert)
    return PriceAlertOut.model_validate(alert)


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    alert = await db.get(PriceAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _can_access(alert, user):
        raise HTTPException(status_code=403, detail="Not allowed to delete this alert")
    ip, ua = client_meta(request)
    await log_activity(
        db,
        user=user,
        action="alert.delete",
        resource_type="price_alert",
        resource_id=str(alert.id),
        ip_address=ip,
        user_agent=ua,
    )
    await db.delete(alert)
    await db.commit()
