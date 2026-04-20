from __future__ import annotations

import json
import re

def repair_json(text: str) -> str:
    """
    Attempts to repair common JSON truncation issues by:
    1. Finding the first '{' and the likely boundary of the JSON.
    2. Closing open quotes.
    3. Closing open braces/brackets in reverse order of opening.
    """
    text = text.strip()
    if not text:
        return text

    # Locate the start of JSON
    start_idx = text.find('{')
    if start_idx == -1:
        return text
    
    json_part = text[start_idx:]
    
    # 1. Close an open string if the count of solo double quotes is odd
    # This is a bit naive but handles the most common mid-reasoning cutoffs.
    if json_part.count('"') % 2 != 0:
        json_part += '"'

    # 2. Track depth of braces and brackets
    stack = []
    in_string = False
    escaped = False

    for i, char in enumerate(json_part):
        if char == '"' and not escaped:
            in_string = not in_string
        
        if in_string:
            if char == '\\' and not escaped:
                escaped = True
            else:
                escaped = False
            continue
        
        if char == '{':
            stack.append('}')
        elif char == '[':
            stack.append(']')
        elif char == '}':
            if stack and stack[-1] == '}':
                stack.pop()
        elif char == ']':
            if stack and stack[-1] == ']':
                stack.pop()
        
        escaped = False

    # 3. Add closing components in reverse order
    while stack:
        json_part += stack.pop()

    # Final check: can we parse it now?
    try:
        json.loads(json_part)
        return json_part
    except json.JSONDecodeError:
        # If it still fails, let the original text through; 
        # the Pydantic parser will handle the failure.
        return text
