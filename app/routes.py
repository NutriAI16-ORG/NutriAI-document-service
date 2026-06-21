import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from azure.core.exceptions import AzureError

from app.config import get_settings
from app.database import get_db
from app.models import Document
from app.services import upload_document, get_document_url, delete_document_blob

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/documents", tags=["Documents"])

DOCUMENT_NOT_FOUND = "Document not found."
NOT_AUTHENTICATED = "Not authenticated"
INVALID_ID_FORMAT = "Invalid format for user ID or document ID"
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def get_openai_client():
    if not settings.AZURE_OPENAI_KEY or not settings.AZURE_OPENAI_ENDPOINT:
        return None
    try:
        from openai import AzureOpenAI
        return AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    except (ValueError, OSError, ImportError) as e:
        logger.error(f"Failed to create OpenAI client: {e}")
        return None


def fallback_validate_document(ocr_content: str, filename: str) -> dict:
    content_lower = (ocr_content or "").lower() + " " + (filename or "").lower()
    
    # Lab report keywords
    lab_keywords = ["lab", "report", "test", "result", "blood", "urine", "panel", "cholesterol", "glucose", "hemoglobin", "vitamin", "bpm", "mmhg", "patient health metrics"]
    # Prescription keywords
    rx_keywords = ["prescription", "rx", "medication", "mg", "tablet", "capsule", "take", "dosage", "doctor", "signature", "recipe", "pharmacy", "sig:"]
    
    is_lab = any(kw in content_lower for kw in lab_keywords)
    is_rx = any(kw in content_lower for kw in rx_keywords)
    
    if is_lab:
        return {"is_valid": True, "document_type": "lab_report", "error_message": ""}
    elif is_rx:
        return {"is_valid": True, "document_type": "prescription", "error_message": ""}
    else:
        return {
            "is_valid": False,
            "document_type": "other",
            "error_message": "Invalid document. The uploaded file does not appear to be a medical lab report or a doctor's prescription. Please upload a valid document."
        }


def validate_document_with_ai(ocr_content: str, original_filename: str) -> dict:
    import json
    client = get_openai_client()
    
    is_mock = (
        not settings.AZURE_OPENAI_KEY
        or settings.AZURE_OPENAI_KEY == ""
        or "your-" in settings.AZURE_OPENAI_KEY
        or settings.AZURE_OPENAI_KEY.startswith("<")
        or not settings.AZURE_OPENAI_ENDPOINT
        or settings.AZURE_OPENAI_ENDPOINT == ""
        or "your-" in settings.AZURE_OPENAI_ENDPOINT
        or settings.AZURE_OPENAI_ENDPOINT.startswith("<")
    )
    
    if is_mock or not client:
        logger.warning("Azure OpenAI is not configured/configured as mock. Using rule-based validation fallback.")
        return fallback_validate_document(ocr_content, original_filename)
        
    try:
        system_prompt = (
            "You are an AI assistant designed to classify and validate uploaded medical documents for a health portal.\n"
            "Your job is to determine if the document is either:\n"
            "1. A Lab Report (containing lab test results, blood tests, panel results, medical metrics, etc.)\n"
            "2. A Prescription (containing doctor's prescriptions, list of medications, medical instructions, dosage, doctor sign-offs, etc.)\n"
            "3. Irrelevant or invalid (anything else, such as restaurant receipts, personal photos, general articles, books, food recipes, IDs, invoices, etc.)\n\n"
            "You MUST respond with valid JSON in the following exact structure:\n"
            "{\n"
            "    \"is_valid\": true/false,\n"
            "    \"document_type\": \"lab_report\"/\"prescription\"/\"other\",\n"
            "    \"error_message\": \"If not valid, a user-friendly soft error message explaining that the document is invalid and only lab reports or prescriptions are accepted. Otherwise, empty string.\"\n"
            "}"
        )
        
        user_message = (
            f"Filename: {original_filename}\n\n"
            f"Extracted Document Text:\n{ocr_content[:4000]}"
        )
        
        response = client.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=500,
        )
        
        result = json.loads(response.choices[0].message.content)
        if "is_valid" in result and "document_type" in result:
            return {
                "is_valid": bool(result.get("is_valid")),
                "document_type": result.get("document_type"),
                "error_message": result.get("error_message", "")
            }
    except (ValueError, OSError, RuntimeError) as e:
        logger.error(f"AI document validation error: {e}. Falling back to rule-based validation.")
        
    return fallback_validate_document(ocr_content, original_filename)


def _update_document_ocr(db, doc_uuid, extracted_text, original_filename):
    document = db.query(Document).filter(Document.id == doc_uuid).first()
    if not document:
        return
    validation = validate_document_with_ai(extracted_text, original_filename)
    if validation["is_valid"]:
        document.ocr_content = extracted_text
        document.ocr_status = "completed"
        document.document_type = validation["document_type"]
    else:
        document.ocr_content = validation["error_message"]
        document.ocr_status = "failed"
        document.document_type = "other"
    db.commit()


