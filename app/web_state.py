"""Bounded, expiring, browser-owned data for the public web service."""
from collections import OrderedDict, deque
import secrets
import threading
import time


class BrowserStore:
    def __init__(self, *, ttl=1800, max_entries=128, max_bytes=64 * 1024 * 1024,
                 per_kind=4, clock=time.monotonic):
        self.ttl, self.max_entries, self.max_bytes = ttl, max_entries, max_bytes
        self.per_kind, self.clock = per_kind, clock
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    def _expire(self):
        now = self.clock()
        for key in [key for key, item in self.entries.items() if item[0] <= now]:
            del self.entries[key]

    def put(self, kind, owner, value, *, key=None, size=0):
        if size > self.max_bytes:
            raise ValueError("Çıktı sunucu sınırını aşıyor; daha kısa bir MIDI seç.")
        key = key or secrets.token_urlsafe(24)
        identity = kind, owner, key
        with self.lock:
            self._expire()
            self.entries.pop(identity, None)
            own = [k for k in self.entries if k[:2] == (kind, owner)]
            while len(own) >= self.per_kind:
                del self.entries[own.pop(0)]
            self.entries[identity] = (self.clock() + self.ttl, size, value)
            while (len(self.entries) > self.max_entries
                   or sum(item[1] for item in self.entries.values()) > self.max_bytes):
                self.entries.popitem(last=False)
        return key

    def get(self, kind, owner, key):
        with self.lock:
            self._expire()
            identity = kind, owner, key
            item = self.entries.get(identity)
            if item is None:
                return None
            self.entries.move_to_end(identity)
            self.entries[identity] = (self.clock() + self.ttl, item[1], item[2])
            return item[2]

    def values(self, kind, owner):
        with self.lock:
            self._expire()
            return [item[2] for key, item in self.entries.items() if key[:2] == (kind, owner)]


class RequestLimiter:
    def __init__(self, *, count=120, window=60, clock=time.monotonic):
        self.count, self.window, self.clock = count, window, clock
        self.clients = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, client):
        with self.lock:
            now = self.clock()
            queue = self.clients.setdefault(client, deque())
            self.clients.move_to_end(client)
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            allowed = len(queue) < self.count
            if allowed:
                queue.append(now)
            while len(self.clients) > 512:
                self.clients.popitem(last=False)
            return allowed
