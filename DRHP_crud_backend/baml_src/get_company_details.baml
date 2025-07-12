// Defining a data model.
class CompanyDetails {
  name string
  corporate_identity_number string
  qr_code_url string
  website_link string
}

function ExtractCompanyDetails(text: string) -> CompanyDetails {
  client BedrockClaudeIAM
  prompt #"
 Extract the following company details from the DRHP content:
1. Company Name (full legal name)
2. Corporate Identity Number (CIN)
3. QR code URL (present at the top left corner, of the first page)
4. Company website link
Format the response as a JSON object with these fields:
- name: string (full legal name of the company)
- corporate_identity_number: string (CIN number)
- qr_code_url: string (URL of QR code if present, or empty string)
- website_link: string (company's website URL)
Look for these details in:
- Company information section
- Corporate details section
- General information section
- First few pages of the DRHP
Here is the DRHP content to analyze:
{{ text }}

{{ ctx.output_format }}
  "#
}


