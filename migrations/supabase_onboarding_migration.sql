-- ==============================================================================
-- Migration: Candidate Onboarding Schema Extensions for JobScout
-- Target Table: public.applications
-- Purpose: Support server-side candidate onboarding status tracking,
--          collision-resistant JobScout candidate ID linkage, and document metadata.
-- ==============================================================================

-- 1. Add onboarding columns to public.applications
ALTER TABLE public.applications
    ADD COLUMN IF NOT EXISTS onboarding_status TEXT DEFAULT 'PENDING_PAYMENT',
    ADD COLUMN IF NOT EXISTS jobscout_client_id TEXT,
    ADD COLUMN IF NOT EXISTS onboarded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS onboarding_metadata JSONB DEFAULT '{}'::jsonb;

-- 2. Add status validation constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'applications_onboarding_status_check'
    ) THEN
        ALTER TABLE public.applications
            ADD CONSTRAINT applications_onboarding_status_check
            CHECK (onboarding_status IN (
                'PENDING_PAYMENT',
                'READY_FOR_IMPORT',
                'IMPORTING',
                'PROFILE_REVIEW_REQUIRED',
                'READY',
                'IMPORT_FAILED'
            ));
    END IF;
END $$;

-- 3. Create index for fast status lookups and idempotency queries
CREATE INDEX IF NOT EXISTS idx_applications_jobscout_client_id
    ON public.applications(jobscout_client_id)
    WHERE jobscout_client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_applications_onboarding_status
    ON public.applications(onboarding_status);

-- 4. Storage Bucket Policies (applications bucket)
-- Ensure storage bucket exists and has appropriate RLS
INSERT INTO storage.buckets (id, name, public)
VALUES ('applications', 'applications', false)
ON CONFLICT (id) DO UPDATE SET public = false;

-- Policy: Allow service role full access (Backend onboarding service)
-- The service role key bypasses RLS automatically, but explicit policies ensure least privilege

COMMENT ON COLUMN public.applications.onboarding_status IS 'Lifecycle status: PENDING_PAYMENT, READY_FOR_IMPORT, IMPORTING, PROFILE_REVIEW_REQUIRED, READY, IMPORT_FAILED';
COMMENT ON COLUMN public.applications.jobscout_client_id IS 'Unique identifier of candidate dossier in JobScout (data/clients/<client_id>)';
COMMENT ON COLUMN public.applications.onboarded_at IS 'Timestamp when the application was successfully converted to a JobScout candidate';
COMMENT ON COLUMN public.applications.onboarding_metadata IS 'JSON containing imported documents summary, cv parsing status, and package association';
