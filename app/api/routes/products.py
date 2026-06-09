from fastapi import APIRouter, HTTPException, Query

from app.services import market_service
from app.schemas.product import (
    ProductSchema,
    ProductListResponse,
    ProductSearchResponse,
    MarketTradesResponse,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
async def list_products(
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    """List top products sorted by 24h volume."""
    fetch_count = offset + limit
    products = await market_service.get_top_products(limit=fetch_count)
    total = len(products)
    return ProductListResponse(
        products=products[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=ProductSearchResponse)
async def search_products(
    q: str = Query(default="", description="Search query (symbol or name)"),
):
    """Search products by symbol or name across the full spot catalog."""
    products = await market_service.search_products(query=q)
    return ProductSearchResponse(
        products=products,
        total=len(products),
        query=q,
    )


@router.get("/{product_id}", response_model=ProductSchema)
async def get_product(product_id: str):
    """Get a single product by ID (e.g. BTC-USD)."""
    product = await market_service.get_product_detail(product_id.upper())
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return product


@router.get("/{product_id}/trades", response_model=MarketTradesResponse)
async def get_market_trades(
    product_id: str,
    limit: int = Query(default=25, ge=1, le=100),
):
    """Get recent market trades (best bid/ask + recent trades)."""
    data = await market_service.get_market_trades(product_id.upper(), limit=limit)
    return data
