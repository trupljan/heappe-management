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
            'heappe_password': forms.PasswordInput(render_value=True),
            'log_db_password': forms.PasswordInput(render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        optional_fields = [
            'log_db_host',
            'log_db_port',
            'log_db_user',
            'log_db_password',
            'log_db_database'
        ]

        placeholders = {
            'instance_name': 'e.g. dev_instance',
            'heappe_host': 'e.g. https://p01-183.cloud.it4i.cz',
            'heappe_login': 'e.g. admin',
            'heappe_password': 'Enter HEAppE password',
            'heappe_port': 'e.g. 5000',
            'log_db_host': 'e.g. 192.168.1.15',
            'log_db_port': 'e.g. 1433',
            'log_db_user': 'e.g. SA',
            'log_db_password': 'Enter DB password',
            'log_db_database': 'e.g. heappe-monitoring',
        }

        for field_name, field in self.fields.items():
            if field_name != 'is_deployed':
                field.widget.attrs.update({'class': 'form-control'})
            else:
                field.widget.attrs.update({'class': 'form-check-input ms-0 me-2'})
            if field_name in placeholders:
                field.widget.attrs.update({'placeholder': placeholders[field_name]})
            if field_name in optional_fields:
                field.required = False

        self.fields['heappe_password'].required = False