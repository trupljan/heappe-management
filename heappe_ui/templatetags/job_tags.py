from django import template

register = template.Library()

@register.simple_tag
def job_state_badge(state):
    states = {
        1: ('Configuring', 'bg-secondary', 'text-white'),
        2: ('Submitted', 'bg-info', 'text-white'),
        4: ('Queued', 'bg-primary', 'text-white'),
        8: ('Running', 'bg-warning', 'text-dark'),
        16: ('Finished', 'bg-success', 'text-white'),
        32: ('Failed', 'bg-danger', 'text-white'),
        64: ('Canceled', 'bg-dark', 'text-white'),
        128: ('Waiting For Service Account', 'bg-secondary', 'text-white'),
        256: ('Deleted', 'bg-secondary', 'text-white'),
    }
    state_info = states.get(state, ('Unknown', 'bg-secondary', 'text-white'))
    return f'<span class="badge rounded-pill {state_info[1]} {state_info[2]}" aria-label="Job state: {state_info[0]}">{state_info[0]}</span>'