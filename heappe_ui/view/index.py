from .imports import *

def index(request: HttpRequest) -> HttpResponse:
    return HttpResponse(f"Session code: {request.session_code}")