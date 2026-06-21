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


class TestDocumentServiceLayer:
    """Direct tests for the core logic in app/services.py and routes validation."""

    @patch("app.routes.get_openai_client")
    def test_validate_document_with_ai_success(self, mock_get_client):
        from app.routes import validate_document_with_ai
        
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_choice = MagicMock()
        mock_choice.message.content = '{"is_valid": true, "document_type": "lab_report", "error_message": ""}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        # Enable mock openAI endpoint
        with patch("app.routes.settings.AZURE_OPENAI_KEY", "dummy-key"), \
             patch("app.routes.settings.AZURE_OPENAI_ENDPOINT", "https://dummy-endpoint"):
            res = validate_document_with_ai("Cholesterol: 200", "report.pdf")
            assert res["is_valid"] is True
            assert res["document_type"] == "lab_report"

    @patch("app.routes.get_openai_client")
    def test_validate_document_with_ai_exception(self, mock_get_client):
        from app.routes import validate_document_with_ai
        
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("OpenAI error")

        with patch("app.routes.settings.AZURE_OPENAI_KEY", "dummy-key"), \
             patch("app.routes.settings.AZURE_OPENAI_ENDPOINT", "https://dummy-endpoint"):
            # Should fallback to rule-based validation (which detects 'blood' as lab_report)
            res = validate_document_with_ai("Patient blood test results", "blood_report.pdf")
            assert res["is_valid"] is True
            assert res["document_type"] == "lab_report"

    @patch("app.routes.validate_document_with_ai")
    def test_process_document_ocr_mock_success(self, mock_validate, db_session, test_user):
        from app.routes import process_document_ocr
        mock_validate.return_value = {"is_valid": True, "document_type": "lab_report", "error_message": ""}
        
        doc = Document(
            id=uuid.uuid4(),
            user_id=test_user.id,
            document_type="other",
            original_filename="lab_report.pdf",
            blob_name="lab.pdf",
            blob_url="/mock-uploads/lab.pdf",
            ocr_status="pending"
        )
        db_session.add(doc)
        db_session.commit()

        # Set is_mock to True implicitly by having empty connection string
        with patch("app.routes.settings.AZURE_STORAGE_CONNECTION_STRING", ""):
            process_document_ocr(str(doc.id), doc.blob_name)
            
        db_session.refresh(doc)
        assert doc.ocr_status == "completed"
        assert doc.document_type == "lab_report"

    @patch("app.routes.validate_document_with_ai")
    def test_process_document_ocr_mock_failed(self, mock_validate, db_session, test_user):
        from app.routes import process_document_ocr
        mock_validate.return_value = {"is_valid": False, "document_type": "other", "error_message": "Invalid document"}
        
        doc = Document(
            id=uuid.uuid4(),
            user_id=test_user.id,
            document_type="other",
            original_filename="Walmart_receipt.pdf",
            blob_name="receipt.pdf",
            blob_url="/mock-uploads/receipt.pdf",
            ocr_status="pending"
        )
        db_session.add(doc)
        db_session.commit()

        with patch("app.routes.settings.AZURE_STORAGE_CONNECTION_STRING", ""):
            process_document_ocr(str(doc.id), doc.blob_name)
            
        db_session.refresh(doc)
        assert doc.ocr_status == "failed"
        assert doc.document_type == "other"

    @patch("app.routes.settings.AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
    @patch("app.routes.settings.AZURE_DOCUMENT_INTELLIGENCE_KEY", "dummy-key")
    @patch("azure.ai.formrecognizer.DocumentAnalysisClient")
    @patch("app.routes.validate_document_with_ai")
    @patch("app.services.get_blob_service_client")
    def test_process_document_ocr_live_success(self, mock_get_blob_client, mock_validate, mock_analysis_client_class, db_session, test_user):
        from app.routes import process_document_ocr
        mock_validate.return_value = {"is_valid": True, "document_type": "lab_report", "error_message": ""}
        
        doc = Document(
            id=uuid.uuid4(),
            user_id=test_user.id,
            document_type="other",
            original_filename="lab_results.pdf",
            blob_name="results.pdf",
            blob_url="https://test.blob/results.pdf",
            ocr_status="pending"
        )
        db_session.add(doc)
        db_session.commit()

        # Mock download blob stream
        mock_blob_client = MagicMock()
        mock_container_client = MagicMock()
        mock_service_client = MagicMock()
        
        mock_service_client.get_container_client.return_value = mock_container_client
        mock_container_client.get_blob_client.return_value = mock_blob_client
        mock_get_blob_client.return_value = mock_service_client
        
        mock_stream = MagicMock()
        mock_stream.readall.return_value = b"Some blood sugar results"
        mock_blob_client.download_blob.return_value = mock_stream

        # Mock document analyzer
        mock_analyzer = MagicMock()
        mock_analysis_client_class.return_value = mock_analyzer
        
        mock_poller = MagicMock()
        mock_result = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_analyzer.begin_analyze_document.return_value = mock_poller
        
        mock_line = MagicMock()
        mock_line.content = "Patient Health Metrics: blood sugar sugar sugar"
        mock_page = MagicMock()
        mock_page.lines = [mock_line]
        mock_result.pages = [mock_page]
        mock_result.tables = []

        process_document_ocr(str(doc.id), doc.blob_name)
        
        db_session.refresh(doc)
        assert doc.ocr_status == "completed"
        assert doc.document_type == "lab_report"

    def test_local_storage_operations(self):
        from app.services import upload_document, get_document_url, delete_document_blob
        
        with patch("app.services.settings.AZURE_STORAGE_CONNECTION_STRING", ""):
            # Test local mock mode upload
            res = upload_document(b"dummy content", "doc.pdf", "application/pdf")
            assert "blob_name" in res
            assert res["blob_url"].startswith("/mock-uploads/")

            # Test local mock mode URL
            url = get_document_url(res["blob_name"])
            assert url == f"/api/documents/mock-uploads/{res['blob_name']}"

            # Test local mock mode delete
            delete_res = delete_document_blob(res["blob_name"])
            assert delete_res is True

    @patch("app.services.settings.AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
    @patch("app.services.get_blob_service_client")
    @patch("app.services.generate_blob_sas")
    def test_live_storage_operations(self, mock_generate_sas, mock_get_blob_client):
        from app.services import upload_document, get_document_url, delete_document_blob
        
        mock_blob_client = MagicMock()
        mock_container_client = MagicMock()
        mock_service_client = MagicMock()
        
        mock_service_client.get_container_client.return_value = mock_container_client
        mock_container_client.get_blob_client.return_value = mock_blob_client
        mock_get_blob_client.return_value = mock_service_client
        
        # Test upload
        res = upload_document(b"content", "doc.pdf", "application/pdf")
        assert "blob_name" in res
        
        # Test sas url
        mock_service_client.account_name = "test"
        mock_service_client.credential.account_key = "key"
        mock_generate_sas.return_value = "token"
        url = get_document_url("results.pdf")
        assert "results.pdf?token" in url
        
        # Test delete
        delete_res = delete_document_blob("results.pdf")
        assert delete_res is True

    @patch("app.services.settings.AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
    @patch("app.services.get_blob_service_client")
    def test_live_storage_operations_exceptions(self, mock_get_blob_client):
        from app.services import upload_document, get_document_url, delete_document_blob
        from azure.core.exceptions import AzureError

        mock_blob_client = MagicMock()
        mock_container_client = MagicMock()
        mock_service_client = MagicMock()
        
        mock_service_client.get_container_client.return_value = mock_container_client
        mock_container_client.get_blob_client.return_value = mock_blob_client
        mock_get_blob_client.return_value = mock_service_client

        # 1. ContainerAlreadyExists handled
        mock_container_client.create_container.side_effect = AzureError("ContainerAlreadyExists")
        upload_document(b"content", "doc.pdf", "application/pdf") # should pass

        # 2. Other AzureError logged and passed
        mock_container_client.create_container.side_effect = AzureError("SomeOtherError")
        upload_document(b"content", "doc.pdf", "application/pdf") # should pass since it logs debug

        # 3. upload raises AzureError
        mock_blob_client.upload_blob.side_effect = AzureError("UploadFailed")
        with pytest.raises(AzureError):
            upload_document(b"content", "doc.pdf", "application/pdf")

        # 4. delete_blob raises AzureError
        mock_blob_client.delete_blob.side_effect = AzureError("DeleteFailed")
        with pytest.raises(AzureError):
            delete_document_blob("doc.pdf")

        # 5. get_document_url raises exception
        mock_service_client.account_name = "test"
        mock_service_client.credential.account_key = "key"
        with patch("app.services.generate_blob_sas", side_effect=ValueError("SAS Error")):
            with pytest.raises(ValueError):
                get_document_url("results.pdf")

    def test_local_storage_operations_exceptions(self):
        from app.services import upload_document, delete_document_blob
        
        with patch("app.services.settings.AZURE_STORAGE_CONNECTION_STRING", ""), \
             patch("builtins.open", side_effect=OSError("Write permission denied")), \
             patch("os.makedirs"):
            with pytest.raises(OSError):
                upload_document(b"content", "doc.pdf", "application/pdf")

        with patch("app.services.settings.AZURE_STORAGE_CONNECTION_STRING", ""), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove", side_effect=OSError("Delete permission denied")):
            # delete should log warning but not raise exception, returning True
            assert delete_document_blob("doc.pdf") is True

    def test_get_blob_service_client(self):
        from app.services import get_blob_service_client, settings
        with patch("app.services.BlobServiceClient.from_connection_string") as mock_from_conn:
            get_blob_service_client()
            mock_from_conn.assert_called_once_with(settings.AZURE_STORAGE_CONNECTION_STRING)

    def test_get_openai_client_exceptions(self):
        from app.routes import get_openai_client
        with patch("app.routes.settings.AZURE_OPENAI_KEY", "dummy-key"), \
             patch("app.routes.settings.AZURE_OPENAI_ENDPOINT", "https://dummy-endpoint"), \
             patch("openai.AzureOpenAI", side_effect=ImportError("No module named openai")):
            assert get_openai_client() is None


class TestRoutesAdditionalCoverage:
    """Extra router unit tests to cover missing exception and error paths."""

    def test_list_documents_invalid_user_id(self, authenticated_client):
        # Header value is not a valid UUID format
        response = authenticated_client.get("/documents/list", headers={"X-User-ID": "invalid-uuid"})
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user ID format"

    def test_upload_doc_invalid_user_id(self, authenticated_client):
        response = authenticated_client.post(
            "/documents/upload",
            headers={"X-User-ID": "invalid-uuid"},
            files={"file": ("test.pdf", b"pdf content", "application/pdf")},
            data={"document_type": "lab_report"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user ID format"

    def test_upload_doc_empty_file(self, authenticated_client):
        response = authenticated_client.post(
            "/documents/upload",
            files={"file": ("test.pdf", b"", "application/pdf")},
            data={"document_type": "lab_report"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "File is empty."

    def test_upload_doc_oversized_file(self, authenticated_client):
        large_content = b"a" * (10 * 1024 * 1024 + 1)
        response = authenticated_client.post(
            "/documents/upload",
            files={"file": ("test.pdf", large_content, "application/pdf")},
            data={"document_type": "lab_report"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "File size exceeds 10MB limit."

    @patch("app.routes.upload_document", side_effect=OSError("Upload service down"))
    def test_upload_doc_service_exception(self, mock_upload, authenticated_client):
        response = authenticated_client.post(
            "/documents/upload",
            files={"file": ("test.pdf", b"some pdf content", "application/pdf")},
            data={"document_type": "lab_report"},
        )
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to upload document."

    def test_document_status_invalid_ids(self, authenticated_client):
        # Invalid user id
        response = authenticated_client.get(
            "/documents/some-doc-uuid/status",
            headers={"X-User-ID": "invalid-uuid"}
        )
        assert response.status_code == 400
        assert "Invalid format" in response.json()["detail"]

        # Invalid document id
        response = authenticated_client.get(
            "/documents/invalid-uuid/status"
        )
        assert response.status_code == 400
        assert "Invalid format" in response.json()["detail"]

    def test_document_preview_endpoints(self, authenticated_client, db_session, test_user):
        doc_uuid = uuid.uuid4()
        # Invalid format
        response = authenticated_client.get(
            f"/documents/{doc_uuid}/preview",
            headers={"X-User-ID": "invalid-uuid"}
        )
        assert response.status_code == 400

        response = authenticated_client.get(
            "/documents/invalid-uuid/preview"
        )
        assert response.status_code == 400

        # Document not found
        response = authenticated_client.get(
            f"/documents/{doc_uuid}/preview"
        )
        assert response.status_code == 404

        # Document found but SAS fails
        doc = Document(
            id=doc_uuid,
            user_id=test_user.id,
            document_type="prescription",
            original_filename="pres.pdf",
            blob_name="pres.pdf",
            blob_url="/uploads/pres.pdf",
            ocr_status="completed"
        )
        db_session.add(doc)
        db_session.commit()

        with patch("app.routes.get_document_url", side_effect=ValueError("SAS Error")):
            response = authenticated_client.get(
                f"/documents/{doc_uuid}/preview"
            )
            assert response.status_code == 500

    def test_delete_document_invalid_ids_and_exceptions(self, authenticated_client, db_session, test_user):
        # Invalid UUIDs
        response = authenticated_client.delete(
            "/documents/invalid-uuid"
        )
        assert response.status_code == 400

        # Delete database error during commit
        doc_uuid = uuid.uuid4()
        doc = Document(
            id=doc_uuid,
            user_id=test_user.id,
            document_type="prescription",
            original_filename="pres.pdf",
            blob_name="pres.pdf",
            blob_url="/uploads/pres.pdf",
            ocr_status="completed"
        )
        db_session.add(doc)
        db_session.commit()

        from sqlalchemy.exc import SQLAlchemyError
        with patch("app.routes.delete_document_blob"), \
             patch("sqlalchemy.orm.session.Session.commit", side_effect=SQLAlchemyError("DB delete failed")):
            response = authenticated_client.delete(
                f"/documents/{doc_uuid}"
            )
            assert response.status_code == 500
            assert response.json()["error"] == "Failed to delete document."

    @patch("app.routes.validate_document_with_ai")
    def test_process_document_ocr_db_error_handling(self, mock_validate, db_session, test_user):
        from app.routes import process_document_ocr
        from sqlalchemy.exc import SQLAlchemyError
        
        doc_uuid = uuid.uuid4()
        doc = Document(
            id=doc_uuid,
            user_id=test_user.id,
            document_type="other",
            original_filename="lab_report.pdf",
            blob_name="lab.pdf",
            blob_url="/mock-uploads/lab.pdf",
            ocr_status="pending"
        )
        db_session.add(doc)
        db_session.commit()

        # Mock the session inside process_document_ocr to fail on commit
        mock_session = MagicMock()
        mock_session.query().filter().first.return_value = doc
        mock_session.commit.side_effect = SQLAlchemyError("Commit error")

        with patch("app.database.SessionLocal", return_value=mock_session), \
             patch("app.routes.settings.AZURE_STORAGE_CONNECTION_STRING", ""):
            # Should not raise exception, just handle gracefully and log error
            process_document_ocr(str(doc_uuid), doc.blob_name)
            mock_session.rollback.assert_called_once()

    def test_serve_mock_upload_endpoint(self, authenticated_client):
        # 1. 404 response
        with patch("os.path.exists", return_value=False):
            response = authenticated_client.get("/documents/mock-uploads/nonexistent.pdf")
            assert response.status_code == 404
            assert response.json()["detail"] == "Mock file not found."

        # 2. 200 response
        from fastapi.responses import JSONResponse
        with patch("os.path.exists", return_value=True), \
             patch("app.routes.FileResponse") as mock_response_class:
            mock_response_class.return_value = JSONResponse(content={"msg": "file served"})
            response = authenticated_client.get("/documents/mock-uploads/exists.pdf")
            assert response.status_code == 200
            assert response.json() == {"msg": "file served"}


