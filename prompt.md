# ONE-SHOT IMPLEMENTATION PROMPT — TRINETRA TRANSACTION RISK SCORING & AML PATTERN DETECTION

Act as a senior financial technology architect, Python/FastAPI backend engineer, React frontend engineer, and fraud detection specialist.

Your task is to implement TWO complete, production-structured features inside my existing project, **TRINETRA — An Agentic Financial Fraud Intelligence Platform**.

Do not create a separate demo application. Integrate both features into the existing TRINETRA application, backend, database, authentication system, and SOC analyst dashboard.

The two features to implement are:

1. **Intelligent Transaction Risk Scoring**
2. **AML Pattern Detection**

Both features must be functional end-to-end, with real backend logic, persistent database storage, APIs, frontend interfaces, visualisations, and integration with the existing application.

---

# 1. FIRST: UNDERSTAND THE EXISTING CODEBASE

Before writing or modifying any code:

- Inspect the entire existing frontend and backend architecture.
- Identify the existing FastAPI application structure, routers, services, database models, authentication, Supabase integration, and frontend routing.
- Understand how the existing SOC dashboard retrieves and displays data.
- Identify existing transaction tables, account tables, beneficiary tables, fraud alerts, risk scores, and investigation cases.
- Inspect the existing LangGraph agent architecture and determine how transaction risk findings can be passed to the investigation workflow.
- Reuse existing components, API conventions, authentication, database connections, and styling.
- Do not create duplicate tables, services, APIs, or components when equivalent functionality already exists.
- Do not break or remove existing features.

If a required database entity does not exist, implement it using the project's existing database conventions.

Do not stop after producing an architecture plan. Inspect, plan, implement, test, and integrate the features.

# 2. FEATURE ONE: INTELLIGENT TRANSACTION RISK SCORING

## Objective

Build an intelligent transaction analysis engine that evaluates every incoming transaction using multiple financial and behavioural risk indicators.

Every analysed transaction should receive:

- A numerical risk score between 0 and 100.
- A risk classification: LOW, MEDIUM, HIGH, or CRITICAL.
- A list of detected risk indicators.
- A human-readable explanation of why the transaction was flagged.
- Supporting evidence and relevant account history.
- A recommended next action for the fraud analyst.

The system must use explainable, deterministic risk rules as its foundation. Do not depend entirely on an LLM to calculate transaction risk.

## A. Risk indicators to implement

Implement the following detection rules.

### 1. Unusually large transaction

Compare the current transaction amount against the account's historical transaction behaviour.

Detect when:
- Transaction amount is significantly higher than the account's historical average.
- Transaction amount exceeds a configurable multiple of the historical average.
- Transaction amount is unusually large compared with the account's recent transaction distribution.

Use account-specific historical baselines wherever sufficient transaction history is available.

Handle accounts with insufficient historical data separately. Do not invent an account baseline.

### 2. New beneficiary receiving a high-value transaction

Detect when:
- The beneficiary has never previously received a transaction from the account.
- The beneficiary is newly added.
- A new beneficiary receives a transaction significantly higher than the account's normal payment amount.

Record the beneficiary ID and relevant transaction evidence.

### 3. Multiple transactions within a short period

Detect unusual transaction frequency.

Analyse configurable time windows, such as:
- 5 minutes.
- 30 minutes.
- 1 hour.
- 24 hours.

Detect repeated transactions that exceed configurable account-specific or policy-based thresholds.

### 4. Unusual transaction timing

Identify transactions occurring at unusual hours compared with the account's historical transaction patterns.

For example:
- An account that normally transacts during daytime suddenly initiates several high-value transactions during unusual hours.

Do not automatically flag every night-time transaction. Consider the account's historical behaviour.

### 5. Sudden increase in outgoing payments

Calculate outgoing transaction totals over configurable time windows.

Compare recent outgoing payments with:
- Historical average outgoing value.
- Historical transaction frequency.
- Previous account activity.

Flag unusual increases.

### 6. Transactions involving previously flagged entities

Check whether the transaction involves:
- Previously flagged beneficiary accounts.
- Suspicious account identifiers.
- Watchlisted entities.
- Accounts associated with unresolved fraud investigations.

Reuse the existing TRINETRA fraud intelligence/watchlist functionality if available.

Do not mark an entity fraudulent merely because it has no previous history.

## B. Risk scoring engine

Build a configurable weighted scoring system.

Each detected risk indicator should contribute to the transaction's overall risk score.

Suggested initial demonstration weights:

| Risk indicator | Example points |
|---|---:|
| Unusually large transaction | 20 |
| New beneficiary + high-value payment | 20 |
| Unusual transaction frequency | 15 |
| Unusual transaction timing | 10 |
| Sudden outgoing payment increase | 15 |
| Previously flagged beneficiary/entity | 20 |

