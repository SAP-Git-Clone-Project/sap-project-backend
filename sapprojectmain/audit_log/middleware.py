import threading

# NOTE: Thread-local storage to safely isolate request data per execution thread
_thread_locals = threading.local()

def get_current_ip():
    # NOTE: Global helper to retrieve the stored IP for audit logging
    return getattr(_thread_locals, "request_ip", None)

class AuditIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # SECURITY: Prioritize X-Forwarded-For to capture true client IP behind proxies
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")

        # IMP: Temporarily store the IP address in the current thread's local storage
        _thread_locals.request_ip = ip

        response = self.get_response(request)

        # CLEAN: Remove thread-local data after response to prevent memory leaks
        if hasattr(_thread_locals, "request_ip"):
            del _thread_locals.request_ip

        return response

# IMP: Ensure this middleware is registered in settings.py to enable IP tracking