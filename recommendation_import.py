"""Bounded, explicit Hugging Face pulls. No network calls on validation/Start.

Only structured generation config and named, tested model-card formats produce
values. Unsupported prose is retained as a short review note, never interpreted
by an LLM or executed as code.
"""
import copy
import datetime
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = 'hf-settings-v2'
MAX_BYTES = 1_000_000
REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,159}')
REVISION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
SHA = re.compile(r'[a-f0-9]{40}')
FILES = ('generation_config.json', 'README.md')


def repository_name(value):
    if not isinstance(value, str):
        raise ValueError('Enter the authoritative publisher repository, such as Qwen/Qwen3.8-27B.')
    value = value.strip()
    if value.startswith('https://huggingface.co/'):
        u = urllib.parse.urlsplit(value)
        if u.query or u.fragment or u.username or u.password:
            raise ValueError('Use a publisher repository without query parameters or credentials.')
        value = u.path.strip('/')
    if not REPOSITORY.fullmatch(value):
        raise ValueError('Use a Hugging Face publisher/model repository, not an arbitrary URL or file path.')
    return value


def _safe_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or u.netloc != 'huggingface.co' or u.username or u.password or u.fragment:
        raise ValueError('Recommendation downloads must stay on https://huggingface.co.')


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    _safe_url(url)
    # No environment proxy, credentials, cookies, or local-file handlers.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirect())
    deadline = time.monotonic() + 15
    try:
        with opener.open(urllib.request.Request(url, headers={'Accept': 'application/json, text/plain', 'User-Agent': 'Hourglass-settings-import/1'}), timeout=15) as response:
            chunks, size = [], 0
            while size <= MAX_BYTES:
                if time.monotonic() >= deadline:
                    raise ValueError('Publisher download exceeded the time limit.')
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b''.join(chunks)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ValueError('Publisher download failed (HTTP ' + str(exc.code) + '). Saved settings were not changed.') from None
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError('Could not download publisher settings. Retry Pull when connected; saved settings are unchanged.') from exc
    if len(raw) > MAX_BYTES:
        raise ValueError('Publisher settings file exceeds the import size limit.')
    return raw


