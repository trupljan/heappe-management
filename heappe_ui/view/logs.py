import os
import re
import json
import time
from collections import Counter, deque
from datetime import datetime, timedelta
import pymssql

from django.utils import timezone
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.http import StreamingHttpResponse, JsonResponse
from heappe_ui.DeployService import get_instance_settings
from heappe_ui.models import InstanceCredentials

class DatabaseSettingsError(Exception):
    pass

@login_required
def logs_view(request):
    context = {}
    context['default_date_from'] = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    # Handle database configuration form submission
    if request.method == 'POST' and request.POST.get('config_submit'):
        InstanceCredentials.objects.update_or_create(
            instance_name=request.session['chosen_instance'],
            defaults={
                "heappe_host": request.session["heappe_host"],
                "heappe_login": request.session["heappe_username"],
                "log_db_host": request.POST.get('server'),
                "log_db_port": request.POST.get('port'),
                "log_db_user": request.POST.get('user'),
                "log_db_password": request.POST.get('password'),
                "log_db_database": request.POST.get('database'),
            }
        )

    credentials = get_instance_settings(instance_name=request.session['chosen_instance'])
    db_settings = {}
    if credentials:
        db_settings = {
            'server': credentials.log_db_host,
            'port': credentials.log_db_port,
            'user': credentials.log_db_user,
            'password': credentials.log_db_password,
            'database': credentials.log_db_database,
            'tds_version': '8.0',
        }

    if db_settings:
        # Pass current database settings to template
        context['db_server'] = db_settings['server']
        context['db_port'] = db_settings['port']
        context['db_user'] = db_settings['user']
        context['db_password'] = db_settings['password']
        context['db_database'] = db_settings['database']

    # Initialize default context values to prevent template errors
    context['levels'] = []
    context['logs'] = []
    context['summary_levels'] = Counter()
    context['summary_classes'] = []
    context['chart_dates'] = []
    context['chart_errors'] = []
    context['chart_warnings'] = []
    context['chart_info'] = []
    context['chart_debug'] = []
    context['chart_critical'] = []
    context['error_count'] = 0
    context['warning_count'] = 0
    context['info_count'] = 0
    context['debug_count'] = 0
    context['critical_count'] = 0

    # Attempt database connection
    try:
        if db_settings:
            required_fields = ['server', 'port', 'user', 'password', 'database']
            missing_fields = [field for field in required_fields if db_settings[field] is None or db_settings[field] == '']
            if missing_fields:
                raise DatabaseSettingsError(f"Missing required database settings: {', '.join(missing_fields)}")
        else:
            raise DatabaseSettingsError(f"Please configure Log Database.")
        conn = pymssql.connect(**db_settings)
        cursor = conn.cursor(as_dict=True)
        cursor.execute("SELECT * FROM LoggingLevelType")
        rows = cursor.fetchall()
        LoggingLevelType = {row['Id']: row['Name'] for row in rows}
        context['levels'] = [{'Id': k, 'Name': v} for k, v in LoggingLevelType.items()]
        cursor.close()

        # Filtry z GET parametrů
        date_from = request.GET.get('date_from')
        if date_from is not None:
            date_from = date_from.replace('T', ' ')
        date_to = request.GET.get('date_to')
        if date_to is not None:
            date_to = date_to.replace('T', ' ')
        level_filter = request.GET.get('level')
        search = request.GET.get('search', '').lower()

        # SQL dotaz s podmínkami
        query = "SELECT * FROM Log WHERE 1=1"
        params = []

        if date_from:
            query += " AND Date >= %s"
            params.append(date_from)
        if date_to:
            query += " AND Date <= %s"
            params.append(date_to)
        if level_filter:
            query += " AND LevelId = %s"
            params.append(level_filter)
        if search:
            query += " AND (LOWER(Message) LIKE %s OR LOWER(Class) LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY Date DESC"

        cursor = conn.cursor(as_dict=True)
        cursor.execute(query, params)
        logs = cursor.fetchall()
        for log in logs:
            log_date = log['Date']
            if isinstance(log_date, str):
                log['Date'] = datetime.strptime(log_date[:26], "%Y-%m-%d %H:%M:%S.%f")
            log['LevelName'] = LoggingLevelType.get(log['LevelId'], 'Unknown')

        cursor.close()
        conn.close()

        # Pagination
        paginator = Paginator(logs, 10)  # Show 10 logs per page
        page_number = request.GET.get('page')
        try:
            logs_page = paginator.page(page_number)
        except PageNotAnInteger:
            logs_page = paginator.page(1)  # Default to page 1 if page is not an integer
        except EmptyPage:
            logs_page = paginator.page(paginator.num_pages)  # Show last page if page is out of range

        context['logs'] = logs_page  # Pass paginated logs to template

        # Souhrny a grafy (calculated on full logs, not paginated)
        level_counts = Counter([log['LevelName'] for log in logs])
        context['summary_levels'] = level_counts
        context['summary_classes'] = Counter([log['Class'] for log in logs]).most_common(10)
        dates = sorted({log['Date'].date() for log in logs})
        context['chart_dates'] = [d.strftime("%Y-%m-%d") for d in dates]

        def counts_per_day(level=None):
            return [
                sum(1 for log in logs if (level is None or log['LevelName'] == level) and log['Date'].date() == d)
                for d in dates
            ]

        context['chart_errors'] = counts_per_day('Error')
        context['chart_warnings'] = counts_per_day('Warning')
        context['chart_info'] = counts_per_day('Information')
        context['chart_debug'] = counts_per_day('Debug')
        context['chart_critical'] = counts_per_day('Critical')

        context['error_count'] = level_counts.get('Error', 0)
        context['warning_count'] = level_counts.get('Warning', 0)
        context['info_count'] = level_counts.get('Information', 0)
        context['debug_count'] = level_counts.get('Debug', 0)
        context['critical_count'] = level_counts.get('Critical', 0)

    except DatabaseSettingsError as e:
        context['error'] = f"Database connection failed: {str(e)}"
    except pymssql.Error as e:
        context['error'] = f"Database connection failed: {str(e)}"

    return render(request, "logs.html", context)
    # Pagination
    paginator = Paginator(logs, 10)  # Show 10 logs per page
    page_number = request.GET.get('page')
    try:
        logs_page = paginator.page(page_number)
    except PageNotAnInteger:
        logs_page = paginator.page(1)  # Default to page 1 if page is not an integer
    except EmptyPage:
        logs_page = paginator.page(paginator.num_pages)  # Show last page if page is out of range

    context['logs'] = logs_page  # Pass paginated logs to template

    # Souhrny a grafy (calculated on full logs, not paginated)
    level_counts = Counter([log['LevelName'] for log in logs])
    context['summary_levels'] = level_counts
    context['summary_classes'] = Counter([log['Class'] for log in logs]).most_common(10)
    dates = sorted({log['Date'].date() for log in logs})
    context['chart_dates'] = [d.strftime("%Y-%m-%d") for d in dates]

    def counts_per_day(level=None):
        return [
            sum(1 for log in logs if (level is None or log['LevelName'] == level) and log['Date'].date() == d)
            for d in dates
        ]

    context['chart_errors'] = counts_per_day('Error')
    context['chart_warnings'] = counts_per_day('Warning')
    context['chart_info'] = counts_per_day('Information')
    context['chart_debug'] = counts_per_day('Debug')
    context['chart_critical'] = counts_per_day('Critical')

    context['error_count'] = level_counts.get('Error', 0)
    context['warning_count'] = level_counts.get('Warning', 0)
    context['info_count'] = level_counts.get('Information', 0)
    context['debug_count'] = level_counts.get('Debug', 0)
    context['critical_count'] = level_counts.get('Critical', 0)

    return render(request, "logs.html", context)

