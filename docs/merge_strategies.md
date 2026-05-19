# Merge Strategies

When hyperspace clustering identifies groups of similar nodes, the Comparator Agent selects one of four merge strategies. The Challenger Agent then validates the decision.

## Strategy: EXTRACT_SHARED

**When to use:** Nodes share significant common logic but also have meaningful unique parts.

**Action:**
1. Create a new shared component node containing the common logic
2. Each original node retains its unique parts and references the shared component
3. Add `shared_ref` edges from original nodes to the new component

**Example:** Three payment modules (credit card, e-wallet, bank transfer) all share order validation, amount calculation, and receipt generation. Extract these into a `PaymentCommon` component.

**Risk level:** Medium. Requires careful interface design to avoid leaky abstractions.

## Strategy: MERGE_DUPLICATES

**When to use:** Nodes are near-identical with only trivial differences (naming, comments).

**Action:**
1. Keep the most complete node as the canonical version
2. Invalidate all other nodes (status -> `invalidated`)
3. Update parent references to point to the canonical node

**Example:** Two teams independently designed a notification service with the same interface and behavior.

**Risk level:** Low, but verify that "trivial" differences aren't actually important edge cases.

## Strategy: PARAMETERIZE

**When to use:** Nodes share the same core logic but differ in configuration or parameters.

**Action:**
1. Create a unified component with a parameter/configuration interface
2. Each original use case becomes a configuration profile
3. Original nodes are replaced with references to the parameterized component + their config

**Example:** CRUD modules for User, Product, and Store differ only in entity schema and validation rules. Parameterize into a generic CRUD service with schema-driven behavior.

**Risk level:** Medium-high. Over-parameterization can create "god objects." The Challenger Agent specifically checks for this.

## Strategy: KEEP_SEPARATE

**When to use:** Despite surface similarity, nodes have fundamentally different:
- Change frequencies (one is stable, another changes weekly)
- Team ownership (crossing team boundaries creates coordination overhead)
- Performance profiles (one is latency-critical, another is batch)
- Business rules (shared interface would require too many special cases)

**Action:** No merge. Document the reason for future reference.

**Risk level:** None (no change), but missed reuse opportunity is the implicit cost.

## Decision Flow

```
Cluster identified
  -> Comparator analyzes commonalities/differences
    -> Selects strategy + designs shared interface (if applicable)
      -> Challenger reviews from 6 dimensions
        -> Approved? -> Backprop applies changes
        -> Rejected? -> KEEP_SEPARATE (with improvement notes)
```

## Challenger Review Dimensions

1. **Coupling risk**: Does the merge create unwanted cross-domain coupling?
2. **Performance bottleneck**: Could the shared component become a hotspot?
3. **Complexity inflation**: Does the merged component violate single responsibility?
4. **Team boundaries**: Does the merge cross natural team divisions?
5. **Change frequency mismatch**: Are stable and volatile parts being combined?
6. **Abstraction leakage**: Is the shared interface over-complex to accommodate all cases?
