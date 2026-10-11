# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Original offline public-event contracts and two bounded, read-only tools.

Coordinates are integer WGS84 microdegrees, times are Unix milliseconds.
Hashes bind supplied bytes/records; they do not establish truth or rights.
SourcePolicy and Scope must come from the trusted application, never a model.
No network, MCP transport, approval, publication or credential access occurs.
"""
from dataclasses import dataclass
import hashlib
import json
from typing import ClassVar
from urllib.parse import urlsplit

from .canonical import canonical_bytes
from .modelos import Evidence, Scope, _exact_fields, _hash, _identifier

FORMAT = "radar-public-events-v1"
MAX_SNAPSHOT_BYTES = 12 * 1024
MAX_RECORDS = 100
MAX_SNAPSHOTS = 16
MAX_TIME_MS = 253402300799999


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {name}")


def _url(value):
    if type(value) is not str or len(value.encode("utf-8")) > 2048:
        raise ValueError("invalid source_url")
    if any(ord(char) <= 32 for char in value):
        raise ValueError("invalid source_url")
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == "https" and parts.hostname and
                 not parts.username and not parts.password and
                 not parts.query and not parts.fragment)
        parts.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("source_url requires HTTPS without credentials, query or fragment")


def _age(timestamp, now_ms, max_age_ms):
    if timestamp is None:
        return "unknown"
    if timestamp > now_ms:
        return "future"
    return "fresh" if now_ms - timestamp <= max_age_ms else "stale"


@dataclass(frozen=True, slots=True)
class PublicEvent:
    event_id: str
    kind: str
    observed_at_ms: int | None
    latitude_e6: int
    longitude_e6: int
    summary: str

    FIELDS: ClassVar[frozenset[str]] = frozenset({
        "event_id", "kind", "observed_at_ms", "latitude_e6", "longitude_e6", "summary",
    })

    def __post_init__(self):
        _identifier(self.event_id, "event_id")
        _identifier(self.kind, "kind")
        if self.observed_at_ms is not None:
            _int(self.observed_at_ms, "observed_at_ms", 1, MAX_TIME_MS)
        _int(self.latitude_e6, "latitude_e6", -90_000_000, 90_000_000)
        _int(self.longitude_e6, "longitude_e6", -180_000_000, 180_000_000)
        if type(self.summary) is not str or not self.summary.strip():
            raise ValueError("summary must be nonempty text")
        if len(self.summary.encode("utf-8")) > 1024:
            raise ValueError("summary exceeds 1 KiB UTF-8")

    @classmethod
    def from_dict(cls, value):
        _exact_fields(value, cls.FIELDS, "PublicEvent")
        return cls(**value)

    def to_dict(self):
        return {key: getattr(self, key) for key in sorted(self.FIELDS)}


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    tenant_id: str
    project_id: str
    snapshot_id: str
    revision: int
    source_id: str
    source_url: str
    license_ref: str
    source_sha256: str
    retrieved_at_ms: int
    coverage: str
    records: tuple[PublicEvent, ...]

    FIELDS: ClassVar[frozenset[str]] = frozenset({
        "tenant_id", "project_id", "snapshot_id", "revision", "source_id",
        "source_url", "license_ref", "source_sha256", "retrieved_at_ms", "coverage", "records",
    })

    def __post_init__(self):
        for name in ("tenant_id", "project_id", "snapshot_id", "source_id", "license_ref"):
            _identifier(getattr(self, name), name)
        _int(self.revision, "revision", 1, 2**31 - 1)
        _int(self.retrieved_at_ms, "retrieved_at_ms", 1, MAX_TIME_MS)
        _url(self.source_url)
        _hash(self.source_sha256, "source_sha256")
        if self.coverage not in ("complete", "partial", "unknown"):
            raise ValueError("invalid coverage")
        if type(self.records) is not tuple or len(self.records) > MAX_RECORDS:
            raise ValueError("records requires a bounded immutable tuple")
        ids = set()
        for row in self.records:
            if type(row) is not PublicEvent:
                raise TypeError("records must contain PublicEvent")
            if row.event_id in ids:
                raise ValueError("duplicate event ID in snapshot")
            ids.add(row.event_id)
            if row.observed_at_ms is not None and row.observed_at_ms > self.retrieved_at_ms:
                raise ValueError("observation cannot follow retrieval")
        if len(canonical_bytes(self.to_dict())) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot exceeds 12 KiB")

    @classmethod
    def from_dict(cls, value):
        _exact_fields(value, cls.FIELDS, "EventSnapshot")
        if type(value["records"]) is not list:
            raise TypeError("serialized records must be a list")
        if len(value["records"]) > MAX_RECORDS:
            raise ValueError("too many records")
        return cls(**{**value, "records": tuple(PublicEvent.from_dict(row) for row in value["records"])})

    def to_dict(self):
        return {key: [row.to_dict() for row in self.records] if key == "records"
                else getattr(self, key) for key in sorted(self.FIELDS)}

    @property
    def snapshot_sha256(self):
        return hashlib.sha256(canonical_bytes(self.to_dict())).hexdigest()

    def to_evidence(self):
        """Bridge into the existing journal; pending, identity unverified.

        Human/app review and original artifact verification remain external.
        The document binding is snapshot_id/revision in the trusted Scope.
        """
        text = canonical_bytes(self.to_dict()).decode("utf-8")
        return Evidence(self.tenant_id, self.project_id, self.snapshot_id,
                        self.revision, 1, 0, len(text), text, self.source_sha256,
                        hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "pending", "", False)


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    source_id: str
    source_url: str
    license_ref: str
    commercial_allowed: bool = False

    def __post_init__(self):
        _identifier(self.source_id, "source_id")
        _identifier(self.license_ref, "license_ref")
        _url(self.source_url)
        if type(self.commercial_allowed) is not bool:
            raise TypeError("commercial_allowed must be bool")


class PublicEventCatalog:
    """Server-configured allowlist over immutable offline snapshots.

    Exactly two tools; arguments cannot set scope, source URL, freshness policy,
    licensing, file path, review status or credentials. Not an MCP server.
    """
    TOOLS = ("events.query", "events.get")

    def __init__(self, *, scope, sources, snapshots, commercial=False, max_age_ms=300_000):
        if type(scope) is not Scope:
            raise TypeError("scope must be Scope")
        if type(commercial) is not bool:
            raise TypeError("commercial must be bool")
        _int(max_age_ms, "max_age_ms", 1, 86_400_000)
        if type(sources) is not tuple or not 1 <= len(sources) <= MAX_SNAPSHOTS:
            raise ValueError("sources requires a bounded tuple")
        if any(type(source) is not SourcePolicy for source in sources):
            raise TypeError("sources must contain SourcePolicy")
        allowed = {source.source_id: source for source in sources}
        if len(allowed) != len(sources):
            raise ValueError("duplicate source policy")
        if type(snapshots) is not tuple or len(snapshots) > MAX_SNAPSHOTS:
            raise ValueError("snapshots requires a bounded tuple")
        ids = set()
        for snapshot in snapshots:
            if type(snapshot) is not EventSnapshot:
                raise TypeError("snapshots must contain EventSnapshot")
            if (snapshot.tenant_id, snapshot.project_id) != (scope.tenant_id, scope.project_id):
                raise ValueError("snapshot outside trusted scope")
            if scope.current_revisions.get(snapshot.snapshot_id) != snapshot.revision:
                raise ValueError("snapshot revision not current")
            if snapshot.snapshot_id in ids:
                raise ValueError("duplicate snapshot ID")
            ids.add(snapshot.snapshot_id)
            policy = allowed.get(snapshot.source_id)
            if policy is None or (snapshot.source_url, snapshot.license_ref) != (policy.source_url, policy.license_ref):
                raise ValueError("source not allowed")
            if commercial and not policy.commercial_allowed:
                raise ValueError("source not approved for commercial use")
        self._snapshots = snapshots
        self._max_age_ms = max_age_ms

    def _metadata(self, snapshot, now_ms):
        return {"snapshot_id": snapshot.snapshot_id, "revision": snapshot.revision,
                "source_id": snapshot.source_id, "source_url": snapshot.source_url,
                "license_ref": snapshot.license_ref, "source_sha256": snapshot.source_sha256,
                "snapshot_sha256": snapshot.snapshot_sha256,
                "retrieved_at_ms": snapshot.retrieved_at_ms, "coverage": snapshot.coverage,
                "collection_freshness": _age(snapshot.retrieved_at_ms, now_ms, self._max_age_ms)}

    def _row(self, snapshot, row, now_ms):
        return {**row.to_dict(), **self._metadata(snapshot, now_ms),
                "observation_freshness": _age(row.observed_at_ms, now_ms, self._max_age_ms)}

    def call(self, name, arguments, *, now_ms):
        """now_ms is supplied by the application, never by tool arguments."""
        _int(now_ms, "now_ms", 1, MAX_TIME_MS)
        if name == "events.get":
            _exact_fields(arguments, frozenset({"snapshot_id", "event_id"}), "events.get")
            for key in arguments:
                _identifier(arguments[key], key)
            for snapshot in self._snapshots:
                if snapshot.snapshot_id == arguments["snapshot_id"]:
                    for row in snapshot.records:
                        if row.event_id == arguments["event_id"]:
                            return {"format": FORMAT, "record": self._row(snapshot, row, now_ms),
                                    "absence_supported": False}
            return {"format": FORMAT, "record": None, "absence_supported": False}
        if name != "events.query":
            raise ValueError("unknown read-only tool")
        _exact_fields(arguments, frozenset({"bbox_e6", "start_ms", "end_ms", "limit"}), "events.query")
        bbox = arguments["bbox_e6"]
        if type(bbox) is not list or len(bbox) != 4:
            raise ValueError("bbox_e6 requires four integers")
        west, south, east, north = bbox
        for value in (west, east):
            _int(value, "longitude bound", -180_000_000, 180_000_000)
        for value in (south, north):
            _int(value, "latitude bound", -90_000_000, 90_000_000)
        if west > east or south > north:
            raise ValueError("bbox must be ordered; split antimeridian queries")
        start, end, limit = (arguments[key] for key in ("start_ms", "end_ms", "limit"))
        _int(start, "start_ms", 1, MAX_TIME_MS)
        _int(end, "end_ms", start, MAX_TIME_MS)
        _int(limit, "limit", 1, 20)
        matches = []
        unknown = 0
        for snapshot in self._snapshots:
            for row in snapshot.records:
                if not (west <= row.longitude_e6 <= east and south <= row.latitude_e6 <= north):
                    continue
                if row.observed_at_ms is None:
                    unknown += 1
                elif start <= row.observed_at_ms <= end:
                    matches.append((snapshot, row))
        matches.sort(key=lambda pair: (pair[1].observed_at_ms, pair[0].snapshot_id, pair[1].event_id))
        return {"format": FORMAT,
                "records": [self._row(snapshot, row, now_ms) for snapshot, row in matches[:limit]],
                "matched_records": len(matches), "truncated": len(matches) > limit,
                "unknown_time_records_in_area": unknown,
                "sources": [self._metadata(snapshot, now_ms) for snapshot in self._snapshots],
                "absence_supported": False}