def _run_mock_ocr(db, doc_uuid, document_id) -> str:
    logger.warning(f"Running OCR background task in MOCK mode for document: {document_id}")
    import time
    time.sleep(2) # Simulate processing delay
    document = db.query(Document).filter(Document.id == doc_uuid).first()
    if not document:
        return ""
    filename_lower = document.original_filename.lower()
    if any(w in filename_lower for w in ["receipt", "invoice", "recipe", "dog", "cat", "sample", "photo", "book"]):
        return (
            "Walmart Supercenter Receipt\n"
            "Transaction: 9283401923\n"
            "1. Organic Bananas - $1.99\n"
            "2. Whole Milk Gallon - $3.49\n"
            "3. Dog Food Kibbles - $12.99\n"
            "Total: $18.47\n"
            "Thank you for shopping!"
        )
    return (
        "Lab Report Analysis (Local Mock Mode)\n\n"
        "Patient Health Metrics Summary:\n"
        "- Heart Rate: 72 bpm (Normal)\n"
        "- Blood Pressure: 120/80 mmHg (Optimal)\n"
        "- Blood Sugar: 95 mg/dL (Normal)\n"
        "- Cholesterol: 185 mg/dL (Desirable)\n"
        "- Hemoglobin: 14.5 g/dL (Normal)\n"
        "- Vitamin D: 32 ng/mL (Sufficient)\n"
    )


def _extract_text_from_pages(pages) -> str:
    extracted_text = ""
    for page in pages:
        for line in page.lines:
            extracted_text += line.content + "\n"
        extracted_text += "\n"
    return extracted_text


def _process_table_cells(cells) -> str:
    current_row = -1
    row_data = []
    extracted_text = ""
    for cell in cells:
        if cell.row_index != current_row:
            if row_data:
                extracted_text += " | ".join(row_data) + "\n"
            row_data = []
            current_row = cell.row_index
        row_data.append(cell.content)
    if row_data:
        extracted_text += " | ".join(row_data) + "\n"
    return extracted_text


def _extract_text_from_tables(tables) -> str:
    if not tables:
        return ""
    extracted_text = "\n--- Tables ---\n"
    for table_idx, table in enumerate(tables):
        extracted_text += f"\nTable {table_idx + 1}:\n"
        extracted_text += _process_table_cells(table.cells)
    return extracted_text


def _parse_ocr_result(result) -> str:
    text_content = _extract_text_from_pages(result.pages)
    table_content = _extract_text_from_tables(result.tables)
    return (text_content + table_content).strip()


def _run_live_ocr(blob_name: str) -> str:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential

    # Download blob
    from app.services import get_blob_service_client
    blob_service_client = get_blob_service_client()
    container_client = blob_service_client.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
    blob_client = container_client.get_blob_client(blob_name)
    download_stream = blob_client.download_blob()
    document_content = download_stream.readall()
    logger.info(f"Downloaded blob {blob_name}: {len(document_content)} bytes")

    # Run OCR
    client = DocumentAnalysisClient(
        endpoint=settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_DOCUMENT_INTELLIGENCE_KEY),
    )
    poller = client.begin_analyze_document(model_id="prebuilt-read", document=document_content)
    result = poller.result()

    return _parse_ocr_result(result)


def process_document_ocr(document_id: str, blob_name: str):
    """
    Background task: download blob, run OCR, update database.
    """
    from app.database import SessionLocal
    db = SessionLocal()
    doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id

    try:
        # Check if we should run in mock mode
        conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
        ocr_key = settings.AZURE_DOCUMENT_INTELLIGENCE_KEY
        is_mock = (
            not conn_str or conn_str == "" or "base64" in conn_str or "your-" in conn_str or conn_str.startswith("<") or
            not ocr_key or ocr_key == "" or ocr_key.startswith("<")
        )

        if is_mock:
            extracted_text = _run_mock_ocr(db, doc_uuid, document_id)
        else:
            extracted_text = _run_live_ocr(blob_name)

        if extracted_text is not None:
            document = db.query(Document).filter(Document.id == doc_uuid).first()
            if document:
                _update_document_ocr(db, doc_uuid, extracted_text, document.original_filename)
                logger.info(f"OCR and validation completed for document {document_id}")

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        try:
            document = db.query(Document).filter(Document.id == doc_uuid).first()
            if document:
                document.ocr_status = "failed"
                db.commit()
        except SQLAlchemyError:
            db.rollback()
    finally:
        db.close()


