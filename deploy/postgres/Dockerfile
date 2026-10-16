# The official entrypoint is a shell script, so this image keeps the Alpine shell;
# the database network is internal-only and nothing else runs in this container.
ARG POSTGRES_IMAGE=postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24

# pgvector (embeddings for "Ask the wiki"), compiled from a checksum-verified source archive.
FROM ${POSTGRES_IMAGE} AS pgvector
ARG PGVECTOR_VERSION=0.8.7
ARG PGVECTOR_SHA256=cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85
RUN apk add --no-cache build-base \
 && wget -q -O /tmp/pgvector.tar.gz \
      "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" \
 && echo "${PGVECTOR_SHA256}  /tmp/pgvector.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/pgvector.tar.gz -C /tmp \
 && cd "/tmp/pgvector-${PGVECTOR_VERSION}" \
 # Portable code (no -march=native) and no JIT bitcode: the runtime image has no LLVM.
 && make OPTFLAGS="" with_llvm=no \
 && make OPTFLAGS="" with_llvm=no install DESTDIR=/out \
 # Trusted: the database owner (migrations) can create it; the application is never superuser.
 && echo "trusted = true" >> /out/usr/local/share/postgresql/extension/vector.control

FROM ${POSTGRES_IMAGE}
COPY --from=pgvector /out/usr/local/ /usr/local/

# gosu only serves to drop root in the entrypoint; this image never runs as root.
RUN rm -f /usr/local/bin/gosu \
 && install -d -m 0755 /etc/postgresql
COPY --chmod=0644 deploy/postgres/pg_hba.conf /etc/postgresql/pg_hba.conf
COPY --chmod=0755 deploy/postgres/initdb/ /docker-entrypoint-initdb.d/
COPY --chmod=0755 deploy/postgres/start.sh /usr/local/bin/wiki-db-start

USER 70:70
ENTRYPOINT ["/usr/local/bin/wiki-db-start"]
