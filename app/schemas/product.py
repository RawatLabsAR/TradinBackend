from pydantic import BaseModel, Field
from typing import Optional


class ProductSchema(BaseModel):
    product_id: str
    price: str = "0"
    price_percentage_change_24h: str = "0"
    volume_24h: str = "0"
    volume_percentage_change_24h: str = "0"
    base_increment: str = ""
    quote_increment: str = ""
    base_min_size: str = ""
    base_max_size: str = ""
    quote_min_size: str = ""
    quote_max_size: str = ""
    base_name: str = ""
    quote_name: str = ""
    is_disabled: bool = False
    new: bool = False
    status: str = ""
    cancel_only: bool = False
    limit_only: bool = False
    post_only: bool = False
    trading_disabled: bool = False
    auction_mode: bool = False
    product_type: str = "SPOT"
    quote_currency_id: str = ""
    base_currency_id: str = ""
    mid_market_price: str = ""
    base_display_symbol: str = ""
    quote_display_symbol: str = ""
    display_name: str = ""
    approximate_quote_24h_volume: str = ""

    model_config = {"from_attributes": True, "extra": "ignore"}


class ProductListResponse(BaseModel):
    products: list[ProductSchema]
    total: int
    limit: int
    offset: int


class ProductSearchResponse(BaseModel):
    products: list[ProductSchema]
    total: int
    query: str


class MarketTradeSchema(BaseModel):
    trade_id: str = ""
    product_id: str = ""
    price: str = ""
    size: str = ""
    side: str = ""
    time: str = ""

    model_config = {"extra": "ignore"}


class MarketTradesResponse(BaseModel):
    trades: list[MarketTradeSchema] = []
    best_bid: str = ""
    best_ask: str = ""
    best_bid_size: str = ""
    best_ask_size: str = ""

    model_config = {"extra": "ignore"}
