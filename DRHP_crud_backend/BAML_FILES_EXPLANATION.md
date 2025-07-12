# BAML Files Explanation and System Architecture

## Overview
The DRHP (Draft Red Herring Prospectus) analysis system uses BAML (Boundary ML) files to define AI functions that process PDF documents and extract structured information. BAML provides a type-safe way to define AI functions with structured inputs and outputs.

## BAML Files Structure

### 1. **clients.baml** - AI Model Configuration
```baml
client<llm> BedrockClaudeIAM {
  provider aws-bedrock
  retry_policy Exponential
  options {
    model "us.anthropic.claude-sonnet-4-20250514-v1:0"
    region "us-east-1"
  }
}
```
- **Purpose**: Defines the AI models used throughout the system
- **Models Used**: 
  - Claude Sonnet 4 (primary model for complex analysis)
  - Claude Haiku (faster model for simpler tasks)
- **Features**: Includes retry policies for reliability

### 2. **extract_toc_content.baml** - Table of Contents Extraction
```baml
class TocContent {
  toc_entries string[]
  toc_text string
}

function ExtractTocContent(page_image: image) -> TocContent
```
- **Purpose**: Extracts structured table of contents from page images
- **Input**: Page image (PNG/JPEG)
- **Output**: 
  - `toc_entries`: Array of formatted entries (e.g., "1. Introduction - 5")
  - `toc_text`: Full text content of the TOC page
- **Use Case**: When TOC page is detected, extract all section names and page numbers

### 3. **get_toc_page.baml** - TOC Page Detection
```baml
class IsTocPage {
  isTocPage bool
}

function ExtractTableOfContents(page_image: image) -> IsTocPage
```
- **Purpose**: Determines if a given page image is a table of contents page
- **Input**: Page image
- **Output**: Boolean indicating if it's a TOC page
- **Use Case**: Scan first 20 pages to find the TOC page

### 4. **direct_retrieval.baml** - Content Analysis and Answer Generation
```baml
class DirectRetrievalResponse {
  ai_output string
  relevant_pages string[]
}

function DirectRetrieval(ai_prompt: string, drhp_content: string) -> DirectRetrievalResponse
```
- **Purpose**: Analyzes DRHP content and generates structured answers based on AI prompts
- **Input**: 
  - `ai_prompt`: Specific question or analysis request
  - `drhp_content`: Retrieved page content with facts and queries
- **Output**: 
  - `ai_output`: Structured answer based on the prompt
  - `relevant_pages`: List of page numbers where relevant info was found
- **Use Case**: Final step in query processing - takes retrieved content and generates answers

### 5. **get_facts_from_pages.baml** - Fact Extraction
```baml
class FactsFromPages {
  facts string[]  
}

function GetFactsFromPages(user_query: string) -> FactsFromPages
```
- **Purpose**: Extracts 5 key factual points from each page
- **Input**: Page content text
- **Output**: Array of 5 concise bullet-point facts
- **Use Case**: During PDF processing, each page is analyzed to extract key facts for better search

### 6. **get_queries_from_page.baml** - Query Generation
```baml
class QueriesFromPages {
  Queries string[]  
}

function GetQueriesFromPage(user_query: string) -> QueriesFromPages
```
- **Purpose**: Generates 5 investor-style questions that each page answers
- **Input**: Page content text
- **Output**: Array of 5 natural-language questions
- **Use Case**: During PDF processing, generates searchable queries for each page

### 7. **get_company_details.baml** - Company Information Extraction
```baml
class CompanyDetails {
  name string
  corporate_identity_number string
  qr_code_url string
  website_link string
}

function ExtractCompanyDetails(text: string) -> CompanyDetails
```
- **Purpose**: Extracts basic company information from DRHP
- **Input**: DRHP text content
- **Output**: Structured company details (name, CIN, QR code, website)
- **Use Case**: Extract metadata about the company for reference

## System Flow with BAML Integration

### Phase 1: PDF Processing and TOC Detection
1. **PDF Upload**: System receives a DRHP PDF
2. **TOC Detection**: Uses `get_toc_page.baml` to scan first 20 pages
3. **TOC Extraction**: If TOC found, uses `extract_toc_content.baml` to get structured TOC
4. **Page Processing**: Each page is processed using local page processor
5. **Fact/Query Generation**: For each page:
   - Uses `get_facts_from_pages.baml` to extract 5 key facts
   - Uses `get_queries_from_page.baml` to generate 5 searchable queries
6. **JSON Storage**: All data stored in JSON with TOC content included

### Phase 2: Embedding Creation and Storage
1. **Text Combination**: Combines page content + facts + queries for embedding
2. **Hybrid Embeddings**: Creates both dense (OpenAI) and sparse (SPLADE) embeddings
3. **Qdrant Storage**: Stores embeddings with metadata in vector database

### Phase 3: Query Processing (NEW APPROACH)
1. **Search Query Construction**: Only uses `topic + section_name` (AI prompt excluded)
2. **Content Retrieval**: Searches Qdrant using hybrid search
3. **Content Analysis**: Uses `direct_retrieval.baml` with:
   - Retrieved page content
   - Original AI prompt
   - Generates structured answer

## Key Changes Made

### 1. Enhanced TOC Storage
- **Before**: Only stored TOC page number
- **After**: Stores complete TOC content including:
  - TOC entries with page numbers
  - Full TOC text
  - Entry count for reference

### 2. Improved Query Construction
- **Before**: Used `topic + section_name + ai_prompt` for search
- **After**: Uses only `topic + section_name` for search
- **Rationale**: AI prompts are often too specific and can reduce search recall
- **Benefit**: Better semantic search results, AI prompt used only for content analysis

### 3. Structured Processing Flow
```
Search Query (topic + section) → Content Retrieval → AI Analysis (prompt + content) → Structured Answer
```

## Benefits of This Approach

1. **Better Search**: Topic + section provides broader, more relevant search results
2. **Focused Analysis**: AI prompt is used only when we have relevant content to analyze
3. **Rich TOC Data**: Complete TOC information available for navigation and reference
4. **Type Safety**: BAML provides compile-time validation of AI function inputs/outputs
5. **Modularity**: Each BAML function has a specific, well-defined purpose

## Error Handling and Reliability

- **Retry Policies**: Exponential backoff for API failures
- **Fallback Search**: If hybrid search fails, falls back to dense search
- **Content Validation**: Ensures retrieved content is sufficient before AI analysis
- **Structured Logging**: Comprehensive logging for debugging and monitoring

This architecture provides a robust, scalable system for DRHP analysis with clear separation of concerns between search, retrieval, and analysis phases. 