-- JobScout WhatsApp AI Customer Support Center Schema
-- SQLite DDL Migration

PRAGMA foreign_keys = ON;

-- 1. Conversations Table
CREATE TABLE IF NOT EXISTS whatsapp_conversations (
    id TEXT PRIMARY KEY,
    wa_id TEXT UNIQUE NOT NULL,
    client_id TEXT,
    client_code TEXT,
    display_name TEXT DEFAULT '',
    assigned_agent TEXT DEFAULT '',
    mode TEXT DEFAULT 'AI_ACTIVE',
    last_inbound_at TEXT,
    last_activity_at TEXT NOT NULL,
    escalation_status TEXT DEFAULT 'none',
    escalation_reason TEXT DEFAULT '',
    unread_count INTEGER DEFAULT 0,
    summary TEXT DEFAULT '',
    ai_config_override TEXT DEFAULT '{}',
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wa_conv_wa_id ON whatsapp_conversations(wa_id);
CREATE INDEX IF NOT EXISTS idx_wa_conv_client_id ON whatsapp_conversations(client_id);
CREATE INDEX IF NOT EXISTS idx_wa_conv_mode ON whatsapp_conversations(mode);
CREATE INDEX IF NOT EXISTS idx_wa_conv_escalation ON whatsapp_conversations(escalation_status);
CREATE INDEX IF NOT EXISTS idx_wa_conv_last_activity ON whatsapp_conversations(last_activity_at DESC);

-- 2. Messages Table
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id TEXT PRIMARY KEY,
    provider_message_id TEXT UNIQUE,
    conversation_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    sender_type TEXT NOT NULL,
    sender_name TEXT DEFAULT '',
    content TEXT NOT NULL,
    media_type TEXT DEFAULT 'text',
    media_url TEXT DEFAULT '',
    media_meta TEXT DEFAULT '{}',
    delivery_status TEXT DEFAULT 'pending',
    failure_reason TEXT DEFAULT '',
    ai_metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES whatsapp_conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wa_msg_conv_id ON whatsapp_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_wa_msg_provider_id ON whatsapp_messages(provider_message_id);
CREATE INDEX IF NOT EXISTS idx_wa_msg_created_at ON whatsapp_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_wa_msg_direction_status ON whatsapp_messages(direction, delivery_status);

-- 3. Audit Logs Table
CREATE TABLE IF NOT EXISTS whatsapp_audit_logs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    old_state TEXT DEFAULT '',
    new_state TEXT DEFAULT '',
    details TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES whatsapp_conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wa_audit_conv_id ON whatsapp_audit_logs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_wa_audit_created_at ON whatsapp_audit_logs(created_at DESC);

-- 4. Knowledge Base Table
CREATE TABLE IF NOT EXISTS whatsapp_knowledge_base (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'faq',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wa_kb_category ON whatsapp_knowledge_base(category);
CREATE INDEX IF NOT EXISTS idx_wa_kb_active ON whatsapp_knowledge_base(is_active);

-- 5. WhatsApp System Settings Table
CREATE TABLE IF NOT EXISTS whatsapp_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
