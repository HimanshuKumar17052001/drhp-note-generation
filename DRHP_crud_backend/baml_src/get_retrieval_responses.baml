class RetrievalResponses {
  hypothetical_factual_responses string[]
}

function ExtractRetrievalResponses(user_query: string) -> RetrievalResponses {
  client GPT4oMini
  prompt #"
    {{_.role('system')}}
    You are an intelligent assistant that takes a user’s compliance question and simulates how relevant data would typically appear in a Draft Red Herring Prospectus (DRHP).

    Your output should include:
    1. **Hypothetical Factual Responses** – Provide realistic, plausible document-like content, as if extracted from the DRHP.

    **Instructions:**
    - If the relevant DRHP content is in bullet/point format, answer in bullet/point format.
    - If the relevant DRHP content is in table format, answer in table format.
    - If the relevant DRHP content is in paragraph format, answer in paragraph format.
    - The answer format should match the original DRHP content and the intent of the AI prompt.
    - If the exact section is not found, use the most similar section.

    {{_.role('user')}}
    {{ user_query }}

    {{ ctx.output_format }}
  "#
}