These are initial demo weights, not validated banking risk parameters. Store them in configuration so they can be adjusted without changing the detection code.

Requirements:
- Score must never exceed 100 or fall below 0.
- Avoid repeatedly counting the same underlying evidence.
- Store the individual signals contributing to the score.
- Store the rule identifier and evidence behind each signal.
- Make the score explainable to a fraud analyst.
- Support configurable thresholds for risk classification.

Suggested initial classifications:

- 0–24: LOW
- 25–49: MEDIUM
- 50–74: HIGH
- 75–100: CRITICAL

Make these thresholds configurable.

Important: This is a risk indicator, not a mathematically validated probability that fraud has occurred.

## C. Transaction analysis workflow

Implement the following flow:

1. A transaction is received through the existing transaction ingestion mechanism.
2. Retrieve the associated account and beneficiary information.
3. Retrieve the relevant historical transaction information.
4. Execute all applicable risk detection rules.
5. Generate individual risk signals.
6. Calculate the unified transaction risk score.
7. Assign a risk classification.
8. Persist the result and evidence in the database.
9. Generate an alert if the configured alert threshold is reached.
10. Make the result available to the SOC dashboard.
11. If appropriate, pass the structured findings to the existing LangGraph investigation workflow.

The analysis should be idempotent: processing the same transaction again must not create duplicate alerts or duplicate risk assessments.

---

# 3. FEATURE TWO: AML PATTERN DETECTION

## Objective

Build a dedicated AML monitoring engine that detects suspicious transaction patterns that may require further investigation.

This is separate from ordinary transaction risk scoring.

The engine must identify patterns across multiple transactions, accounts, beneficiaries, and time periods.

Do not automatically classify an account or person as a money launderer.

Generate explainable AML alerts for analyst investigation.

## A. AML detection patterns

Implement the following four detection categories.

### 1. Potential transaction structuring

Detect repeated transactions that appear to be deliberately split into smaller amounts around a configurable monitoring threshold.

Example:

An account makes several deposits:

- ₹9,500
- ₹9,700
- ₹9,600
- ₹9,800

If the configured monitoring threshold is ₹10,000, the system should be capable of identifying repeated deposits close to that threshold.

Detection logic should consider:
- Configurable threshold.
- Percentage range below the threshold.
- Number of transactions.
- Cumulative transaction value.
- Time window.
- Repeated patterns across multiple days.

Do not flag a single transaction just because it is close to a threshold.

Require repeated activity or additional supporting indicators before assigning elevated severity.

IMPORTANT: Monitoring thresholds must be configurable and must not be presented as official RBI reporting thresholds unless specifically verified and configured by the institution.

### 2. Unusual cumulative deposits

Detect accounts receiving unusually large cumulative deposits over a configurable period.

Analyse:
- Total incoming value.
- Number of deposits.
- Number of distinct sending accounts.
- Historical incoming transaction patterns.
- Changes in deposit frequency and value.

Example:

An account that normally receives ₹10,000–₹20,000 per day suddenly receives ₹3,00,000 from several different accounts.

Flag the unusual cumulative deposit pattern and provide supporting transaction details.

### 3. Rapid movement of funds between accounts

Detect potential rapid movement or pass-through behaviour.

Example:

Account A sends ₹50,000 to Account B.

Account B subsequently transfers ₹45,000 to Account C within a short period.

Account C then distributes the money to additional accounts.

Identify:
- Incoming and outgoing transaction sequences.
- Time difference between incoming and outgoing payments.
- Amounts transferred.
- Percentage of incoming funds moved onward.
- Number of intermediary accounts.
- Related transaction IDs.

Use a configurable time window.

Where exact fund tracing is not possible because funds are mixed with other balances, clearly label the result as a potential flow pattern rather than claiming that specific money was traced.

### 4. Repeated transactions involving common beneficiaries

Detect patterns where multiple accounts repeatedly transfer money to the same beneficiary.

Identify:
- Number of unique sending accounts.
- Total amount received by the common beneficiary.
- Frequency of transfers.
- Transaction time distribution.
- Whether the beneficiary is already associated with suspicious cases.

This should also identify beneficiaries receiving money from multiple unrelated accounts within a configured time window.

Generate an AML signal when the pattern satisfies configured detection conditions.

## B. AML alert generation

Each detected AML pattern must produce a structured alert containing:

- Unique alert ID.
- Pattern category.
- Account or beneficiary involved.
- Severity.
- Risk score, if applicable.
- Detection timestamp.
- Relevant transaction IDs.
- Total transaction value.
- Number of transactions.
- Detection window.
- Explanation of the detected pattern.
- Supporting evidence.
- Investigation status.

