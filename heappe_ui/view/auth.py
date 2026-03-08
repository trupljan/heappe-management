from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from datetime import datetime
from heappe_ui.auth_backend import HeappeAuthBackend

@login_required
def logout_view(request):
    from django.contrib.auth import logout
    HeappeAuthBackend.api_instance = None
    HeappeAuthBackend.session_code = None
    request.session.flush()
    logout(request)
    return redirect("login")

@login_required
def profile_view(request):
    last_auth_ts = request.session.get("heappe_last_auth")

    if last_auth_ts:
        last_auth = datetime.fromtimestamp(float(last_auth_ts))
    else:
        last_auth = None

    return render(request, "user_profile.html", {"user": request.user,  "last_auth": last_auth})

@login_required
def reconnect_view(request):
    request.session["force_reauth"] = True
    # reload
    return redirect(request.META.get('HTTP_REFERER', '/'))  # Redirect back to the previous page or home if no referrer

