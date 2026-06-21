"""
NutriAI Document Service - Comprehensive Tests
"""

import uuid
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.models import Document

def test_health_endpoint(client):
    """Health check endpoint should return 200 and document service identification."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "document-service"


class TestDocumentsList:
    """Tests for the documents listing endpoint."""

    def test_documents_list_renders(self, authenticated_client):
        """Documents list endpoint should return 200 for authenticated users."""
        response = authenticated_client.get("/documents/list")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_documents_list_requires_auth(self, client):
        """Documents list endpoint should return 401 for unauthenticated users."""
        response = client.get("/documents/list")
        assert response.status_code == 401


class TestDocumentUpload:
    """Tests for document upload functionality."""

    @patch("app.routes.upload_document")
    @patch("app.routes.process_document_ocr")
    def test_upload_document_success(self, mock_ocr, mock_upload, authenticated_client, db_session, test_user):
        """Upload should succeed with valid PDF file."""
        mock_upload.return_value = {
            "blob_name": "test-uuid.pdf",
            "blob_url": "https://storage.blob.core.windows.net/test-uuid.pdf",
        }

        response = authenticated_client.post(
            "/documents/upload",
            files={"file": ("test_report.pdf", b"%PDF-1.4 test content", "application/pdf")},
            data={"document_type": "lab_report"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Document uploaded successfully."

    def test_upload_rejects_invalid_file_type(self, authenticated_client):
        """Upload should reject non-PDF/image files."""
        response = authenticated_client.post(
            "/documents/upload",
            files={"file": ("malware.exe", b"malicious content", "application/x-executable")},
            data={"document_type": "other"},
        )
        assert response.status_code == 400
        assert "error" in response.json()


class TestDocumentStatus:
    """Tests for document OCR status checking."""

    def test_document_status_endpoint(self, authenticated_client, db_session, test_user):
        """Status endpoint should return JSON with current OCR status."""
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id,
            user_id=test_user.id,
            document_type="lab_report",
            original_filename="test.pdf",
            blob_name="test-blob.pdf",
            blob_url="https://storage.blob.core.windows.net/test-blob.pdf",
            ocr_status="completed",
            ocr_content="Test OCR content",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()

        response = authenticated_client.get(f"/documents/{doc_id}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["ocr_status"] == "completed"

    def test_document_status_not_found(self, authenticated_client):
        """Status endpoint should return 404 for non-existent document."""
        fake_id = uuid.uuid4()
        response = authenticated_client.get(f"/documents/{fake_id}/status")
        assert response.status_code == 404


class TestDocumentDeletion:
    """Tests for document deletion."""

    @patch("app.routes.delete_document_blob")
    def test_delete_own_document(self, mock_delete, authenticated_client, db_session, test_user):
        """Users should be able to delete their own documents."""
        mock_delete.return_value = True

        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id,
            user_id=test_user.id,
            document_type="other",
            original_filename="to_delete.pdf",
            blob_name="delete-blob.pdf",
            blob_url="https://storage.blob.core.windows.net/delete-blob.pdf",
            ocr_status="pending",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()

        response = authenticated_client.delete(f"/documents/{doc_id}")
        assert response.status_code == 200

    def test_delete_nonexistent_document(self, authenticated_client):
        """Deleting a non-existent document should return 404."""
        fake_id = uuid.uuid4()
        response = authenticated_client.delete(f"/documents/{fake_id}")
        assert response.status_code == 404

    def test_delete_other_users_document(self, authenticated_client, db_session):
        """Users should not be able to delete other users' documents."""
        other_user_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id,
            user_id=other_user_id,
            document_type="other",
            original_filename="not_mine.pdf",
            blob_name="other-blob.pdf",
            blob_url="https://storage.blob.core.windows.net/other-blob.pdf",
            ocr_status="pending",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()

        response = authenticated_client.delete(f"/documents/{doc_id}")
        assert response.status_code in [403, 404]


class TestDocumentValidation:
    """Tests for AI and fallback document validation logic."""

    def test_fallback_validation_lab_report(self):
        from app.routes import fallback_validate_document
        res = fallback_validate_document(
            ocr_content="Patient blood test results showing cholesterol levels",
            filename="blood_test.pdf"
        )
        assert res["is_valid"] is True
        assert res["document_type"] == "lab_report"
        assert res["error_message"] == ""

    def test_fallback_validation_prescription(self):
        from app.routes import fallback_validate_document
        res = fallback_validate_document(
            ocr_content="Rx: take 1 tablet of Metformin 500mg daily",
            filename="prescription.png"
        )
        assert res["is_valid"] is True
        assert res["document_type"] == "prescription"
        assert res["error_message"] == ""

    def test_fallback_validation_invalid_document(self):
        from app.routes import fallback_validate_document
        res = fallback_validate_document(
            ocr_content="Walmart receipt total amount $23.50",
            filename="receipt.jpg"
        )
        assert res["is_valid"] is False
        assert res["document_type"] == "other"
        assert "Invalid document" in res["error_message"]
