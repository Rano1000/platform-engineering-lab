"""Application-owned Prometheus metrics."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "golden_path_http_requests_total",
    "HTTP requests processed by the reference API.",
    ("method", "path", "status"),
)
REQUEST_DURATION = Histogram(
    "golden_path_http_request_duration_seconds",
    "Reference API request duration in seconds.",
    ("method", "path"),
)
