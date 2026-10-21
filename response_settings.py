"""User-controlled delivery preferences; truthfulness is never adjustable."""
import json
from pathlib import Path
from filelock import FileLock

STORE = Path(__file__).resolve().parent / 'data' / 'response-settings.json'
DEFAULT = {'humor':25, 'directness':75, 'detail':'brief', 'tone':'classic',
           'pushback':'balanced', 'address':'occasionally'}
CHOICES = {'detail':('brief','balanced','detailed'), 'tone':('classic','friendly','professional'),
           'pushback':('gentle','balanced','firm'), 'address':('never','occasionally','often')}


def validate(changes):
    if not isinstance(changes,dict) or any(key not in DEFAULT for key in changes):
        raise ValueError('Choose humor, directness, detail, tone, pushback or address.')
    for key,value in changes.items():
        if key in ('humor','directness'):
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(key.capitalize()+' must be an integer from 0 to 100.')
        elif value not in CHOICES[key]:
            raise ValueError('Invalid '+key+' option.')
    return changes


def read():
    try:
        return dict(DEFAULT,**validate(json.loads(STORE.read_text(encoding='utf-8'))))
    except FileNotFoundError:
        return dict(DEFAULT)


def update(changes):
    validate(changes)
    STORE.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(STORE)+'.lock',timeout=10):
        result=dict(read(),**changes)
        temp=STORE.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2),encoding='utf-8');temp.replace(STORE)
    return result


def prompt(settings):
    validate(settings)
    humor=settings['humor']; direct=settings['directness']
    jokes=('No jokes, sarcasm, teasing or chuckles.' if humor==0 else
           'Rare, understated wit.' if humor<=30 else 'Occasional dry humor when it fits.' if humor<=65 else
           'Frequent playful dry wit when the situation permits; never force a joke into every reply.')
    candor=('Be tactful and soften phrasing without concealing the answer.' if direct<=30 else
            'Be clear and considerate, with little cushioning.' if direct<=70 else
            'Be candid and blunt about mistakes and limitations, without insults or hostility.')
    detail={'brief':'Give concise explanations; expand when asked or needed for a meaningful decision.',
            'balanced':'Give the answer and a short useful explanation.',
            'detailed':'For substantive questions, give thorough explanations and useful examples; keep speech organized.'}[settings['detail']]
    tone={'classic':'Calm, composed JARVIS delivery with a British flavor.',
          'friendly':'Warm, conversational and approachable.',
          'professional':'Neutral, precise and businesslike.'}[settings['tone']]
    pushback={'gentle':'Disagree tactfully and explain the concern.', 'balanced':'State disagreements plainly and give the reason.',
              'firm':'Challenge weak assumptions directly and explain a better option.'}[settings['pushback']]
    address={'never':'Do not address the user as sir.', 'occasionally':'Use sir occasionally in natural conversation.',
             'often':'Use sir regularly when natural, but not in every sentence.'}[settings['address']]
    return ('\n\nResponse preferences (apply to delivery, not factual accuracy or permissions):\n'
        'Truthfulness is always required: never invent facts, sources, certainty, tool results or completed work. '
        'Acknowledge uncertainty and distinguish evidence from inference. Never agree merely to flatter.\n'
        f'Humor {humor}/100: {jokes}\nDirectness {direct}/100: {candor}\n{detail}\n{tone}\n{pushback}\n{address}\n'
        'The current explicit request overrides stylistic preferences. Keep simple action confirmations short, '
        'with no forced humor or honorific. Serious, sensitive or distressing situations take priority over humor. '
        'These preferences never authorize actions or change approval requirements. Do not mention the settings unless asked.')
