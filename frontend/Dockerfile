# node:22, not 20: six @supabase/* packages declare "engines": { node: >=22 }.
# npm only warns (EBADENGINE), so a Node 20 image builds and then risks
# hard-to-attribute auth failures at runtime — and auth is precisely what runs
# through @supabase/auth-js. 22 is current LTS and supported by Next 16.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
# Tailwind v4 compiles CSS through native modules (lightningcss and
# @tailwindcss/oxide), shipped as per-platform optional dependencies.
# package-lock.json was generated on Windows, so its `packages` map contains
# only lightningcss-win32-x64-msvc and @tailwindcss/oxide-win32-x64-msvc —
# there is no linux-x64-gnu entry at all. Neither `npm ci` nor `npm install`
# can materialise a package the lockfile does not list, so a Linux build fails
# with "Cannot find module '../lightningcss.linux-x64-gnu.node'".
#
# `npm ci` is kept for reproducibility and the two Linux binaries are added
# explicitly, pinned to the versions the lockfile already resolves for their
# parent packages (lightningcss 1.32.0, @tailwindcss/oxide 4.3.2). --no-save
# leaves package.json and the lockfile untouched.
#
# MAINTENANCE: these two versions must move whenever lightningcss or
# @tailwindcss/oxide changes in the lockfile. The permanent fix is to commit a
# lockfile generated ON Linux (e.g. in CI), after which both lines can go.
# -gnu, not -musl: node:22-slim is Debian and therefore glibc.
RUN npm ci --no-audit --no-fund \
 && npm install --no-save --no-audit --no-fund \
      lightningcss-linux-x64-gnu@1.32.0 \
      @tailwindcss/oxide-linux-x64-gnu@4.3.2

COPY --chown=node:node . .

# NEXT_PUBLIC_* are inlined into the client bundle by `next build`, so they must
# exist at BUILD time — setting them under compose's `environment:` does nothing
# for code that runs in the browser. .dockerignore excludes .env.local (rightly:
# it is a developer's local file, not an image input), so without these args
# lib/supabase.ts builds against its "https://placeholder.supabase.co" fallback
# and sign-in fails in the container while working fine under `npm run dev`.
#
# The anon key is public by design — it is shipped to every browser that loads
# the app, and Supabase RLS is what actually protects the data. Baking it into
# the image is therefore fine. SUPABASE_SERVICE_ROLE_KEY must never appear here.
ARG NEXT_PUBLIC_API_URL=http://localhost:8010/api/v1
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY

RUN npm run build && npm prune --omit=dev

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
USER node
EXPOSE 3000

CMD ["npm", "start"]
