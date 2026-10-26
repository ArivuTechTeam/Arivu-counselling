import {sqliteTable,text,integer} from 'drizzle-orm/sqlite-core';

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
