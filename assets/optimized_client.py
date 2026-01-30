
import os
import time
from google import genai
from google.genai import types

# 1. Load System Prompt once at module level
SYSTEM_PROMPT_PATH = "/Users/satyendrasahani/Documents/agriSulopa/rishi/oan-ai-api/assets/prompts/en.md"
try:
    with open(SYSTEM_PROMPT_PATH, "r") as f:
        SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    print(f"Warning: System prompt file not found at {SYSTEM_PROMPT_PATH}")
    SYSTEM_PROMPT = ""

# 2. Initialize Client once
# Ensure the API key is available
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Handle the missing key gracefully or let the library handle it if it checks other env vars
    pass

client = genai.Client(api_key=api_key)

# 3. Pre-define static configurations
MODEL_ID = "gemini-3-flash-preview"

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_crop_price_quick",
                description="to find crop prices",
                parameters=genai.types.Schema(
                    type = genai.types.Type.OBJECT,
                    required = ["crop", "market"],
                    properties = {
                        "crop": genai.types.Schema(
                            type = genai.types.Type.STRING,
                        ),
                        "market": genai.types.Schema(
                            type = genai.types.Type.STRING,
                        ),
                    },
                ),
            ),
        ])
]

# We need to recreate the config for each request if we want to change dynamic parameters,
# but the tools and system instruction parts can be reused if the library allows deep reuse.
# For safety, we keep the config construction light.
# Using 'thinking_level="MINIMAL"' as requested.

def generate_optimized(user_input: str):
    """
    Optimized generation function reusing global resources.
    """
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=user_input),
            ],
        ),
    ]

    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        thinking_config=types.ThinkingConfig(
            thinking_level="MINIMAL",
        ),
        tools=TOOLS,
        system_instruction=[
           types.Part.from_text(text=SYSTEM_PROMPT),
        ],
    )

    # Streaming is usually faster for TTFT (Time To First Token) perception,
    # but for total time it is same or slightly slower.
    # The user asked for "LLM call is crossing 2sec", implying total time or response wait.
    # We stick to streaming as per their original code.
    
    return client.models.generate_content_stream(
        model=MODEL_ID,
        contents=contents,
        config=generate_content_config,
    )

if __name__ == "__main__":
    if not api_key:
        print("Please set GEMINI_API_KEY environment variable.")
    else:
        print("Running optimized generation...")
        start_time = time.time()
        
        response_stream = generate_optimized("What is the price of wheat in Amber?")
        
        first_token = False
        for chunk in response_stream:
            if not first_token:
                print(f"Time to First Token: {time.time() - start_time:.4f}s")
                first_token = True
            print(chunk.text if chunk.function_calls is None else chunk.function_calls[0])
            
        print(f"Total Time: {time.time() - start_time:.4f}s")