@router.get(
    "/list",
    responses={
        400: {"description": "Invalid user ID format"},
        401: {"description": NOT_AUTHENTICATED},
    }
)
async def list_documents(request: Request, db: Annotated[Session, Depends(get_db)]):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    documents = (
        db.query(Document)
        .filter(Document.user_id == user_id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )

    return [
        {
            "id": str(doc.id),
            "document_type": doc.document_type,
            "original_filename": doc.original_filename,
            "blob_url": doc.blob_url,
            "ocr_status": doc.ocr_status,
            "ocr_content": doc.ocr_content,
            "uploaded_at": doc.uploaded_at.isoformat(),
        }
        for doc in documents
    ]


@router.post(
    "/upload",
    responses={
        400: {"description": "Invalid file format, file too large, or empty file"},
        401: {"description": NOT_AUTHENTICATED},
        500: {"description": "Failed to upload document"},
    }
)
async def upload_doc(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[Session, Depends(get_db)],
    document_type: Annotated[str, Form()] = "other",
):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    file_extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if file_extension not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"},
        )

    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        return JSONResponse(status_code=400, content={"error": "File size exceeds 10MB limit."})

    if len(file_content) == 0:
        return JSONResponse(status_code=400, content={"error": "File is empty."})

    try:
        blob_result = upload_document(
            file_content=file_content,
            original_filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
        )

        document = Document(
            user_id=user_id,
            document_type=document_type,
            original_filename=file.filename,
            blob_name=blob_result["blob_name"],
            blob_url=blob_result["blob_url"],
            ocr_status="pending",
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        # Run OCR processing in background
        document.ocr_status = "processing"
        db.commit()
        background_tasks.add_task(process_document_ocr, str(document.id), document.blob_name)

        return JSONResponse(content={
            "message": "Document uploaded successfully.",
            "document_id": str(document.id),
            "status": document.ocr_status,
        })

    except (AzureError, SQLAlchemyError, OSError) as e:
        logger.error(f"Error uploading document: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to upload document."})


@router.get(
    "/{document_id}/status",
    responses={
        400: {"description": INVALID_ID_FORMAT},
        401: {"description": NOT_AUTHENTICATED},
        404: {"description": "Document not found"},
    }
)
async def document_status(
    document_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)
    try:
        user_id = uuid.UUID(user_id_str)
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=INVALID_ID_FORMAT)

    document = db.query(Document).filter(
        Document.id == doc_uuid,
        Document.user_id == user_id,
    ).first()

    if not document:
        return JSONResponse(status_code=404, content={"error": DOCUMENT_NOT_FOUND})

    return {"id": str(document.id), "ocr_status": document.ocr_status}


@router.get(
    "/{document_id}/preview",
    responses={
        400: {"description": INVALID_ID_FORMAT},
        401: {"description": NOT_AUTHENTICATED},
        404: {"description": "Document not found"},
        500: {"description": "Failed to generate preview URL"},
    }
)
async def document_preview(
    document_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)
    try:
        user_id = uuid.UUID(user_id_str)
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=INVALID_ID_FORMAT)

    document = db.query(Document).filter(
        Document.id == doc_uuid,
        Document.user_id == user_id,
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)

    try:
        sas_url = get_document_url(document.blob_name)
        return JSONResponse(content={"preview_url": sas_url})
    except (AzureError, OSError, ValueError) as e:
        logger.error(f"Error generating preview URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate preview URL.")


@router.delete(
    "/{document_id}",
    responses={
        400: {"description": INVALID_ID_FORMAT},
        401: {"description": NOT_AUTHENTICATED},
        404: {"description": "Document not found"},
        500: {"description": "Failed to delete document"},
    }
)
async def delete_doc(
    document_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)
    try:
        user_id = uuid.UUID(user_id_str)
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=INVALID_ID_FORMAT)

    document = db.query(Document).filter(
        Document.id == doc_uuid,
        Document.user_id == user_id,
    ).first()

    if not document:
        return JSONResponse(status_code=404, content={"error": DOCUMENT_NOT_FOUND})

    try:
        try:
            delete_document_blob(document.blob_name)
        except (AzureError, OSError) as e:
            logger.warning(f"Could not delete blob {document.blob_name}: {e}")

        db.delete(document)
        db.commit()
        return JSONResponse(content={"message": "Document deleted successfully."})

    except (AzureError, SQLAlchemyError, OSError) as e:
        logger.error(f"Error deleting document: {e}")
        db.rollback()
        return JSONResponse(status_code=500, content={"error": "Failed to delete document."})


from fastapi.responses import FileResponse
import os

@router.get(
    "/mock-uploads/{filename}",
    responses={
        404: {"description": "Mock file not found"},
    }
)
async def serve_mock_upload(filename: str):
    filepath = os.path.join("/app/uploads", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Mock file not found.")
    return FileResponse(filepath)
