"""Recording on by default: every organization gets a call-settings row at
creation (recording on, 30 days). Existing rows count as confirmed."""

from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE organization_call_settings
  ADD COLUMN recording_confirmed_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION organization_call_settings_default() RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO organization_call_settings (organization_id, recording_enabled, recording_retention_days)
  VALUES (NEW.id, TRUE, 30)
  ON CONFLICT (organization_id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organization_call_settings_default AFTER INSERT ON organizations
  FOR EACH ROW EXECUTE FUNCTION organization_call_settings_default();

-- Organizations that exist already: same default, and no onboarding prompt.
INSERT INTO organization_call_settings (organization_id, recording_enabled, recording_retention_days)
SELECT o.id, TRUE, 30 FROM organizations o
WHERE NOT EXISTS (SELECT 1 FROM organization_call_settings s WHERE s.organization_id = o.id);

UPDATE organization_call_settings
SET recording_enabled = COALESCE(recording_enabled, TRUE),
    recording_retention_days = COALESCE(recording_retention_days, 30),
    recording_confirmed_at = now();
""")


def downgrade() -> None:
    op.execute("""
DROP TRIGGER IF EXISTS organization_call_settings_default ON organizations;
DROP FUNCTION IF EXISTS organization_call_settings_default();
ALTER TABLE organization_call_settings DROP COLUMN recording_confirmed_at;
""")
