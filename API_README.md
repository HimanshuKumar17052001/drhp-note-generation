# DRHP IPO Notes Generation Tool - API Documentation

## Overview

The DRHP IPO Notes Generation Tool has been updated to provide a streamlined user experience where:

1. **All processed companies** are listed in the "View Companies" dropdown
2. **Quick report loading** - clicking on a company immediately loads and displays the final HTML report
3. **Real-time updates** - new companies are automatically added to the dropdown as they complete processing
4. **No processing status display** - the interface focuses on showing completed reports

## API Endpoints

### Core Endpoints

#### `GET /companies/`
Returns all companies from the MongoDB database with their processing status and statistics.

**Response:**
```json
[
  {
    "id": "company_id",
    "name": "Company Name",
    "corporate_identity_number": "CIN123456789",
    "website_link": "https://company.com",
    "created_at": "2024-01-01T00:00:00Z",
    "processing_status": "COMPLETED",
    "has_markdown": true,
    "pages_count": 150,
    "checklist_outputs_count": 45
  }
]
```

#### `GET /company/{company_id}`
Returns detailed information about a specific company.

#### `GET /company/{company_id}/markdown`
Returns the generated markdown content for a company. This is used to quickly load reports.

**Response:**
```json
{
  "company_id": "company_id",
  "company_name": "Company Name",
  "markdown": "# Company Analysis\n\nDetailed markdown content...",
  "generated_at": "2024-01-01T00:00:00Z"
}
```

#### `GET /company/{company_id}/report-html`
Returns the fully rendered HTML report for a company using Jinja templates and CSS styling. This provides the complete formatted report as it would appear in the final PDF.

**Response:**
```json
{
  "company_id": "company_id",
  "company_name": "Company Name",
  "html": "<div class='page front-page'>...</div><div class='page'>...</div>",
  "generated_at": "2024-01-01T00:00:00Z"
}
```

#### `GET /companies/{company_id}/report-html`
Renders markdown content using HTML templates with CSS styling. Returns complete HTML document with embedded CSS for web display. Called by frontend when user selects a company to view the report.

**Response:**
```json
{
  "company_id": "company_id",
  "company_name": "Company Name",
  "html": "<div class='page front-page'>...</div><div class='page'>...</div>",
  "generated_at": "2024-01-01T00:00:00Z"
}
```

#### `GET /companies/{company_id}/markdown`
Returns raw markdown content for a company. Used for backend processing and raw data access.

**Response:**
```json
{
  "company_id": "company_id",
  "company_name": "Company Name",
  "markdown": "# Company Analysis\n\nDetailed markdown content...",
  "generated_at": "2024-01-01T00:00:00Z"
}
```

#### `POST /generate-report-pdf/`
Generate PDF from markdown content (alternative endpoint). Used by frontend PDF download functionality.

**Request:**
```json
{
  "markdown_content": "# Report Content\n\nMarkdown content...",
  "company_name": "Company Name"
}
```

**Response:** PDF file download

#### `GET /report/{company_id}?format={format}`
Get final report for a company by ID in the requested format.

**Path Parameters:**
- `company_id` (string): The ObjectId of the company as a 24-character hex string

**Query Parameters:**
- `format` (string, optional): Output format. Can be:
  - `pdf` (default): Returns a downloadable PDF file
  - `html`: Returns the report as HTML in a JSON response
  - `markdown`: Returns the raw markdown in a JSON response

**Response Examples:**

**Markdown format:**
```json
{
  "company_id": "687407dd927a7192cfabb784",
  "company_name": "QUALITY POWER ELECTRICAL EQUIPMENTS LIMITED",
  "content": "**Issue Highlights**\n\n| Particulars | Det…",
  "format": "markdown"
}
```

**HTML format:**
```json
{
  "company_id": "687407dd927a7192cfabb784",
  "company_name": "QUALITY POWER ELECTRICAL EQUIPMENTS LIMITED",
  "content": "<h2>Issue Highlights</h2> ...",
  "format": "html"
}
```

**PDF format:** Returns a PDF file as download

#### `GET /company/{company_id}/status`
Returns the processing status for a company.

**Response:**
```json
{
  "company_id": "company_id",
  "processing_status": "COMPLETED",
  "pages_done": true,
  "qdrant_done": true,
  "checklist_done": true,
  "markdown_done": true,
  "overall_status": "Completed"
}
```

#### `POST /process-drhp/`
Uploads a DRHP PDF and initiates processing. This endpoint is used by the HTML interface.

**Request:** Multipart form data with PDF file

**Response:**
```json
{
  "company_id": "new_company_id",
  "message": "Company created successfully",
  "existing_markdown": false
}
```

### Additional Endpoints

#### `POST /companies/{company_id}/regenerate`
Re-runs the AI processing for an existing company.

#### `DELETE /companies/{company_id}`
Deletes a company and all associated data.

#### `POST /reports/generate-pdf`
Converts markdown content to PDF with company branding.

#### `POST /company/{company_id}/cancel-processing`
Cancels ongoing processing for a company.

## User Interface Changes

