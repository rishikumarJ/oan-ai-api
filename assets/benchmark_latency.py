
import time
import os
import sys

# Measure import time
start_import = time.time()
import base64
from google import genai
from google.genai import types
end_import = time.time()
print(f"Import Time: {end_import - start_import:.4f}s")

SYSTEM_PROMPT_PATH = "/Users/satyendrasahani/Documents/agriSulopa/rishi/oan-ai-api/assets/prompts/en.md"

def load_system_prompt():
    with open(SYSTEM_PROMPT_PATH, "r") as f:
        return f.read()

def benchmark_original():
    print("\n--- Benchmarking Original Implementation ---")
    
    # Measure Setup (Prompt Load + Client Init)
    t0 = time.time()
    system_prompt = load_system_prompt()
    
    # Original code structure
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
    )
    t1 = time.time()
    print(f"Setup & Client Init Time: {t1 - t0:.4f}s")

    model = "gemini-3-flash-preview"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="What is the price of wheat in Amber?"),
            ],
        ),
    ]
    tools = [
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
    
    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        thinking_config=types.ThinkingConfig(
            thinking_level="MINIMAL",
        ),
        tools=tools,
        system_instruction=[
            types.Part.from_text(text=system_prompt ),
        ],
    )

    print("Sending request...")
    req_start = time.time()
    
    # We will just iterate to find first token time and total time
    first_token_time = None
    chunk_count = 0
    
    try:
        response_stream = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        )
        
        for chunk in response_stream:
            if first_token_time is None:
                first_token_time = time.time()
            chunk_count += 1
            # Simulate processing
            _ = chunk.text if chunk.function_calls is None else chunk.function_calls[0]
            
    except Exception as e:
        print(f"Error during generation: {e}")
        return

    req_end = time.time()
    
    if first_token_time:
        ttft = first_token_time - req_start
        print(f"Time To First Token (TTFT): {ttft:.4f}s")
    
    print(f"Total API Call Time: {req_end - req_start:.4f}s")
    print(f"Total Wall Time (incl setup): {req_end - t0:.4f}s")

if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)
        
    benchmark_original()
