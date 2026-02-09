from pydantic_ai import RunContext
from app.models.market import Livestock, LivestockBreed, MarketPrice, Marketplace
from agents.deps import FarmerContext
from app.database import async_session_maker
from sqlalchemy import func, select, or_
from typing import List, Optional, Tuple
from sqlalchemy.orm import joinedload
from helpers.utils import get_logger
from app.core.cache import cache
import re
from agents.tools.MarketPlace import find_livestock_marketplace_by_name, find_nearest_livestock_marketplaces

logger = get_logger(__name__)

CACHE_TTL_PRICE = 900  # 15 minutes
CACHE_TTL_LIST = 3600  # 1 hour


async def _get_marketplace(
    db,
    marketplace_name: str,
    region: Optional[str] = None
) -> Tuple[Optional[Marketplace], Optional[str]]:
    """
    Internal helper to get livestock marketplace by name, optionally filtered by region.

    Returns:
        Tuple of (marketplace, error_message)
        - (Marketplace, None) if found
        - (None, error_message) if not found or ambiguous
    """
    stmt = select(Marketplace).where(
        Marketplace.marketplace_type == "livestock",
        Marketplace.is_active == True,
        or_(
            func.lower(Marketplace.name) == func.lower(marketplace_name),
            func.lower(Marketplace.name_amharic) == func.lower(marketplace_name),
            func.lower(Marketplace.name).contains(func.lower(marketplace_name)),
            func.lower(Marketplace.name_amharic).contains(func.lower(marketplace_name))
        )
    )

    # Filter by region if provided
    if region:
        stmt = stmt.where(
            or_(
                func.lower(Marketplace.region) == func.lower(region),
                func.lower(Marketplace.region_amharic) == func.lower(region)
            )
        )

    result = await db.execute(stmt)
    marketplaces = result.scalars().all()

    if not marketplaces:
        return None, f"Marketplace '{marketplace_name}' not found."

    if len(marketplaces) == 1:
        return marketplaces[0], None

    # Multiple matches - need region to disambiguate
    regions_list = [f"{m.name} ({m.region})" for m in marketplaces]
    return None, f"Multiple marketplaces found: {', '.join(regions_list)}. Please specify region."


async def list_livestock_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    region: Optional[str] = None
) -> str:
    """
    List all livestock types available in a specific livestock marketplace.

    Args:
        marketplace_name: Name of the livestock marketplace (e.g., "Dubti", "Aysaita")
        region: Optional region name to disambiguate if same marketplace name exists in multiple regions

    Returns:
        Formatted list of available livestock with Amharic names
    """
    logger.info(f"list_livestock_in_marketplace: marketplace={marketplace_name}, region={region}")

    # Check cache
    cache_key = f"livestock:list:{marketplace_name}:{region or 'none'}"
    cached_data = await cache.get(cache_key)
    if cached_data:
        logger.info(f"Cache HIT for livestock list: {cache_key}")
        return cached_data

    async with async_session_maker() as db:
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error:
            return error

        stmt = (
            select(Livestock)
            .join(MarketPrice, MarketPrice.livestock_id == Livestock.livestock_id)
            .where(MarketPrice.marketplace_id == marketplace.marketplace_id)
            .where(MarketPrice.price_date >= (func.current_date() - 364))
            .options(joinedload(Livestock.breeds))
            .distinct()
            .order_by(Livestock.name)
        )
        result = await db.execute(stmt)
        livestocks = result.scalars().unique().all()

        if not livestocks:
            return f"No livestock found in {marketplace.name} marketplace."

        livestock_list = [
            f"* {livestock.name}" +
            (f" ({livestock.name_amharic})" if livestock.name_amharic else "") +
            (f" - Breeds: {', '.join([b.name for b in livestock.breeds])}" if livestock.breeds else "") +
            f"\n  Source: https://nmis.et/"
            for livestock in livestocks
        ]

        result_str = (
            f"Livestock available in {marketplace.name} ({marketplace.region}):\n\n" +
            "\n".join(livestock_list)
        )
        
        # Cache result
        await cache.set(cache_key, result_str, ttl=CACHE_TTL_LIST)
        return result_str


