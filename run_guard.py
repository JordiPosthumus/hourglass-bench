"""Worker lifecycle receipts and controller-loss cancellation; no model settings."""
import json
import os
from pathlib import Path
import signal
import threading
import time


def write_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False) + '\n')
    temporary.replace(path)


class WorkerGuard:
    def __init__(self, root, prefix='HOURGLASS'):
        self.root = Path(root).resolve()
        self.env = os.environ
        self.prefix = prefix
        self.stop = threading.Event()
        self.parent_lost = False
        self.receipt = None
        self.previous = None
        self.thread = None

    def __enter__(self):
        token = self.env.get(self.prefix + '_QUESTION_TOKEN')
        if not token:
            return self
        jid = self.env[self.prefix + '_EVALUATION_ID']
        if not token.isalnum() or not jid.isalnum():
            raise ValueError('Invalid worker lifecycle identity.')
        self.parent = int(self.env[self.prefix + '_CONTROLLER_PID'])
        self.started_mono = float(self.env[self.prefix + '_QUESTION_STARTED_MONOTONIC'])
        self.receipt = self.root/'logs'/f'worker-{jid}-{token}.json'
        self.base = {'version':'worker-lifecycle-v1', 'evaluation_id':jid,
                     'token':token, 'task':self.env[self.prefix + '_QUESTION_TASK'],
                     'controller_pid':self.parent, 'worker_pid':os.getpid(),
                     'started_at':float(self.env[self.prefix + '_QUESTION_STARTED_AT'])}
        write_receipt(self.receipt, {**self.base, 'phase':'running'})
        self.previous = signal.getsignal(signal.SIGTERM)
        try:
            signal.signal(signal.SIGTERM, self._terminate)
            self.thread = threading.Thread(target=self._watch_parent, daemon=True)
            self.thread.start()
        except BaseException as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise
        return self

    def _terminate(self, *_):
        raise SystemExit(130)

    def _watch_parent(self):
        while not self.stop.wait(.25):
            if os.getppid() != self.parent:
                self.parent_lost = True
                # Only the benchmark worker's own isolated group is eligible.
                if os.getpgrp() == os.getpid():
                    os.killpg(os.getpid(), signal.SIGTERM)
                else:
                    os.kill(os.getpid(), signal.SIGTERM)
                return

    def __exit__(self, kind, error, traceback):
        if self.receipt is None:
            return False
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        self.stop.set()
        if self.thread and self.thread.ident is not None:
            self.thread.join()
        code = error.code if isinstance(error, SystemExit) else 1 if error else 0
        phase = 'stopped' if code in (130,143) or self.parent_lost else 'completed' if code in (0,None) else 'error'
        try:
            write_receipt(self.receipt, {**self.base, 'phase':phase,
                                        'ended_at':time.time(),
                                        'elapsed_s':max(0,time.monotonic()-self.started_mono),
                                        'controller_lost':self.parent_lost})
        finally:
            signal.signal(signal.SIGTERM, self.previous)
        return False