def parse_log_line(line):
    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', line)
    timestamp_str = timestamp_match.group(1) if timestamp_match else None

    level = "INFO"
    if "ERROR" in line or "Exception" in line:
        level = "ERROR"
    elif "WARN" in line:
        level = "WARN"
    elif "DEBUG" in line:
        level = "DEBUG"

    return {
        'timestamp_str': timestamp_str,
        'level': level,
        'content': line
    }

def render_log_row(entry):
    border_class = "border-info"
    text_class = "text-info"
    if entry['level'] == "ERROR":
        border_class = "border-danger";
        text_class = "text-danger"
    elif entry['level'] == "WARN":
        border_class = "border-warning";
        text_class = "text-warning"

    formatted_content = escape(entry['content'])

    formatted_content = re.sub(
        r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
        r'<span class="time-badge" style="background:#f1f5f9;border:1px solid #e2e8f0;padding:0 4px;border-radius:4px;color:#64748b;margin-right:8px;font-size:0.85em">\1</span>',
        formatted_content
    )

    def json_repl(match):
        try:
            raw_json = match.group(0).replace('&quot;', '"').replace('&#x27;', "'")
            parsed = json.loads(raw_json)
            pretty = json.dumps(parsed, indent=2)
            return f'<div class="json-block" style="background:#f8fafc;border-left:3px solid #0dcaf0;padding:8px;margin:8px 0;white-space:pre;font-size:0.85em;color:#1e293b;border-radius:0 4px 4px 0;">{escape(pretty)}</div>'
        except:
            return match.group(0)

    formatted_content = re.sub(r'(\{.*?\})', json_repl, formatted_content, flags=re.DOTALL)

    return f"""
    <tr class="log-row {border_class}" style="border-left: 4px solid;">
        <td style="width: 100px; vertical-align: top;" class="ps-3 py-2">
            <span class="badge {text_class} bg-light border fw-bold">{entry['level']}</span>
        </td>
        <td class="py-2 pe-3">
            <div class="log-content" style="font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-all;">{formatted_content}</div>
        </td>
    </tr>
    """

