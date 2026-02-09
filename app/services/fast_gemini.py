"""
Fast Gemini Service - Direct API calls matching AI Studio code exactly.
For voice queries where latency is critical.
"""
import os
import re
import time
import json
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional, Tuple
from google import genai
from google.genai import types
from helpers.utils import get_logger, get_prompt, get_today_date_str

logger = get_logger(__name__)




class FastGeminiService:
    """Direct Gemini API service for low-latency voice queries - matches AI Studio exactly."""
    
    def __init__(self, model: str = None, lang: str = "en"):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = model or os.getenv("LLM_MODEL_NAME", "gemini-3-flash-preview")
        self.lang = lang
        
        # Configure tools exactly as AI Studio exports
        self.system_prompt = get_prompt(lang, context={'today_date': get_today_date_str(lang)})
        
        self.tools = [
            types.Tool(
                function_declarations=[
                    # PRIMARY TOOL: Crop Prices - Single entry point for ALL crop price queries
                    types.FunctionDeclaration(
                        name="smart_crop_price_query",
                        description="Get crop prices. This tool handles geocoding internally - DO NOT call forward_geocode first. Just provide crop_name and location. Optionally provide ref_lat/ref_lon if you know them from your world knowledge (e.g., Adama is ~8.54, 39.27).",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["crop_name", "location"],
                            properties={
                                "crop_name": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Name of the crop (e.g., 'Teff', 'Wheat', 'Onion').",
                                ),
                                "location": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Location/marketplace name (e.g., 'Adama', 'Gondar').",
                                ),
                                "is_proximity": genai.types.Schema(
                                    type=genai.types.Type.BOOLEAN,
                                    description="True if user asks for 'near', 'around', or Amharic 'አቅራቢያ'.",
                                ),
                                "ref_lat": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: latitude if you know it from world knowledge.",
                                ),
                                "ref_lon": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: longitude if you know it from world knowledge.",
                                ),
                            },
                        ),
                    ),
                    # PRIMARY TOOL: Livestock Prices - Single entry point for ALL livestock price queries
                    types.FunctionDeclaration(
                        name="smart_livestock_price_query",
                        description="Get livestock prices. This tool handles geocoding internally - DO NOT call forward_geocode first. Just provide livestock_type and location. Optionally provide ref_lat/ref_lon if you know them.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["livestock_type", "location"],
                            properties={
                                "livestock_type": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Type of livestock (e.g., 'Ox', 'Camel', 'Goat', 'Sheep').",
                                ),
                                "location": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Location/marketplace name.",
                                ),
                                "is_proximity": genai.types.Schema(
                                    type=genai.types.Type.BOOLEAN,
                                    description="True if user asks for 'near', 'around'.",
                                ),
                                "ref_lat": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: latitude if you know it.",
                                ),
                                "ref_lon": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: longitude if you know it.",
                                ),
                            },
                        ),
                    ),
                    # Weather tools - coordinates encouraged but tools have internal geocoding fallback
                    types.FunctionDeclaration(
                        name="get_current_weather",
                        description="Get current weather. Provide place_name, and optionally latitude/longitude if you know them. The tool can geocode place_name if coordinates not provided.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            properties={
                                "place_name": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Name of the location (e.g., 'Addis Ababa', 'Gondar').",
                                ),
                                "latitude": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: latitude if known from world knowledge.",
                                ),
                                "longitude": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: longitude if known from world knowledge.",
                                ),
                                "units": genai.types.Schema(type=genai.types.Type.STRING),
                                "language": genai.types.Schema(type=genai.types.Type.STRING),
                            },
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="get_weather_forecast",
                        description="Get weather forecast. Provide place_name, and optionally latitude/longitude if you know them. The tool can geocode place_name if coordinates not provided.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            properties={
                                "place_name": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Name of the location.",
                                ),
                                "latitude": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: latitude if known.",
                                ),
                                "longitude": genai.types.Schema(
                                    type=genai.types.Type.NUMBER,
                                    description="Optional: longitude if known.",
                                ),
                                "units": genai.types.Schema(type=genai.types.Type.STRING),
                                "language": genai.types.Schema(type=genai.types.Type.STRING),
                            },
                        ),
                    ),
                    # Listing tools - for browsing available items (NOT for price queries)
                    types.FunctionDeclaration(
                        name="list_crops_in_marketplace",
                        description="List available crops in a marketplace. Use ONLY when user asks 'what crops are available in X?' - NOT for price queries.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["marketplace_name"],
                            properties={
                                "marketplace_name": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Name of the marketplace.",
                                ),
                            },
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="list_livestock_in_marketplace",
                        description="List available livestock in a marketplace. Use ONLY when user asks 'what livestock is available?'.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["marketplace_name"],
                            properties={
                                "marketplace_name": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Name of the marketplace.",
                                ),
                            },
                        ),
                    ),
                    # Geocoding - ONLY for explicit coordinate requests, NOT needed before price/weather tools
                    types.FunctionDeclaration(
                        name="forward_geocode",
                        description="Get coordinates for a place. Use ONLY when user explicitly asks for coordinates (e.g., 'what are the coordinates of Adama?'). DO NOT use this before calling price or weather tools - they handle geocoding internally.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["place_name"],
                            properties={
                                "place_name": genai.types.Schema(type=genai.types.Type.STRING),
                            },
                        ),
                    ),
                    # Knowledge base search
                    types.FunctionDeclaration(
                        name="search_documents",
                        description="Search agricultural knowledge base for cultivation advice, pest management, irrigation, harvesting tips, and farming best practices.",
                        parameters=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["query"],
                            properties={
                                "query": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Search query in English.",
                                ),
                                "top_k": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Number of results (default: 5).",
                                ),
                            },
                        ),
                    ),
                ]
            )
        ]
        
        # Config exactly as AI Studio
        self.config = types.GenerateContentConfig(
            temperature=0.2,
            # thinking_config removed for speed
            tools=self.tools,
            system_instruction=[types.Part.from_text(text=self.system_prompt)],
            # safety_settings=[
            #     types.SafetySetting(
            #         category="HARM_CATEGORY_HARASSMENT",
            #         threshold="BLOCK_ONLY_HIGH",
            #     ),
            #     types.SafetySetting(
            #         category="HARM_CATEGORY_HATE_SPEECH",
            #         threshold="BLOCK_ONLY_HIGH",
            #     ),
            #     types.SafetySetting(
            #         category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            #         threshold="BLOCK_ONLY_HIGH",
            #     ),
            #     types.SafetySetting(
            #         category="HARM_CATEGORY_DANGEROUS_CONTENT",
            #         threshold="BLOCK_ONLY_HIGH",
            #     ),
            # ],
        )
        
        logger.info(f"FastGeminiService initialized: model={self.model}, lang={lang}")



    
    async def generate_response(
        self,
        query: str,
        metrics: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """
        Generate response using direct Gemini API with tool execution.
        Supports multi-turn tool calling (up to MAX_TOOL_ROUNDS).
        """
        MAX_TOOL_ROUNDS = 5  # Prevent infinite loops, but allow exploration
        
        t_start = time.perf_counter()
        metrics['llm_start'] = t_start
        


        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=query)],
            ),
        ]
        
        first_token_recorded = False
        tool_round = 0
        
        if 'timings' not in metrics:
            metrics['timings'] = []
        
        # Prepare runtime config (can be modified per round)
        current_config = self.config
        # Tools that trigger IMMEDIATE filtering of redundant tools
        trigger_filtering_tools = {
            "smart_crop_price_query", 
            "smart_livestock_price_query",
            "get_crop_price_quick", 
            "get_livestock_price_quick"
        } 
        filter_next_round = False
        
        # Track allowed tools for enforcement (initially all tools)
        current_allowed_tools = {f.name for f in self.tools[0].function_declarations}
        
        try:
            while tool_round < MAX_TOOL_ROUNDS:
                tool_round += 1
                logger.info(f"[LLM] LLM call round {tool_round}...")
                
                # Check if we should filter tools for this round
                if filter_next_round:
                    # Filter out redundant tools (proximity/price) to prevent loops
                    # but KEEP other tools (weather, search)
                    all_funcs = self.tools[0].function_declarations
                    redundant_tools = {
                        "smart_crop_price_query", "get_crop_price_quick", "get_livestock_price_quick",
                        "forward_geocode", "detect_crop_region", "detect_livestock_region",
                        "find_nearest_crop_marketplaces", "find_nearest_livestock_marketplaces",
                        "list_crops_in_marketplace", "list_livestock_in_marketplace",
                        "list_active_crop_marketplaces", "list_active_livestock_marketplaces"
                    }
                    filtered_funcs = [f for f in all_funcs if f.name not in redundant_tools]
                    
                    # Update allowed list for enforcement
                    current_allowed_tools = {f.name for f in filtered_funcs}
                    
                    logger.info(f"[FILTER] Smart tool executed - Filtering redundant tools for next round. Remaining: {list(current_allowed_tools)}")
                    
                    current_config = types.GenerateContentConfig(
                        temperature=0.2,
                        # thinking_config removed
                        tools=[types.Tool(function_declarations=filtered_funcs)],
                        system_instruction=[types.Part.from_text(text=self.system_prompt)],
                    )
                    
                    # Reset flag so we don't re-filter (though config persists for this iteration)
                    filter_next_round = False

                # Stream response from Gemini (Async)
                has_function_call = False
                
                # Use Async Client via .aio to avoid blocking event loop
                async for chunk in await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=current_config,
                ):
                    # Check for function calls
                    if chunk.function_calls:
                        has_function_call = True
                        func_call = chunk.function_calls[0]
                        tool_name = func_call.name
                        tool_args = dict(func_call.args) if func_call.args else {}
                        
                        t_tool_start = time.perf_counter()
                        if 'first_tool_start' not in metrics:
                            metrics['first_tool_start'] = t_tool_start
                        
                        logger.info(f"[TOOL] Tool call #{tool_round}: {tool_name}({tool_args})")
                        
                        # ENFORCEMENT: Check if tool is allowed
                        if tool_name not in current_allowed_tools:
                            logger.warning(f"[BLOCKED] LLM tried to call disabled tool '{tool_name}'. Blocking execution.")
                            tool_result = f"Tool '{tool_name}' is currently unavailable as you already have the necessary data. Please synthesize your answer using the information from previous steps."
                        else:
                            # Execute tool
                            tool_result = await self._execute_tool(tool_name, tool_args)
                        
                        # Check if this tool should trigger filtering for next round
                        if tool_name in trigger_filtering_tools:
                            logger.info(f"[FILTER] Tool '{tool_name}' executed - enabling selective filtering for next round")
                            filter_next_round = True
                        
                        t_tool_end = time.perf_counter()
                        metrics['last_tool_end'] = t_tool_end
                        tool_duration = (t_tool_end - t_tool_start) * 1000
                        
                        metrics.setdefault('timings', []).append({
                            'step': 'tool_start',
                            'timestamp': t_tool_start,
                            'tool': tool_name
                        })
                        metrics.setdefault('timings', []).append({
                            'step': 'tool_end',
                            'timestamp': t_tool_end,
                            'duration': tool_duration,
                            'tool': tool_name
                        })
                        
                        logger.info(f"[TIMING] Tool {tool_name} completed in {tool_duration:.2f}ms")
                        
                        # Populate metrics['tool_calls'] for pipeline reporting
                        if 'tool_calls' not in metrics:
                            metrics['tool_calls'] = []
                        metrics['tool_calls'].append({
                            'tool': tool_name,
                            'duration_ms': tool_duration
                        })
                        
                        # CRITICAL: Use the ORIGINAL chunk content (preserves thoughtSignature)
                        contents.append(chunk.candidates[0].content)
                        
                        # TERMINATION LOGIC: For definitive answer tools, add strong nudge to respond NOW
                        definitive_tools = {
                            "smart_crop_price_query", 
                            "smart_livestock_price_query",
                            "get_current_weather",
                            "get_weather_forecast"
                        }
                        
                        if tool_name in definitive_tools:
                            # Add tool response WITH termination instruction
                            contents.append(types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_function_response(
                                        name=tool_name,
                                        response={"result": tool_result}
                                    ),
                                    types.Part.from_text(
                                        text="You have the answer. Respond to the user now. Do not call any more tools."
                                    ),
                                ],
                            ))
                        else:
                            # Standard tool response
                            contents.append(types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_function_response(
                                        name=tool_name,
                                        response={"result": tool_result}
                                    ),
                                ],
                            ))
                        
                        break  # Exit streaming loop to make another LLM call
                        
                    elif chunk.text:
                        # Text response - we're done with tool calls
                        if not first_token_recorded:
                            metrics['first_token'] = time.perf_counter()
                            first_token_recorded = True
                        yield chunk.text
                    
                    # Log finish reason if present
                    if chunk.candidates:
                         cand = chunk.candidates[0]
                         if cand.finish_reason:
                             logger.info(f"[FINISH] Finish Reason (Round {tool_round}): {cand.finish_reason}")
                
                # If no function call in this round, we're done
                if not has_function_call:
                    logger.info(f"[SUCCESS] Response complete after {tool_round} round(s)")
                    break
            
            if tool_round >= MAX_TOOL_ROUNDS:
                logger.warning(f"[WARNING] Reached max tool rounds ({MAX_TOOL_ROUNDS})")
                metrics['llm_end'] = time.perf_counter()
                return
            
            # Check if we yielded ANY text
            if not first_token_recorded:
                # If we never recorded first token stats, it means we never yielded text
                logger.warning("[WARNING] LLM finished without yielding text! Sending fallback.")
                fallback_msg = "I found the information but couldn't summarize it. Please ask again."
                if self.lang and self.lang.lower().startswith('am'):
                    fallback_msg = "መረጃውን አግኝቼዋለሁ ነገር ግን ማጠቃለል አልቻልኩም። እባክዎ እንደገና ይጠይቁ።"
                yield fallback_msg
            
            metrics['llm_end'] = time.perf_counter()
            
        except Exception as e:
            logger.error(f"FastGemini error: {e}")
            import traceback
            traceback.print_exc()
            metrics['llm_end'] = time.perf_counter()
            metrics['llm_end'] = time.perf_counter()
            error_msg = "I encountered an error. Please try again."
            if self.lang and self.lang.lower().startswith('am'):
                error_msg = "ስህተት አጋጥሞኛል። እባክዎ እንደገና ይሞክሩ።"
            yield error_msg
    
    async def _execute_tool(self, tool_name: str, args: Dict) -> str:
        """Execute a tool and return its result."""
        from agents.tools.crop import get_crop_price_quick, list_crops_in_marketplace, smart_crop_price_query
        from agents.tools.MarketPlace import list_active_crop_marketplaces, list_active_livestock_marketplaces
        from agents.tools.Livestock import get_livestock_price_quick, list_livestock_in_marketplace
        from agents.tools.weather_tool import get_current_weather
        from agents.deps import FarmerContext
        
        class MockRunContext:
            def __init__(self, lang):
                self.deps = FarmerContext(query="", lang_code=lang)
        
        ctx = MockRunContext(self.lang)
        
        # --- ROBUST ARGUMENT NORMALIZATION ---
        # Handle common model hallucinations like double underscores (marketplace__name)
        normalized_args = {}
        for k, v in args.items():
            # Fix double underscores (Django style hallucination)
            clean_k = k.replace('__', '_')
            normalized_args[clean_k] = v
            # Also keep original just in case
            if k not in normalized_args:
                normalized_args[k] = v
        args = normalized_args
        # -------------------------------------
        try:
            if tool_name == "smart_crop_price_query":
                result = await smart_crop_price_query(
                    ctx, 
                    crop_name=args.get("crop_name", ""),
                    location=args.get("location") or args.get("marketplace_name", ""),
                    is_proximity=bool(args.get("is_proximity", False)),
                    ref_lat=args.get("ref_lat"),
                    ref_lon=args.get("ref_lon")
                )
            elif tool_name == "smart_livestock_price_query":
                from agents.tools.Livestock import smart_livestock_price_query
                result = await smart_livestock_price_query(
                    ctx,
                    livestock_type=args.get("livestock_type", ""),
                    location=args.get("location") or args.get("marketplace_name", ""),
                    is_proximity=bool(args.get("is_proximity", False)),
                    ref_lat=args.get("ref_lat"),
                    ref_lon=args.get("ref_lon")
                )
            elif tool_name == "get_crop_price_quick":
                # Fallback to smart logic to ensure "Deep Search" (geocoding + proximity) is used
                # even if the model picks the simple tool.
                result = await smart_crop_price_query(
                    ctx, 
                    crop_name=args.get("crop_name", ""),
                    location=args.get("marketplace_name", ""),
                    is_proximity=False,
                    ref_lat=args.get("ref_lat"),
                    ref_lon=args.get("ref_lon")
                )
            elif tool_name == "get_livestock_price_quick":
                # Fallback to smart if model still calls old name
                from agents.tools.Livestock import smart_livestock_price_query
                result = await smart_livestock_price_query(
                    ctx,
                    livestock_type=args.get("livestock_type", ""),
                    location=args.get("marketplace_name", ""),
                    is_proximity=False,
                    ref_lat=args.get("ref_lat"),
                    ref_lon=args.get("ref_lon") 
                )
            elif tool_name == "list_crops_in_marketplace":
                result = await list_crops_in_marketplace(ctx, args.get("marketplace_name", ""))
            elif tool_name == "list_livestock_in_marketplace":
                result = await list_livestock_in_marketplace(ctx, args.get("marketplace_name", ""))
            elif tool_name == "list_active_crop_marketplaces":
                result = await list_active_crop_marketplaces()  # No args
            elif tool_name == "list_active_livestock_marketplaces":
                result = await list_active_livestock_marketplaces()  # No args
            elif tool_name in ["get_current_weather", "get_weather_forecast"]:
                from agents.tools.weather_tool import CurrentWeatherInput, ForecastInput, get_current_weather, get_weather_forecast
                
                lat = args.get("latitude")
                lon = args.get("longitude")
                place_name = args.get("place_name")
                
                # Internal Geocoding Fallback if Place Name provided but Coords missing
                if (lat is None or lon is None) and place_name:
                    from agents.tools.maps import forward_geocode
                    from helpers.market_place_json import MARKETPLACES, LIVESTOCK_MARKETPLACES, EXACT_MATCH_UP_MARKETPLACES
                    
                    # 1. Try local JSON map first (Fastest)
                    simple_place = place_name.split(',')[0].strip().lower()
                    json_match = None
                    
                    # Check exact match map
                    for k, v in EXACT_MATCH_UP_MARKETPLACES.items():
                        if k.lower() == simple_place:
                            json_match = v
                            break
                    
                    # Check Marketplaces lists (Exact match scan)
                    if not json_match:
                        all_lists = list(MARKETPLACES.values()) + list(LIVESTOCK_MARKETPLACES.values()) 
                        for r_list in all_lists:
                             for m in r_list:
                                 if m['name'].strip().lower() == simple_place:
                                     json_match = m
                                     break
                             if json_match: break
                    
                    if json_match:
                        lat = json_match.get('lat', json_match.get('latitude'))
                        lon = json_match.get('lon', json_match.get('longitude'))
                        logger.info(f"[LOCATION] Found '{place_name}' in local JSON map (lat={lat})")
                    else:
                        # 2. External Geocoding (Slow backup)
                        logger.info(f"[LOCATION] Internal Geocoding for weather: {place_name}")
                        loc_result = await forward_geocode(place_name)
                        if loc_result:
                            lat = loc_result.latitude
                            lon = loc_result.longitude
                        else:
                            return f"Could not find coordinates for '{place_name}'. Please verify the place name."

                if lat is None or lon is None:
                    return "Latitude and Longitude are required if place_name is not valid."

                if tool_name == "get_current_weather":
                    weather_input = CurrentWeatherInput(
                        latitude=lat,
                        longitude=lon,
                        units=args.get("units", "metric"),
                        language=args.get("language", "en")
                    )
                    result = await get_current_weather(weather_input)
                else: # get_weather_forecast
                    forecast_input = ForecastInput(
                        latitude=lat,
                        longitude=lon,
                        units=args.get("units", "metric"),
                        language=args.get("language", "en")
                    )
                    result = await get_weather_forecast(forecast_input)
            elif tool_name == "forward_geocode":
                from agents.tools.maps import forward_geocode
                # Run async geocoding directly
                result = await forward_geocode(args.get("place_name", ""))
            elif tool_name == "detect_crop_region":
                from agents.tools.Regions import detect_crop_region
                result = await detect_crop_region(
                    latitude=args.get("latitude"),
                    longitude=args.get("longitude")
                )
            elif tool_name == "detect_livestock_region":
                from agents.tools.Regions import detect_livestock_region
                result = await detect_livestock_region(
                    latitude=args.get("latitude"),
                    longitude=args.get("longitude")
                )
            elif tool_name == "find_nearest_crop_marketplaces":
                from agents.tools.MarketPlace import find_nearest_crop_marketplaces
                result = await find_nearest_crop_marketplaces(
                    user_lat=args.get("user_lat"),
                    user_lon=args.get("user_lon"),
                    region=args.get("region"),
                    radius_km=args.get("radius_km", 20),
                    limit=args.get("limit", 5)
                )
            elif tool_name == "find_nearest_livestock_marketplaces":
                from agents.tools.MarketPlace import find_nearest_livestock_marketplaces
                result = await find_nearest_livestock_marketplaces(
                    user_lat=args.get("user_lat"),
                    user_lon=args.get("user_lon"),
                    region=args.get("region"),
                    radius_km=args.get("radius_km", 20),
                    limit=args.get("limit", 5)
                )
            elif tool_name == "search_documents":
                from agents.tools.rag_router import search_documents
                # Run RAG search in thread (it involves blocking HTTP calls)
                result = await asyncio.to_thread(
                    search_documents,
                    query=args.get("query", ""),
                    top_k=int(args.get("top_k", 5)),
                    type=args.get("type")
                )
            else:
                result = f"Tool {tool_name} not implemented"
            
            # Serialize Pydantic models if returned
            if hasattr(result, 'model_dump'):
                result = result.model_dump()
            elif hasattr(result, 'dict'):
                result = result.dict()
                
            return result if isinstance(result, str) else json.dumps(result)
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            import traceback
            traceback.print_exc()
            return f"Error executing tool: {str(e)}"
