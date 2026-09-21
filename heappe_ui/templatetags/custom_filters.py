from django import template
import py4heappe.heappe_v6.core as hp
from heappe_ui.view.utils import clean_ver

register = template.Library()

@register.filter
def get_item(dictionary, key):
    if not isinstance(dictionary, dict) or key is None:
        return None
    val = dictionary.get(key)
    if val is not None:
        return val
    if isinstance(key, str):
        k_strip = key.strip()
        val = dictionary.get(k_strip)
        if val is not None:
            return val
        k_lower = k_strip.lower()
        val = dictionary.get(k_lower)
        if val is not None:
            return val
        k_upper = k_strip.upper()
        val = dictionary.get(k_upper)
        if val is not None:
            return val
        for d_key, d_val in dictionary.items():
            if isinstance(d_key, str) and d_key.strip().lower() == k_lower:
                return d_val
    return None

@register.filter
def get_user_system_roles(user_or_username, system_role_user_map):
    """
    Returns system roles for a user, checking:
    1. Direct 'system_roles' attribute/key on user dict or object
    2. Lookup in system_role_user_map by username, email, or idp_sid
       with case-insensitivity and whitespace trimming.
    """
    if isinstance(user_or_username, dict):
        if user_or_username.get("system_roles"):
            return user_or_username["system_roles"]
        username = user_or_username.get("username")
        email = user_or_username.get("email")
        idp_sid = user_or_username.get("idp_sid") or user_or_username.get("IdpSid")
    elif hasattr(user_or_username, 'username'):
        if getattr(user_or_username, 'system_roles', None):
            return user_or_username.system_roles
        username = getattr(user_or_username, 'username', None)
        email = getattr(user_or_username, 'email', None)
        idp_sid = getattr(user_or_username, 'idp_sid', None) or getattr(user_or_username, 'IdpSid', None)
    else:
        username = str(user_or_username) if user_or_username is not None else None
        email = None
        idp_sid = None

    if not isinstance(system_role_user_map, dict):
        return []

    for cand in (username, email, idp_sid):
        if cand:
            res = get_item(system_role_user_map, cand)
            if res:
                return res
    return []

@register.simple_tag(takes_context=True)
def heappe_version_ok(context, min_version):
    request = context.get('request')
    if not request or not hasattr(request, 'api_instance'):
        return False
    try:
        controller = hp.HealthApi(request.api_instance)
        health_info = controller.heappe_health_get()
        current_version = health_info.version.lstrip("vV")



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


@register.filter
def get_job_state_source(job):
    if not job:
        return None
    val = None
    if isinstance(job, dict):
        if 'state_source' in job and job['state_source'] is not None:
            val = job['state_source']
        elif 'StateSource' in job and job['StateSource'] is not None:
            val = job['StateSource']
    else:
        val = getattr(job, 'state_source', getattr(job, 'StateSource', None))

    if val is None:
        return None

    mapping = {
        0: "Unknown",
        1: "Callback",
        2: "User Verified",
        3: "Background Poll",
        "0": "Unknown",
        "1": "Callback",
        "2": "User Verified",
        "3": "Background Poll",
        "Unknown": "Unknown",
        "Callback": "Callback",
        "UserVerified": "User Verified",
        "BackgroundPoll": "Background Poll",
        "Scheduler": "Scheduler",
        "Framework": "Framework",
        "Proxy": "Proxy",
        "User": "User",
    }
    return mapping.get(val, str(val))


@register.filter
def get_job_state_updated_at(job):
    if not job:
        return None
    if isinstance(job, dict):
        if 'state_updated_at' in job and job['state_updated_at'] is not None:
            return job['state_updated_at']
        elif 'StateUpdatedAt' in job and job['StateUpdatedAt'] is not None:
            return job['StateUpdatedAt']
        return None
    return getattr(job, 'state_updated_at', getattr(job, 'StateUpdatedAt', None))


@register.filter
def format_cluster_auth_type(val):
    if val is None:
        return "N/A"
    mapping = {
        0: "None / Unknown",
        1: "Password",
        2: "Password Interactive",
        3: "Password & Private Key",
        4: "SSH Private Key",
        5: "Password via Proxy",
        6: "Password Interactive via Proxy",
        7: "Password & Private Key via Proxy",
        8: "Private Key via Proxy",
        9: "SSH Agent Key",
        10: "Vault & SSH Agent Key",
        11: "SSH Certificate",
        12: "SSH Certificate via Proxy",
        13: "Kerberos Keytab",
        14: "FirecREST IDP via Expirio",
    }
    try:
        int_val = int(val)
        return mapping.get(int_val, str(val))
    except (ValueError, TypeError):
        return str(val)


@register.filter
def format_task_priority(val):
    if val is None:
        return "N/A"
    mapping = {
        0: "Lowest",
        1: "Very Low",
        2: "Low",
        3: "Below Average",
        4: "Average",
        5: "Above Average",
        6: "High",
        7: "Very High",
        8: "Critical",
    }
    try:
        int_val = int(val)
        return mapping.get(int_val, str(val))
    except (ValueError, TypeError):
        return str(val)


@register.filter
def in_csv(value, csv):
    """
    Return True if *value*, as a string, is found in the comma‑separated string csv.
    """
    return str(value) in csv.split(',')



