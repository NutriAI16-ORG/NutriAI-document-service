# NutriAI — Document Service

The **Document Service** manages health document uploads (such as lab sheets, blood reports, and dietary reports). It uploads files securely into **Azure Blob Storage**, processes optical character recognition (OCR) scanning via **Azure AI Document Intelligence**, and generates temporary, secure preview links.

---

## 🏗️ Core Role & Functionality
1. **Blob Storage Streaming**: Receives file streams and writes them into a private Azure Blob Storage container (`health-documents`).
2. **AI OCR Parsing**: Connects to the Azure AI Document Intelligence API to extract structured layout and text content from PDFs/images, saving the output as metadata.
3. **Secure Document Previews**: Generates short-lived, read-only Shared Access Signature (SAS) tokens to serve files to frontend clients without exposing private container access.
4. **Lifecycle Operations**: Manages metadata indexing in PostgreSQL and syncs deletions with both the database and Azure Blob Storage.

---

## 🛠️ Technology Stack
* **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.12)
* **Storage SDK**: [Azure Storage Blob SDK](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-blob)
* **OCR Service SDK**: [Azure AI Document Intelligence / Form Recognizer SDK](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/formrecognizer/azure-ai-formrecognizer)
* **Auth Identity**: [Azure Identity SDK](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/identity/azure-identity) (`DefaultAzureCredential`)
* **ORM & DB Connection**: [SQLAlchemy](https://www.sqlalchemy.org/) & [Psycopg2](https://www.psycopg.org/)

---

## ⚙️ Configuration & Environment Variables

Variables are configured in [app/config.py](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-document-service/app/config.py):

| Variable Name | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./test.db` | PostgreSQL connection URL. |
| `AZURE_STORAGE_CONNECTION_STRING` | *Empty* | Storage account connection string (local fallback). |
| `AZURE_STORAGE_CONTAINER_NAME` | `health-documents` | Name of storage container. |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | *Empty* | Azure Document Intelligence endpoint. |
| `AZURE_DOCUMENT_INTELLIGENCE_KEY` | *Empty* | Azure Document Intelligence key. |
| `AZURE_OPENAI_ENDPOINT` | *Empty* | Optional Azure OpenAI endpoint. |
| `AZURE_OPENAI_KEY` | *Empty* | Optional Azure OpenAI key. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | *Empty* | Telemetry connection string. |

---

## 🗄️ Database Models

Model details are in [app/models.py](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-document-service/app/models.py):

* **Document**: Fields include user ID, document type (`lab_report`, `dietary_log`, `other`), original filename, target blob name, absolute blob URL, OCR extracted text string (`ocr_content`), OCR parsing status (`pending`, `completed`, `failed`), and upload timestamp.

---

## 🔌 API Endpoints Reference

All routes are declared in [app/routes.py](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-document-service/app/routes.py).

| HTTP Method | Route | Description | Auth Header Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/documents/list` | Lists document records uploaded by the current patient. | `X-User-ID` |
| **POST** | `/documents/upload` | Streams document file, writes to Blob storage, runs OCR in background. | `X-User-ID` |
| **GET** | `/documents/{document_id}/status` | Checks status of OCR parsing progress. | `X-User-ID` |
| **GET** | `/documents/{document_id}/preview` | Returns a temporary secure SAS URL for document preview. | `X-User-ID` |
| **DELETE** | `/documents/{document_id}` | Removes file from Azure Storage and deletes database index. | `X-User-ID` |
| **GET** | `/documents/mock-uploads/{filename}`| Fallback routes to fetch mock files. | None |

---

## 🔄 Azure Storage & AI Integration

### 1. Azure Blob Storage
* Files are uploaded using `BlobServiceClient`. In AKS, authorization uses **Workload Identity** with the `Storage Blob Data Contributor` role (no connection strings are used).
* **SAS Token Generation**: The service uses `generate_blob_sas` to construct temporary access signatures valid for a short duration (e.g. 15 minutes), ensuring files remain private.

### 2. Azure AI Document Intelligence
* When a file is uploaded, the service calls `begin_analyze_document` (using the `prebuilt-layout` model) to run layout and OCR analysis.
* The extracted text lines are compiled, cleaned, and updated in the PostgreSQL database.

---

## 🚀 CI/CD Pipeline
* Code triggers: [.github/workflows/cicd.yml](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-document-service/.github/workflows/cicd.yml).
* Uses reusable shared pipelines: format verification, unit testing, SonarQube quality gate and Snyk checks, Trivy container validation, push to ACR, and updates the manifests repository (`helm/nutriai/values-{env}.yaml`).

---

## 💻 Local Development

```bash
# Install packages
pip install -r requirements.txt

# Run document service locally (starts on port 8002)
uvicorn app.main:app --port 8002 --reload
```
Access at `http://127.0.0.1:8002`.
