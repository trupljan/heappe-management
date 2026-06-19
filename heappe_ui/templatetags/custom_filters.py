from django import template
import py4heappe.heappe_v6.core as hp

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.simple_tag(takes_context=True)
def heappe_version_ok(context, min_version):
    request = context.get('request')
    if not request or not hasattr(request, 'api_instance'):
        return False
    try:
        controller = hp.HealthApi(request.api_instance)
        health_info = controller.heappe_health_get()
        current_version = health_info.version.lstrip("vV")

        def clean_ver(v):
            res = [int(n) for n in v.lower().split('.') if n.isdigit()]
            return res if res else [0]

        return clean_ver(current_version) >= clean_ver(str(min_version))
    except Exception:
        return False


from datetime import datetime

@register.filter
def format_datetime(value, format_str='%d.%m.%Y %H:%M:%S'):
    if not value:
        return ""
    if hasattr(value, 'strftime'):
        return value.strftime(format_str)
    
    if isinstance(value, str):
        value_clean = value.replace('T', ' ').replace('Z', '').strip()
        if '.' in value_clean:
            base, sub = value_clean.split('.', 1)
            sub_clean = sub[:6]
            value_clean = f"{base}.{sub_clean}"
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                try:
                    dt = datetime.strptime(value_clean, fmt)
                    return dt.strftime(format_str)
                except ValueError:
                    pass
        else:
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    dt = datetime.strptime(value_clean, fmt)
                    if ':' in fmt:
                        return dt.strftime(format_str)
                    else:
                        out_fmt = format_str if format_str != '%d.%m.%Y %H:%M:%S' else '%d.%m.%Y'
                        return dt.strftime(out_fmt)
                except ValueError:
                    pass
            
    return value


@register.filter
def instance_links(instance_name):
    if not instance_name:
        return {}
    from heappe_ui.view.utils import get_instance_api_links
    try:
        return get_instance_api_links(instance_name)
    except Exception:
        return {}





