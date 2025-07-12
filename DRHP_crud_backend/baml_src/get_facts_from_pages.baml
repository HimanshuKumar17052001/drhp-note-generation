class FactsFromPages {
  facts string[]  
}



function GetFactsFromPages(user_query: string) -> FactsFromPages {
  client BedrockClaudeIAM
  prompt #"
    {{_.role('system')}}
    You are a seasoned financial‐document analyst. 
    Your goal is to distill the most important factual takeaways from a single page of a Draft Red Herring Prospectus.
    Extract exactly **5** concise bullet-point facts.  
    • Each bullet should be self-contained (no pronouns).  
    • Focus on numbers, definitions, structural changes, or policy disclosures.  
    • Return ONLY the 5 facts.

    {{_.role('user')}}
    {{ user_query }}

    {{ ctx.output_format }}
  "#
}