def process_log_entry(buffer, logs, stats, time_from, time_to, search_query):
    combined_line = "".join(buffer)
    parsed = parse_log_line(combined_line)

    show_row = True
    if parsed['timestamp_str']:
        try:
            time_part = parsed['timestamp_str'].split(' ')[1]
            if time_from and time_part < (time_from + ":00"): show_row = False
            if time_to and time_part > (time_to + ":59"): show_row = False
        except:
            pass

    if search_query and search_query not in combined_line.lower():
        show_row = False

    if show_row:
        if parsed['level'] in stats:
            stats[parsed['level']] += 1
        logs.append(render_log_row(parsed))

@login_required
def log_viewer_view(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.now().strftime('%Y-%m-%d')
    selected_date = request.GET.get('date', today)
    time_from = request.GET.get('time_from', '')
    time_to = request.GET.get('time_to', '')
    search_query = request.GET.get('search', '').lower()

    log_path = get_log_file_path(instance, selected_date)
    logs = deque(maxlen=3000)
    stats = {"ERROR": 0, "WARN": 0}

    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                buffer = []
                for line in f:
                    if re.search(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}', line):
                        if buffer:
                            process_log_entry(buffer, logs, stats, time_from, time_to, search_query)
                        buffer = [line]
                    else:
                        buffer.append(line)

                if buffer:
                    process_log_entry(buffer, logs, stats, time_from, time_to, search_query)
        except Exception as e:
            logs.append(f"<tr><td colspan='2'>Error: {str(e)}</td></tr>")

    return render(request, 'file_log_viewer.html', {
        'logs': list(logs),
        'stats': stats,
        'selected_date': selected_date,
        'time_from': time_from,
        'time_to': time_to,
        'search_query': search_query,
        'instance': instance
    })

def render_log_row(entry):
    border_class = "border-info"
    text_class = "text-info"
    if entry['level'] == "ERROR":
        border_class = "border-danger";
        text_class = "text-danger"
    elif entry['level'] == "WARN":
        border_class = "border-warning";
        text_class = "text-warning"
    elif entry['level'] == "DEBUG":
        border_class = "border-secondary";
        text_class = "text-muted"

    formatted_content = escape(entry['content'])

    # Highlight time
    formatted_content = re.sub(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
                               r'<span class="time-badge" style="background:#f1f5f9;border:1px solid #e2e8f0;padding:0 4px;border-radius:4px;color:#64748b;margin-right:8px;font-size:0.85em">\1</span>',
                               formatted_content)

    # Format JSON if present
    if "{" in formatted_content and "}" in formatted_content:
        def json_repl(match):
            try:
                raw_json = match.group(0).replace('&quot;', '"')
                parsed = json.loads(raw_json)
                pretty = json.dumps(parsed, indent=2)
                return f'<div class="json-block" style="background:#f8fafc;border-left:3px solid #cbd5e1;padding:5px;margin:5px 0;white-space:pre;font-size:0.8em;color:#334155">{escape(pretty)}</div>'
            except:
                return match.group(0)

        formatted_content = re.sub(r'(\{.*?\})', json_repl, formatted_content)

    return f"""
    <tr class="log-row {border_class}" style="border-left: 4px solid;">
        <td style="width: 100px; vertical-align: top;" class="ps-3 py-2">
            <span class="badge {text_class} bg-light border fw-bold">{entry['level']}</span>
        </td>
        <td class="py-2 pe-3">
            <div class="log-content" style="font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-all;">{formatted_content}</div>
        </td>
    </tr>
    """

def get_log_file_path(instance, date_str):
    base_path = f"/opt/heappe-deployment/{instance}/app/logs/API/"
    date_formatted = date_str.replace("-", "_")

    if not os.path.exists(base_path):
        return None

    files = sorted([f for f in os.listdir(base_path) if f.startswith(date_formatted) and f.endswith(".log")])

    if files:
        return os.path.join(base_path, files[-1])
    return None

def parse_log_line(line):
    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', line)
    timestamp_str = timestamp_match.group(1) if timestamp_match else None

    level = "INFO"
    if "ERROR" in line or "Exception" in line:
        level = "ERROR"
    elif "WARN" in line:
        level = "WARN"
    elif "DEBUG" in line:
        level = "DEBUG"

    return {
        'timestamp_str': timestamp_str,
        'level': level,
        'content': line
    }

@login_required
def stream_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.now().strftime('%Y-%m-%d')
    log_path = get_log_file_path(instance, today)

    def event_stream():
        if not log_path or not os.path.exists(log_path):
            yield "data: <tr><td colspan='2'>Log file not found.</td></tr>\n\n"
            return

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, os.SEEK_END)

            while True:
                line = f.readline()
                if line:
                    parsed = parse_log_line(line)
                    html_row = render_log_row(parsed)
                    clean_html = html_row.replace('\n', '')
                    yield f"data: {clean_html}\n\n"
                else:
                    time.sleep(0.5)

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response

