# Hyperspace Vector Schema

Each node in the decomposition tree carries an 8-axis hyperspace vector tag. These tags enable multi-dimensional clustering to discover reuse opportunities across subsystem boundaries.

## Axes

### 1. domain (string[])
Functional domain labels. Identifies which business domains this node belongs to.

Examples: `["payments", "order_management"]`, `["user_auth", "security"]`

### 2. entities (string[])
Core data entities involved. Names the domain objects this node reads, writes, or transforms.

Examples: `["Order", "Payment", "Refund"]`, `["User", "Session"]`

### 3. patterns (string[])
Design patterns used or recommended. Captures architectural and design pattern choices.

Examples: `["CQRS", "Event Sourcing"]`, `["Repository", "Unit of Work"]`

### 4. api_shape (object)
Interface shape descriptor with three sub-fields:
- **inputs**: Parameter types the node accepts
- **outputs**: Return types the node produces
- **side_effects**: External effects (notifications, writes, charges)

Example:
```json
{
  "inputs": ["order_id: string", "amount: decimal"],
  "outputs": ["PaymentResult", "Receipt"],
  "side_effects": ["charge_payment_gateway", "send_confirmation_email"]
}
```

### 5. tech_traits (string[])
Technical characteristics and quality attributes.

Examples: `["real_time", "idempotent", "high_throughput"]`, `["batch_processing", "eventually_consistent"]`

### 6. actors (string[])
User roles or system actors that interact with this node.

Examples: `["consumer", "merchant", "rider"]`, `["admin", "system_scheduler"]`

### 7. nfr (string[])
Non-functional requirements relevant to this node.

Examples: `["low_latency", "high_availability", "GDPR_compliant"]`, `["audit_trail", "rate_limited"]`

### 8. rule_fingerprint (string)
One-sentence summary of the core business rule chain. Used for deduplication of business logic.

Examples:
- `"order_create -> merchant_confirm -> rider_assign -> deliver -> complete"`
- `"user_register -> verify_phone -> set_password -> activate"`

## Usage in Clustering

### Structural Clustering
Tags are stored in the `tags` SQLite table as key-value pairs. Set operations (intersection, Jaccard similarity) identify nodes sharing domain/entity/pattern/actor overlaps.

### Semantic Clustering
The `rule_fingerprint` and full vector description are embedded into ChromaDB. DBSCAN clustering on these embeddings discovers semantically similar nodes even when tag labels differ.

### Cross-Validation
Structural and semantic clusters are cross-referenced to increase precision and reduce false positives.
