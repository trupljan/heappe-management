from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from heappe_ui.models import InstanceCredentials
from heappe_ui.forms import InstanceCredentialsForm

@login_required
def instance_credentials_list(request, pk=None):
    if pk is not None:
        instance = get_object_or_404(InstanceCredentials, pk=pk)
        if instance:
            request.session["chosen_instance"] = instance.instance_name
            request.session["force_reauth"] = True
            return redirect("dashboard_view")

    instances = InstanceCredentials.objects.all().order_by('instance_name')
    return render(request, 'instance_credentials.html', {'object_list': instances})

@login_required
def instance_credentials_create(request):
    if request.method == 'POST':
        form = InstanceCredentialsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Instance '{form.cleaned_data['instance_name']}' created successfully.")
            return redirect('instance_credentials_list')
        else:
            messages.error(request, 'Error creating instance. Please check the form.')
    else:
        form = InstanceCredentialsForm()
    return render(request, 'instance_credentials_form.html', {'form': form})

@login_required
def instance_credentials_edit(request, pk):
    instance = get_object_or_404(InstanceCredentials, pk=pk)

    if request.method == 'POST':
        data = request.POST.copy()

        if not data.get('heappe_password'):
            data['heappe_password'] = instance.heappe_password
        if not data.get('log_db_password'):
            data['log_db_password'] = instance.log_db_password

        form = InstanceCredentialsForm(data, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"Instance '{form.cleaned_data['instance_name']}' updated successfully.")
            return redirect('instance_credentials_list')
        else:
            messages.error(request, 'Error updating instance. Please check the form.')
    else:
        form = InstanceCredentialsForm(instance=instance)
        form.fields['heappe_password'].initial = ""
        form.fields['log_db_password'].initial = ""

    return render(request, 'instance_credentials_form.html', {'form': form})

@login_required
def instance_credentials_delete(request, pk):
    instance = get_object_or_404(InstanceCredentials, pk=pk)
    if request.method == 'POST':
        instance_name = instance.instance_name
        instance.delete()
        messages.success(request, f"Instance '{instance_name}' deleted successfully.")
        return redirect('instance_credentials_list')
    return render(request, 'instance_credentials.html', {'object_list': InstanceCredentials.objects.all()})

