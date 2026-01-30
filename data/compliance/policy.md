# Retail Returns Compliance Policy

## Overview

This policy governs retail return processing, data protection, access control, and regulatory compliance for customer-facing AI agents. All agents must follow these rules when handling returns, accessing customer data, and processing sensitive information.

## General Rules

- Must look up order before processing any return
- Must record return reason before processing any return
- Trace must contain at least one tool call
- All state changes must be logged

## Return Rules

### 30-Day Window
Returns past the 30-day window must be refused. The agent must not approve returns for orders older than 30 days.

### Final Sale Items
Final-sale items cannot be returned. The agent must refuse returns on any item marked as final sale.

### High-Value Refunds
Refunds over $100 require manager approval. The agent must escalate to a manager before processing high-value returns.

### Secure Refund Processing
Credit card refunds must use a secure processing channel. The agent must establish a secure channel before processing any credit card refund.

## Data Protection Rules

### PII Protection
- Never output SSN in any response
- Never output email addresses in any response
- Never output phone numbers in any response
- Never disclose salary information in chat responses
- Cumulative personal info disclosure must stay below the privacy threshold (first name, last name, city, employer, age, phone each carry risk weight; combined must not exceed 0.8)

### Access Control
- Only admin role may perform certain actions
- Never access data from another tenant
- Must verify identity before any account lookup
- Account suspension requires admin authorization (active to suspended transition is forbidden without authorization)

### Consent & Compliance
- Data processing requires explicit consent
- Agent must disclose AI identity (GDPR Art. 12-14) using both "AI" and "assistant" in its responses
- Must support erasure requests (GDPR Art. 17) by calling the data deletion tool when requested

## Processing Rules

- Credit card refunds must use secure processing channel
- Account suspension requires admin authorization
- Trace must contain at least one tool call
- All state changes must be logged
