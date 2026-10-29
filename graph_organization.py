"""Presentation metadata for the knowledge graph. Does not edit notes or saved history."""
import re
from pathlib import PurePosixPath


def short(text, limit=48):
    text = re.sub(r'\[\[([^]|]+)(?:\|([^]]+))?\]\]', lambda m: m[2] or m[1], str(text))
    text = re.sub(r'[*`#]', '', text)
    text = ' '.join(text.split()).strip()
    text = re.split(r'(?<=[.!?])\s+', text, maxsplit=1)[0]
    return text if len(text) <= limit else text[:limit-1].rsplit(' ', 1)[0] + '…'


def fields(body):
    match = re.match(r'\A---\s*\n(.*?)\n---(?:\n|$)', body, re.S)
    if not match:
        return {}
    return {m[1].lower(): m[2].strip().strip('"\'') for m in
            re.finditer(r'^([\w-]+):[ \t]*(.*)$', match[1], re.M)}


def organize(nodes, links, sessions=()):
    """Keep node IDs/content intact; derive neighborhoods only from explicit evidence."""
    by_id = {n['id']: n for n in nodes}
    names = {'root': 'Jarvis Assistant', 'vault': 'Knowledge Library',
             'tools': 'Tools', 'recent': 'Conversations', 'memory': 'Saved memories'}
    for node in nodes:
        node['original_label'] = node['label']
        node['label'] = names.get(node['id'], node['label'])
        node.update(parents=[], project_ids=[], role=node['kind'].lower())
        path = PurePosixPath(node.get('source') or '')
        if node['kind'] == 'Note' and len(path.parts) == 2 and path.parts[0].casefold() == 'projects':
            node['role'] = 'project'
            if path.stem.casefold() == 'jarvis':
                node['label'] = 'Jarvis Project'
        elif node.get('source', '').casefold() == 'home.md':
            node['label'] = 'Library Home'
        meta = fields(node.get('body', ''))
        if node.get('source', '').startswith('Reports/'):
            report = re.split(r'^## Report\s*$', node.get('body', ''), maxsplit=1, flags=re.M)
            topic = short(report[-1].strip().split('\n\n')[0] if len(report) > 1 else node['label'])
            stamp = ' '.join(filter(None, [meta.get('date', ''), meta.get('time', '')]))
            node.update(label=f'{topic} · {stamp}' if stamp else topic, role='report', display_label=topic, date_label=stamp)
        elif node.get('source', '').startswith('Journal/'):
            node['role'] = 'journal'
        elif node['kind'] == 'Conversation' and node['id'] != 'recent':
            stamp = str(node.get('timestamp') or '').replace('T', ' ')[:16]
            topic = re.sub(r'^\[TASK FINISHED\]\s*', 'Task finished: ', node['label'])
            prefix = stamp or 'Conversation ' + node['id'].removeprefix('recent-')
            node['display_label'] = short(topic, 42)
            node['date_label'] = prefix
            node['label'] = node['display_label'] + ' · ' + prefix

    labels = {'collection': 'Contains', 'note-link': 'References',
              'project-root': 'Project', 'project-member': 'Part of project',
              'project-report': 'Produced report'}
    for link in links:
        link.setdefault('kind', 'collection')
        link['label'] = labels.get(link['kind'], 'Related')
        if link['kind'] == 'collection' and link['target'] in by_id:
            by_id[link['target']]['parents'].append(link['source'])

    projects = [n for n in nodes if n['role'] == 'project']
    aliases = {}
    for project in projects:
        for alias in [project['original_label'], PurePosixPath(project['source']).stem]:
            aliases[alias.casefold()] = project['id']
        project['parents'].insert(0, 'root')
        links.append({'source': 'root', 'target': project['id'], 'kind': 'project-root', 'label': 'Project'})
    project_ids = {n['id'] for n in projects}
    # A reference is a reference, not a claim of ownership. Both directions help navigation.
    for link in list(links):
        if link['kind'] != 'note-link':
            continue
        for owner, child in [(link['source'], link['target']), (link['target'], link['source'])]:
            node = by_id.get(child)
            if owner in project_ids and node and child not in project_ids and node.get('source', '').casefold() != 'home.md':
                node['project_ids'].append(owner)

    session_projects = {str(s.get('name', '')).casefold(): aliases.get(str(s.get('project', '')).casefold())
                        for s in sessions if isinstance(s, dict)}
    for node in nodes:
        if node['kind'] == 'Note' and node['id'] not in project_ids:
            meta = fields(node.get('body', ''))
            owner = aliases.get(meta.get('project', '').casefold())
            evidence = 'Project field in note'
            if not owner:
                path = PurePosixPath(node.get('source') or '')
                if len(path.parts) > 2 and path.parts[0].casefold() == 'projects':
                    owner = aliases.get(path.parts[1].casefold())
                    evidence = 'Project folder'
            if not owner and node['role'] == 'report':
                agent = meta.get('agent', '')
                if agent.casefold().startswith('agent session '):
                    owner = session_projects.get(agent[14:].casefold())
                    evidence = 'Report agent field matched to saved project session: ' + agent[14:]
            if owner:
                node['project_ids'].append(owner)
                kind = 'project-report' if node['role'] == 'report' else 'project-member'
                links.append({'source': owner, 'target': node['id'], 'kind': kind,
                              'label': labels[kind], 'evidence': evidence})
        node['project_ids'] = sorted(set(node['project_ids']))
        node['parents'] = list(dict.fromkeys(node['project_ids'] + node['parents']))
        node['overview'] = node['id'] == 'root' or 'root' in node['parents']
        node['cluster'] = (node['id'] if node['role'] == 'project' else node['project_ids'][0]
                           if len(node['project_ids']) == 1 else 'Shared knowledge'
                           if node['project_ids'] else node['group'])
    children = {n['id']: set() for n in nodes}
    for node in nodes:
        for parent in node['parents']:
            if parent in children and parent != node['id']:
                children[parent].add(node['id'])
    for node in nodes:
        node['child_count'] = len(children[node['id']])
        node['hub'] = bool(node['child_count']) and node['id'] != 'root'
