from django.apps import AppConfig


class HeappeUiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'heappe_ui'

    def ready(self):
        import os
        import py4heappe.heappe_v6.core as hp

        # Try finding ApiClient dynamically across all possible import paths
        ApiClient = None
        debug_log = ["--- HEAppE UI Ready Debug ---"]
        
        # Inspect local folder
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            local_heappe_v6 = os.path.join(base_dir, "py4heappe", "heappe_v6")
            debug_log.append(f"local_heappe_v6 path: {local_heappe_v6}")
            if os.path.exists(local_heappe_v6):
                debug_log.append(f"local_heappe_v6 exists. Contents: {os.listdir(local_heappe_v6)}")
                core_path = os.path.join(local_heappe_v6, "core")
                if os.path.exists(core_path):
                    debug_log.append(f"local_heappe_v6/core exists. Contents: {os.listdir(core_path)}")
        except Exception as e:
            debug_log.append(f"Failed to inspect directories: {e}")

        candidate_imports = [
            ("py4heappe.heappe_v6.core.api_client", "ApiClient"),
            ("py4heappe.heappe_v6.core", "ApiClient"),
            ("py4heappe.heappe_v6.api_client", "ApiClient"),
            ("py4heappe.heappe_v6", "ApiClient"),
            ("heappe_v6.core.api_client", "ApiClient"),
            ("heappe_v6.core", "ApiClient"),
            ("heappe_v6.api_client", "ApiClient"),
            ("heappe_v6", "ApiClient"),
        ]

        import_errors = []
        for module_name, attr_name in candidate_imports:
            try:
                mod = __import__(module_name, fromlist=[attr_name])
                val = getattr(mod, attr_name, None)
                if val:
                    ApiClient = val
                    debug_log.append(f"SUCCESS: Imported {attr_name} from {module_name}")
                    break
            except Exception as e:
                import_errors.append(f"Failed {module_name}.{attr_name}: {e}")

        if ApiClient is None:
            debug_log.append("ERROR: ApiClient not found in any candidates.")
            debug_log.append("Import errors:\n" + "\n".join(import_errors))
            print("\n".join(debug_log))
            raise AttributeError(f"ApiClient not found. Import attempts failed. Details: {import_errors}")

        # Debug print
        try:
            import py4heappe
            print(f"[DEBUG_IMPORT] py4heappe loaded from: {getattr(py4heappe, '__file__', 'No file')}")
            import py4heappe.heappe_v6 as hp_v6
            print(f"[DEBUG_IMPORT] heappe_v6 loaded from: {getattr(hp_v6, '__file__', 'No file')}")
            import py4heappe.heappe_v6.core.models as hp_models
            print(f"[DEBUG_IMPORT] heappe_v6 models loaded from: {getattr(hp_models, '__file__', 'No file')}")
        except Exception as e:
            print(f"[DEBUG_IMPORT] Failed loading py4heappe models: {e}")

        # Ensure ApiClient is exposed on the hp module for other parts of the application
        if not hasattr(hp, 'ApiClient'):
            hp.ApiClient = ApiClient

        from heappe_ui.auth_backend import patch_api_client

        original_init = ApiClient.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            patch_api_client(self)

        ApiClient.__init__ = patched_init

        original_request = ApiClient.request

        def patched_request(self, method, url, *args, **kwargs):
            response = original_request(self, method, url, *args, **kwargs)
            try:
                raw_data = getattr(response, 'data', None)
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode('utf-8')
                print(f"[RAW HTTP RESPONSE] {method} {url} -> Status: {getattr(response, 'status', 'Unknown')}, Body: {raw_data}")
                
                # Deserialization check
                if response and getattr(response, 'data', None):
                    try:
                        import json
                        parsed_json = json.loads(response.data)
                        print(f"[DEBUG_DESER] URL: {url} | parsed JSON count: {len(parsed_json) if isinstance(parsed_json, list) else 'not a list'}")
                        if 'Management/Clusters' in url:
                            try:
                                man_deser = self.deserialize(response, 'list[ExtendedClusterExt]')
                                print(f"[DEBUG_DESER] URL: {url} | manual deserialize success: {man_deser is not None}, count: {len(man_deser) if man_deser else 0}")
                            except Exception as ex_cls:
                                print(f"[DEBUG_DESER] URL: {url} | manual deserialize clusters failed: {ex_cls}")
                                import traceback; traceback.print_exc()
                        elif 'Management/Projects' in url:
                            try:
                                man_deser = self.deserialize(response, 'list[ProjectExt]')
                                print(f"[DEBUG_DESER] URL: {url} | manual deserialize success: {man_deser is not None}, count: {len(man_deser) if man_deser else 0}")
                            except Exception as ex_prj:
                                print(f"[DEBUG_DESER] URL: {url} | manual deserialize projects failed: {ex_prj}")
                                import traceback; traceback.print_exc()
                    except Exception as ex_gen:
                        print(f"[DEBUG_DESER] URL: {url} | general check failed: {ex_gen}")
            except Exception as e:
                print(f"[RAW HTTP RESPONSE] Error reading response details: {e}")
            return response

        ApiClient.request = patched_request
        print("[heappe_ui] Globally patched hp.ApiClient with timeout, logging, and raw response tracing.")

        # Dynamically wrap all Api classes and methods to handle SessionCode transparently
        import inspect
        import functools
        
        api_modules = []
        try:
            import py4heappe.heappe_v6.core.api as api_mod
            for name in dir(api_mod):
                attr = getattr(api_mod, name)
                if inspect.isclass(attr) and name.endswith("Api"):
                    api_modules.append(attr)
        except Exception:
            pass

        try:
            import py4heappe.heappe_v6.core as hp_core
            for k in dir(hp_core):
                if k.endswith("Api"):
                    cls = getattr(hp_core, k)
                    if inspect.isclass(cls) and cls not in api_modules:
                        api_modules.append(cls)
        except Exception:
            pass

        def pascal_to_snake(name):
            import re
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

        def wrap_api_method(original_method):
            @functools.wraps(original_method)
            def method_wrapper(self, *args, **kwargs):
                session_code = kwargs.get('SessionCode') or kwargs.get('session_code')
                try:
                    return original_method(self, *args, **kwargs)
                except TypeError as e:
                    err_msg = str(e)
                    if "unexpected keyword argument" in err_msg:
                        import re
                        m = re.search(r"unexpected keyword argument '([^']+)'", err_msg)
                        if m:
                            rejected_arg = m.group(1)
                            # Handle session code
                            if rejected_arg == 'session_code' or rejected_arg == 'SessionCode':
                                kwargs.pop(rejected_arg, None)
                                if session_code and getattr(self, 'api_client', None):
                                    client = self.api_client
                                    client.set_default_header("Authorization", f"Bearer {session_code}")
                                    if getattr(client, 'configuration', None):
                                        cfg = client.configuration
                                        if not hasattr(cfg, 'api_key') or not isinstance(cfg.api_key, dict):
                                            cfg.api_key = {}
                                        cfg.api_key['Authorization'] = session_code
                                        if not hasattr(cfg, 'api_key_prefix') or not isinstance(cfg.api_key_prefix, dict):
                                            cfg.api_key_prefix = {}
                                        cfg.api_key_prefix['Authorization'] = 'Bearer'
                                return method_wrapper(self, *args, **kwargs)
                            
                            # Convert PascalCase to snake_case
                            snake_arg = pascal_to_snake(rejected_arg)
                            if snake_arg != rejected_arg and rejected_arg in kwargs:
                                val = kwargs.pop(rejected_arg)
                                kwargs[snake_arg] = val
                                return method_wrapper(self, *args, **kwargs)
                    raise
            return method_wrapper

        patched_methods_count = 0
        for cls in api_modules:
            for attr_name in dir(cls):
                if attr_name.startswith('_'):
                    continue
                attr = getattr(cls, attr_name)
                if inspect.isfunction(attr) or inspect.ismethod(attr):
                    try:
                        sig = inspect.signature(attr)
                        if 'kwargs' in sig.parameters:
                            setattr(cls, attr_name, wrap_api_method(attr))
                            patched_methods_count += 1
                    except Exception:
                        pass
        print(f"[heappe_ui] Dynamically patched {patched_methods_count} Api methods to handle SessionCode and authorization.")