def _json(raw):
    try:
        result = json.loads(raw, parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('Publisher returned invalid JSON.') from None
    if not isinstance(result, dict):
        raise ValueError('Publisher configuration must be a JSON object.')
    return result


def parse(repository, lane, files):
    """Pure extraction. All files are bytes and are already pinned to one revision."""
    import inference_profiles as profiles
    repository = repository_name(repository)
    if lane not in profiles.catalog()['lanes']:
        raise ValueError('Choose a lane before pulling recommendations.')
    candidates, evidence, notes = {}, [], []

    def add(key, value, filename, excerpt):
        if key not in profiles.FIELDS:
            return
        profiles._check_values({key: value})
        candidate = {'value': value, 'source': filename}
        if candidate not in candidates.setdefault(key, []):
            candidates[key].append(candidate)
        if excerpt and excerpt not in evidence:
            evidence.append(excerpt[:1000])

    config_raw = files.get('generation_config.json')
    if config_raw is not None:
        config = _json(config_raw)
        if config.get('do_sample') is False:
            raise ValueError('Publisher configuration requests greedy decoding (do_sample=false). This importer cannot map that mode; review and create a manual profile.')
        else:
            for key, value in config.items():
                if key in profiles.FIELDS:
                    add(key, value, 'generation_config.json', key + '=' + json.dumps(value))
        if 'max_new_tokens' in config:
            notes.append('Publisher max_new_tokens: ' + str(config['max_new_tokens'])[:80] + '. Review the separate output-budget choice.')
    card_raw = files.get('README.md')
    card = ''
    if card_raw is not None:
        try:
            card = card_raw.decode('utf-8')
        except UnicodeError:
            raise ValueError('Publisher model card is not UTF-8 text.') from None
    kind = profiles.family(repository)
    card_supported = False
    if kind == 'qwen38':
        if lane not in ('thinking', 'non-thinking'):
            raise ValueError('Select Thinking or Non-thinking for Qwen3.8.')
        # Restrict numeric extraction to the named recommendation section and
        # its exact lane bullet, never unrelated example code earlier in the card.
        section = re.search(r'^## Best Practices\s*\n(.*?)(?=^## |\Z)', card, re.M | re.S)
        if section:
            label = 'Thinking Mode' if lane == 'thinking' else r'Instruct \(or non-thinking\) mode'
            lines = re.findall(r'^\s*[-*] ' + label + r': ([^\n]+)$', section.group(1), re.M)
            if len(lines) == 1:
                pairs = re.findall(r'`([a-z_]+)=(-?\d+(?:\.\d+)?)`', lines[0])
                if set(k for k, _ in pairs) == set(profiles.SAMPLING) and len(pairs) == len(profiles.SAMPLING):
                    for key, number in pairs:
                        add(key, int(number) if key == 'top_k' else float(number), 'README.md', lines[0])
                    card_supported = True
        if card_supported:
            # This adapter is for the publisher's specific 3.8 template contract.
            if '`enable_thinking`' in card or re.search(r'"enable_thinking"\s*:\s*(?:True|False|true|false)', card):
                add('enable_thinking', lane == 'thinking', 'README.md', 'Qwen3.8 lane uses enable_thinking.')
            if 'retains thinking blocks from all historical messages' in card or '`preserve_thinking` is enabled by default' in card:
                add('preserve_thinking', True, 'README.md', 'Publisher enables preserved thinking by default.')
            if lane == 'thinking' and re.search(r'(?:xhigh by default|`xhigh` \(default\))', card):
                add('reasoning_effort', 'xhigh', 'README.md', 'Publisher default reasoning effort: xhigh.')
            notes.append('Review output capacity separately. The Qwen3.8 card discusses separate reasoning/final budgets; this chat API mapping sends one combined limit or deliberately omits it.')
    elif kind == 'deepseek4':
        if lane == 'standard':
            raise ValueError('Select a DeepSeek thinking lane before pulling.')
        line = re.search(r'For local deployment, we recommend setting the sampling parameters to `([^`]+)`', card)
        if line:
            pairs = re.findall(r'(temperature|top_p)\s*=\s*(\d+(?:\.\d+)?)', line.group(1))
            if len(pairs) == 2 and {k for k, _ in pairs} == {'temperature', 'top_p'}:
                for key, value in pairs:
                    add(key, float(value), 'README.md', line.group(0))
                card_supported = True
        # The mode is an explicit owner choice. Do not claim a publisher default.
        notes.append('Select thinking mode and effort explicitly. Think Max needs at least 384K context.')
    if not card_supported:
        notes.append('This model-card format is not supported automatically. Review the publisher card and enter any missing or ambiguous controls manually.')
    # A recognized mode-specific model card overrides generic generation defaults.
    # Retain every candidate for audit; genuinely conflicting equal-priority values still block.
    selected = {key: ([o for o in options if o['source']=='README.md'] or options)
                if card_supported else options for key, options in candidates.items()}
    conflicts = {key: options for key, options in selected.items() if len({json.dumps(o['value'], sort_keys=True) for o in options}) > 1}
    values = {key: options[0]['value'] for key, options in selected.items() if key not in conflicts}
    return {'candidates': candidates, 'suggested': values, 'conflicts': conflicts,
            'evidence': evidence, 'notes': notes, 'card_supported': card_supported}


def pull(repository, revision, lane=None, fetcher=fetch):
    """Download once; omit lane to review all modes before choosing a profile.

    Explicit-lane callers retain the original single-source response format.
    Each proposal is independently valid as saved provenance.
    """
    import inference_profiles as profiles
    repository = repository_name(repository)
    if lane and (not isinstance(lane, str) or lane not in profiles.catalog()['lanes']):
        raise ValueError('Unknown thinking mode.')
    revision = revision or 'main'
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError('Use a revision name, tag or commit without path characters.')
    metadata = fetcher('https://huggingface.co/api/models/' + repository + '/revision/' + revision)
    if metadata is None:
        raise ValueError('Publisher repository or revision was not found.')
    commit = _json(metadata).get('sha')
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise ValueError('Publisher did not supply a pinned source revision.')
    files = {name: fetcher('https://huggingface.co/' + repository + '/resolve/' + commit + '/' + name) for name in FILES}
    if all(raw is None for raw in files.values()):
        raise ValueError('No supported publisher settings files were found.')
    source = {'repository': repository, 'revision': commit, 'requested_revision': revision,
              'importer_version': VERSION,
              'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'files': [{'name': name, 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items() if raw is not None]}
    kind = profiles.family(repository)
    lanes = ([lane] if lane else ['thinking', 'non-thinking'] if kind == 'qwen38'
             else ['thinking', 'non-thinking', 'think-max'] if kind == 'deepseek4'
             else list(profiles.catalog()['lanes']))
    proposals = {}
    for mode in lanes:
        proposal = {**source, 'lane': mode, **parse(repository, mode, files)}
        validate_source(proposal)
        proposals[mode] = proposal
    if lane:
        return copy.deepcopy(proposals[lane])
    return copy.deepcopy({**source, 'proposals': proposals})


def validate_source(source):
    import inference_profiles as profiles
    if not isinstance(source, dict) or source.get('importer_version') not in ('hf-settings-v1', VERSION):
        raise ValueError('Unsupported recommendation source version; use an explicit Pull/Refresh.')
    if repository_name(source.get('repository')) != source['repository']:
        raise ValueError('Source repository must use publisher/model notation.')
    if not isinstance(source.get('revision'), str) or not SHA.fullmatch(source['revision']):
        raise ValueError('Recommendation source must have a pinned revision.')
    if source.get('lane') not in profiles.catalog()['lanes']:
        raise ValueError('Invalid source lane.')
    if not isinstance(source.get('files'), list) or not 1 <= len(source['files']) <= 2:
        raise ValueError('Record the source file hashes.')
    for file in source['files']:
        if not isinstance(file, dict) or file.get('name') not in FILES or not re.fullmatch(r'[a-f0-9]{64}', str(file.get('sha256', ''))):
            raise ValueError('Invalid source file hash.')
    candidates = source.get('candidates')
    if not isinstance(candidates, dict) or set(candidates) - set(profiles.FIELDS):
        raise ValueError('Invalid recommendation candidates.')
    for key, options in candidates.items():
        if not isinstance(options, list) or not 1 <= len(options) <= 4:
            raise ValueError('Invalid recommendation candidates.')
        for option in options:
            if not isinstance(option, dict) or option.get('source') not in FILES:
                raise ValueError('Invalid recommendation attribution.')
            profiles._check_values({key: option.get('value')})
    if len(json.dumps(source)) > 24000:
        raise ValueError('Saved recommendation evidence is too large.')
