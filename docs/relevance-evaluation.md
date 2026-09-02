# Relevance Evaluation Fixtures

These frozen fixtures define the first precision gate for compound and Chinese queries. The expansion arrays are test data, not live model output.

| Query | Intent | Phrases | Include terms |
|---|---|---|---|
| `AI客服` | AI customer service | `AI客服`, `customer service chatbot` | `AI`, `artificial intelligence`, `customer service`, `chatbot`, `conversational AI`, `virtual agent`, `contact center` |
| `人工智能客服` | AI customer service | `人工智能客服`, `customer service chatbot` | `人工智能`, `artificial intelligence`, `customer service`, `chatbot`, `conversational AI`, `virtual agent`, `contact center` |
| `customer service chatbot` | customer service chatbot | `customer service chatbot` | `customer service`, `chatbot`, `conversational AI`, `virtual agent`, `contact center` |

For each query, the first ten labeled results must contain at least 80% relevant records. A record that only matches `AI` or `artificial intelligence` is not relevant for the first two queries.
