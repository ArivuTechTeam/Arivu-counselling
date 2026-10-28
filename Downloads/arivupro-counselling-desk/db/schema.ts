import {sqliteTable,text,integer,real} from 'drizzle-orm/sqlite-core';

export const requests=sqliteTable('requests',{
  id:text('id').primaryKey(),
  userId:text('user_id').notNull(),
  name:text('name').notNull(),
  email:text('email').notNull(),
  phone:text('phone').notNull(),
  course:text('course').notNull(),
  level:text('level').notNull(),
  slot:text('slot').notNull(),
  concern:text('concern').notNull(),
  status:text('status').notNull().default('Requested'),
  notes:text('notes').notNull().default(''),
  meetLink:text('meet_link').notNull().default(''),
  otpVerified:integer('otp_verified',{mode:'boolean'}).notNull().default(false),
  emailSent:integer('email_sent',{mode:'boolean'}).notNull().default(false),
  created:text('created').notNull(),
});

export const staffOwner=sqliteTable('staff_owner',{
  id:text('id').primaryKey(),
  userId:text('user_id').notNull(),
});

// Temporary OTP store — TTL enforced in app logic
export const otpStore=sqliteTable('otp_store',{
  phone:text('phone').primaryKey(),
  code:text('code').notNull(),
  expiresAt:text('expires_at').notNull(),
  attempts:integer('attempts').notNull().default(0),
});

export const botSessions=sqliteTable('bot_sessions',{
  id:text('id').primaryKey(),
  startedAt:text('started_at').notNull(),
  endedAt:text('ended_at'),
  language:text('language').default(''),
  turnCount:integer('turn_count').default(0),
  escalated:integer('escalated',{mode:'boolean'}).default(false),
  escalationScore:real('escalation_score').default(0),
  course:text('course').default(''),
});

export const botMessages=sqliteTable('bot_messages',{
  id:text('id').primaryKey(),
  sessionId:text('session_id').references(()=>botSessions.id),
  role:text('role').notNull(),
  content:text('content').notNull(),
  sentimentScore:real('sentiment_score').default(0),
  timestamp:text('timestamp').notNull(),
});

export const botLeads=sqliteTable('bot_leads',{
  id:text('id').primaryKey(),
  sessionId:text('session_id').notNull(),
  name:text('name').default(''),
  phone:text('phone').default(''),
  email:text('email').default(''),
  course:text('course').default(''),
  concern:text('concern').default(''),
  calendlyBooked:integer('calendly_booked',{mode:'boolean'}).default(false),
  created:text('created').notNull(),
});

export const wpData=sqliteTable('wp_data',{
  id:integer('id').primaryKey({autoIncrement:true}),
  pageSlug:text('page_slug').notNull(),
  title:text('title').notNull(),
  content:text('content').notNull(),
  acfFields:text('acf_fields').notNull(),
  updatedAt:text('updated_at').notNull(),
});
