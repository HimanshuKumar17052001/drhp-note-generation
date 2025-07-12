class PageNumber {
  is_page_number bool
  page_number string
}

function ExtractPageNumber(image: image) -> PageNumber {
  client BedrockHaikuIAM
  prompt #"
    {{_.role('system')}}
    You are an expert OCR detector. You will get a thin strip of the page, and you need to do 2 things:
    1. If the strip contains a page number.
    2. If the strip contains a page number then extract the page number.

    Page numbers can be of the following formats: -> (1, 2, 12, 345, 123, 345, A-12, A12, F-14, F-45, etc. etc. so it can be alphanumeric)

    You might also get empty strips, or strips containing some other text.
    In such cases just return empty string.
    sample output:
    {
        is_page_number: true,
        page_number: "123"
    }
    or
    {
        is_page_number: false,
        page_number: ""
    }

    {{_.role('user')}}
    {{ image }}

    {{ ctx.output_format }}
  "#
}