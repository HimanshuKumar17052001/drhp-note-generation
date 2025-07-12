class DirectRetrievalResponse {
  ai_output string
  relevant_pages string[]
}

function DirectRetrieval(ai_prompt: string, drhp_content: string) -> DirectRetrievalResponse {
  client BedrockClaudeIAM
  prompt #"
    {{_.role('system')}}
    You are an expert DRHP analyst. Your task is to extract relevant information from the provided DRHP content based on the AI prompt.

    **Content Structure:**
    The DRHP content is organized as follows:
    - PAGE NUMBER: The page number from the PDF
    - Main content: The extracted text from the page
    - FACTS: Key facts extracted from the page (if available)
    - QUERIES: Related queries/questions for the page (if available)

    **Instructions:**
    1. Analyze ALL sections of the DRHP content (main content, facts, and queries)
    2. Extract the most relevant information that answers the AI prompt
    3. Look for information in:
       - The main page content
       - The FACTS section (often contains key data points)
       - The QUERIES section (may contain relevant questions/context)
    4. Format your response based on the AI prompt requirements:
       - If the prompt asks for a list, provide a bulleted/numbered list
       - If the prompt asks for a table, provide a table format
       - If the prompt asks for a paragraph, provide a paragraph
       - If the prompt asks for specific data points, provide them clearly
    5. Extract page numbers from the content (format: "PAGE NUMBER : X")
    6. Provide a comprehensive, accurate response based on the DRHP content

    **Important:**
    - Search through ALL content sections (main content, facts, queries)
    - Only use information that is explicitly mentioned in the DRHP content
    - If information is not available in any section, state "Information not found in DRHP"
    - Maintain the original format and structure as requested in the AI prompt
    - Be precise and factual in your response
    - Return page numbers as a list of strings (e.g., ["12", "27", "345"])
    - If you find relevant information in facts or queries sections, include it in your response

    {{_.role('user')}}
    **AI Prompt:**
    {{ ai_prompt }}

    **DRHP Content:**
    {{ drhp_content }}

    {{ ctx.output_format }}
  "#
} 