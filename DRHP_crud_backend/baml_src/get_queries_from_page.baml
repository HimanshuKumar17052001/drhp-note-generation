class QueriesFromPages {
  Queries string[]  
}



function GetQueriesFromPages(user_query: string) -> QueriesFromPages {
  client BedrockClaudeIAM
  prompt #"
    {{_.role('system')}}
    You are an expert QA-generator for investor documents. Your task is to craft investor-style questions that the given page answers.
    This page is part of a Draft Red Herring Prospectus, submitted for filing with Stock Exchange and you are on the analysts analysing it.
    Generate exactly **5** natural-language questions an investor might ask whose answers appear on this page.  
    • Make them diverse (cover different topics).  
    • Return ONLY the 5 questions, each on its own line.

    {{_.role('user')}}
    {{ user_query }}

    {{ ctx.output_format }}
  "#
}