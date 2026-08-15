-- Records database — the READ-FROM datastore for the prior-authorization demo.
--
-- ALL DATA IN THIS FILE IS SYNTHETIC. Names, MRNs, dates of birth, addresses,
-- phone numbers, e-mail addresses, policy numbers, NPIs and prescription
-- numbers are invented. They are shaped like the real thing on purpose: the
-- demo exists to move realistic personal data through a realistic system.

CREATE TABLE members (
    mrn              TEXT PRIMARY KEY,
    full_name        TEXT NOT NULL,
    date_of_birth    DATE NOT NULL,
    gender           TEXT,
    address          TEXT,
    phone            TEXT,
    email            TEXT,
    policy_number    TEXT NOT NULL,
    coverage_tier    TEXT,
    plan_name        TEXT
);

CREATE TABLE policies (
    policy_number            TEXT PRIMARY KEY,
    plan_name                TEXT NOT NULL,
    coverage_tier            TEXT,
    annual_deductible_usd    NUMERIC(10,2),
    prior_auth_required      BOOLEAN NOT NULL DEFAULT TRUE,
    excluded_procedure_codes TEXT[],
    effective_from           DATE,
    effective_to             DATE
);

CREATE TABLE encounters (
    id                     SERIAL PRIMARY KEY,
    mrn                    TEXT NOT NULL REFERENCES members(mrn),
    encounter_date         DATE NOT NULL,
    department             TEXT,
    hospital_name          TEXT,
    diagnosis_name         TEXT,
    icd10_code             TEXT,
    attending_provider_npi TEXT
);

