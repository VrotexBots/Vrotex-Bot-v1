import time
import threading
from collections import defaultdict


class Metrics:

    def __init__(self):
        self._lock = threading.Lock()

        self._counters = defaultdict(int)
        self._gauges = {}
        self._timings = defaultdict(list)

        self._started_at = time.time()

    def increment(self, name, value=1):
        with self._lock:
            self._counters[name] += value

    def set_gauge(self, name, value):
        with self._lock:
            self._gauges[name] = value

    def record_timing(self, name, duration):
        with self._lock:
            self._timings[name].append(float(duration))

            # Retain only the most recent 500 measurements.
            self._timings[name] = self._timings[name][-500:]

    def timer(self, name):
        return MetricTimer(self, name)

    def get_counter(self, name):
        with self._lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name):
        with self._lock:
            return self._gauges.get(name)

    def get_average_timing(self, name):
        with self._lock:
            values = self._timings.get(name, [])

            if not values:
                return 0.0

            return sum(values) / len(values)

    def snapshot(self):
        with self._lock:
            return {
                "uptime_seconds": round(
                    time.time() - self._started_at, 2
                ),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timings": {
                    name: {
                        "count": len(values),
                        "average": (
                            sum(values) / len(values)
                            if values else 0
                        ),
                    }
                    for name, values in self._timings.items()
                },
            }


class MetricTimer:

    def __init__(self, metrics, name):
        self.metrics = metrics
        self.name = name
        self.start_time = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        duration = time.perf_counter() - self.start_time

        self.metrics.record_timing(
            self.name,
            duration
        )


metrics = Metrics()
