from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.price_alert import PriceAlert
from app.schemas.alert import PriceAlertCreate, PriceAlertOut, PriceAlertUpdate
from app.services.alert_service import list_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[PriceAlertOut])
async def get_alerts(
    product_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[PriceAlertOut]:
    alerts = await list_alerts(db, product_id)
    return [PriceAlertOut.model_validate(a) for a in alerts]


@router.post("", response_model=PriceAlertOut, status_code=201)
async def create_alert(
    payload: PriceAlertCreate,
    db: AsyncSession = Depends(get_db),
) -> PriceAlertOut:
    alert = PriceAlert(
        product_id=payload.product_id.upper(),
        target_price=payload.target_price,
        direction=payload.direction,
        message=payload.message,
        notify_telegram=payload.notify_telegram,
        channel_id=payload.channel_id,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return PriceAlertOut.model_validate(alert)


@router.patch("/{alert_id}", response_model=PriceAlertOut)
async def update_alert(
    alert_id: int,
    payload: PriceAlertUpdate,
    db: AsyncSession = Depends(get_db),
) -> PriceAlertOut:
    alert = await db.get(PriceAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(alert, field, value)
    await db.commit()
    await db.refresh(alert)
    return PriceAlertOut.model_validate(alert)


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    alert = await db.get(PriceAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