CREATE TABLE medications (
    id                  SERIAL PRIMARY KEY,
    mrn                 TEXT NOT NULL REFERENCES members(mrn),
    drug_name           TEXT NOT NULL,
    dose                TEXT,
    frequency           TEXT,
    started_on          DATE,
    prescription_number TEXT,
    active              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE lab_results (
    id             SERIAL PRIMARY KEY,
    mrn            TEXT NOT NULL REFERENCES members(mrn),
    test_name      TEXT NOT NULL,
    result_value   TEXT,
    unit           TEXT,
    collected_on   DATE,
    interpretation TEXT
);

INSERT INTO members (mrn, full_name, date_of_birth, gender, address, phone, email, policy_number, coverage_tier, plan_name) VALUES
 ('MRN-4417822', 'Miriam Okonkwo',   '1968-03-14', 'female', '412 Fairmount Ave, Apt 7B, Baltimore, MD 21217', '+1-410-555-0142', 'm.okonkwo@examplemail.net', 'HP-88213445', 'gold',     'Meridian Gold PPO'),
 ('MRN-9930517', 'Tomasz Bielawski', '1955-11-02', 'male',   '88 Larkspur Lane, Rochester, NY 14620',          '+1-585-555-0197', 't.bielawski@examplemail.net', 'HP-44120987', 'silver',   'Meridian Silver HMO'),
 ('MRN-2261094', 'Aisha Rahimi',     '1990-07-29', 'female', '1530 Cedar Springs Rd, Unit 12, Dallas, TX 75201','+1-214-555-0163', 'a.rahimi@examplemail.net',    'HP-77650321', 'bronze',   'Meridian Bronze EPO'),
 ('MRN-7784310', 'Devon Whitfield',  '1982-01-19', 'male',   '9 Harborview Ct, Portland, ME 04101',            '+1-207-555-0118', 'd.whitfield@examplemail.net', 'HP-88213446', 'gold',     'Meridian Gold PPO'),
 ('MRN-5518203', 'Lucia Ferreira',   '1974-09-06', 'female', '2201 Mission St, San Francisco, CA 94110',       '+1-415-555-0176', 'l.ferreira@examplemail.net',  'HP-31009887', 'platinum', 'Meridian Platinum PPO'),
 ('MRN-3092776', 'Henry Adeyemi',    '2001-05-23', 'male',   '77 Beechwood Dr, Columbus, OH 43201',            '+1-614-555-0155', 'h.adeyemi@examplemail.net',   'HP-44120988', 'silver',   'Meridian Silver HMO');

INSERT INTO policies (policy_number, plan_name, coverage_tier, annual_deductible_usd, prior_auth_required, excluded_procedure_codes, effective_from, effective_to) VALUES
 ('HP-88213445', 'Meridian Gold PPO',     'gold',     1500.00, TRUE,  ARRAY['0554T','0555T'],               '2026-01-01', '2026-12-31'),
 ('HP-44120987', 'Meridian Silver HMO',   'silver',   3500.00, TRUE,  ARRAY['0554T','0555T','93312','70553'],'2026-01-01', '2026-12-31'),
 ('HP-77650321', 'Meridian Bronze EPO',   'bronze',   7000.00, TRUE,  ARRAY['0554T','0555T','93312','70553','29881'], '2026-01-01', '2026-12-31'),
 ('HP-88213446', 'Meridian Gold PPO',     'gold',     1500.00, TRUE,  ARRAY['0554T','0555T'],               '2026-01-01', '2026-12-31'),
 ('HP-31009887', 'Meridian Platinum PPO', 'platinum',  500.00, FALSE, ARRAY[]::TEXT[],                      '2026-01-01', '2026-12-31'),
 ('HP-44120988', 'Meridian Silver HMO',   'silver',   3500.00, TRUE,  ARRAY['0554T','0555T','93312','70553'],'2026-01-01', '2026-12-31');

INSERT INTO encounters (mrn, encounter_date, department, hospital_name, diagnosis_name, icd10_code, attending_provider_npi) VALUES
 ('MRN-4417822', '2026-06-11', 'Rheumatology',   'St. Agnes Regional Hospital', 'Rheumatoid arthritis, unspecified',        'M06.9',  '1487302259'),
 ('MRN-4417822', '2026-02-03', 'Internal Medicine','St. Agnes Regional Hospital','Essential hypertension',                   'I10',    '1043778812'),
 ('MRN-9930517', '2026-05-27', 'Cardiology',     'Lakeside General Hospital',   'Chronic systolic heart failure',           'I50.22', '1558903221'),
 ('MRN-9930517', '2026-03-15', 'Nephrology',     'Lakeside General Hospital',   'Chronic kidney disease, stage 3',          'N18.3',  '1229004417'),
 ('MRN-2261094', '2026-07-02', 'Neurology',      'Trinity Park Medical Center', 'Migraine without aura, intractable',       'G43.019','1330558842'),
 ('MRN-7784310', '2026-04-19', 'Orthopedics',    'Harborview Community Hospital','Tear of medial meniscus, right knee',     'S83.241A','1667203355'),
 ('MRN-5518203', '2026-06-30', 'Oncology',       'Bay Ridge Cancer Institute',  'Malignant neoplasm of breast, upper-outer', 'C50.411','1774829906'),
 ('MRN-3092776', '2026-05-08', 'Endocrinology',  'Buckeye Metro Hospital',      'Type 1 diabetes mellitus without complications','E10.9','1885640022');

INSERT INTO medications (mrn, drug_name, dose, frequency, started_on, prescription_number, active) VALUES
 ('MRN-4417822', 'Methotrexate',  '15 mg',   'weekly',      '2026-02-10', 'RX-5590231', TRUE),
 ('MRN-4417822', 'Lisinopril',    '10 mg',   'once daily',  '2026-02-03', 'RX-5590188', TRUE),
 ('MRN-9930517', 'Furosemide',    '40 mg',   'twice daily', '2026-03-20', 'RX-6612044', TRUE),
 ('MRN-9930517', 'Carvedilol',    '6.25 mg', 'twice daily', '2026-03-20', 'RX-6612045', TRUE),
 ('MRN-2261094', 'Sumatriptan',   '100 mg',  'as needed',   '2026-07-02', 'RX-7729551', TRUE),
 ('MRN-7784310', 'Ibuprofen',     '600 mg',  'three times daily','2026-04-19','RX-8830127', TRUE),
 ('MRN-5518203', 'Anastrozole',   '1 mg',    'once daily',  '2026-07-05', 'RX-9940318', TRUE),
 ('MRN-3092776', 'Insulin glargine','22 units','at bedtime', '2026-05-08', 'RX-1120887', TRUE);

INSERT INTO lab_results (mrn, test_name, result_value, unit, collected_on, interpretation) VALUES
 ('MRN-4417822', 'C-reactive protein', '18.4',  'mg/L',   '2026-06-10', 'high'),
 ('MRN-4417822', 'Rheumatoid factor',  '96',    'IU/mL',  '2026-06-10', 'high'),
 ('MRN-9930517', 'NT-proBNP',          '1840',  'pg/mL',  '2026-05-26', 'high'),
 ('MRN-9930517', 'Creatinine',         '1.9',   'mg/dL',  '2026-05-26', 'high'),
 ('MRN-2261094', 'Hemoglobin',         '13.1',  'g/dL',   '2026-07-01', 'normal'),
 ('MRN-7784310', 'ESR',                '11',    'mm/hr',  '2026-04-18', 'normal'),
 ('MRN-5518203', 'CA 15-3',            '41',    'U/mL',   '2026-06-29', 'high'),
 ('MRN-3092776', 'Hemoglobin A1c',     '8.7',   '%',      '2026-05-07', 'high');
