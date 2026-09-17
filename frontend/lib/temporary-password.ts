const PASSWORD_GROUPS = [
  "ABCDEFGHJKLMNPQRSTUVWXYZ",
  "abcdefghijkmnopqrstuvwxyz",
  "23456789",
  "!@#$%",
];

export function generateTemporaryPassword(): string {
  const alphabet = PASSWORD_GROUPS.join("");
  const random = crypto.getRandomValues(new Uint32Array(28));
  const characters = PASSWORD_GROUPS.map(
    (group, index) => group[random[index] % group.length],
  );

  for (let index = characters.length; index < 14; index += 1) {
    characters.push(alphabet[random[index] % alphabet.length]);
  }

  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swapIndex = random[index + 14] % (index + 1);
    [characters[index], characters[swapIndex]] = [
      characters[swapIndex],
      characters[index],
    ];
  }

  return characters.join("");
}

export function validTemporaryPassword(password: string): boolean {
  return (
    password.length >= 12 &&
    /[A-Z]/.test(password) &&
    /[a-z]/.test(password) &&
    /\d/.test(password)
  );
}
