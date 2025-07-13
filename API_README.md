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
- **HTML Rendering**: Markdown is converted to HTML and displayed in the right pane
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

## Key Features

- **Fast Report Loading**: Reports load instantly from pre-generated markdown
- **Clean Interface**: Focus on completed reports rather than processing status
- **Real-time Updates**: New companies appear automatically in the dropdown
- **Robust Error Handling**: Clear feedback for all operations
- **Enhanced Styling**: Modern, responsive design with smooth animations 