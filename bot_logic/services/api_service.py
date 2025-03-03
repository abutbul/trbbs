import os
import logging
import socket
import json
import asyncio
from typing import Dict, Any, Optional, Tuple
import httpx
from bot_logic.core.status import service_status

logger = logging.getLogger(__name__)

# Configuration
API_TIMEOUT = float(os.environ.get("API_TIMEOUT", "60.0"))  # Increase default to 60 seconds
API_RETRIES = int(os.environ.get("API_RETRIES", "2"))
API_RETRY_DELAY = float(os.environ.get("API_RETRY_DELAY", "1.0"))

# Cache the API URL to avoid repeated environment lookups
_API_URL = None

def get_api_url() -> str:
    """Get the API URL from environment with fallbacks."""
    global _API_URL
    if (_API_URL is None):
        _API_URL = os.environ.get("API_CHAT_URL", "http://host.docker.internal:8000/message")
        logger.info(f"Using API URL: {_API_URL}")
    return _API_URL

async def check_api_connectivity(url: str) -> Tuple[bool, str]:
    """Check if an API endpoint is reachable."""
    try:
        # Extract hostname and port from URL
        if url.startswith("http://"):
            hostname = url[7:].split("/")[0]
        elif url.startswith("https://"):
            hostname = url[8:].split("/")[0]
        else:
            hostname = url.split("/")[0]
        
        # Split hostname and port
        if ":" in hostname:
            hostname, port_str = hostname.split(":")
            port = int(port_str)
        else:
            port = 80 if url.startswith("http://") else 443
        
        # Try to connect to the socket first to quickly check connectivity
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(3.0)  # Short timeout for connection test
        
        logger.info(f"Testing connection to {hostname}:{port}")
        conn.connect((hostname, port))
        conn.close()
        
        return True, f"Successfully connected to {hostname}:{port}"
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False, f"Failed to connect: {str(e)}"

async def api_post_request(endpoint: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """
    Make a POST request to an API endpoint with retry logic.
    
    Returns:
        Tuple of (success, response_data, error_message)
    """
    url = endpoint if endpoint.startswith('http') else f"{get_api_url()}"
    
    # First check if we can reach the service
    can_connect, message = await check_api_connectivity(url)
    if not can_connect:
        return False, {}, f"API unreachable: {message}"
    
    # Try the request with retries
    for attempt in range(API_RETRIES + 1):
        try:
            logger.info(f"API request to {url} (attempt {attempt+1}/{API_RETRIES+1})")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, 
                    json=data,
                    timeout=API_TIMEOUT
                )
            
            # Success case
            if response.status_code == 200:
                try:
                    response_json = response.json()
                    logger.debug(f"API response: {json.dumps(response_json)[:500]}...")
                    return True, response_json, ""
                except json.JSONDecodeError:
                    # Handle non-JSON responses
                    text_response = response.text[:1000]  # Limit text length for logging
                    logger.warning(f"API returned non-JSON response: {text_response}")
                    return True, {"text_response": text_response}, ""
            else:
                # Non-200 status code
                error_msg = f"API Error: Status code {response.status_code}"
                logger.error(error_msg)
                
                if attempt < API_RETRIES:
                    await asyncio.sleep(API_RETRY_DELAY * (attempt + 1))
                    continue
                return False, {}, error_msg
                
        except httpx.TimeoutException:
            logger.error(f"Request timeout (attempt {attempt+1})")
            if attempt < API_RETRIES:
                await asyncio.sleep(API_RETRY_DELAY * (attempt + 1))
                continue
            return False, {}, "API request timed out after {API_TIMEOUT} seconds"
            
        except Exception as e:
            logger.error(f"API request error: {str(e)}")
            service_status.record_error(e)
            
            if attempt < API_RETRIES:
                await asyncio.sleep(API_RETRY_DELAY * (attempt + 1))
                continue
            return False, {}, f"Error: {str(e)}"
    
    # Should not reach here, but just in case
    return False, {}, "Maximum retries reached"

async def send_chat_message(message: str) -> Tuple[bool, Optional[str], str]:
    """Send a message to the chat API and return the response."""
    success, response_data, error = await api_post_request(
        get_api_url(),
        {"message": message}
    )
    
    if not success:
        return False, None, error
    
    try:
        # Check specifically for response.messages[].content structure
        output = None
        if "response" in response_data and isinstance(response_data["response"], dict):
            if "messages" in response_data["response"] and isinstance(response_data["response"]["messages"], list):
                # Get the last message (assistant's response)
                messages = response_data["response"]["messages"]
                if messages and len(messages) > 0:
                    # Look for the last assistant message (assuming it's the reply)
                    # Usually this would be the last message in the list
                    last_message = messages[-1]
                    if isinstance(last_message, dict) and "content" in last_message:
                        output = last_message["content"]
                        logger.info("Extracted content from response.messages[].content structure")
        
        # If that specific structure wasn't found, fall back to other extraction methods
        if not output:
            # Try standard response format
            output = response_data.get("response", {}).get("return_values", {}).get("output", "")
            
            # If that's not found, try alternative formats
            if not output and "response" in response_data:
                if isinstance(response_data["response"], str):
                    output = response_data["response"]
                elif isinstance(response_data["response"], dict):
                    # Try common field names for the response
                    for field in ["text", "content", "message", "answer", "result"]:
                        if field in response_data["response"]:
                            output = response_data["response"][field]
                            break
            
            # If still nothing, check top level fields
            if not output:
                for field in ["output", "text", "content", "message", "answer", "result"]:
                    if field in response_data:
                        output = response_data[field]
                        break
            
            # If we have text_response from non-JSON response, use that
            if not output and "text_response" in response_data:
                output = response_data["text_response"]
        
        # If still no output found, dump the entire response structure for debugging
        if not output:
            logger.warning(f"Could not find response content in structure: {json.dumps(response_data)[:500]}...")
            output = f"Received response but couldn't extract content. Response structure: {json.dumps(response_data)[:200]}..."
        
        return True, output, ""
    except Exception as e:
        logger.error(f"Error parsing API response: {e}")
        return False, None, f"Error parsing API response: {str(e)}"
