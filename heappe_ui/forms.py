from django import forms
from .models import InstanceCredentials

class InstanceCredentialsForm(forms.ModelForm):
    class Meta:
        model = InstanceCredentials
        fields = [
            'instance_name', 'heappe_host', 'heappe_login', 'heappe_password', 'heappe_port',
            'log_db_host', 'log_db_port', 'log_db_user', 'log_db_password', 'log_db_database', 'is_deployed'
        ]
        widgets = {
            'heappe_password': forms.PasswordInput(),
            'log_db_password': forms.PasswordInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})