from .imports import *

def file_transfer_method_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        payload_data = {
            "ServerHostname": request.POST.get("ServerHostname", ""),
            "Protocol": request.POST.get("Protocol", "SSH"),
            "Port": int(request.POST.get("Port")) if request.POST.get("Port") else 22,
        }
        payload = _create_payload(request.session_code, payload_data)
        return _handle_api_call(
            request,
            lambda: controller.heappe_management_file_transfer_method_post(**payload),
            "File Transfer Method created successfully!",
            "Failed to create File Transfer Method",
            redirect_url='file_transfer_methods'
        )
    return render(request, 'create_file_transfer_method.html')
