client<llm> BedrockClaudeIAM {
  provider aws-bedrock
  retry_policy Exponential
  options {
    model "us.anthropic.claude-3-5-sonnet-20240620-v1:0"
    region "us-east-1"
  }
}


client<llm> BedrockHaikuIAM {
  provider aws-bedrock
  retry_policy Exponential
  options {
    model "apac.anthropic.claude-3-haiku-20240307-v1:0"
    region "ap-south-1"
  }
}

client<llm> GPT4oMini {
  provider openai
  retry_policy Exponential
  options {
    model "gpt-4o-mini"
  }
}


// https://docs.boundaryml.com/docs/snippets/clients/retry
retry_policy Constant {
  max_retries 3
  // Strategy is optional
  strategy {
    type constant_delay
    delay_ms 200
  }
}

retry_policy Exponential {
  max_retries 2
  // Strategy is optional
  strategy {
    type exponential_backoff
    delay_ms 300
    multiplier 1.5
    max_delay_ms 10000
  }
}
