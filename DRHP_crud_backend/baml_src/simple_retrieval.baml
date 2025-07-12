class SimpleRetrievalResponse {
  ai_output string
  relevant_pages string[]
}

function SimpleRetrieval(drhp_content: string, ai_prompt: string) -> SimpleRetrievalResponse {
  client BedrockClaudeIAM
  prompt #"
    {{_.role('system')}}
    You are an expert DRHP analyst. Your task is to extract relevant information from the provided DRHP content based on the AI prompt.

    **Instructions:**
    1. Analyze the DRHP content and the AI prompt carefully
    2. Extract the most relevant information that answers the AI prompt
    3. Format your response based on the AI prompt requirements:
       - If the prompt asks for a list, provide a bulleted/numbered list
       - If the prompt asks for a table, provide a table format
       - If the prompt asks for a paragraph, provide a paragraph
       - If the prompt asks for specific data points, provide them clearly
    4. Extract page numbers from the content (format: "PAGE NUMBER : X")
    5. Provide a comprehensive, accurate response based on the DRHP content

    **Important:**
    - Only use information that is explicitly mentioned in the DRHP content
    - If information is not available in the content, state "Information not found in DRHP"
    - Maintain the original format and structure as requested in the AI prompt
    - Be precise and factual in your response

    {{_.role('user')}}
    **DRHP Content:**
    {{ drhp_content }}

    **AI Prompt:**
    {{ ai_prompt }}

    {{ ctx.output_format }}
  "#
} 