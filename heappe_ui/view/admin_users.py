import secrets
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden
from django.urls import reverse

def superuser_required(view_func):
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Only superusers are allowed to access this section.")
            return redirect("dashboard_view")
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@superuser_required
def admin_users_list(request):
    users = User.objects.all().order_by('username')
    return render(request, "admin_users_list.html", {"users": users})

@superuser_required
def admin_users_create(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        is_superuser = request.POST.get("is_superuser") == "on"
        is_staff = request.POST.get("is_staff") == "on" or is_superuser

        if not username:
            messages.error(request, "Username is required.")
            return render(request, "admin_users_form.html", {"action": "create"})

        if User.objects.filter(username=username).exists():
            messages.error(request, f"User with username '{username}' already exists.")
            return render(request, "admin_users_form.html", {"action": "create", "username": username, "email": email})

        # Generate random password if not provided
        if not password:
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            password = "".join(secrets.choice(alphabet) for _ in range(16))

        # Create user
        user = User.objects.create_user(username=username, email=email, password=password)
        user.is_superuser = is_superuser
        user.is_staff = is_staff
        user.save()

        messages.success(request, f"User '{username}' created successfully.")
        
        # Calculate absolute URL for login
        admin_panel_url = request.build_absolute_uri(reverse('login'))
        decryption_url = request.build_absolute_uri(reverse('decrypt_credentials_view'))
        
        return render(request, "admin_users_success.html", {
            "username": username,
            "email": email,
            "password": password,
            "is_superuser": is_superuser,
            "is_staff": is_staff,
            "admin_panel_url": admin_panel_url,
            "decryption_url": decryption_url,
            "type": "create"
        })

    return render(request, "admin_users_form.html", {"action": "create"})

@superuser_required
def admin_users_edit(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        is_superuser = request.POST.get("is_superuser") == "on"
        is_staff = request.POST.get("is_staff") == "on" or is_superuser
        is_active = request.POST.get("is_active") == "on"

        if not username:
            messages.error(request, "Username is required.")
            return render(request, "admin_users_form.html", {"action": "edit", "edit_user": user})

        # Check if username is taken by another user
        if User.objects.filter(username=username).exclude(id=user.id).exists():
            messages.error(request, f"User with username '{username}' already exists.")
            return render(request, "admin_users_form.html", {"action": "edit", "edit_user": user})

        # Prevent superusers from de-activating or removing superuser status from themselves
        if user.id == request.user.id:
            if not is_active:
                messages.error(request, "You cannot deactivate your own account.")
                return redirect("admin_users_list")
            if not is_superuser:
                messages.error(request, "You cannot remove superuser status from your own account.")
                return redirect("admin_users_list")

        user.username = username
        user.email = email
        user.is_superuser = is_superuser
        user.is_staff = is_staff
        user.is_active = is_active
        user.save()

        messages.success(request, f"User '{username}' updated successfully.")
        return redirect("admin_users_list")

    return render(request, "admin_users_form.html", {"action": "edit", "edit_user": user})

@superuser_required
def admin_users_password(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        password = request.POST.get("password", "").strip()
        
        # Generate random password if not provided
        if not password:
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            password = "".join(secrets.choice(alphabet) for _ in range(16))

        user.set_password(password)
        user.save()

        messages.success(request, f"Password for user '{user.username}' updated successfully.")
        
        # Calculate absolute URL for login
        admin_panel_url = request.build_absolute_uri(reverse('login'))
        decryption_url = request.build_absolute_uri(reverse('decrypt_credentials_view'))
        
        return render(request, "admin_users_success.html", {
            "username": user.username,
            "email": user.email,
            "password": password,
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
            "admin_panel_url": admin_panel_url,
            "decryption_url": decryption_url,
            "type": "password"
        })

    return render(request, "admin_users_password.html", {"edit_user": user})

@superuser_required
def admin_users_delete(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if user.id == request.user.id:
        messages.error(request, "You cannot delete your own account.")
        return redirect("admin_users_list")
    
    if request.method == "POST":
        username = user.username
        user.delete()
        messages.success(request, f"User '{username}' deleted successfully.")
        return redirect("admin_users_list")
        
    return render(request, "admin_users_delete_confirm.html", {"edit_user": user})

def decrypt_credentials_view(request):
    return render(request, "decrypt_credentials.html")
