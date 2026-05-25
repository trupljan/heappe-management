from django import template
import py4heappe.heappe_v6.core as hp

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.simple_tag(takes_context=True)
def heappe_version_ok(context, min_version):
    request = context['request']
    try:
        controller = hp.HealthApi(request.api_instance)
        health_info = controller.heappe_health_get()
        current_version = health_info.version.lstrip("vV")

        return current_version >= str(min_version)
    except Exception:
        return False


from datetime import datetime

@register.filter
def format_datetime(value):
    if not value:
        return ""
    if hasattr(value, 'strftime'):
        return value.strftime('%d.%m.%Y %H:%M:%S')
    
    if isinstance(value, str):
        value_clean = value.replace('T', ' ').replace('Z', '').strip()
        if '.' in value_clean:
            base, sub = value_clean.split('.', 1)
            sub_clean = sub[:6]
            value_clean = f"{base}.{sub_clean}"
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                try:
                    dt = datetime.strptime(value_clean, fmt)
                    return dt.strftime('%d.%m.%Y %H:%M:%S')
                except ValueError:
                    pass
        else:
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    dt = datetime.strptime(value_clean, fmt)
                    return dt.strftime('%d.%m.%Y %H:%M:%S') if ':' in fmt else dt.strftime('%d.%m.%Y')
                except ValueError:
                    pass
            
    return value




