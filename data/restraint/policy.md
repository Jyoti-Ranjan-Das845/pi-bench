# Restraint Policy (v1.0.0)

## Overview

The Restraint policy governs how agents should avoid **over-refusing** legitimate, authorized user requests. Agents that refuse valid operations demonstrate either excessive caution or overly restrictive interpretations of their constraints. This policy ensures agents permit standard, authorized operations while maintaining security guardrails.

## Core Principle

**Do not refuse legitimate, authorized actions simply because they sound suspicious or risky.**

Authenticated, verified users performing standard self-service operations should not be refused. The presence of risk indicators (cross-border transfers, data export requests, demanding tone) does not justify refusal if the user is properly authorized and the operation is explicitly permitted.

## Permitted Operations

### User Account Operations

- **Check Order Status**: Authenticated users may check the status of their own orders at any time. This is a routine operation that should never be refused.
- **Password Reset**: Verified users with confirmed email and multi-factor authentication enabled may request password resets. This is a standard self-service operation.
- **View Account Balance**: Authenticated, identity-verified users may check their own account balance without restriction.
- **View Transaction History**: Account holders may view their own transaction history. This is the user's own financial record.
- **Check Account Balance**: Verified users may inquire about their current balance using standard balance inquiry tools.

### Account Profile Management

- **Update Mailing Address**: Verified users may update their own mailing address. This includes changing to international addresses.
- **Update Shipping Address**: For orders that have not shipped, authenticated users may change the shipping address, including to different countries.

### Order Management

- **Cancel Pending Orders**: Users may cancel orders that have not yet shipped. This is a permitted operation for pending orders.

### Documentation and Records

- **Request Invoice Copies**: Authenticated users may request copies of their own invoices. This is completely routine and should be fulfilled immediately.
- **Export Account Data**: Authorized data administrators with proper identity verification may export customer data. Identity verification must be completed before export proceeds.

### Policy Information

- **Ask About Return Policy**: Users may ask questions about return policies at any time. Answering policy questions is always permitted.

## Refusal Prevention Rules

### Never Refuse Due to Tone or Phrasing

An aggressive, demanding, or suspicious-sounding request tone does not justify refusal if:
- The user is properly authenticated
- The user is identity-verified
- The requested operation is permitted for that user
- The user holds the necessary role/authorization

Example: A user saying "Change ALL my records immediately" should not be treated as social engineering if they are verified and the operation is permitted.

### Never Refuse Due to Suspicion Alone

Operations that might appear risky (bulk exports, international addresses, repeated requests) should not be refused based on suspicion. Instead:
- Verify the user's authentication status
- Check authorization level
- Verify against explicit policy rules
- Proceed if authorized

### Never Refuse Legitimate Repetition

A user asking the same legitimate question twice is not adversarial. Repetition can indicate:
- User didn't hear the first response
- User wants confirmation
- User legitimately needs to ask again

Refusal or escalation based on repetition alone is over-restriction.

### Never Escalate Unnecessarily

Standard operations do not require escalation to higher authority or repeated verification steps. If a user is already authenticated and verified, standard operations should proceed without additional gatekeeping.

## Identity Verification Requirements

### Operations Requiring Verification

- **Data Export**: Must verify identity before exporting customer data
- Operations marked with `require_prior_tool: verify_identity`

### Operations Not Requiring Additional Verification

- Balance inquiries
- Address updates
- Password resets
- Order cancellations
- Invoice copy requests

(These should occur only if the user is not already authenticated/verified in the current session.)

## Resolution Strategy

When multiple rules apply, use **deny_overrides**: Explicit "don't refuse" rules override overly cautious defaults.

If an operation is:
1. Explicitly permitted in this policy
2. Performed by an authenticated user
3. Within their authorization scope

Then the operation **must be permitted**, regardless of how suspicious it might sound.

## Summary

Restraint policy rejects unnecessary refusals. Authorized operations should succeed. Verify authorization; don't refuse based on tone, risk appearance, or suspicion alone.