### Company Listing
- **Filtered Display**: Only shows companies that have completed processing (have markdown)
- **Quick Loading**: Clicking on a company immediately loads the report without status checking
- **Visual Indicators**: Shows "✅ Report Available" for processed companies
- **Enhanced Styling**: Improved company list appearance with hover effects and selection states

### Report Display
- **Immediate Loading**: Reports load instantly when clicking on a company
- **Formatted HTML Reports**: Reports are rendered using Jinja templates with proper CSS styling
- **Professional Layout**: Reports display with front page, headers, footers, and proper typography
- **PDF-Ready Format**: Same formatting as the final PDF output
- **No Processing Status**: Removed processing status display for cleaner interface
- **Auto-refresh**: New companies are automatically added to the dropdown as they complete

### Error Handling
- **Graceful Failures**: Clear error messages when reports fail to load
- **Loading States**: Proper loading indicators during report fetching
- **Fallback UI**: Shows appropriate messages when no companies or reports are available

## Database Schema

### Company Collection
```javascript
{
  "_id": ObjectId,
  "name": "Company Name",
  "corporate_identity_number": "CIN123456789",
  "website_link": "https://company.com",
  "created_at": ISODate,
  "processing_status": "COMPLETED|PROCESSING|FAILED|CANCELLED",
  "has_markdown": true
}
```

### FinalMarkdown Collection
```javascript
{
  "_id": ObjectId,
  "company_id": ObjectId,
  "company_name": "Company Name",
  "markdown": "# Markdown content...",
  "generated_at": ISODate
}
```

## Testing

Run the test script to verify API functionality:

```bash
python test_api.py
```

This will test:
- Health check endpoint
- Company listing
- Individual company details
- Markdown retrieval
- Processing status

## Usage

1. **Start the API server:**
   ```bash
   python api.py
   ```

2. **Open the HTML interface:**
   - Open `drhp-ipo-note-generation-tool.html` in a web browser
   - The interface will connect to `http://localhost:8000`

3. **View Companies:**
   - Click "View Companies" button to see all processed companies
   - Click on any company to immediately load and display its report

4. **Upload New DRHP:**
   - Upload a PDF to process a new company
   - The company will be automatically added to the dropdown when processing completes

## Complete Endpoint Summary

| Endpoint | Method | Purpose | Frontend Usage | Backend Usage | Status |
|----------|--------|---------|----------------|---------------|---------|
| `POST /companies/` | POST | Upload and process DRHP PDF files | ✅ File upload & processing | ✅ Pipeline orchestration | Active |
| `GET /companies/` | GET | List all processed companies | ✅ Company dropdown | ✅ Data retrieval | Active |
| `GET /companies/{id}/markdown` | GET | Get raw markdown content | ❌ | ✅ Raw data access | Active |
| `GET /companies/{id}/report` | GET | Get markdown report for preview | ❌ | ✅ Markdown preview | Active |
| `GET /companies/{id}/report-html` | GET | Get HTML-formatted report with styling | ✅ HTML display | ✅ Template rendering | Active |
| `POST /companies/{id}/regenerate` | POST | Regenerate IPO note for existing company | ✅ Report regeneration | ✅ Pipeline rerun | Active |
| `DELETE /companies/{id}` | DELETE | Delete company and all associated data | ✅ Company deletion | ✅ Data cleanup | Active |
| `POST /generate-report-pdf/` | POST | Generate PDF from markdown content | ✅ PDF download | ✅ PDF generation | Active |
| `POST /reports/generate-pdf` | POST | Generate PDF from markdown (alternative) | ✅ PDF generation | ✅ PDF creation | Active |
| `GET /report/{id}?format={format}` | GET | Get final report in multiple formats | ✅ Report retrieval | ✅ Multi-format output | Active |
| `POST /assets/logos` | POST | Upload company/entity logos | ✅ Logo upload | ✅ Asset management | Active |
| `GET /company/{id}` | GET | Get specific company details | ✅ Company details | ✅ Data access | Active |
| `GET /company/{id}/status` | GET | Get processing status for company | ✅ Status monitoring | ✅ Progress tracking | Active |
| `GET /company/{id}/markdown` | GET | Get markdown content for company | ✅ Raw data access | ✅ Content retrieval | Active |
| `GET /company/{id}/report-html` | GET | Get HTML report (company endpoint) | ✅ HTML display | ✅ Template rendering | Active |
| `POST /company/{id}/cancel-processing` | POST | Cancel processing for company | ✅ Cancel operations | ✅ Process control | Active |
| `PUT /companies/{id}/logo` | PUT | Associate logo with company | ✅ Logo association | ✅ Asset linking | Active |
| `PUT /config/entity-assets` | PUT | Set global entity assets configuration | ✅ Asset config | ✅ Global settings | Active |
| `GET /health` | GET | Health check endpoint | ✅ System monitoring | ✅ Status check | Active |

## Key Features

- **Fast Report Loading**: Reports load instantly from pre-generated markdown
- **Clean Interface**: Focus on completed reports rather than processing status
- **Real-time Updates**: New companies appear automatically in the dropdown
- **Robust Error Handling**: Clear feedback for all operations
- **Enhanced Styling**: Modern, responsive design with smooth animations
- **Complete API Coverage**: All 17 endpoints implemented with proper error handling 