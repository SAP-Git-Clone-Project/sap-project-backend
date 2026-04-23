import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.db.models.signals import post_save
from audit_log.signals import log_doc_activity

from audit_log.models import AuditLogModel
from audit_log.signals import log_login
from documents.models import DocumentModel

User = get_user_model()

IP = "203.0.113.42"
FAKE_IP_PATCH = "audit_log.signals.get_current_ip"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email="user@example.com", is_staff=False, is_superuser=False):
    username = email.split("@")[0]
    if is_superuser:
        return User.objects.create_superuser(
            username=username,
            email=email,
            password="Str0ng!Pass123",
            first_name=username.capitalize(),
            last_name="Test",
        )
    return User.objects.create_user(
        username=username,
        email=email,
        password="Str0ng!Pass123",
        first_name=username.capitalize(),
        last_name="Test",
        is_staff=is_staff,
    )


def make_document(title, created_by):
    """Create a document while suppressing the post_save audit signal."""
    post_save.disconnect(log_doc_activity, sender=DocumentModel)
    try:
        doc = DocumentModel.objects.create(title=title, created_by=created_by)
    finally:
        post_save.connect(log_doc_activity, sender=DocumentModel)
    return doc


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class AuditLogHardenedTests(TestCase):
    """
    Covers basic logic, security hardening, and database integrity.
    """

    def setUp(self):
        self.client = APIClient()
        self.staff = make_user("admin@example.com", is_staff=True)
        self.regular = make_user("regular@example.com")
        self.url = reverse("auditlog-list")

    # -------------------------------------------------------------------------
    # Immutability — the API must be strictly read-only
    # -------------------------------------------------------------------------

    def test_api_is_strictly_read_only(self):
        """DELETE and PATCH on a log record must return 405, not modify the row."""
        log = AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        self.client.force_authenticate(user=self.staff)
        detail_url = reverse("auditlog-detail", args=[str(log.id)])

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

    def test_post_to_list_is_not_allowed(self):
        """POST to the list endpoint must also be rejected."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(self.url, {"action_type": "FAKE"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # -------------------------------------------------------------------------
    # UUID crash guard — bad query params must never cause a 500
    # -------------------------------------------------------------------------

    def test_malformed_uuid_params_do_not_500(self):
        """Garbage user_id values should return 200 (empty) or 400, never 500."""
        self.client.force_authenticate(user=self.staff)
        payloads = ["' OR 1=1--", "not-a-uuid", "00000000-0000-0000-0000-000000000000"]

        for payload in payloads:
            response = self.client.get(self.url, {"user_id": payload})
            self.assertIn(
                response.status_code,
                [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST],
                msg=f"Unexpected status for payload: {payload!r}",
            )

    # -------------------------------------------------------------------------
    # Ghost log — audit rows must survive user deletion
    # -------------------------------------------------------------------------

    def test_logs_persist_after_user_deletion(self):
        """Deleting a user must SET_NULL on related log rows, not delete them."""
        user_to_delete = make_user("temp@example.com")
        AuditLogModel.objects.create(
            user=user_to_delete, action_type="SENSITIVE_ACCESS"
        )

        user_to_delete.delete()
        log = AuditLogModel.objects.filter(action_type="SENSITIVE_ACCESS").first()

        self.assertIsNotNone(log)
        self.assertIsNone(log.user)

    # -------------------------------------------------------------------------
    # IP spoof guard — get_current_ip result is stored, not X-Forwarded-For
    # -------------------------------------------------------------------------

    @patch(FAKE_IP_PATCH, return_value="127.0.0.1")
    def test_ignore_spoofed_x_forwarded_for(self, mock_ip):
        """The stored IP must come from get_current_ip, not X-Forwarded-For."""
        factory = RequestFactory()
        request = factory.get("/", HTTP_X_FORWARDED_FOR="8.8.8.8")
        log_login(sender=User, user=self.regular, request=request)

        log = AuditLogModel.objects.filter(user=self.regular).latest("timestamp")
        self.assertEqual(log.ip_address, "127.0.0.1")

    # -------------------------------------------------------------------------
    # Filtering — action_type / user_id / document_id params narrow results
    # -------------------------------------------------------------------------

    def test_filter_by_action_type(self):
        """?action=LOGIN must return only LOGIN records."""
        AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        AuditLogModel.objects.create(action_type="LOGOUT", user=self.regular)

        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url, {"action": "LOGIN"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data.get("results", response.data)
        action_types = {row["action_type"] for row in data}
        self.assertEqual(action_types, {"LOGIN"})

    def test_filter_by_multiple_action_types(self):
        """?action=LOGIN&action=DOC_VIEW must return both, excluding others."""
        AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        AuditLogModel.objects.create(action_type="DOC_VIEW", user=self.regular)
        AuditLogModel.objects.create(action_type="DELETE", user=self.regular)

        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url + "?action=LOGIN&action=DOC_VIEW")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data.get("results", response.data)
        action_types = {row["action_type"] for row in data}
        self.assertIn("LOGIN", action_types)
        self.assertIn("DOC_VIEW", action_types)
        self.assertNotIn("DELETE", action_types)

    def test_filter_by_user_id(self):
        """?user_id=<uuid> must return only logs for that user."""
        other = make_user("other@example.com")
        AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        AuditLogModel.objects.create(action_type="LOGIN", user=other)

        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url, {"user_id": str(self.regular.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data.get("results", response.data)
        user_ids = {str(row["user"]) for row in data}
        self.assertEqual(user_ids, {str(self.regular.id)})

    def test_filter_by_document_id(self):
        doc = make_document("Sensitive Doc", self.regular)
        AuditLogModel.objects.create(document=doc, action_type="DOC_VIEW")
        AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)

        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url, {"document_id": str(doc.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data.get("results", response.data)
        self.assertEqual(len(data), 1, "Filter failed: returned more than 1 record.")
        self.assertEqual(data[0]["action_type"], "DOC_VIEW")

    # -------------------------------------------------------------------------
    # Access control
    # -------------------------------------------------------------------------

    def test_unauthenticated_request_is_rejected(self):
        """No credentials → 401."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_user_is_forbidden(self):
        """Authenticated but non-staff → 403."""
        self.client.force_authenticate(user=self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_user_can_list_logs(self):
        """Staff users must receive 200 on the list endpoint."""
        AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_staff_user_can_retrieve_single_log(self):
        """Staff users must be able to retrieve a single log entry."""
        log = AuditLogModel.objects.create(action_type="LOGIN", user=self.regular)
        self.client.force_authenticate(user=self.staff)
        detail_url = reverse("auditlog-detail", args=[str(log.id)])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["action_type"], "LOGIN")

    def test_superuser_can_list_logs(self):
        """Superusers must also be able to access the audit log."""
        superuser = make_user("super@example.com", is_superuser=True)
        self.client.force_authenticate(user=superuser)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -------------------------------------------------------------------------
    # Pagination
    # -------------------------------------------------------------------------

    def test_response_is_paginated(self):
        """List response must include pagination envelope keys."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertIn("count", response.data)

    # -------------------------------------------------------------------------
    # Ordering — newest records come first
    # -------------------------------------------------------------------------

    def test_results_are_ordered_newest_first(self):
        """Log entries must be returned in descending timestamp order."""
        first = AuditLogModel.objects.create(action_type="FIRST", user=self.regular)
        second = AuditLogModel.objects.create(action_type="SECOND", user=self.regular)

        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url)
        data = response.data.get("results", response.data)

        action_types = [row["action_type"] for row in data]
        self.assertGreater(
            action_types.index("FIRST"),
            action_types.index("SECOND"),
            "SECOND (newer) should appear before FIRST (older).",
        )