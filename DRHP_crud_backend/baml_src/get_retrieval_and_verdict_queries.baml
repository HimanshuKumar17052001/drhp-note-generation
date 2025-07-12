class RetrievalAndVerdictQueries {
  hypothetical_factual_responses string[]
}


// Create a function to extract the resume from a string.
function ExtractRetrievalAndVerdictQueries(user_query: string) -> RetrievalAndVerdictQueries {
  // Specify a client as provider/model-name
  // you can use custom LLM params with a custom client name from clients.baml like "client CustomHaiku"
  client BedrockClaudeIAM // Set OPENAI_API_KEY to use this client.
  prompt #"

  {{_.role('system')}}
**System Prompt for Generating Hypothetical DRHP Insights**

You are an intelligent assistant that takes a user's compliance question and simulates how relevant data would typically appear in a Draft Red Herring Prospectus (DRHP). Your output should include:

1. **Hypothetical Factual Responses** – Provide realistic, plausible document-like paragraphs, as if extracted from the DRHP. The goal is that from these hypotheitcal paragraphs when compiled together should be able to asnwer the use query.
The user has also mentioned sections and heading where u can find the information, u need to include these into ur hypothetical factual responses.


**Instructions:** 

* In **hypothetical_factual_responses**, do not ask retrieval questions or suggest checking sections.
* Reference **exact section names** where appropriate, e.g., "As disclosed in the 'Risk Factors' section...".
* Use realistic financial data and legal phrasing seen in offer documents.


Here are some examples of hypothetical factual responses:

Example 1:
1. Good Manufacturing Practice Guidelines (GMP) 
These guidelines are provided under Schedule T of Drug and Cosmetic Act, 1940. Good manufacturing 
practices (GMP) are the practices required in order to confirm the guidelines recommended by agencies 
that  control  authorization  and  licensing  for  manufacture  and  sale  of  food,  drug  products,  and  active 
pharmaceutical products. These guidelines provide minimum requirements that a pharmaceutical or a 
food product manufacturer must meet to assure that the products are of high quality and do not pose 
any risk to the consumer or public. Good manufacturing practices, along with good laboratory practices 
and good clinical practices, are overseen by regulatory agencies in various sectors in India.

Example 2:
# DETAILS OF SHARE CAPITAL AS RESTATED  
**ANNEXURE - V**  
*(₹ In Lakhs)*

| Particulars                           | As at March 31, 2024 | 2023   | 2022   |
|--------------------------------------|-----------------------|--------|--------|
| **EQUITY SHARE CAPITAL:**            |                       |        |        |
| **AUTHORISED:**                      |                       |        |        |
| Equity Share Capital of ₹10/- each   | 1,150.00              | 400.00 | 400.00 |
| **TOTAL**                            | **1,150.00**          | 400.00 | 400.00 |

|                                      |                       |        |        |
| **ISSUED, SUBSCRIBED AND PAID UP**   |                       |        |        |
| 76,00,000 Equity Shares of ₹10/- each fully paid  | 760.00 | 400.00 | 400.00 |
| *(40,00,000 as on 31st March 2023 and 2022)* |       |        |        |
| **TOTAL**                            | **760.00**            | 400.00 | 400.00 |

Example 3:

Other Income: 
  During the Fiscal year March 31, 2024, other income was ₹ 9.76 Lakhs. For financial year March 31, 
  2023, it was ₹ 20.78 Lakhs representing a decrease of 53%.  The Company has earned a profit on the 
  sales of fixed asset in the Fiscal year 2023, due to which there was increase in other income. 
  
Total Expenses: 
  The Total Expenses for the Fiscal year March 31,2024 stood at ₹ 7,518.33Lakhs. The total expenses 
  represented an increase of 13.61 % as compared to previous year which is ₹ 6,617.74 Lakhs due to the 
  factors described below: - 
 
Cost of Material consumed: 
  Our cost of material consumed is ₹5,849.43 Lakhs for the Fiscal year March 31,2024 as compared to 
  ₹5,252.68 Lakhs for the Fiscal year March 31,2023 representing an increase of 11.36% due to increase 
  in our scale of operations. 
 
Changes in Inventories 
  Our changes in inventories is ₹ (210.74) Lakhs for the financial year March 31, 2024 which is ₹ (246.70) 
  Lakhs in the financial year March 31,2023

  {{_.role('user')}}
  Extract from this content:
  {{ user_query }}

  {{ ctx.output_format }}
"#
}