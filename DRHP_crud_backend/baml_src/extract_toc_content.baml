class TocContent {
  toc_entries string[]
  toc_text string
}

function ExtractTocContent(page_image: image) -> TocContent {
  client BedrockClaudeIAM
  
  prompt #"
    {{_.role('system')}}
    You are an expert at extracting table of contents from DRHP documents. Your task is to extract all table of contents entries from the provided page image.
    
    **Instructions:**
    1. Identify all table of contents entries on the page
    2. Extract both the section/topic names and their corresponding page numbers
    3. Format each entry as: "Section Name - Page Number"
    4. If there are subsections, include them with proper indentation or hierarchy
    5. Extract the full text content of the table of contents for reference
    
    **Output Format:**
    - toc_entries: Array of formatted TOC entries (e.g., ["1. Introduction - 5", "2. Company Overview - 12"])
    - toc_text: Full text content of the table of contents page
    
    **Important:**
    - Only extract actual table of contents entries
    - Include page numbers when available
    - Maintain the hierarchical structure if present
    - If this is not a table of contents page, return empty arrays
    
    {{_.role('user')}}
    Extract the table of contents from this page image. If this is not a table of contents page, return empty arrays.
    
    {{ page_image }}
    
    {{ ctx.output_format }}
  "#
} 