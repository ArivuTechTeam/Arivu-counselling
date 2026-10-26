CREATE TABLE `requests` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`name` text NOT NULL,
	`email` text NOT NULL,
	`phone` text NOT NULL,
	`course` text NOT NULL,
	`level` text NOT NULL,
	`slot` text NOT NULL,
	`concern` text NOT NULL,
	`status` text DEFAULT 'Requested' NOT NULL,
	`notes` text DEFAULT '' NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `staff_owner` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL
);
