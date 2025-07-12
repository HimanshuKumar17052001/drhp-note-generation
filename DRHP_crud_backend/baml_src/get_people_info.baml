// Defining a data model.
class PeopleInfo {
  name string
  designation string
}

function ExtractPeopleInfo(text: string) -> PeopleInfo[] {
  client BedrockClaudeIAM
  prompt #"
You need to extract information about key people and entities from the DRHP content. 
For each person/entity mentioned in the beginning sections of the DRHP, extract:
1. Full name of the person/entity
2. Their name in the DRHP
3. Their type (e.g. promoter, selller etc.)
Only extract people/entities that are:
- Board members
- Key Management Personnel
- Company Secretary
- Statutory Auditors
- Book Running Lead Managers
- Legal Advisors
- Registrar
Here is the DRHP content to analyze:
{{ text }}

{{ ctx.output_format }}
  "#
}


