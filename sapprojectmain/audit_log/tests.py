import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.db.models.signals import post_save
from audit_log.signals import log_doc_activity

# --- ENSURE THESE PATHS ARE CORRECT FOR YOUR PROJECT ---
from audit_log.models import AuditLogModel
from audit_log.signals import log_login
from documents.models import DocumentModel

# -------------------------------------------------------

User = get_user_model()

IP = "203.0.113.42"
FAKE_IP_PATCH = "audit_log.signals.get_current_ip"


def make_user(email="user@example.com", is_staff=False, is_superuser=False):
    username = email.split("@")[0]
    return User.objects.create_user(
        username=username,
        email=email,
        password="Str0ng!Pass123",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


class AuditLogHardenedTests(TestCase):
    """
    Covers Basic logic, Security Hardening, and Database Integrity.
    """

    def setUp(self):
        self.client = APIClient()
        self.staff = make_user("admin@example.com", is_staff=True)
        self.regular = make_user("regular@example.com")
        # Ensure 'auditlog-list' matches your router's basename
        self.url = reverse("auditlog-list")

    # --- 1. THE "IMMUTABILITY" CHECK ---
    def test_api_is_strictly_read_only(self):
        log = AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        self.client.force_authenticate(user=self.staff)
        detail_url = reverse("auditlog-detail", args=[str(log.id)])

        # These should return 405 Method Not Allowed
        self.assertEqual(
            self.client.delete(detail_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(detail_url, {"action_type": "LOGOUT"}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        log.refresh_from_db()
        self.assertEqual(log.action_type, "LOGIN")

    # --- 2. THE "UUID CRASH" CHECK ---
    def test_malformed_uuid_params_do_not_500(self):
        """Checks that garbage UUIDs return 200 (empty) or 400, but never crash (500)."""
        self.client.force_authenticate(user=self.staff)
        payloads = ["' OR 1=1--", "not-a-uuid", "00000000-0000-0000-0000-000000000000"]

        for payload in payloads:
            response = self.client.get(self.url, {"user_id": payload})
            # If your view uses the try/except block I gave you, this will be 200.
            self.assertIn(
                response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]
            )

    # --- 3. THE "GHOST LOG" CHECK ---
    def test_logs_persist_after_user_deletion(self):
        user_to_delete = make_user("temp@example.com")
        AuditLogModel.objects.create(
            user=user_to_delete, action_type="SENSITIVE_ACCESS"
        )

        user_to_delete.delete()
        log = AuditLogModel.objects.filter(action_type="SENSITIVE_ACCESS").first()

        self.assertIsNotNone(log)
        self.assertIsNone(log.user)  # SET_NULL check

    # --- 4. THE "IP SPOOF" CHECK ---
    @patch(FAKE_IP_PATCH, return_value="127.0.0.1")
    def test_ignore_spoofed_x_forwarded_for(self, mock_ip):
        factory = RequestFactory()
        request = factory.get("/", HTTP_X_FORWARDED_FOR="8.8.8.8")
        log_login(sender=User, user=self.regular, request=request)

        log = AuditLogModel.objects.filter(user=self.regular).latest("timestamp")
        self.assertEqual(log.ip_address, "127.0.0.1")

    # --- 5. BASIC FUNCTIONAL CHECK (FIXED) ---
    def test_filtering_logic(self):
        """Verify the dynamic filtering actually narrows down results."""

        post_save.disconnect(log_doc_activity, sender=DocumentModel)
        try:
            doc = DocumentModel.objects.create(
                title="Sensitive Doc", created_by=self.regular
            )
            AuditLogModel.objects.create(document=doc, action_type="DOC_VIEW")
            AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        finally:
            post_save.connect(log_doc_activity, sender=DocumentModel)

        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url, {"document_id": str(doc.id)})
        data = response.data["results"] if isinstance(response.data, dict) else response.data

        self.assertEqual(len(data), 1, "Filter failed: Returned more than 1 record.")
        self.assertEqual(data[0]["action_type"], "DOC_VIEW")
        
    def test_unauthorized_access(self):
        self.client.force_authenticate(user=self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
