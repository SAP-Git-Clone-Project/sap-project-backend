import threading

_thread_locals = threading.local()


class AuditIPMiddleware:
    """
    Stores client IP per request thread so it can be used in signals safely.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")

        # store for both views + signals
        request.client_ip = ip
        _thread_locals.request_ip = ip

        response = self.get_response(request)

        # cleanup after request
        if hasattr(_thread_locals, "request_ip"):
            del _thread_locals.request_ip

        return response


def get_current_ip(request=None):
    """
    Works in:
    - Views (pass request)
    - Signals (no request)
    """

    # If request exists (views / APIs)
    if request is not None:
        return getattr(request, "client_ip", None) or "system"

    # If no request (signals)
    return getattr(_thread_locals, "request_ip", None) or "system"