@login_required
def fetch_new_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.now().strftime('%Y-%m-%d')
    log_path = get_log_file_path(instance, today)

    try:
        offset = int(request.GET.get('offset', 0))
    except ValueError:
        offset = 0

    if not log_path or not os.path.exists(log_path):
        return JsonResponse({'html': '', 'offset': offset})

    new_rows = []
    file_size = os.path.getsize(log_path)

    if offset == -1:
        return JsonResponse({'html': '', 'offset': file_size})

    if offset > file_size:
        offset = 0

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        f.seek(offset)
        for line in f:
            if line.strip():
                parsed = parse_log_line(line)
                new_rows.append(render_log_row(parsed))

        new_offset = f.tell()

    return JsonResponse({
        'html': "".join(new_rows),
        'offset': new_offset
    })

@login_required
def stream_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    log_base_path = f"/opt/heappe-deployment/{instance}/app/logs/API/"

    def event_stream():
        today_prefix = datetime.now().strftime('%Y_%m_%d')
        latest_file = None

        while True:
            files = sorted([f for f in os.listdir(log_base_path) if f.startswith(today_prefix) and f.endswith(".log")])

            if not files:
                time.sleep(1)
                continue

            current_target = files[-1]
            file_path = os.path.join(log_base_path, current_target)

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)

                while True:
                    line = f.readline()
                    if not line:
                        check_files = sorted([f for f in os.listdir(log_base_path) if f.startswith(today_prefix)])
                        if check_files and check_files[-1] != current_target:
                            break

                        time.sleep(0.5)
                        continue

                    entry = process_log_entry(line, current_target, {'colors': True, 'meta': True, 'json': True})

                    html = f'<tr class="log-row {entry["border_class"]}"><td class="ps-4 py-3"><span class="badge {entry["text_class"]}">LIVE</span></td><td class="py-3 pe-4">{entry["content"]}</td></tr>'

                    clean_html = html.replace('\n', '')

                    yield f"data: {clean_html}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response

