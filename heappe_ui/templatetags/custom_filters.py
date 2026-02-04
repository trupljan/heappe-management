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



