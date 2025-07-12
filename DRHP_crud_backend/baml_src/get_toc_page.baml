class IsTocPage {
  isTocPage bool
}

// Create a function to extract the resume from a string.
function ExtractTableOfContents(page_image: image) -> IsTocPage {

  client BedrockClaudeIAM

  prompt #"

    {{_.role('system')}}
    You are a helpful assistant that verifies if a given image is a table of contents page.
    Please analyze the following image and determine if it is a table of contents page.   
    OUTPUT FORMAT:
    {
        isTocPage: bool
    }
    {{_.role('user')}}
    Find out if this is image is a table of contents page.
    {{ page_image }}

    {{ ctx.output_format }}
  "#
}

