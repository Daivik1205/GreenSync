# tomtom_poller.py — Phase B: TomTom Traffic Flow API baseline
#
# Polls TomTom Traffic Flow API every POLL_INTERVAL seconds for real-world
# speed and density per road segment over the Bengaluru bounding box.
# Results are stored in a shared dict consumed by HybridDigitalTwin.
#
# API docs: https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
# Endpoint: GET /traffic/services/4/flowSegmentData/relative0/{zoom}/json
#           ?point={lat},{lon}&key={API_KEY}&unit=KMPH
#
# The "relative0" style returns freeFlowSpeed and currentSpeed — we compute
# congestion ratio = currentSpeed / freeFlowSpeed as the normalised edge weight.

import os
import time
import threading
import logging
import requests

logger = logging.getLogger(__name__)

POLL_INTERVAL   = 60        # seconds between refreshes
TOMTOM_BASE_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json"
ZOOM            = 10        # tile zoom level for segment granularity

# Bengaluru corridor sample points (lat, lon) — one per major corridor segment.
# Expand this list for denser coverage.
BENGALURU_SAMPLE_POINTS: list[tuple[float, float]] = [
    (13.1007, 77.5963),   # Yelahanka
    (13.0629, 77.5870),   # Hebbal flyover
    (12.9716, 77.5946),   # Mehkri Circle
    (12.9762, 77.5929),   # Sadashivanagar
    (12.9698, 77.5948),   # Palace Road
    (12.9591, 77.5761),   # Rajajinagar
    (12.9141, 77.5990),   # Jayanagar
    (12.9698, 77.7499),   # Whitefield
    (12.9352, 77.6245),   # Koramangala
    (12.9784, 77.6408),   # Indiranagar
    (12.8952, 77.5765),   # Bannerghatta Road
    (12.9121, 77.5590),   # Mysore Road (inner)
    (12.8628, 77.5152),   # Mysore Road (outer)
]


class TomTomPoller:
    """
    Background thread that refreshes TomTom flow data for Bengaluru corridors.

    Exposes:
        segment_speeds: dict[str, SegmentFlow]   keyed by "{lat},{lon}"
        last_poll_at:   float (unix timestamp)
    """

    def __init__(self, api_key: str | None = None):
        self.api_key       = api_key or os.environ.get("TOMTOM_API_KEY", "")
        self.segment_speeds: dict[str, "SegmentFlow"] = {}
        self.last_poll_at: float = 0.0
        self._lock         = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event   = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the background polling thread."""
        if not self.api_key:
            logger.warning("TOMTOM_API_KEY not set — TomTom poller running in MOCK mode")
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TomTomPoller")
        self._thread.start()
        logger.info("TomTom poller started (interval=%ds, points=%d)", POLL_INTERVAL, len(BENGALURU_SAMPLE_POINTS))

    def stop(self):
        self._stop_event.set()

    def get_flow(self, point_key: str) -> "SegmentFlow | None":
        with self._lock:
            return self.segment_speeds.get(point_key)

    def get_all_flows(self) -> dict[str, "SegmentFlow"]:
        with self._lock:
            return dict(self.segment_speeds)

    def get_congestion_ratio(self, point_key: str) -> float:
        """Returns currentSpeed / freeFlowSpeed in [0, 1]. 1.0 = free-flow, 0.0 = standstill."""
        flow = self.get_flow(point_key)
        if flow is None or flow.free_flow_speed <= 0:
            return 1.0
        return min(flow.current_speed / flow.free_flow_speed, 1.0)

    # ── Background loop ───────────────────────────────────────────────────────

    def _poll_loop(self):
        while not self._stop_event.is_set():
            self._fetch_all()
            self._stop_event.wait(timeout=POLL_INTERVAL)

    def _fetch_all(self):
        results: dict[str, "SegmentFlow"] = {}
        for lat, lon in BENGALURU_SAMPLE_POINTS:
            key  = f"{lat},{lon}"
            flow = self._fetch_point(lat, lon)
            if flow:
                results[key] = flow

        with self._lock:
            self.segment_speeds.update(results)
            self.last_poll_at = time.time()

        logger.info("TomTom refresh: %d/%d points retrieved", len(results), len(BENGALURU_SAMPLE_POINTS))

    def _fetch_point(self, lat: float, lon: float) -> "SegmentFlow | None":
        if not self.api_key:
            return _mock_flow(lat, lon)

        try:
            resp = requests.get(
                TOMTOM_BASE_URL,
                params={
                    "point": f"{lat},{lon}",
                    "key":   self.api_key,
                    "unit":  "KMPH",
                    "zoom":  ZOOM,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("flowSegmentData", {})
            return SegmentFlow(
                lat=lat,
                lon=lon,
                current_speed=float(data.get("currentSpeed", 0)),
                free_flow_speed=float(data.get("freeFlowSpeed", 1)),
                confidence=float(data.get("confidence", 0)),
                road_closure=bool(data.get("roadClosure", False)),
            )
        except requests.RequestException as exc:
            logger.warning("TomTom fetch failed for (%s,%s): %s", lat, lon, exc)
            return None


class SegmentFlow:
    __slots__ = ("lat", "lon", "current_speed", "free_flow_speed", "confidence", "road_closure")

    def __init__(self, lat, lon, current_speed, free_flow_speed, confidence, road_closure):
        self.lat            = lat
        self.lon            = lon
        self.current_speed  = current_speed
        self.free_flow_speed = free_flow_speed
        self.confidence     = confidence
        self.road_closure   = road_closure

    @property
    def congestion_ratio(self) -> float:
        if self.free_flow_speed <= 0:
            return 1.0
        return min(self.current_speed / self.free_flow_speed, 1.0)

    def __repr__(self):
        return (f"SegmentFlow({self.lat},{self.lon} "
                f"cur={self.current_speed:.1f} free={self.free_flow_speed:.1f} "
                f"ratio={self.congestion_ratio:.2f})")


def _mock_flow(lat: float, lon: float) -> SegmentFlow:
    """Deterministic mock for offline development — uses lat parity as seed."""
    import math
    pseudo = abs(math.sin(lat * 17.3 + lon * 13.7))
    current = 20 + pseudo * 40     # 20–60 km/h
    free    = 60.0
    return SegmentFlow(lat=lat, lon=lon,
                       current_speed=current, free_flow_speed=free,
                       confidence=0.8, road_closure=False)
