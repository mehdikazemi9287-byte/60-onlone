-- Legal checklist (pre-launch): statutory 7-working-day withdrawal (E-commerce Law art. 37),
-- recorded acceptance of terms with version/hash/IP (evidence for courts and regulators).

-- Goods the law lets us exclude from withdrawal: perishable, custom-made, opened hygiene, digital.
ALTER TABLE products ADD COLUMN withdrawal_exempt_reason TEXT
    CHECK (withdrawal_exempt_reason IS NULL OR withdrawal_exempt_reason IN ('perishable', 'custom_made', 'hygiene', 'digital'));

-- 'withdrawal' = statutory, no reason required; 'return' = defect/other (existing flow).
ALTER TABLE order_return_requests ADD COLUMN kind TEXT NOT NULL DEFAULT 'return'
    CHECK (kind IN ('return', 'withdrawal'));
ALTER TABLE order_return_requests ADD COLUMN refund_due_at TEXT;

-- Published legal texts; a new version is a new row (never edited).
CREATE TABLE IF NOT EXISTS legal_documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_key        TEXT NOT NULL CHECK (doc_key IN ('buyer_terms', 'seller_terms', 'org_terms', 'privacy', 'credit_terms')),
    version        TEXT NOT NULL,
    text_sha256    TEXT NOT NULL CHECK (length(text_sha256) = 64),
    url            TEXT NOT NULL,
    effective_from TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (doc_key, version)
);
CREATE TRIGGER IF NOT EXISTS legal_documents_no_update BEFORE UPDATE ON legal_documents
BEGIN SELECT RAISE(ABORT, 'legal_documents are immutable; publish a new version'); END;
CREATE TRIGGER IF NOT EXISTS legal_documents_no_delete BEFORE DELETE ON legal_documents
BEGIN SELECT RAISE(ABORT, 'legal_documents are immutable'); END;

-- Placeholder versions: replace the hash/url with the lawyer-approved text before launch.
INSERT INTO legal_documents (doc_key, version, text_sha256, url) VALUES
    ('buyer_terms', 'draft-1405-1', '0000000000000000000000000000000000000000000000000000000000000000', '/terms'),
    ('seller_terms', 'shop-terms-1405-1', '0000000000000000000000000000000000000000000000000000000000000000', '/terms/sellers'),
    ('privacy', 'draft-1405-1', '0000000000000000000000000000000000000000000000000000000000000000', '/privacy');

-- Append-only evidence of who accepted which text, when, from where.
CREATE TABLE IF NOT EXISTS terms_acceptances (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    document_id    INTEGER NOT NULL REFERENCES legal_documents(id),
    context        TEXT NOT NULL CHECK (context IN ('checkout', 'seller_apply', 'org_join', 'signup', 'explicit')),
    context_ref    TEXT,
    ip_address     TEXT,
    user_agent     TEXT,
    accepted_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_terms_acceptances_user ON terms_acceptances(user_id, document_id);
CREATE TRIGGER IF NOT EXISTS terms_acceptances_no_update BEFORE UPDATE ON terms_acceptances
BEGIN SELECT RAISE(ABORT, 'terms_acceptances are append-only'); END;
CREATE TRIGGER IF NOT EXISTS terms_acceptances_no_delete BEFORE DELETE ON terms_acceptances
BEGIN SELECT RAISE(ABORT, 'terms_acceptances are append-only'); END;