async def get_livestock_price_in_marketplace(
    ctx: RunContext[FarmerContext],
    marketplace_name: str,
    livestock_type: str,
    region: Optional[str] = None
) -> str:
    """
    Get detailed price information for a specific livestock type in a marketplace.
    """
    logger.info(f"get_livestock_price_in_marketplace: livestock={livestock_type}, marketplace={marketplace_name}, region={region}")

    # Check cache
    cache_key = f"livestock:price:full:{livestock_type}:{marketplace_name}:{region or 'none'}"
    cached_data = await cache.get(cache_key)
    if cached_data:
        logger.info(f"Cache HIT for livestock price (full): {cache_key}")
        return cached_data

    async with async_session_maker() as db:
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error:
            return error

        stmt = (
            select(
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.modal_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                MarketPrice.meta_data,
                Livestock.name_amharic.label('livestock_name_amharic'),
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name'),
                LivestockBreed.name_amharic.label('breed_name_amharic')
            )
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .outerjoin(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                MarketPrice.marketplace_id == marketplace.marketplace_id,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(Livestock.name).contains(livestock_type.lower()),
                    func.lower(Livestock.name_amharic) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic).contains(livestock_type.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            return f"No price data found for '{livestock_type}' in {marketplace.name}."

        price_data_breeds = {}
        for price_row in price_data_list:
            breed_key = price_row.breed_name or "Default"
            variations_info = ""
            if price_row.meta_data and price_row.meta_data.get("variations"):
                variations = price_row.meta_data["variations"]
                var_details = []
                for var in variations:
                    parts = []
                    if var.get("gender"): parts.append(var["gender"])
                    if var.get("age"): parts.append(var["age"])
                    if var.get("grade"): parts.append(f"Grade: {var['grade']}")
                    if var.get("productionType"): parts.append(f"Type: {var['productionType']}")
                    if var.get("location"): parts.append(f"From: {var['location']}")

                    price_range = ""
                    if var.get("pmin") and var.get("pmax"):
                        price_range = f" ({var['pmin']}-{var['pmax']} ETB)"
                    elif var.get("pmin"): price_range = f" ({var['pmin']} ETB)"

                    if parts:
                        var_details.append(f"  - {', '.join(parts)}{price_range}")

                if var_details:
                    variations_info = "\n* Variations:\n" + "\n".join(var_details)

            price_data_breeds[breed_key] = (
                f"{price_row.livestock_name} ({price_row.livestock_name_amharic}) prices in {marketplace.name}:\n\n"
                f"* Breed: {price_row.breed_name or 'N/A'}" +
                (f" ({price_row.breed_name_amharic})" if price_row.breed_name_amharic else "") + "\n"
                f"{variations_info}\n"
                f"* As of Date: {price_row.price_date.strftime('%Y-%m-%d')}\n"
                f"* Source: https://nmis.et/"
            )

        result_str = "\n\n".join(price_data_breeds.values())
        await cache.set(cache_key, result_str, ttl=CACHE_TTL_PRICE)
        return result_str


async def compare_livestock_prices_nearby(
    ctx: RunContext[FarmerContext],
    livestock_type: str,
    marketplace_names: List[str],
) -> str:
    """
    Compare prices of a livestock type across multiple marketplaces.
    """
    logger.info(f"compare_livestock_prices_nearby: livestock={livestock_type}, marketplaces={marketplace_names}")

    if not marketplace_names:
        return "No marketplaces provided for comparison."

    async with async_session_maker() as db:
        stmt = (
            select(
                Marketplace.name,
                Marketplace.region,
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                MarketPrice.meta_data,
                Livestock.name.label('livestock_name'),
                LivestockBreed.name.label('breed_name')
            )
            .join(MarketPrice, MarketPrice.marketplace_id == Marketplace.marketplace_id)
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .outerjoin(LivestockBreed, MarketPrice.breed_id == LivestockBreed.breed_id)
            .where(
                Marketplace.marketplace_type == "livestock",
                Marketplace.is_active == True,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(Livestock.name).contains(livestock_type.lower()),
                    func.lower(Livestock.name_amharic) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic).contains(livestock_type.lower())
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .where(
                or_(
                    Marketplace.name.in_(marketplace_names),
                    Marketplace.name_amharic.in_(marketplace_names)
                )
            )
            .order_by(MarketPrice.avg_price.asc())
        )
        result = await db.execute(stmt)
        markets = result.all()

        if not markets:
            return f"No price data found for '{livestock_type}' in the specified marketplaces."

        lines = [f"{livestock_type} price comparison:\n"]

        for idx, market in enumerate(markets, 1):
            lines.append(
                f"{idx}. **{market.name}** ({market.region})\n"
                f"   * Avg: {market.avg_price} ETB\n"
                f"   * As of Date: {market.price_date.strftime('%Y-%m-%d')}\n"
                f"   * Source: https://nmis.et/"
            )

        return "\n\n".join(lines)


async def get_livestock_price_quick(
    ctx: RunContext[FarmerContext],
    livestock_type: str,
    marketplace_name: str
) -> str:
    """
    Get livestock price by marketplace name directly.
    """
    logger.info(f"get_livestock_price_quick: livestock={livestock_type}, marketplace={marketplace_name}")
    
    cache_key = f"livestock:price:quick:{livestock_type}:{marketplace_name}"
    cached_data = await cache.get(cache_key)
    if cached_data: return cached_data
    
    vague_terms = ['livestock', 'animal', 'it', 'that', 'this', 'something', 'anything', 'price', 'market']
    if livestock_type.lower() in vague_terms or len(livestock_type) < 2:
        return "ERROR: I need to know which specific livestock type."
    if marketplace_name.lower() in vague_terms or len(marketplace_name) < 3:
        return "ERROR: I need to know which specific marketplace."
    
    from helpers.market_place_json import EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES
    marketplace_info = EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES.get(marketplace_name)
    if not marketplace_info:
        for key, value in EXACT_MATCH_UP_LIVESTOCK_MARKETPLACES.items():
            if key.lower() == marketplace_name.lower():
                marketplace_info = value
                marketplace_name = key
                break
    
    if not marketplace_info:
        from agents.tools.MarketPlace import find_livestock_marketplace_by_name
        db_result = await find_livestock_marketplace_by_name(marketplace_name)
        if isinstance(db_result, dict):
            marketplace_info = db_result
            marketplace_name = db_result['name']
    
    if not marketplace_info:
         return f"Marketplace '{marketplace_name}' not found."

    region = marketplace_info.get("region")
    async with async_session_maker() as db:
        marketplace, error = await _get_marketplace(db, marketplace_name, region)
        if error: return f"Marketplace '{marketplace_name}' not found in database."

        stmt = (
            select(
                MarketPrice.min_price,
                MarketPrice.max_price,
                MarketPrice.avg_price,
                MarketPrice.price_date,
                MarketPrice.unit,
                Livestock.name_amharic.label('livestock_name_amharic'),
                Livestock.name.label('livestock_name')
            )
            .join(Livestock, MarketPrice.livestock_id == Livestock.livestock_id)
            .where(
                MarketPrice.marketplace_id == marketplace.marketplace_id,
                or_(
                    func.lower(Livestock.name) == livestock_type.lower(),
                    func.lower(Livestock.name_amharic) == livestock_type.lower()
                ),
                MarketPrice.price_date >= (func.current_date() - 364)
            )
            .order_by(MarketPrice.price_date.desc())
        )
        result = await db.execute(stmt)
        price_data_list = result.all()

        if not price_data_list:
            return f"No price data found for '{livestock_type}' in {marketplace_name}."

        price_data = price_data_list[0]
        res = (
            f"{price_data.livestock_name} ({price_data.livestock_name_amharic}) prices in {marketplace_name} ({region}):\n\n"
            f"* Avg Price: {price_data.avg_price} ETB\n"
            f"* As of Date: {price_data.price_date.strftime('%Y-%m-%d')}\n"
            f"* Source: https://nmis.et/"
        )
        await cache.set(cache_key, res, ttl=CACHE_TTL_PRICE)
        return res


async def smart_livestock_price_query(
    ctx: RunContext[FarmerContext],
    livestock_type: str,
    location: str,
    is_proximity: bool = False,
    ref_lat: float = None,
    ref_lon: float = None
) -> str:
    """
    Query livestock prices with support for proximity and automatic fallback.
    
    Args:
        livestock_type: e.g. "Oxen", "Sheep"
        location: Specific town/market name (e.g. "Amber", "Addis Ababa")
        is_proximity: Set to True if user ask for "near", "around"
        ref_lat: Optional latitude of the location if known (internal use).
        ref_lon: Optional longitude of the location if known (internal use).
    """
    logger.info(f"smart_livestock_price_query: type={livestock_type}, location={location}, proximity={is_proximity}")

    livestock_type = livestock_type.strip().capitalize()
    location = location.strip().rstrip('?.!,')

    if not livestock_type: return "Please specify the livestock type."
    if not location: return "Please specify the location."

    # 1. Initial Lookup
    result = await get_livestock_price_quick(ctx, livestock_type, location)
    
    # 2. Smart Fallback
    no_data_found = "No price data found" in result or "Marketplace" in result and "not found" in result
    
    if (is_proximity or no_data_found) and location:
        logger.info(f"smart_livestock_price_query: Proximity/Fallback triggered for '{location}'")
        try:
             from agents.tools.MarketPlace import find_livestock_marketplace_by_name, find_nearest_livestock_marketplaces
             from agents.tools.maps import forward_geocode
             from helpers.market_place_json import LIVESTOCK_MARKETPLACES
             
             ref_market = await find_livestock_marketplace_by_name(location)
             lat, lon, region = None, None, None
             
             # Check if we have coordinates in our static JSON map (Fastest fallback)
             # Handle "Arero, Oromia" -> "Arero"
             simple_loc_name = location.split(',')[0].strip().lower()
             json_market = None
             
             if not json_market:
                 for r_list in LIVESTOCK_MARKETPLACES.values():
                     for m in r_list:
                         if m['name'].strip().lower() == simple_loc_name:
                             json_market = m
                             break
                     if json_market: break
             
             if isinstance(ref_market, dict):
                  lat, lon, region = ref_market.get('latitude'), ref_market.get('longitude'), ref_market.get('region')
             elif json_market:
                  logger.info(f"smart_livestock_price_query: Found '{location}' in local JSON map (lat={json_market['lat']})")
                  lat, lon = json_market['lat'], json_market['lon']
                  region = json_market.get('region')
             elif ref_lat is not None and ref_lon is not None:
                  logger.info(f"smart_livestock_price_query: Using provided coords for '{location}': ({ref_lat}, {ref_lon})")
                  lat, lon = ref_lat, ref_lon
             else:
                  logger.info(f"smart_livestock_price_query: Using global geocode for '{location}'")
                  geo = await forward_geocode(location)
                  if geo: lat, lon = geo.latitude, geo.longitude
             
             if lat and lon:
                  neighbors = await find_nearest_livestock_marketplaces(lat, lon, region=region, radius_km=200, limit=3)
                  target = None
                  for n in neighbors:
                      if n['name'].lower() != location.lower():
                          target = n
                          break
                  
                  if target:
                      logger.info(f"smart_livestock_price_query: Re-routing '{location}' -> '{target['name']}'")
                      neighbor_result = await get_livestock_price_quick(ctx, livestock_type, target['name'])
                      if neighbor_result and "prices in" in neighbor_result:
                          msg = f"(Note: '{location}' has no direct data. Showing data for nearest market '{target['name']}'. No further search required.)"
                          if no_data_found:
                              return f"I couldn't find data for '{location}', but here is the data from the nearest market:\n\n{neighbor_result}\n\n{msg}"
                          return f"{neighbor_result}\n\n{msg}"
        except Exception as e:
            logger.error(f"Fallback failed: {e}")

    if result and "prices in" in result and "No further search required" not in result:
        result += f"\n\n(Note: Price data retrieved for '{location}'. No further search required.)"
    return result
