# --------------------------------------------------------------------------- #
# BC-Dx Platform — frontend image
#
# Two stages: build the SPA with Node, then serve the static output from nginx.
# The Node toolchain is ~1 GB and has no business being in a runtime image.
# --------------------------------------------------------------------------- #

FROM node:20-alpine AS build

WORKDIR /app

# Copy the lockfile first so `npm ci` can be cached and only re-runs when the
# dependency set actually changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine

# The dev server's `/api` and `/health` proxies in vite.config.ts only exist in
# `npm run dev`. A production build is plain static files, so the same routing
# has to be done by nginx — see nginx.conf.
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
