import threading

# Create a thread-local storage for saving client IP per request thread
_thread_locals = threading.local()


class AuditIPMiddleware:
    # Stores client IP per request thread so it can be used in signals safely.

    # Setting up the middleware (connecting the chain)
    def __init__(self, get_response):
        self.get_response = get_response

    # Captures the cleints IP and stores in thread local storage
    def __call__(self, request):

        # NOTE: Saves the raw client IP from the request headers
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

        # NOTE: If the header is present it takes the first IP (the user's IP), if the header is empty falls back to the remote address
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")

        # NOTE: Stores the client IP in the request object (for views) and in thread local storage (for signals)
        request.client_ip = ip
        _thread_locals.request_ip = ip

        response = self.get_response(request)

        # NOTE: Clean up (emptying it for the next request) the thread local storage after the response is processed to prevent memory leaks and ensure that IPs from different requests do not interfere with each other
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
