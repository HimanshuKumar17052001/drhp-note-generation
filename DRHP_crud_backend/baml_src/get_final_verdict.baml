class FinalVerdict {
  flag_status FlagStatus
  detailed_reasoning string
  citations string[]
}

enum FlagStatus {
    FLAGGED
    NOT_FLAGGED
}

// Create a function to extract the resume from a string.
function ExtractFinalVerdict(insights: string, user_query: string) -> FinalVerdict {
  client BedrockClaudeIAM 
  prompt #"

    {{_.role('system')}}
    You work for an stock exchange, where you analyse the draft red herring prospectus (DRHP) of a company, and provide a final verdict on the compliance of the company with the regulations.

    You have been given insights from the DRHP, by your junior analyst.
    You need to analyse the insights, and provide a final verdict on the compliance of the company with the regulations.
    The insights are: {{ insights }}

    Your senior will ask for queries, and give you information from the DRHP and you need to provide the flag not flag verdict, with proper reasoning.

    You need to provide the citations for the insights, in the format of "Page Number", just give the list of page numbers, which you used to come to the conclusion.

    Output Format:
    {
      "flag_status": "FLAGGED" | "NOT_FLAGGED",
      "detailed_reasoning": "string",
      "citations": ["12", "27", "345", "F-16", "A123", "217", ...]
    }

    
    citations is a LIST of page numbers, which you used to come to the conclusion. dont output anything else in the list other than the exact page number, no text, assumption etc, page number written literally.


    {{_.role('user')}}
    What do you think about the user query, should it be flagged or not?
    {{ user_query }}

    {{ ctx.output_format }}
  "#
}

