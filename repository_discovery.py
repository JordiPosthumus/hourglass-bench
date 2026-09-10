"""Stable insertion of repository discovery cases into the existing bank order."""
from collections import deque

SECTION = 'repository_discovery'
DOMAINS = ('games', 'hourglass', 'dsg')
ORDER_POLICY = 'existing_cycle_with_repository_discovery_every_ninth_v1'


def weave(base_order, cases):
    queues = {domain: deque(sorted(t['id'] for t in cases if t.get('discovery_domain') == domain))
              for domain in DOMAINS}
    pending = deque()
    while any(queues.values()):
        for domain in DOMAINS:
            if queues[domain]:
                pending.append(queues[domain].popleft())
    pending.extend(sorted(t['id'] for t in cases if t.get('discovery_domain') not in DOMAINS))
    output = []
    for index, tid in enumerate(base_order, 1):
        output.append(tid)
        if index % 8 == 0 and pending:
            output.append(pending.popleft())
    output.extend(pending)
    return output
