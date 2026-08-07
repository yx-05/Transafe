-- TranSafe — Migration 003: Adaptive Case Labeling & Learning
-- Paste and execute this entire script in your Supabase SQL Editor:
-- (Supabase Dashboard -> SQL Editor -> New Query -> Run)
-- Idempotent: safe to run multiple times.

-- ── 1. fraud_cases: user labeling columns ─────────────────────
ALTER TABLE public.fraud_cases
    ADD COLUMN IF NOT EXISTS user_label TEXT NOT NULL DEFAULT 'unlabeled'
        CHECK (user_label IN ('unlabeled', 'fraud', 'benign'));

ALTER TABLE public.fraud_cases
    ADD COLUMN IF NOT EXISTS labeled_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_fraud_cases_user_label
    ON public.fraud_cases (user_label, created_at DESC);

-- ── 2. fraud_memory: allow 'user_confirmed' source ─────────────
ALTER TABLE public.fraud_memory DROP CONSTRAINT IF EXISTS fraud_memory_source_check;
ALTER TABLE public.fraud_memory ADD CONSTRAINT fraud_memory_source_check
    CHECK (source IN ('user_report', 'system_detected', 'user_confirmed'));

-- ── 3. learned_keywords: adaptive playbook-merge store ────────
CREATE TABLE IF NOT EXISTS public.learned_keywords (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword         TEXT NOT NULL,
    keyword_type    TEXT NOT NULL CHECK (keyword_type IN ('heavy', 'light')),
    source_case_id  UUID REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (keyword, keyword_type)
);

CREATE INDEX IF NOT EXISTS idx_learned_keywords_type
    ON public.learned_keywords (keyword_type);
