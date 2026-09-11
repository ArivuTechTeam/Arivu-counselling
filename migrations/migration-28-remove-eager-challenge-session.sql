-- Challenge creation now creates only the shareable game. Each participant,
-- including the creator, starts a practice session later from the game lobby.
-- Remove the obsolete service-role helper that created both rows eagerly.

drop function if exists public.create_challenge_with_session(
  uuid, uuid, text, uuid, uuid[], jsonb, jsonb, integer, text, timestamptz,
  timestamptz
);
