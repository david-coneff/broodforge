# Project Charter

Purpose:
Provide objective infrastructure assessment.

SHALL:
- Collect facts
- Normalize facts
- Generate reports
- Track historical changes

SHALL NOT:
- Recommend upgrades
- Recommend purchases
- Recommend replacements
- Make subjective judgments

**Scope note (added 2026-06-07, clarifying original intent — see AD-040):**
The four items above name *specific-hardware* recommendations — e.g., what
product or component to buy, add, or swap into an existing or a new node —
the kind of call that requires granular product-and-pricing knowledge
(specific PC products, vendor catalogs, pricing databases) this project does
not, and should not, take on; that knowledge is what would make such a
recommendation "subjective" in the sense this charter excludes. They do
**not** bound the platform's own resource-provisioning and deployment-
strategy decisions for infrastructure it already manages or is asked to
manage — e.g., how to allocate or provision resources within an existing or
new node, or how to plan a bounded, safeguarded remediation. Those are a
broad function of the platform's chartered deployment strategy (see AD-013,
AD-014, AD-032, and AD-040's revised AD-034), not a "subjective judgment" or
"recommendation" in the excluded, hardware-specific sense.
