CREATE TABLE `otp_store` (
	`phone` text PRIMARY KEY NOT NULL,
	`code` text NOT NULL,
	`expires_at` text NOT NULL,
	`attempts` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
ALTER TABLE `requests` ADD `meet_link` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `requests` ADD `otp_verified` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `requests` ADD `email_sent` integer DEFAULT false NOT NULL;