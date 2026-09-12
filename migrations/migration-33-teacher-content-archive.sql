-- Reversible teacher cleanup: retain source files and relational history while
-- allowing old uploads to disappear from active teacher lists.
alter type document_status add value if not exists 'archived';
