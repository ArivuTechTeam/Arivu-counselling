This is the frontend for quiz-generator (Next.js 14, App Router), bootstrapped
with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

**Port:** this project runs on **3001**, not Next's default 3000 — port 3000
is used locally by a different project (`arivupro_examapp`) on this machine.
`pnpm dev` (see `scripts.dev` in `package.json`) already passes `-p 3001`, so
just run:

```bash
pnpm dev
```

Open [http://localhost:3001](http://localhost:3001) with your browser to see
the result. The backend (FastAPI) runs on **8001** locally for the same
reason — see `backend/.env.example` / `NEXT_PUBLIC_API_BASE_URL` in
`.env.local`.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
