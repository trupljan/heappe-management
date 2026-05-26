from django.apps import AppConfig


class HeappeUiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'heappe_ui'

    def ready(self):
        import py4heappe.heappe_v6.core as hp
        from heappe_ui.auth_backend import patch_api_client

        original_init = hp.ApiClient.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            patch_api_client(self)

        hp.ApiClient.__init__ = patched_init
        print("[heappe_ui] Globally patched hp.ApiClient with timeout and logging.")
