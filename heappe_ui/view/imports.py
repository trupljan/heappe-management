import json
from typing import Optional, Dict, Any, List
from django.http import HttpResponse, HttpRequest
from django.shortcuts import render, redirect
from django.contrib import messages
import sys

import py4heappe.heappe_v6.core as hp


def ensure_heappe_version(
    request,
    min_version: str,
    error_message: str,
    fallback_url: str,
):
    controller = hp.HealthApi(request.api_instance)
    health_info = controller.heappe_health_get()

    # clean v/V prefix
    version = health_info.version.lstrip("vV")

    # if version is too low → stop and redirect
    if version < min_version:
        messages.error(request, error_message)
        reload_url = request.META.get("HTTP_REFERER", fallback_url)
        return redirect(reload_url)

    # otherwise → allow to continue
    return None
