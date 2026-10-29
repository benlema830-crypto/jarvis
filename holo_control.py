"""Explicit local UI commands; displayed content cannot issue commands."""
import re


def dispatch(text, emit):
    text = str(text).strip().rstrip('.!?')
    model = re.fullmatch(r'(?:switch to|use|show) (?:the )?(holographic core|jarvis orbit|fracture sphere)(?: model)?',text,re.I)
    if model:
        emit('visual-model',model=model[1].lower().replace(' ','-'))
        return ''
    if re.fullmatch(r'(?:please )?(?:bring|pull) (?:that|this|it)(?: panel)? (?:closer|up)', text, re.I):
        emit('holo-panel', action='focus', query='')
        return ''
    if re.fullmatch(r'(?:please )?(?:put (?:that|this|it) away|dismiss (?:that|this)(?: panel)?|close (?:that|this) panel)', text, re.I):
        emit('holo-panel', action='dismiss', query='')
        return ''
    match = re.fullmatch(r'(?:show|expand|bring up) (?:the )?(?:panel|pane)(?: for)? (.{1,100})', text, re.I)
    if match:
        emit('holo-panel', action='focus', query=match[1])
        return ''
    if re.fullmatch(r'(?:show|bring up) (?:my )?tasks', text, re.I):
        emit('holo-panel', action='focus', query='Tasks')
        return ''
    match = re.fullmatch(r'(?:resume|continue(?: working on)?|pick up) (?:the )?(Jarvis|Rocket Frontier)(?: project)?', text, re.I)
    if match:
        import project_memory
        result=project_memory.resume(match[1])
        emit('project-resume', **result)
        return f"I've restored {result['project']}. The recorded next step is: {result['next_action']}"
    return None
