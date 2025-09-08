from .imports import *

def _create_payload(session_code: str, data: Dict[str, Any], id_field: Optional[str] = None) -> Dict[str, Any]:
    """Create a standardized payload for API requests."""
    payload = {
        "_preload_content": False,
        "body": {"SessionCode": session_code, **data}
    }
    if id_field and id_field in data:
        payload["body"]["Id"] = data[id_field]
    return payload

def _handle_api_call(
    request: HttpRequest,
    api_call: callable,
    success_message: str,
    error_message: str,
    redirect_url: Optional[str] = None
) -> HttpResponse:
    """Handle API call with error handling and messaging."""
    try:
        result = api_call()
        messages.success(request, success_message)
        return result.json()
    except Exception as e:
        messages.error(request, f"{error_message}: {str(e)}")
        print(f"Error: {error_message}: {e}")