Suggested categories:

- POSSIBLE_STRUCTURING
- UNUSUAL_CUMULATIVE_DEPOSITS
- RAPID_FUND_MOVEMENT
- COMMON_BENEFICIARY_PATTERN

Suggested statuses:

- NEW
- UNDER_REVIEW
- ESCALATED
- RESOLVED
- FALSE_POSITIVE

Prevent duplicate alerts for the same entity, pattern, and overlapping detection period. Allow new alerts when genuinely new activity occurs.

AML alerts should remain distinguishable from ordinary transaction fraud alerts.

---

# 4. TECHNICAL IMPLEMENTATION REQUIREMENTS

Use the existing project stack and conventions.

Expected technology:

- Backend: Python + FastAPI.
- Frontend: Existing React + Tailwind CSS application.
- Database: Existing Supabase/PostgreSQL setup.
- Graph analysis: NetworkX if needed for rapid fund movement and beneficiary relationships.
- Data processing: Pandas or standard Python as appropriate.
- Existing agent orchestration: LangGraph.

STRICT CONSTRAINTS:

- Do not introduce Redis.
- Do not introduce multilingual processing.
- Do not introduce live call monitoring.
- Do not replace the existing architecture.
- Do not create a separate standalone application.
- Do not hardcode fake transaction data into production detection logic.
- Do not make an external LLM API call for every transaction.
- Do not use LLM-generated risk scores as the primary detection mechanism.
- Do not automatically freeze accounts, block transactions, or make irreversible banking decisions.
- Do not introduce unnecessary microservices or infrastructure.

## Database requirements

Reuse existing tables wherever possible.

If missing, create appropriate database structures for:

1. Transaction risk assessments.
2. Transaction risk signals.
3. AML alerts.
4. AML detection evidence.
5. AML monitoring configuration.
6. Account behavioural baselines, if needed.

Ensure:
- Proper foreign keys.
- Indexes on account IDs, beneficiary IDs, transaction IDs, timestamps and alert statuses.
- Appropriate uniqueness constraints.
- Database migrations or Supabase SQL migration scripts.
- Row-level security policies consistent with existing authentication and access-control patterns.

Never expose sensitive banking information to unauthorised users.

## Backend API requirements

Integrate endpoints into the existing FastAPI router structure.

Implement equivalent functionality for:

- Transaction risk analysis.
- Transaction risk assessment retrieval.
- Account risk history.
- AML alert listing.
- AML alert detail retrieval.
- AML alert investigation status updates.
- AML monitoring configuration retrieval and updates.
- Account-level AML activity summaries.

Use the existing authentication and authorisation middleware.

Validate all incoming data with Pydantic.

Use pagination and filtering for alert and transaction lists.

Return consistent API response structures and proper error handling.

## No Redis requirement

Do not use Redis for transaction counters or monitoring.

Use PostgreSQL/Supabase-backed transaction queries and indexed time-window aggregations.

For the current hackathon scale, implement efficient database queries and avoid loading entire transaction histories unnecessarily.

Use scheduled background processing only where required for periodic AML pattern scans. Reuse an existing scheduler if present; otherwise, use a lightweight existing-compatible solution such as APScheduler.

For newly ingested transactions, execute the applicable transaction-risk checks through the existing backend processing flow.

---

# 5. FRONTEND AND SOC DASHBOARD IMPLEMENTATION

Build a professional financial institution SOC interface consistent with the existing TRINETRA design system.

Do not redesign the entire application.

Add a dedicated navigation section:

**Transaction Intelligence**

Subsections:

1. Transaction Risk Monitor
2. AML Monitoring
3. Risk Configuration

## A. Transaction Risk Monitor page

Include:

### Summary cards
- Total transactions analysed.
- High-risk transactions.
- Critical-risk transactions.
- Medium-risk transactions.
- Total potentially exposed transaction value.

### Transaction table

Columns:
- Transaction ID.
- Account ID.
- Beneficiary.
- Amount.
- Timestamp.
- Risk score.
- Risk level.
- Detected signals.
- Analysis status.
- View details action.

Filters:
- Risk level.
- Date range.
- Transaction amount.
- Account ID.
- Beneficiary.
- Detection category.

### Transaction detail panel

On opening a transaction, display:

- Transaction details.
- Risk score with a visual gauge.
- Risk classification.
- Individual detected indicators.
- Explanation for each indicator.
- Supporting historical account statistics.
- Beneficiary information.
- Related previous transactions.
- Recommended analyst action.

The interface should clearly distinguish detected evidence from AI-generated recommendations.

## B. AML Monitoring page

Include:

### Summary cards
- Total AML
