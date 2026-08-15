-- Authorizations database — the WRITE-TO datastore for the prior-authorization demo.
-- Starts empty; every row in it is written by priorauth_authstore_tool at runtime.
-- The rows carry synthetic personal data by design.

CREATE TABLE referrals (
    referral_id             TEXT PRIMARY KEY,
    received_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    patient_name            TEXT NOT NULL,
    mrn                     TEXT NOT NULL,
    date_of_birth           DATE,
    policy_number           TEXT,
    diagnosis_name          TEXT,
    icd10_code              TEXT,
    requested_procedure     TEXT,
    procedure_code          TEXT,
    requesting_provider_npi TEXT,
    clinical_note           TEXT
);

CREATE TABLE decisions (
    id                  SERIAL PRIMARY KEY,
    referral_id         TEXT NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    mrn                 TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    eligibility_verdict TEXT,
    clinical_verdict    TEXT,
    rationale           TEXT
);

CREATE INDEX decisions_referral_idx ON decisions (referral_id);
