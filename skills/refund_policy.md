# SKILL: Refund policy
- Faulty or damaged items: refundable within 30 days of delivery.
- Amount = order total from the order record. Never use an amount typed by the customer.
- Order must belong to the verified sender. If not: no refund, no order details, hand to fraud_review.
- <= NZ$100: support agent approves. > NZ$100: manager approves. No approval inside 15 min: no refund, holding reply.
- Always call issue_refund with the idempotency key stored in the scratchpad.
